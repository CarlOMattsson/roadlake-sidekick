"""Storage of push delivery: the outbox, subscription and credential rows `push_delivery` works on.

`SqlPushDeliveryStore` implements `PushDeliveryStore`. It only knows how to read and write; the
rules (when to retry, what to give up) are in `push_delivery`. Every outcome is written only while
the row still carries the claim's lease. Nothing here logs, and an endpoint never leaves the
`Target` it is returned in.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from sidekick.companion.push_delivery import Claim, Target
from sidekick.shared.persistence.models import (
    AuditEventRow,
    CompanionPairingRow,
    PersonalAccessTokenRow,
    PushOutboxRow,
    PushSubscriptionRow,
    UserRow,
)
from sidekick.shared.types import new_uuid7


class SqlPushDeliveryStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def claim_due(
        self, now: datetime, lease: datetime, batch_size: int, max_attempts: int
    ) -> list[Claim]:
        with self._session_factory.begin() as session:
            rows = session.scalars(
                select(PushOutboxRow)
                .where(PushOutboxRow.delivered_at.is_(None), PushOutboxRow.next_attempt_at <= now)
                .order_by(PushOutboxRow.next_attempt_at, PushOutboxRow.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            ).all()
            claims: list[Claim] = []
            for row in rows:
                if row.attempts >= max_attempts:
                    # Kept throwing before the retry could count it out: give it up like a row
                    # that used all its attempts.
                    row.next_attempt_at = None
                    row.last_error_kind = "gave_up"
                    continue
                row.next_attempt_at = lease
                row.attempts += 1
                claims.append(Claim(row.id, row.subscription_id, row.kind, lease, row.attempts))
            return claims

    def failed_rows_waiting(self) -> bool:
        """Whether a row that was attempted is still undelivered and scheduled: it waits for its
        lease to run out or for its backoff, so a poll that found nothing due proves nothing."""

        with self._session_factory() as session:
            return (
                session.scalar(
                    select(PushOutboxRow.id)
                    .where(
                        PushOutboxRow.delivered_at.is_(None),
                        PushOutboxRow.next_attempt_at.is_not(None),
                        PushOutboxRow.attempts > 0,
                    )
                    .limit(1)
                )
                is not None
            )

    def renew_lease(self, claim: Claim, lease: datetime) -> bool:
        with self._session_factory.begin() as session:
            renewed = session.execute(
                update(PushOutboxRow)
                .where(
                    PushOutboxRow.id == claim.outbox_id,
                    PushOutboxRow.delivered_at.is_(None),
                    PushOutboxRow.next_attempt_at == claim.lease,
                )
                .values(next_attempt_at=lease)
                .returning(PushOutboxRow.id)
                .execution_options(synchronize_session=False)
            ).first()
        return renewed is not None

    def target(self, subscription_id: UUID, now: datetime) -> Target | None:
        with self._session_factory() as session:
            row = session.execute(
                select(
                    PushSubscriptionRow.endpoint,
                    PushSubscriptionRow.endpoint_host,
                    PushSubscriptionRow.user_id,
                    PushSubscriptionRow.revoked_at,
                    CompanionPairingRow.device_token_id,
                    PersonalAccessTokenRow.revoked_at,
                    PersonalAccessTokenRow.expires_at,
                    UserRow.active,
                )
                .select_from(PushSubscriptionRow)
                .join(CompanionPairingRow, CompanionPairingRow.id == PushSubscriptionRow.pairing_id)
                .outerjoin(
                    PersonalAccessTokenRow,
                    PersonalAccessTokenRow.id == CompanionPairingRow.device_token_id,
                )
                .outerjoin(UserRow, UserRow.id == PushSubscriptionRow.user_id)
                .where(PushSubscriptionRow.id == subscription_id)
            ).one_or_none()
        if row is None:
            return None
        (endpoint, host, user_id, revoked_at, device_id, token_revoked, expires, active) = row
        # The same checks `verify_companion_token` makes on every request.
        credential_valid = (
            device_id is not None
            and token_revoked is None
            and expires is not None
            and expires > now
            and bool(active)
        )
        return Target(endpoint, host, user_id, device_id, revoked_at is not None, credential_valid)

    def mark_delivered(self, claim: Claim, now: datetime) -> None:
        self._update_leased(claim, {"delivered_at": now, "last_error_kind": None})

    def close(self, claim: Claim, reason: str) -> None:
        self._update_leased(claim, {"next_attempt_at": None, "last_error_kind": reason})

    def schedule_retry(self, claim: Claim, at: datetime | None, error_kind: str) -> None:
        self._update_leased(claim, {"next_attempt_at": at, "last_error_kind": error_kind})

    def defer_unsent(self, claim: Claim, until: datetime | None, error_kind: str | None) -> None:
        values: dict[str, object] = {
            "attempts": func.greatest(PushOutboxRow.attempts - 1, 0),
            "next_attempt_at": until,
        }
        if error_kind is not None:
            values["last_error_kind"] = error_kind
        self._update_leased(claim, values)

    def _update_leased(self, claim: Claim, values: dict[str, object]) -> None:
        """Write the outcome only while the row still carries this claim's lease."""

        with self._session_factory.begin() as session:
            session.execute(
                update(PushOutboxRow)
                .where(
                    PushOutboxRow.id == claim.outbox_id,
                    PushOutboxRow.delivered_at.is_(None),
                    PushOutboxRow.next_attempt_at == claim.lease,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )

    def record_success(
        self, subscription_id: UUID, now: datetime, hold_wakes_until: datetime | None
    ) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                update(PushSubscriptionRow)
                .where(PushSubscriptionRow.id == subscription_id)
                .values(last_success_at=now, failure_count=0)
                .execution_options(synchronize_session=False)
            )
            if hold_wakes_until is not None:
                session.execute(
                    update(PushOutboxRow)
                    .where(
                        PushOutboxRow.subscription_id == subscription_id,
                        PushOutboxRow.kind == "w",
                        PushOutboxRow.delivered_at.is_(None),
                        PushOutboxRow.next_attempt_at.is_not(None),
                    )
                    .values(
                        next_attempt_at=func.greatest(
                            PushOutboxRow.next_attempt_at, hold_wakes_until
                        )
                    )
                    .execution_options(synchronize_session=False)
                )

    def record_failure(self, subscription_id: UUID) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                update(PushSubscriptionRow)
                .where(PushSubscriptionRow.id == subscription_id)
                .values(failure_count=PushSubscriptionRow.failure_count + 1)
                .execution_options(synchronize_session=False)
            )

    def revoke(self, claim: Claim, target: Target, reason: str, now: datetime) -> None:
        """Revoke the subscription and close its pending rows; the audit row names only the
        device and a closed reason.

        Only the endpoint the send was made to is revoked: if the device registered another
        endpoint on the same row meanwhile, nothing is revoked and the pending rows stay for the
        next attempt against the new endpoint."""

        subscription_id = claim.subscription_id
        with self._session_factory.begin() as session:
            revoked = session.execute(
                update(PushSubscriptionRow)
                .where(
                    PushSubscriptionRow.id == subscription_id,
                    PushSubscriptionRow.endpoint == target.endpoint,
                    PushSubscriptionRow.revoked_at.is_(None),
                )
                .values(revoked_at=now, updated_at=now)
                .returning(PushSubscriptionRow.id)
                .execution_options(synchronize_session=False)
            ).first()
            if revoked is None:
                # Already revoked, or the endpoint was replaced: leave the rows. The lease
                # expires and the row is tried again against whatever the row carries now.
                return
            session.execute(
                update(PushOutboxRow)
                .where(
                    PushOutboxRow.subscription_id == subscription_id,
                    PushOutboxRow.delivered_at.is_(None),
                    PushOutboxRow.next_attempt_at.is_not(None),
                )
                .values(next_attempt_at=None, last_error_kind=reason)
                .execution_options(synchronize_session=False)
            )
            session.add(
                AuditEventRow(
                    id=new_uuid7(),
                    actor_id=target.user_id,
                    event="companion.push_revoked",
                    outcome="success",
                    reason=reason,
                    correlation_id=None,
                    target_type="companion_device",
                    target_id=target.device_id,
                    occurred_at=now,
                )
            )

"""Storage of push subscriptions: the registration upsert, revocation, lookups and audit rows.

`SqlPushSubscriptionStore` implements the port `PushSubscriptionService` works against. The rules
(which endpoints are acceptable) are in `push`; this module only reads and writes. An endpoint is
written here and never read back out: the lookups return hosts and ids.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.persistence.models import (
    AuditEventRow,
    CompanionPairingRow,
    PushSubscriptionRow,
)
from sidekick.shared.types import new_uuid7, utc_now


class SqlPushSubscriptionStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def subscribe(
        self,
        user_id: UUID,
        device_id: UUID,
        endpoint: str,
        host: str,
        now: datetime,
        correlation_id: str | None,
    ) -> bool:
        """Register (or replace) the endpoint of the device's pairing and audit it, in one
        transaction. False when the device has no pairing."""

        with self._session_factory.begin() as session:
            pairing_id = _pairing_of(session, user_id, device_id)
            if pairing_id is None:
                return False
            statement = insert(PushSubscriptionRow).values(
                id=new_uuid7(),
                pairing_id=pairing_id,
                user_id=user_id,
                endpoint=endpoint,
                endpoint_host=host,
                created_at=now,
                updated_at=now,
                failure_count=0,
            )
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[PushSubscriptionRow.pairing_id],
                    index_where=PushSubscriptionRow.revoked_at.is_(None),
                    set_={
                        "endpoint": statement.excluded.endpoint,
                        "endpoint_host": statement.excluded.endpoint_host,
                        "updated_at": now,
                        "failure_count": 0,
                    },
                )
            )
            record_device_event(
                session, user_id, "companion.push_subscribed", device_id, correlation_id
            )
        return True

    def unsubscribe(
        self, user_id: UUID, device_id: UUID, now: datetime, correlation_id: str | None
    ) -> bool:
        """Revoke the device's active subscription and audit it. False when there was none."""

        with self._session_factory.begin() as session:
            revoked = revoke_for_device(session, user_id, device_id, now)
            if revoked:
                record_device_event(
                    session, user_id, "companion.push_unsubscribed", device_id, correlation_id
                )
            return revoked

    def active_endpoint_host(self, user_id: UUID, device_id: UUID) -> str | None:
        with self._session_factory() as session:
            return session.scalar(
                select(PushSubscriptionRow.endpoint_host)
                .join(CompanionPairingRow, CompanionPairingRow.id == PushSubscriptionRow.pairing_id)
                .where(
                    CompanionPairingRow.device_token_id == device_id,
                    PushSubscriptionRow.user_id == user_id,
                    PushSubscriptionRow.revoked_at.is_(None),
                )
            )


def revoke_for_device(session: Session, user_id: UUID, device_id: UUID, now: datetime) -> bool:
    """Revoke the active subscription of the pairing behind `device_id`, in the caller's
    transaction. The device store calls this when it revokes the device."""

    pairing_ids = select(CompanionPairingRow.id).where(
        CompanionPairingRow.device_token_id == device_id, CompanionPairingRow.user_id == user_id
    )
    result = session.execute(
        update(PushSubscriptionRow)
        .where(
            PushSubscriptionRow.pairing_id.in_(pairing_ids),
            PushSubscriptionRow.user_id == user_id,
            PushSubscriptionRow.revoked_at.is_(None),
        )
        .values(revoked_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return bool(cast(CursorResult[Any], result).rowcount)


def _pairing_of(session: Session, user_id: UUID, device_id: UUID) -> UUID | None:
    return session.scalar(
        select(CompanionPairingRow.id).where(
            CompanionPairingRow.device_token_id == device_id,
            CompanionPairingRow.user_id == user_id,
        )
    )


def record_device_event(
    session: Session,
    user_id: UUID,
    event: str,
    device_id: UUID,
    correlation_id: str | None,
) -> None:
    session.add(
        AuditEventRow(
            id=new_uuid7(),
            actor_id=user_id,
            event=event,
            outcome="success",
            reason=None,
            correlation_id=correlation_id,
            target_type="companion_device",
            target_id=device_id,
            occurred_at=utc_now(),
        )
    )

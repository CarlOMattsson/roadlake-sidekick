"""Storage of companion pairings and devices: pairing rows, device credential rows, audit rows.

A device is a personal-access-token row with `purpose = 'companion'`. Every method takes the open
transaction that `CompanionDeviceStore.transaction` (or `read`) hands out; the service decides what
to read and write, this module only knows how. Rows never leave it: the service sees `DeviceRecord`
and `ClaimedPairing`. Nothing here logs, and nothing writes a secret or a token, only keyed digests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from sidekick.companion.push_subscription_store import revoke_for_device
from sidekick.shared.auth import TOKEN_PURPOSE_COMPANION
from sidekick.shared.persistence.models import (
    AuditEventRow,
    CompanionPairingRow,
    PersonalAccessTokenRow,
    UserRow,
)
from sidekick.shared.types import TxSession, new_uuid7

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    """One device credential row as stored. The digests are keyed digests, never tokens."""

    id: UUID
    label: str
    scopes: tuple[str, ...]
    token_digest: str
    previous_token_digest: str | None
    previous_valid_until: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ClaimedPairing:
    id: UUID
    user_id: UUID
    label: str
    scopes: tuple[str, ...]
    device_lifetime_days: int


def _record(row: PersonalAccessTokenRow) -> DeviceRecord:
    return DeviceRecord(
        id=row.id,
        label=row.label,
        scopes=tuple(row.scopes),
        token_digest=row.token_digest,
        previous_token_digest=row.previous_token_digest,
        previous_valid_until=row.previous_valid_until,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )


class CompanionDeviceStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def transaction(self, operation: Callable[[TxSession], T]) -> T:
        with self._session_factory.begin() as session:
            return operation(session)

    def read(self, operation: Callable[[TxSession], T]) -> T:
        with self._session_factory() as session:
            return operation(session)

    @staticmethod
    def user_is_active(session: TxSession, user_id: UUID) -> bool:
        return bool(session.scalar(select(UserRow.active).where(UserRow.id == user_id)))

    @staticmethod
    def active_owner_ids(session: TxSession, limit: int) -> list[UUID]:
        """At most `limit` ids of active users."""

        return list(
            session.scalars(select(UserRow.id).where(UserRow.active.is_(True)).limit(limit))
        )

    @staticmethod
    def add_pairing(
        session: TxSession,
        *,
        pairing_id: UUID,
        user_id: UUID,
        label: str,
        scopes: Iterable[str],
        secret_digest: str,
        device_lifetime_days: int,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        session.add(
            CompanionPairingRow(
                id=pairing_id,
                user_id=user_id,
                label=label,
                scopes=sorted(scopes),
                secret_digest=secret_digest,
                device_lifetime_days=device_lifetime_days,
                expires_at=expires_at,
                consumed_at=None,
                device_token_id=None,
                created_at=now,
            )
        )

    @staticmethod
    def claim_pairing(
        session: TxSession, secret_digest: str, now: datetime
    ) -> ClaimedPairing | None:
        """Mark the live, unused pairing with this digest as consumed, in one conditional UPDATE,
        so two simultaneous claims of one secret yield exactly one."""

        claimed = session.execute(
            update(CompanionPairingRow)
            .where(
                CompanionPairingRow.secret_digest == secret_digest,
                CompanionPairingRow.consumed_at.is_(None),
                CompanionPairingRow.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(
                CompanionPairingRow.id,
                CompanionPairingRow.user_id,
                CompanionPairingRow.label,
                CompanionPairingRow.scopes,
                CompanionPairingRow.device_lifetime_days,
            )
            .execution_options(synchronize_session=False)
        ).one_or_none()
        if claimed is None:
            return None
        pairing_id, user_id, label, scopes, lifetime_days = claimed
        return ClaimedPairing(pairing_id, user_id, label, tuple(scopes), lifetime_days)

    @staticmethod
    def add_device(
        session: TxSession,
        *,
        user_id: UUID,
        label: str,
        token_digest: str,
        scopes: Iterable[str],
        expires_at: datetime,
        now: datetime,
    ) -> DeviceRecord:
        device = PersonalAccessTokenRow(
            id=new_uuid7(),
            user_id=user_id,
            label=label,
            token_digest=token_digest,
            scopes=list(scopes),
            expires_at=expires_at,
            revoked_at=None,
            last_used_at=None,
            created_at=now,
            purpose=TOKEN_PURPOSE_COMPANION,
        )
        session.add(device)
        session.flush()
        return _record(device)

    @staticmethod
    def link_pairing_to_device(session: TxSession, pairing_id: UUID, device_id: UUID) -> None:
        session.execute(
            update(CompanionPairingRow)
            .where(CompanionPairingRow.id == pairing_id)
            .values(device_token_id=device_id)
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    def list_devices(session: TxSession, user_id: UUID) -> list[DeviceRecord]:
        rows = session.scalars(
            select(PersonalAccessTokenRow)
            .where(
                PersonalAccessTokenRow.user_id == user_id,
                PersonalAccessTokenRow.purpose == TOKEN_PURPOSE_COMPANION,
            )
            .order_by(PersonalAccessTokenRow.created_at.desc())
        )
        return [_record(row) for row in rows]

    @staticmethod
    def device(
        session: TxSession, user_id: UUID, device_id: UUID, *, lock: bool = False
    ) -> DeviceRecord | None:
        """This owner's device, or `None`. With `lock` the row is held `FOR UPDATE` until the
        transaction ends, so a read-then-write on it is serialized."""

        statement = select(PersonalAccessTokenRow).where(
            PersonalAccessTokenRow.id == device_id,
            PersonalAccessTokenRow.user_id == user_id,
            PersonalAccessTokenRow.purpose == TOKEN_PURPOSE_COMPANION,
        )
        row = session.scalar(statement.with_for_update() if lock else statement)
        return None if row is None else _record(row)

    @staticmethod
    def renewal_times_since(session: TxSession, device_id: UUID, since: datetime) -> list[datetime]:
        """When this device was renewed after `since`, oldest first (from the audit trail)."""

        return list(
            session.scalars(
                select(AuditEventRow.occurred_at)
                .where(
                    AuditEventRow.event == "companion.device_renewed",
                    AuditEventRow.target_type == "companion_device",
                    AuditEventRow.target_id == device_id,
                    AuditEventRow.occurred_at > since,
                )
                .order_by(AuditEventRow.occurred_at)
            )
        )

    @staticmethod
    def pairing_lifetime_days(session: TxSession, device_id: UUID) -> int | None:
        return session.scalar(
            select(CompanionPairingRow.device_lifetime_days).where(
                CompanionPairingRow.device_token_id == device_id
            )
        )

    @staticmethod
    def rotate_credential(
        session: TxSession,
        device_id: UUID,
        *,
        token_digest: str,
        expires_at: datetime,
        keep_previous_until: datetime | None,
    ) -> DeviceRecord:
        """Give the device a new digest and expiry. With `keep_previous_until` the digest it
        replaces stays valid until then; without it the earlier grace window is left as it was."""

        row = session.get(PersonalAccessTokenRow, device_id)
        if row is None:
            raise LookupError("companion device row vanished under its lock")
        if keep_previous_until is not None:
            row.previous_token_digest = row.token_digest
            row.previous_valid_until = keep_previous_until
        row.token_digest = token_digest
        row.expires_at = expires_at
        return _record(row)

    @staticmethod
    def set_scopes(session: TxSession, device_id: UUID, scopes: Iterable[str]) -> DeviceRecord:
        row = session.get(PersonalAccessTokenRow, device_id)
        if row is None:
            raise LookupError("companion device row vanished under its lock")
        row.scopes = sorted(scopes)
        return _record(row)

    @staticmethod
    def revoke_push_subscription(
        session: TxSession, user_id: UUID, device_id: UUID, now: datetime
    ) -> bool:
        return revoke_for_device(session, user_id, device_id, now)

    @staticmethod
    def mark_revoked(session: TxSession, device_id: UUID, now: datetime) -> None:
        row = session.get(PersonalAccessTokenRow, device_id)
        if row is None:
            raise LookupError("companion device row vanished under its lock")
        row.revoked_at = now

    @staticmethod
    def append_audit(
        session: TxSession,
        actor_id: UUID | None,
        event: str,
        outcome: str,
        target: tuple[str, UUID] | None,
        *,
        reason: str | None,
        correlation_id: str | None,
        occurred_at: datetime,
    ) -> None:
        session.add(
            AuditEventRow(
                id=new_uuid7(),
                actor_id=actor_id,
                event=event,
                outcome=outcome,
                reason=reason,
                correlation_id=correlation_id,
                target_type=f"companion_{target[0]}" if target is not None else None,
                target_id=target[1] if target is not None else None,
                occurred_at=occurred_at,
            )
        )

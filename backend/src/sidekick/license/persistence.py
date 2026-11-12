"""The license's storage: the one `instance_license` row and its audit events.

The row belongs to the installation (no owner). Every method takes the open transaction that
`LicenseStore.transaction` hands out; the service decides what to read and write, this module
only knows how.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.persistence.models import AuditEventRow, InstanceLicenseRow, UserRow
from sidekick.shared.types import TxSession, new_uuid7, utc_now

T = TypeVar("T")

ROW_ID = 1
AUDIT_TARGET = "instance_license"

StoreUnavailable = SQLAlchemyError
"""What a database that cannot answer raises; the service treats it as `unlicensed` for display."""


@dataclass(frozen=True, slots=True)
class StoredLicense:
    """The stored key (None when none was entered) and the highest UTC date seen."""

    key: str | None
    max_seen_on: date


class LicenseStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def transaction(self, operation: Callable[[TxSession], T]) -> T:
        with self._session_factory.begin() as session:
            return operation(session)

    @staticmethod
    def read(session: TxSession) -> StoredLicense | None:
        row = session.get(InstanceLicenseRow, ROW_ID)
        return None if row is None else StoredLicense(row.license_key, row.max_seen_on)

    @staticmethod
    def remember_seen(session: TxSession, day: date, now: datetime, *, force: bool) -> None:
        """Remember `day` as the highest date seen: never lower unless `force` (reset-clock)."""

        statement = insert(InstanceLicenseRow).values(
            id=ROW_ID, license_key=None, max_seen_on=day, updated_at=now
        )
        kept = statement.excluded.max_seen_on
        if not force:
            kept = func.greatest(InstanceLicenseRow.max_seen_on, kept)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[InstanceLicenseRow.id], set_={"max_seen_on": kept}
            )
        )

    @staticmethod
    def write_key(session: TxSession, key: str | None, now: datetime) -> None:
        session.execute(
            update(InstanceLicenseRow)
            .where(InstanceLicenseRow.id == ROW_ID)
            .values(license_key=key, updated_at=now)
        )

    @staticmethod
    def active_user_ids(session: TxSession, limit: int) -> list[UUID]:
        return list(
            session.scalars(select(UserRow.id).where(UserRow.active.is_(True)).limit(limit))
        )

    @staticmethod
    def denied_since(
        session: TxSession, actor_id: UUID | None, reason: str, since: datetime
    ) -> bool:
        """Whether this actor's refused `license.set` for this reason is audited since `since`."""

        return (
            session.scalar(
                select(AuditEventRow.id)
                .where(
                    AuditEventRow.event == "license.set",
                    AuditEventRow.outcome == "denied",
                    AuditEventRow.reason == reason,
                    AuditEventRow.target_type == AUDIT_TARGET,
                    AuditEventRow.actor_id.is_not_distinct_from(actor_id),
                    AuditEventRow.occurred_at >= since,
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def append_audit(
        session: TxSession,
        actor_id: UUID | None,
        event: str,
        outcome: str,
        reason: str | None,
        correlation_id: str | None,
    ) -> None:
        session.add(
            AuditEventRow(
                id=new_uuid7(),
                actor_id=actor_id,
                event=event,
                outcome=outcome,
                reason=reason,
                correlation_id=correlation_id,
                target_type=AUDIT_TARGET,
                target_id=None,
                occurred_at=utc_now(),
            )
        )

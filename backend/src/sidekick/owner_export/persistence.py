"""The statements and column rules the owner export and restore need from the database."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Column, Date, DateTime, Numeric, func, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from sidekick.shared.persistence.models import MemorySettingsRow, UserRow
from sidekick.shared.types import TxSession


def is_derived_column(column: Column[Any]) -> bool:
    """Generated columns (for example search vectors) are derived from other columns.

    They are neither exported nor restored: the database recomputes them, and a restore
    must not try to write them.
    """

    return column.computed is not None


def coerce_restore_value(column: Any, value: Any) -> Any:
    """The Python value a restored JSON value stands for in this column's type."""

    if value is None:
        return None
    if isinstance(column.type, PGUUID):
        return value if isinstance(value, UUID) else UUID(str(value))
    if isinstance(column.type, DateTime):
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if isinstance(column.type, Date):
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    if isinstance(column.type, Numeric):
        return value if isinstance(value, Decimal) else Decimal(str(value))
    return value


def all_owner_ids(session: TxSession) -> list[UUID]:
    return list(session.scalars(select(UserRow.id).order_by(UserRow.id)).all())


def lock_restore_scope(session: TxSession, lock_id: int) -> None:
    """Serialise restores into one owner for the rest of the transaction."""

    session.execute(select(func.pg_advisory_xact_lock(lock_id)))


def lock_memory_settings(session: TxSession, owner_id: UUID) -> MemorySettingsRow | None:
    return session.scalar(
        select(MemorySettingsRow).where(MemorySettingsRow.owner_id == owner_id).with_for_update()
    )


def owner_has_rows(session: TxSession, row_type: Any, owner_id: UUID) -> bool:
    return (
        session.scalar(select(row_type).where(row_type.owner_id == owner_id).limit(1)) is not None
    )

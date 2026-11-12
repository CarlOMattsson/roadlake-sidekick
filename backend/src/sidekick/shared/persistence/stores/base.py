"""Shared store plumbing: session factory, transaction boundary, idempotency, audit."""

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any, TypeVar, cast
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.change_source import current_change_source
from sidekick.shared.errors import (
    IdempotencyKeyReusedError,
)
from sidekick.shared.errors.core import InternalFaultError
from sidekick.shared.observability import NoopTelemetryAdapter, TelemetryPort
from sidekick.shared.persistence.models import (
    AuditEventRow,
    IdempotencyRow,
)
from sidekick.shared.types import new_uuid7, utc_now

T = TypeVar("T")

IDEMPOTENCY_RETENTION = timedelta(days=30)
# Rows fetched per round trip when an owner export reads a table.
EXPORT_FETCH_BATCH_ROWS = 500
"""How long a replay record lives. A retry after this window is treated as a new request, so
clients must not reuse a key for the same intent after 30 days. Pruned by the automation worker."""

MAX_REPLAY_RECORD_BYTES = 16 * 1024
"""Hard cap on the serialized size of an identifier-only replay record: 16 KiB. The largest one is
a board-column reorder of 100 Tasks, which keeps an id, a rank and a version each (about 8.5 KB)."""

# A replay record holds identifiers, versions, flags and timestamps, never free text. An operation
# either (a) passes a `replay` projection that reduces its result to such a record and re-reads the
# rest by id, or (b) is listed here because its result is already that small. Anything else is
# refused as a programmer error (`ReplayRecordError`), so a new operation cannot silently start
# storing titles, notes or names. Extending this set is a reviewed change; the stored record of
# every entry is verified to be identifier-only at write time.
IDENTITY_REPLAY_OPERATIONS = frozenset(
    {
        "create_journal_source",
        "create_manual_journal_entry",
        "append_to_journal_entry",
        "update_journal_entry",
        "change_journal_entry_relations",
        "archive_journal_entry",
        "restore_journal_entry",
        "update_journal_draft",
        "reject_journal_draft",
        "link_contact_to_project",
        "unlink_contact_from_project",
        "link_contact_to_task",
        "unlink_contact_from_task",
        "permanently_remove_record",
        "reorder_board_column",
        "finalize_journal_draft",
        "put_manual_daily_summary",
        "external_reference.unlink",
    }
)


_UUID_TEXT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ISO_TEXT = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$"
)


class ReplayRecordError(InternalFaultError):
    """Programmer error: an operation tried to store more than an identifier-only replay record."""


def _identifier_only(value: Any) -> bool:
    if value is None or isinstance(value, bool | int):
        return True
    if isinstance(value, str):
        return bool(_UUID_TEXT.match(value) or _ISO_TEXT.match(value))
    if isinstance(value, list | tuple):
        items = cast("list[Any]", value)
        return all(_identifier_only(item) for item in items)
    if isinstance(value, dict):
        entries = cast("dict[Any, Any]", value)
        return all(isinstance(key, str) and _identifier_only(item) for key, item in entries.items())
    return False


class StoreBase:
    """Short-lived transaction boundary with owner-filtered feature operations.

    Domain operations live in the sibling mixin modules and are composed by
    ``SqlAlchemyStore``.
    """

    def __init__(
        self, session_factory: sessionmaker[Session], telemetry: TelemetryPort | None = None
    ) -> None:
        self._session_factory = session_factory
        self._telemetry = telemetry or NoopTelemetryAdapter()

    def transaction(self, operation: Callable[[Session], T]) -> T:
        with (
            self._telemetry.span("db.transaction", {"db.system.name": "postgresql"}),
            self._session_factory.begin() as session,
        ):
            return operation(session)

    def snapshot_transaction(self, operation: Callable[[Session], T]) -> T:
        """Run a read-only operation against one consistent snapshot of the database.

        Every statement sees the data as of the first one, so rows read from related tables
        cannot disagree because of a write that committed in between.  Postgres accepts
        DEFERRABLE at any level and applies it only to SERIALIZABLE, so it is harmless here.
        """

        def read(session: Session) -> T:
            session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY DEFERRABLE")
            )
            return operation(session)

        return self.transaction(read)

    @staticmethod
    def export_owner_rows(
        session: Session,
        *,
        owner_id: UUID,
        row_type: type[Any],
    ) -> Iterable[Any]:
        """Read one row type for the closed owner-export catalogue.

        The statement runs at once (so it belongs to the caller's snapshot) but the rows are
        fetched in batches while the caller iterates, so an export that is refused part-way never
        loads the rest of the table.  The caller must read the result to its end or abandon the
        transaction.

        The caller supplies only the explicit row types approved by
        ``sidekick.owner_export.core.EXPORT_SOURCES``.  Keeping the owner predicate in
        this persistence adapter makes it difficult for a future export source to
        accidentally turn into an unscoped table read.
        """
        owner_column = getattr(row_type, "owner_id", None)
        if owner_column is None:
            raise TypeError("owner export sources must expose owner_id")
        return session.scalars(
            select(row_type)
            .where(owner_column == owner_id)
            .order_by(*row_type.__table__.primary_key.columns)
        ).yield_per(EXPORT_FETCH_BATCH_ROWS)

    def idempotent(
        self,
        session: Session,
        *,
        actor_id: UUID,
        operation: str,
        key: str,
        payload: dict[str, Any],
        execute: Callable[[], dict[str, Any]],
        replay: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run `execute` once per (actor, operation, key) and return the recorded outcome on retry.

        What is stored is the *replay record*. With `replay`, it is `replay(result)`: a projection
        to identifiers, versions, flags and timestamps only, after which the caller re-reads the
        rest by id. Without `replay`, the whole result is stored, which is allowed only for
        operations in ``IDENTITY_REPLAY_OPERATIONS`` (result already identifier-only); any other
        operation raises `ReplayRecordError`. Every record is checked to be identifier-only and at
        most ``MAX_REPLAY_RECORD_BYTES`` before it is written. The first call and every retry
        return the same record, so the caller builds its answer from the record alone.
        Records older than ``IDEMPOTENCY_RETENTION`` are pruned.
        """
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        lock_material = f"{actor_id}:{operation}:{key}".encode()
        lock_id = int.from_bytes(hashlib.sha256(lock_material).digest()[:8], signed=True)
        session.execute(select(func.pg_advisory_xact_lock(lock_id)))
        existing = session.scalar(
            select(IdempotencyRow).where(
                IdempotencyRow.actor_id == actor_id,
                IdempotencyRow.operation == operation,
                IdempotencyRow.idempotency_key == key,
            )
        )
        if existing:
            if existing.payload_hash != payload_hash:
                raise IdempotencyKeyReusedError()
            return existing.result
        result = execute()
        record = self.replay_record(operation, result, replay)
        session.add(
            IdempotencyRow(
                id=new_uuid7(),
                actor_id=actor_id,
                operation=operation,
                idempotency_key=key,
                payload_hash=payload_hash,
                result=record,
                created_at=utc_now(),
            )
        )
        return record

    @staticmethod
    def replay_record(
        operation: str,
        result: dict[str, Any],
        replay: Callable[[dict[str, Any]], dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """The record stored for `result`, or `ReplayRecordError` when the policy forbids it."""

        if replay is None and operation not in IDENTITY_REPLAY_OPERATIONS:
            raise ReplayRecordError(
                f"operation {operation!r} needs a replay projection or a reviewed allow-list entry"
            )
        record = replay(result) if replay is not None else result
        if not _identifier_only(record):
            raise ReplayRecordError(f"replay record for {operation!r} holds more than identifiers")
        size = len(json.dumps(record, separators=(",", ":"), default=str).encode())
        if size > MAX_REPLAY_RECORD_BYTES:
            raise ReplayRecordError(f"replay record for {operation!r} is {size} bytes")
        return record

    @staticmethod
    def prune_idempotency(session: Session, older_than: datetime) -> int:
        """Delete replay records created before `older_than`; returns how many were removed."""

        outcome = session.execute(
            delete(IdempotencyRow).where(IdempotencyRow.created_at < older_than)
        )
        return int(getattr(outcome, "rowcount", 0) or 0)

    @staticmethod
    def append_audit(
        session: Session,
        *,
        actor_id: UUID | None,
        event: str,
        outcome: str,
        target_type: str | None = None,
        target_id: UUID | None = None,
        related_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Append bounded metadata without storing object text or credentials.

        `related_id` is the other side of a link change, a bare UUID with no text. The source
        (`you` or `claude`) comes from the transport of the request; none is recorded outside one.
        """

        session.add(
            AuditEventRow(
                id=new_uuid7(),
                actor_id=actor_id,
                event=event,
                outcome=outcome,
                reason=None,
                correlation_id=correlation_id,
                target_type=target_type,
                target_id=target_id,
                related_id=related_id,
                source=current_change_source(),
                occurred_at=utc_now(),
            )
        )

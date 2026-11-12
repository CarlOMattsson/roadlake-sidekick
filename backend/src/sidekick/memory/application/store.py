"""The persistence port of derived memory. Application code depends on this, not on SQLAlchemy.

`sidekick.memory.infrastructure.store.SqlAlchemyMemoryStore` implements it. Every method that
reads or writes rows takes the open unit of work (`TxSession`) and filters by owner itself, so no
caller can build an unscoped query. The use cases own the transaction boundaries (`read()` for a
read-only unit, `begin()` for one that commits on success) and the business rules; the store owns
the statements. Methods return plain values or the `memory_*` rows (typed as the structural
`MemorySettingsRecord` and `MemorySourceRecord`), never query objects.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Protocol
from uuid import UUID

from sidekick.memory.application.queries import MemoryCandidate, MemoryTombstone
from sidekick.memory.application.records import MemorySettingsRecord, MemorySourceRecord
from sidekick.memory.domain import MemoryKind
from sidekick.shared.errors.core import InternalFaultError
from sidekick.shared.types import AuditingStore, TxSession


class LockLost(InternalFaultError):
    """The advisory-lock connection is gone, so a pass can no longer exclude other workers."""


class OwnerLockPort(Protocol):
    """A per-owner lock held across many short transactions (and provider calls)."""

    def acquire(self) -> bool: ...

    def assert_alive(self) -> None:
        """Raises `LockLost` when the lock can no longer be trusted."""
        ...

    def release(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SourceRef:
    """What recall needs of a `memory_sources` row."""

    doc_key: str
    source_kind: str
    source_id: UUID
    status: str
    source_updated_at: datetime
    #: When a retain of this document last succeeded (or, before the first success, was reserved).
    retained_at: datetime | None
    #: A parked marker left by a deleted document: nothing of it may be released.
    removed_marker: bool


@dataclass(frozen=True, slots=True)
class LiveSource:
    """A source record that is live (not trashed) with its archived flag and update time."""

    archived: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CitedRecord:
    """Title and date of one cited record. `day` is None when its kind has no date."""

    record_id: UUID
    title: str | None
    day: date | None


@dataclass(frozen=True, slots=True)
class SourceCountRow:
    """How many `memory_sources` rows share one kind, status, exclusion flag and marker flag."""

    source_kind: str
    status: str
    excluded: bool
    removed_marker: bool
    count: int


@dataclass(frozen=True, slots=True)
class RecordTitle:
    """The title of an existing, untrashed record of the owner (the title itself may be None)."""

    title: str | None


@dataclass(frozen=True, slots=True)
class DailyUsage:
    """Documents and characters sent so far on one day."""

    live: int = 0
    backfill: int = 0
    characters: int = 0


@dataclass(frozen=True, slots=True)
class SourceFlags:
    """The policy-relevant columns of one `memory_sources` row."""

    row_id: UUID
    source_kind: str
    excluded: bool


class MemoryStore(AuditingStore, Protocol):
    """Owner-scoped persistence for the memory use cases."""

    # -- units of work --

    def read(self) -> AbstractContextManager[TxSession]:
        """A session for reads; closed (and rolled back) when the block ends."""
        ...

    def begin(self) -> AbstractContextManager[TxSession]:
        """A session in a transaction that commits when the block ends without an error."""
        ...

    def owner_lock(self, owner_id: UUID) -> OwnerLockPort:
        """A not yet acquired session-level lock for this owner on its own connection."""
        ...

    # -- settings --

    def settings(
        self, session: TxSession, owner_id: UUID, *, fresh: bool = False
    ) -> MemorySettingsRecord | None:
        """The owner's settings row. `fresh` reads the database, not the session's identity map."""
        ...

    def settings_for_update(
        self, session: TxSession, owner_id: UUID
    ) -> MemorySettingsRecord | None: ...

    def insert_default_settings(self, session: TxSession, owner_id: UUID, now: datetime) -> None:
        """Create the all-on version-1 row unless a concurrent writer did."""
        ...

    def create_settings(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        journal: bool,
        contacts: bool,
        projects: bool,
        tasks: bool,
        paused: bool,
        now: datetime,
    ) -> bool:
        """Create the version-1 row. False when a concurrent writer created it first."""
        ...

    # -- sources --

    def source_counts(
        self, session: TxSession, owner_id: UUID, kinds: list[MemoryKind]
    ) -> list[SourceCountRow]: ...

    def retained_document_count(
        self, session: TxSession, owner_id: UUID, kind: MemoryKind
    ) -> int: ...

    def record_title(
        self, session: TxSession, owner_id: UUID, kind: MemoryKind, source_id: UUID
    ) -> RecordTitle | None:
        """None when the record does not exist, is another owner's or is in the trash."""
        ...

    def add_source(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        kind: MemoryKind,
        source_id: UUID,
        doc_key: str,
        fingerprint: str,
        pipeline_version: int,
        status: str,
        source_updated_at: datetime,
    ) -> MemorySourceRecord:
        """Add a new row with no attempts, no operation and no failure; flushed with the unit."""
        ...

    def source_row_for_update(
        self, session: TxSession, owner_id: UUID, kind: MemoryKind, source_id: UUID
    ) -> MemorySourceRecord | None: ...

    def upsert_exclusion_marker(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: MemoryKind,
        source_id: UUID,
        *,
        doc_key: str,
        now: datetime,
    ) -> None:
        """Remember an exclusion of a never-synced record as a parked `removed` marker row."""
        ...

    def sources_for_documents(
        self, session: TxSession, owner_id: UUID, doc_keys: set[str]
    ) -> list[SourceRef]:
        """The owner's non-excluded rows for these documents. Other owners' rows never match."""
        ...

    def live_sources(
        self, session: TxSession, owner_id: UUID, kind: MemoryKind, source_ids: set[UUID]
    ) -> dict[UUID, LiveSource]:
        """Live sources of one kind. A journal entry is live only while its source is too."""
        ...

    def cited_records(
        self, session: TxSession, owner_id: UUID, kind: MemoryKind, record_ids: list[UUID]
    ) -> list[CitedRecord]:
        """Titles and dates of cited records in one query. Trashed records are absent."""
        ...

    # -- sync pass --

    def owner_ids(self, session: TxSession) -> list[UUID]:
        """Owners with a settings row or any `memory_sources` row, in no particular order."""
        ...

    def submitted_operations(
        self, session: TxSession, owner_id: UUID
    ) -> list[tuple[str | None, datetime | None]]:
        """(operation id, deadline) of the owner's `submitted` rows, by row id."""
        ...

    def submitted_rows_for_update(
        self, session: TxSession, owner_id: UUID, operation_id: str
    ) -> list[MemorySourceRecord]: ...

    def candidate_page(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: MemoryKind,
        *,
        owner_timezone: tzinfo,
        after: UUID | None,
        limit: int,
    ) -> list[MemoryCandidate]: ...

    def tombstone_page(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: MemoryKind,
        *,
        after: UUID | None,
        limit: int,
    ) -> list[MemoryTombstone]: ...

    def source_rows_by_id(
        self, session: TxSession, owner_id: UUID, row_ids: list[UUID]
    ) -> dict[UUID, MemorySourceRecord]: ...

    def source_rows_by_record(
        self, session: TxSession, owner_id: UUID, kind: MemoryKind, source_ids: list[UUID]
    ) -> dict[UUID, MemorySourceRecord]:
        """The owner's rows of one kind, keyed by source record id."""
        ...

    def source_rows_for_update(
        self, session: TxSession, owner_id: UUID, row_ids: list[UUID]
    ) -> dict[UUID, MemorySourceRecord]: ...

    def settle_removed_row(
        self,
        session: TxSession,
        *,
        row_id: UUID,
        doc_key: str,
        excluded: bool,
        hold_until: datetime | None,
    ) -> bool:
        """Record that the row's document was deleted. True when the row stays as a marker.

        An excluded row always stays (dropping it would forget the owner's exclusion); any row
        with a `hold_until` stays until its second delete. Otherwise the row is dropped.
        """
        ...

    def source_flags(
        self, session: TxSession, owner_id: UUID, row_ids: list[UUID]
    ) -> list[SourceFlags]: ...

    def mark_submitted(
        self,
        session: TxSession,
        row_ids: list[UUID],
        *,
        operation_id: str,
        deadline: datetime,
    ) -> None:
        """Move still-`pending`/`failed` rows to `submitted` under the operation."""
        ...

    def daily_usage(self, session: TxSession, owner_id: UUID, day: date) -> DailyUsage: ...

    def charge_usage(
        self,
        session: TxSession,
        owner_id: UUID,
        day: date,
        *,
        live: int,
        backfill: int,
        characters: int,
        live_cap: int,
        backfill_cap: int,
        char_cap: int,
        single_document: bool,
    ) -> bool:
        """Add to today's usage unless a cap would be exceeded. False when refused, atomically.

        A `single_document` charge longer than the whole character cap is allowed on a day with
        no characters sent yet.
        """
        ...

    def refund_usage(
        self,
        session: TxSession,
        owner_id: UUID,
        day: date,
        *,
        live: int,
        backfill: int,
        characters: int,
    ) -> None: ...

    # -- bank lifecycle --

    def owners_with_retained_rows(self, session: TxSession) -> list[UUID]:
        """Living owners with a `retained`, non-excluded row, ordered by id."""
        ...

    def living_owner_ids(self, session: TxSession) -> list[UUID]: ...

    def owners_expecting_banks(self, session: TxSession) -> set[UUID]:
        """Owner ids that have a `retained`, non-excluded row (living or not)."""
        ...

    def reset_retained_rows(self, session: TxSession, owner_id: UUID) -> int:
        """Set the owner's `retained`, non-excluded rows to `pending`; returns how many."""
        ...

"""Persistence operations the Journal use cases depend on."""

from datetime import date, datetime, tzinfo
from typing import Protocol
from uuid import UUID

from sidekick.contacts.domain.contact import Contact
from sidekick.journal.domain.day_done import DayDone
from sidekick.journal.domain.entry import EntryHead, JournalEntry, JournalOrder
from sidekick.journal.domain.records import (
    DaySummaryStatus,
    EntryRelations,
    PendingJournalItem,
)
from sidekick.journal.domain.source import JournalSource
from sidekick.journal.domain.summary import DailySummary, SummaryContent
from sidekick.projects.domain import Project
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    IdempotentStore,
    KeyValue,
    TransactionalStore,
    TxSession,
)
from sidekick.tasks.domain import Task
from sidekick.work.domain.tag_assignment import RecordTagStore


class JournalStore(TransactionalStore, IdempotentStore, AuditingStore, RecordTagStore, Protocol):
    """Journal-focused persistence operations used by the manual application service."""

    def save_journal_source(self, session: TxSession, source: JournalSource) -> None: ...

    def get_journal_source(
        self, session: TxSession, owner_id: UUID, source_id: UUID
    ) -> JournalSource: ...

    def save_journal_entry(self, session: TxSession, entry: JournalEntry) -> None: ...

    def get_journal_entry(
        self, session: TxSession, owner_id: UUID, entry_id: UUID
    ) -> JournalEntry: ...

    def list_journal_entries(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        start_date: date,
        end_date: date,
        include_archived: bool = False,
        limit: int = 100,
        after: tuple[KeyValue, ...] | None = None,
        tags: tuple[str, ...] = (),
        tag_match: str = "any",
        order: JournalOrder = "asc",
    ) -> list[JournalEntry]: ...

    def list_pending_journal_items(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        start_date: date,
        end_date: date,
        limit: int = 100,
    ) -> list[PendingJournalItem]: ...

    def journal_source_has_live_replacement(
        self, session: TxSession, owner_id: UUID, source_id: UUID
    ) -> bool: ...

    def supersede_pending_journal_drafts(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        source_id: UUID,
        now: datetime,
        correlation_id: str | None,
    ) -> int: ...

    def add_journal_entry_relations(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        entry_id: UUID,
        project_ids: tuple[UUID, ...],
        task_ids: tuple[UUID, ...],
        contact_ids: tuple[UUID, ...],
    ) -> None: ...

    def remove_journal_entry_relations(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        entry_id: UUID,
        project_ids: tuple[UUID, ...],
        contact_ids: tuple[UUID, ...],
    ) -> None: ...

    def get_journal_entry_relations(
        self, session: TxSession, owner_id: UUID, entry_id: UUID
    ) -> "EntryRelations": ...

    def update_journal_entry(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        entry: JournalEntry,
        expected_version: int,
    ) -> JournalEntry: ...

    def get_daily_summary(
        self, session: TxSession, owner_id: UUID, summary_or_date: UUID | date
    ) -> DailySummary | None: ...

    def get_daily_summary_status(
        self,
        session: TxSession,
        owner_id: UUID,
        journal_date: date,
        *,
        summary: DailySummary | None = ...,
        active: list[EntryHead] | None = None,
    ) -> DaySummaryStatus: ...

    def read_day_done(
        self, session: TxSession, actor: Actor, journal_date: date, zone: tzinfo
    ) -> DayDone: ...

    def get_journal_entries_relations(
        self, session: TxSession, owner_id: UUID, entry_ids: tuple[UUID, ...]
    ) -> dict[UUID, "EntryRelations"]: ...

    def upsert_manual_daily_summary(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        journal_date: date,
        content: SummaryContent,
        expected_entry_fingerprint: str,
        expected_summary_version: int | None,
        now: datetime,
        correlation_id: str | None = None,
    ) -> DailySummary: ...

    def list_active_journal_entry_heads(
        self, session: TxSession, owner_id: UUID, journal_date: date
    ) -> list[EntryHead]: ...
    def mark_daily_journal_summary_stale(
        self, session: TxSession, owner_id: UUID, journal_date: date
    ) -> None: ...

    def get_project(self, session: TxSession, owner_id: UUID, project_id: UUID) -> Project: ...

    def get_task(self, session: TxSession, owner_id: UUID, task_id: UUID) -> Task: ...

    def get_contact(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        include_archived: bool = False,
    ) -> Contact: ...

"""Read-side Journal records that stores return and the application service passes on."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from .source import SourceType


@dataclass(frozen=True, slots=True)
class EntryRelations:
    project_ids: tuple[UUID, ...] = ()
    task_ids: tuple[UUID, ...] = ()
    contact_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationLabels:
    """Display names of an entry's linked Projects and Contacts the actor may read."""

    projects: dict[UUID, str]
    contacts: dict[UUID, str]


@dataclass(frozen=True, slots=True)
class DaySummaryStatus:
    state: str = "missing"
    summary_id: UUID | None = None
    version: int | None = None
    changed_entry_count: int = 0


@dataclass(frozen=True, slots=True)
class PendingJournalItem:
    """A preserved source that still needs manual or AI-assisted review."""

    source_id: UUID
    journal_date: date
    source_type: SourceType
    source_created_at: datetime
    character_count: int
    draft_id: UUID | None = None
    draft_title: str | None = None

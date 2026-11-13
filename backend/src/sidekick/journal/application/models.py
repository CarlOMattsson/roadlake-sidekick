"""Commands, results and payload shapes of the manual Journal use cases."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sidekick.journal.domain.day_done import DayDone
from sidekick.journal.domain.entry import JournalEntry, KeyPoint
from sidekick.journal.domain.records import DaySummaryStatus
from sidekick.journal.domain.source import SourceType
from sidekick.journal.domain.summary import DailySummary

MAX_JOURNAL_RANGE_DAYS = 366
MAX_RELATIONS_PER_KIND = 25


@dataclass(frozen=True, slots=True)
class CreateSourceCommand:
    source_type: SourceType
    journal_date: date
    occurred_at: datetime | None
    source_recorded_at: datetime | None
    raw_text: str
    language: str | None
    replaces_source_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateManualEntryCommand:
    source_id: UUID
    title: str
    summary: str | None
    key_points: tuple[KeyPoint, ...]
    project_ids: tuple[UUID, ...] = ()
    task_ids: tuple[UUID, ...] = ()
    contact_ids: tuple[UUID, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationChange:
    """Links to add to and remove from an existing entry (Projects and Contacts only)."""

    add_project_ids: tuple[UUID, ...] = ()
    remove_project_ids: tuple[UUID, ...] = ()
    add_contact_ids: tuple[UUID, ...] = ()
    remove_contact_ids: tuple[UUID, ...] = ()

    def is_empty(self) -> bool:
        return not (
            self.add_project_ids
            or self.remove_project_ids
            or self.add_contact_ids
            or self.remove_contact_ids
        )

    def payload(self) -> dict[str, list[str]]:
        """The non-empty id lists, for the idempotency fingerprint; empty for no change."""

        fields = {
            "add_project_ids": self.add_project_ids,
            "remove_project_ids": self.remove_project_ids,
            "add_contact_ids": self.add_contact_ids,
            "remove_contact_ids": self.remove_contact_ids,
        }
        return {name: [str(value) for value in ids] for name, ids in fields.items() if ids}


@dataclass(frozen=True, slots=True)
class JournalDay:
    journal_date: date
    entries: tuple[JournalEntry, ...]
    next_cursor: str | None
    summary_status: DaySummaryStatus
    entry_fingerprint: str
    summary: DailySummary | None = None
    done: DayDone = field(default_factory=DayDone)
    """What was completed or bought that day, in the owner's zone. Always present."""


def source_command_data(command: CreateSourceCommand) -> dict[str, Any]:
    return {
        "source_type": command.source_type.value,
        "journal_date": command.journal_date.isoformat(),
        "occurred_at": command.occurred_at.isoformat() if command.occurred_at else None,
        "source_recorded_at": command.source_recorded_at.isoformat()
        if command.source_recorded_at
        else None,
        "raw_text": command.raw_text,
        "language": command.language,
        "replaces_source_id": str(command.replaces_source_id)
        if command.replaces_source_id
        else None,
    }


def manual_entry_command_data(command: CreateManualEntryCommand) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source_id": str(command.source_id),
        "title": command.title,
        "summary": command.summary,
        "key_points": [
            {"kind": point.kind.value, "text": point.text} for point in command.key_points
        ],
        "project_ids": [str(value) for value in command.project_ids],
        "task_ids": [str(value) for value in command.task_ids],
        "contact_ids": [str(value) for value in command.contact_ids],
    }
    # Only a given tag set is hashed, so a replay recorded before tags existed still matches.
    if command.tags:
        data["tags"] = list(command.tags)
    return data

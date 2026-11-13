"""Contact commands and the Journal link read models."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, TypedDict
from uuid import UUID

from sidekick.contacts.domain.contact import Contact
from sidekick.projects.domain import Project
from sidekick.shared.types import UNSET, Page, UnsetType
from sidekick.tasks.domain import Task


@dataclass(frozen=True, slots=True)
class CreateContactCommand:
    display_name: str
    context_note: str | None = None
    email: str | None = None
    phone: str | None = None
    aliases: list[str] | None = None
    relationship: str | None = None
    organization: str | None = None
    role: str | None = None
    address: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdateContactCommand:
    display_name: str | UnsetType = UNSET
    context_note: str | None | UnsetType = UNSET
    email: str | None | UnsetType = UNSET
    phone: str | None | UnsetType = UNSET
    relationship: str | None | UnsetType = UNSET
    organization: str | None | UnsetType = UNSET
    role: str | None | UnsetType = UNSET
    address: str | None | UnsetType = UNSET
    # The complete intended tag set; tags are not a column, so they stay out of `changes()`.
    tags: tuple[str, ...] | UnsetType = UNSET

    def changes(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "display_name": self.display_name,
                "context_note": self.context_note,
                "email": self.email,
                "phone": self.phone,
                "relationship": self.relationship,
                "organization": self.organization,
                "role": self.role,
                "address": self.address,
            }.items()
            if value is not UNSET
        }


JOURNAL_CONTEXT_LIMIT = 10


@dataclass(frozen=True, slots=True)
class LinkedJournalEntry:
    """A Journal entry linked to a Contact: identity, date and title, never content."""

    id: UUID
    journal_date: date
    title: str


@dataclass(frozen=True, slots=True)
class LinkedJournalEntries:
    """Newest linked entries, at most JOURNAL_CONTEXT_LIMIT, empty when not readable."""

    items: list[LinkedJournalEntry]
    has_more: bool
    readable: bool


class TaskContactMarks(TypedDict):
    """What a linked Task says about the Contact it is read for."""

    waiting_on_contact: bool
    waiting_since: datetime | None
    follow_up_at: datetime | None
    follow_up_due: bool


@dataclass(frozen=True, slots=True)
class TaskProgress:
    """How many of a Project's active Tasks there are, and how many of them are completed."""

    total: int
    done: int


@dataclass(frozen=True, slots=True)
class ContactContext:
    """A Contact with its linked Projects (and their Task progress), Tasks and Journal entries."""

    contact: Contact
    projects: Page[Project]
    project_progress: dict[UUID, TaskProgress]
    tasks: Page[Task]
    task_marks: dict[UUID, TaskContactMarks]
    journal_entries: LinkedJournalEntries

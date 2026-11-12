"""Contact commands and the Journal link read models."""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sidekick.shared.types import UNSET, UnsetType


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

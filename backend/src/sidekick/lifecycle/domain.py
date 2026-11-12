"""Pure types for the closed record lifecycle surface."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

ChangeAction = Literal[
    "created",
    "updated",
    "completed",
    "archived",
    "restored",
    "trashed",
    "purchased",
    "reopened",
]
ChangeState = Literal["active", "trashed"]
ChangeActor = Literal["you", "claude", "unknown"]


class RecordKind(StrEnum):
    DOMAIN = "domain"
    PROCESS = "process"
    PROJECT = "project"
    TASK = "task"
    STEP = "step"
    ACTION = "action"
    CONTACT = "contact"
    JOURNAL_SOURCE = "journal_source"
    JOURNAL_ENTRY = "journal_entry"
    SHOPPING_ITEM = "shopping_item"


@dataclass(frozen=True, slots=True)
class TrashItem:
    kind: RecordKind
    id: UUID
    label: str
    trashed_at: datetime | None
    version: int


@dataclass(frozen=True, slots=True)
class TrashPosition:
    """Sort key of one trashed record: the keyset a trash page continues after.

    The trash is ordered by this key, descending, so the order is total and stable even when
    records share a trash time. Positions survive records being restored or trashed between pages.
    """

    trashed_at: datetime
    kind: RecordKind
    id: UUID

    def to_token(self) -> str:
        return f"{self.trashed_at.isoformat()}|{self.kind.value}|{self.id}"

    @classmethod
    def from_token(cls, token: str) -> "TrashPosition":
        """Parse a token written by `to_token`; anything else is a ValueError."""

        trashed_at, kind, record_id = token.split("|")
        parsed = datetime.fromisoformat(trashed_at)
        if parsed.tzinfo is None:
            raise ValueError("trash position needs a timezone")
        return cls(parsed, RecordKind(kind), UUID(record_id))

    @classmethod
    def of(cls, item: TrashItem) -> "TrashPosition":
        if item.trashed_at is None:
            raise ValueError("only a trashed record has a trash position")
        return cls(item.trashed_at, item.kind, item.id)

    def sort_key(self) -> tuple[datetime, str, UUID]:
        return (self.trashed_at, self.kind.value, self.id)


@dataclass(frozen=True, slots=True)
class ChangeRecordView:
    """The current state of one record, read from the record itself and never from audit text."""

    title: str
    version: int
    trashed: bool


@dataclass(frozen=True, slots=True)
class RecentChange:
    """One owner change from the audit trail, with the record's current title and version."""

    kind: str
    id: UUID
    title: str
    version: int
    action: ChangeAction
    state: ChangeState
    occurred_at: datetime
    # The other side of a link change (task, project or contact); None for single-record changes.
    related_id: UUID | None = None
    # Who made it: the owner in the app, Claude through a tool, or unknown (not recorded).
    actor: ChangeActor = "unknown"
    # A model-visible tool that undoes this change; None when the undo is only possible in the app.
    undo_tool: str | None = None

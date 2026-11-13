"""Explicit Task child entities with independent optimistic versions."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import NamedTuple
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.shared.types import UNSET, UnsetType
from sidekick.tasks.domain import TaskStatus
from sidekick.work.domain.planning import MAX_ACTION_NOTE_LENGTH, MAX_STEP_INSTRUCTION_LENGTH


class ActionStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"


class ActionCounts(NamedTuple):
    """How many active Actions a Step has and how many of them are completed."""

    active: int
    completed: int


@dataclass(frozen=True, slots=True)
class Step:
    id: UUID
    owner_id: UUID
    task_id: UUID
    title: str
    status: TaskStatus
    position: int
    due_at: datetime | None
    attention_requested: bool
    created_at: datetime
    updated_at: datetime
    version: int = 1
    archived_at: datetime | None = None
    instruction: str | None = None
    """How this step is performed. Especially useful for recurring work."""
    completed_at: datetime | None = None
    """When the step was ticked off; cleared when it is opened again. Older steps have none."""

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title or len(title) > 200:
            raise ValidationError("step title must contain 1-200 characters")
        if self.position < 0 or self.version < 1:
            raise ValidationError("step position and version must be non-negative/positive")
        if self.instruction is not None and len(self.instruction) > MAX_STEP_INSTRUCTION_LENGTH:
            raise ValidationError("step instruction is too long")
        object.__setattr__(self, "title", title)

    def update(
        self,
        *,
        now: datetime,
        title: str | UnsetType = UNSET,
        status: TaskStatus | UnsetType = UNSET,
        due_at: datetime | None | UnsetType = UNSET,
        attention_requested: bool | UnsetType = UNSET,
        instruction: str | None | UnsetType = UNSET,
    ) -> "Step":
        changes = {
            key: value
            for key, value in {
                "title": title,
                "status": status,
                "due_at": due_at,
                "attention_requested": attention_requested,
                "instruction": instruction,
            }.items()
            if value is not UNSET
        }
        if not changes:
            raise ValidationError("at least one step change is required")
        if status is not UNSET and status != self.status:
            changes["completed_at"] = now if status is TaskStatus.COMPLETED else None
        candidate = replace(self, **changes)
        if candidate == self:
            return self
        return replace(candidate, updated_at=now, version=self.version + 1)

    def complete(self, *, now: datetime) -> "Step":
        if self.status is TaskStatus.COMPLETED:
            return self
        return replace(
            self,
            status=TaskStatus.COMPLETED,
            completed_at=now,
            updated_at=now,
            version=self.version + 1,
        )

    def archive(self, *, now: datetime) -> "Step":
        if self.archived_at is not None:
            return self
        return replace(self, archived_at=now, updated_at=now, version=self.version + 1)

    def restore(self, *, now: datetime) -> "Step":
        if self.archived_at is None:
            return self
        return replace(self, archived_at=None, updated_at=now, version=self.version + 1)

    def move(self, *, position: int, now: datetime) -> "Step":
        if position < 0:
            raise ValidationError("step position must be non-negative")
        return replace(self, position=position, updated_at=now, version=self.version + 1)


@dataclass(frozen=True, slots=True)
class Action:
    id: UUID
    owner_id: UUID
    step_id: UUID
    title: str
    status: ActionStatus
    position: int
    due_at: datetime | None
    attention_requested: bool
    created_at: datetime
    updated_at: datetime
    version: int = 1
    archived_at: datetime | None = None
    note: str | None = None
    """One short note. An Action stays short and concrete by design."""

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title or len(title) > 200:
            raise ValidationError("action title must contain 1-200 characters")
        if self.position < 0 or self.version < 1:
            raise ValidationError("action position and version must be non-negative/positive")
        if self.note is not None and len(self.note) > MAX_ACTION_NOTE_LENGTH:
            raise ValidationError("action note is too long")
        object.__setattr__(self, "title", title)

    def complete(self, *, now: datetime) -> "Action":
        if self.status is ActionStatus.COMPLETED:
            return self
        return replace(
            self, status=ActionStatus.COMPLETED, updated_at=now, version=self.version + 1
        )

    def update(
        self,
        *,
        now: datetime,
        title: str | UnsetType = UNSET,
        status: ActionStatus | UnsetType = UNSET,
        due_at: datetime | None | UnsetType = UNSET,
        attention_requested: bool | UnsetType = UNSET,
        note: str | None | UnsetType = UNSET,
    ) -> "Action":
        changes = {
            key: value
            for key, value in {
                "title": title,
                "status": status,
                "due_at": due_at,
                "attention_requested": attention_requested,
                "note": note,
            }.items()
            if value is not UNSET
        }
        if not changes:
            raise ValidationError("at least one action change is required")
        candidate = replace(self, **changes)
        if candidate == self:
            return self
        return replace(candidate, updated_at=now, version=self.version + 1)

    def archive(self, *, now: datetime) -> "Action":
        if self.archived_at is not None:
            return self
        return replace(self, archived_at=now, updated_at=now, version=self.version + 1)

    def restore(self, *, now: datetime) -> "Action":
        if self.archived_at is None:
            return self
        return replace(self, archived_at=None, updated_at=now, version=self.version + 1)

    def move(self, *, position: int, now: datetime) -> "Action":
        if position < 0:
            raise ValidationError("action position must be non-negative")
        return replace(self, position=position, updated_at=now, version=self.version + 1)

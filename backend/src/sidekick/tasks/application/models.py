"""Commands, read models and limits of the Task use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict
from uuid import UUID

from sidekick.shared.cadence import Cadence
from sidekick.shared.types import UNSET, UnsetType
from sidekick.tasks.domain import Priority, RecurrenceRule, Task, TaskStatus
from sidekick.work.domain import Step
from sidekick.work.domain.planning import WorkTag


@dataclass(frozen=True, slots=True)
class UpdateTaskCommand:
    """Explicit mutable Task fields; omitted and null remain distinct."""

    project_id: UUID | UnsetType | None = UNSET
    title: str | UnsetType = UNSET
    description: str | UnsetType | None = UNSET
    status: TaskStatus | UnsetType = UNSET
    priority: Priority | UnsetType = UNSET
    due_at: datetime | UnsetType | None = UNSET
    domain_id: UUID | UnsetType | None = UNSET
    process_id: UUID | UnsetType | None = UNSET
    attention_requested: bool | UnsetType = UNSET
    not_before: datetime | UnsetType | None = UNSET
    estimated_minutes: int | UnsetType | None = UNSET
    waiting_since: datetime | UnsetType | None = UNSET
    follow_up_at: datetime | UnsetType | None = UNSET
    waiting_on_contact_id: UUID | UnsetType | None = UNSET
    blocked_reminder_cadence: Cadence | UnsetType | None = UNSET
    blocked_reminder_snoozed_until: datetime | UnsetType | None = UNSET
    recurrence: RecurrenceRule | dict[str, Any] | UnsetType | None = UNSET
    last_completed_at: datetime | UnsetType | None = UNSET
    """Undo of a recurring completion: an earlier value (or null); never moves it forward."""
    tags: tuple[str, ...] | UnsetType = UNSET
    """The record's complete intended tag set; applied inside this same update."""

    def changes(self) -> dict[str, Any]:
        """Only Task fields. Tags are links and are applied separately."""

        return {
            key: value
            for key, value in {
                "project_id": self.project_id,
                "title": self.title,
                "description": self.description,
                "status": self.status,
                "priority": self.priority,
                "due_at": self.due_at,
                "domain_id": self.domain_id,
                "process_id": self.process_id,
                "attention_requested": self.attention_requested,
                "not_before": self.not_before,
                "estimated_minutes": self.estimated_minutes,
                "waiting_since": self.waiting_since,
                "follow_up_at": self.follow_up_at,
                "waiting_on_contact_id": self.waiting_on_contact_id,
                "blocked_reminder_cadence": self.blocked_reminder_cadence,
                "blocked_reminder_snoozed_until": self.blocked_reminder_snoozed_until,
                "recurrence": self.recurrence,
                "last_completed_at": self.last_completed_at,
            }.items()
            if value is not UNSET
        }

    def has_changes(self) -> bool:
        return bool(self.changes()) or self.tags is not UNSET


@dataclass(frozen=True, slots=True)
class TaskDetailRead:
    """One owned Task with what its detail view names, read in a single transaction."""

    task: Task
    tags: list[WorkTag]
    project_title: str | None
    """The Project's full title; the caller clips it the way a Work record does."""
    step_counts: dict[str, int]
    steps: list[Step]


@dataclass(frozen=True, slots=True)
class RescheduleTaskItem:
    """One Task's new due date, at the version the caller read; `due_at=None` clears it."""

    task_id: UUID
    expected_version: int
    due_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewTaskItem:
    """One Task of a batch create, with its Steps as titles in the order they are created."""

    title: str
    due_at: datetime | None
    priority: Priority
    tags: tuple[str, ...]
    step_titles: tuple[str, ...]


class BatchStep(TypedDict):
    """One Step a batch created, as the reply lists it."""

    id: str
    title: str
    position: int
    version: int


@dataclass(frozen=True, slots=True)
class BatchCreatedTask:
    """A Task of a batch as committed, with its Steps as plain step result data."""

    task: Task
    steps: tuple[BatchStep, ...]


@dataclass(frozen=True, slots=True)
class TaskBatch:
    """The committed batch; `container_label` is the Project or Domain title, or None."""

    container_label: str | None
    tasks: tuple[BatchCreatedTask, ...]


@dataclass(frozen=True, slots=True)
class BoardPlacement:
    """Committed manual position of one Task inside a board status column."""

    task_id: UUID
    board_rank: int
    version: int


MAX_BOARD_COLUMN_REORDER = 100
MAX_RESCHEDULE_TASKS = 20
MAX_BATCH_CREATE_TASKS = 20
MAX_BATCH_STEPS_PER_TASK = 10

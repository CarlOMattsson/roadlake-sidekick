"""Task domain entity and lifecycle invariants."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, tzinfo
from enum import StrEnum
from typing import cast
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.shared.types import UNSET, UnsetType
from sidekick.work.domain.planning import (
    Cadence,
    is_follow_up_due,
    is_waiting,
    validate_estimated_minutes,
    validate_waiting,
)

from .recurrence import RecurrenceRule


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass(frozen=True, slots=True)
class TaskStatusHistory:
    id: UUID
    owner_id: UUID
    task_id: UUID
    from_status: TaskStatus | None
    to_status: TaskStatus
    changed_at: datetime
    source: str


@dataclass(frozen=True, slots=True)
class Task:
    id: UUID
    owner_id: UUID
    project_id: UUID | None
    title: str
    description: str | None
    status: TaskStatus
    priority: Priority
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int = 1
    domain_id: UUID | None = None
    process_id: UUID | None = None
    derived_domain_id: UUID | None = None
    attention_requested: bool = False
    archived_at: datetime | None = None
    board_rank: int | None = None
    """Manual position inside one board status column.

    Presentation ordering only: it expresses no dependency, priority, or schedule.
    """
    not_before: datetime | None = None
    """Earliest time the work is sensible to start. Read by derivation only."""
    estimated_minutes: int | None = None
    """Expected working time in whole minutes. Never aggregated in this change."""
    waiting_since: datetime | None = None
    follow_up_at: datetime | None = None
    waiting_on_contact_id: UUID | None = None
    blocked_reminder_cadence: Cadence | None = None
    blocked_reminder_snoozed_until: datetime | None = None
    blocked_last_reminded_at: datetime | None = None
    recurrence: RecurrenceRule | None = None
    last_completed_at: datetime | None = None

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title or len(title) > 200:
            raise ValidationError("task title must contain 1-200 characters")
        if self.description is not None and len(self.description) > 10_000:
            raise ValidationError("task description is too long")
        if (self.status is TaskStatus.COMPLETED) != (self.completed_at is not None):
            raise ValidationError("completion status and timestamp must agree")
        if (
            sum(value is not None for value in (self.domain_id, self.process_id, self.project_id))
            > 1
        ):
            raise ValidationError(
                "task context must select at most one of domain, process, or project"
            )
        if (
            self.not_before is not None
            and self.due_at is not None
            and self.not_before > self.due_at
        ):
            raise ValidationError(
                "earliest start cannot be later than the due date",
                reason="not_before_after_due",
            )
        validate_estimated_minutes(self.estimated_minutes)
        validate_waiting(
            waiting_since=self.waiting_since,
            follow_up_at=self.follow_up_at,
            waiting_on_contact_id=self.waiting_on_contact_id,
        )
        if self.blocked_reminder_cadence is not None and not isinstance(
            cast(object, self.blocked_reminder_cadence), Cadence
        ):
            raise ValidationError("unsupported blocked reminder cadence")
        if (
            self.status is not TaskStatus.BLOCKED
            and self.blocked_reminder_snoozed_until is not None
        ):
            raise ValidationError("blocked reminder snooze requires a blocked Task")
        object.__setattr__(self, "title", title)

    @property
    def waiting(self) -> bool:
        """Waiting is orthogonal to status: a Task can be in progress and waiting."""

        return is_waiting(
            waiting_since=self.waiting_since, completed=self.status is TaskStatus.COMPLETED
        )

    def follow_up_due(self, *, now: datetime) -> bool:
        return is_follow_up_due(
            waiting_since=self.waiting_since,
            follow_up_at=self.follow_up_at,
            completed=self.status is TaskStatus.COMPLETED,
            now=now,
        )

    def blocked_reminder_due(self, *, now: datetime) -> bool:
        """Whether this blocked Task should be surfaced again right now."""

        if self.status is not TaskStatus.BLOCKED or self.blocked_reminder_cadence is None:
            return False
        if (
            self.blocked_reminder_snoozed_until is not None
            and self.blocked_reminder_snoozed_until > now
        ):
            return False
        if self.blocked_last_reminded_at is None:
            return True
        return self.blocked_last_reminded_at + self.blocked_reminder_cadence.interval <= now

    def update(
        self,
        *,
        now: datetime,
        project_id: UUID | None | UnsetType = UNSET,
        title: str | UnsetType = UNSET,
        description: str | None | UnsetType = UNSET,
        status: TaskStatus | UnsetType = UNSET,
        priority: Priority | UnsetType = UNSET,
        due_at: datetime | None | UnsetType = UNSET,
        domain_id: UUID | None | UnsetType = UNSET,
        process_id: UUID | None | UnsetType = UNSET,
        attention_requested: bool | UnsetType = UNSET,
        not_before: datetime | None | UnsetType = UNSET,
        estimated_minutes: int | None | UnsetType = UNSET,
        waiting_since: datetime | None | UnsetType = UNSET,
        follow_up_at: datetime | None | UnsetType = UNSET,
        waiting_on_contact_id: UUID | None | UnsetType = UNSET,
        blocked_reminder_cadence: Cadence | None | UnsetType = UNSET,
        blocked_reminder_snoozed_until: datetime | None | UnsetType = UNSET,
        recurrence: RecurrenceRule | None | UnsetType = UNSET,
        last_completed_at: datetime | None | UnsetType = UNSET,
    ) -> "Task":
        """Apply only mutable Task fields while preserving completion invariants.

        Clearing `waiting_since` clears the follow-up time and the waiting Contact in
        the same change, so a stale follow-up cannot outlive the waiting it explained.

        `last_completed_at` is the undo of a recurring completion: it can only be set back to an
        earlier value (or cleared) on a recurring Task, never forward, so it cannot claim a
        completion that did not happen.
        """

        changes = {
            key: value
            for key, value in {
                "project_id": project_id,
                "title": title,
                "description": description,
                "status": status,
                "priority": priority,
                "due_at": due_at,
                "domain_id": domain_id,
                "process_id": process_id,
                "attention_requested": attention_requested,
                "not_before": not_before,
                "estimated_minutes": estimated_minutes,
                "waiting_since": waiting_since,
                "follow_up_at": follow_up_at,
                "waiting_on_contact_id": waiting_on_contact_id,
                "blocked_reminder_cadence": blocked_reminder_cadence,
                "blocked_reminder_snoozed_until": blocked_reminder_snoozed_until,
                "recurrence": recurrence,
                "last_completed_at": last_completed_at,
            }.items()
            if value is not UNSET
        }
        if not changes:
            raise ValidationError("at least one task change is required")
        if last_completed_at is not UNSET and last_completed_at != self.last_completed_at:
            if changes.get("recurrence", self.recurrence) is None:
                raise ValidationError("only a recurring task has a last completion to restore")
            if last_completed_at is not None and (
                self.last_completed_at is None or last_completed_at > self.last_completed_at
            ):
                raise ValidationError("last completion can only be restored to an earlier value")
        if (
            changes.get("status", self.status) is not TaskStatus.BLOCKED
            and self.status is TaskStatus.BLOCKED
        ):
            changes["blocked_reminder_snoozed_until"] = None
        if waiting_since is None:
            if follow_up_at not in (UNSET, None) or waiting_on_contact_id not in (UNSET, None):
                raise ValidationError(
                    "clearing waiting cannot set a follow-up time or waiting contact"
                )
            changes["follow_up_at"] = None
            changes["waiting_on_contact_id"] = None
        elif changes.get("waiting_since", self.waiting_since) is None:
            validate_waiting(
                waiting_since=None,
                follow_up_at=self.follow_up_at if follow_up_at is UNSET else follow_up_at,
                waiting_on_contact_id=(
                    self.waiting_on_contact_id
                    if waiting_on_contact_id is UNSET
                    else waiting_on_contact_id
                ),
            )
        next_status = changes.get("status", self.status)
        next_context = {
            "project_id": changes.get("project_id", self.project_id),
            "domain_id": changes.get("domain_id", self.domain_id),
            "process_id": changes.get("process_id", self.process_id),
        }
        if sum(value is not None for value in next_context.values()) > 1:
            raise ValidationError(
                "task context must select at most one of domain, process, or project"
            )
        if next_status is TaskStatus.COMPLETED:
            changes.setdefault("completed_at", self.completed_at or now)
        else:
            changes["completed_at"] = None
        return replace(self, **changes, updated_at=now, version=self.version + 1)

    def reopen_for_recurrence(self, *, now: datetime, zone: tzinfo = UTC) -> "Task":
        """Record a completed cycle by reopening the same Task for its next run."""

        if self.recurrence is None or self.status is not TaskStatus.COMPLETED:
            return self
        next_due = self.recurrence.next_due_at(now, zone)
        if next_due is None:
            return self
        return replace(
            self,
            status=TaskStatus.TODO,
            completed_at=None,
            due_at=next_due,
            blocked_reminder_snoozed_until=None,
            last_completed_at=now,
            updated_at=now,
            version=self.version + 1,
        )

    def rank_on_board(self, *, position: int, now: datetime) -> "Task":
        """Place the Task at a dense one-based position in its status column."""

        if position < 1:
            raise ValidationError("board position must be one or greater")
        if self.board_rank == position:
            return self
        return replace(self, board_rank=position, updated_at=now, version=self.version + 1)

    def complete(self, *, now: datetime, zone: tzinfo = UTC) -> "Task":
        if self.status is TaskStatus.COMPLETED:
            return self
        completed = replace(
            self,
            status=TaskStatus.COMPLETED,
            completed_at=now,
            blocked_reminder_snoozed_until=None,
            updated_at=now,
            version=self.version + 1,
        )
        return completed.reopen_for_recurrence(now=now, zone=zone)

    def archive(self, *, now: datetime) -> "Task":
        if self.archived_at is not None:
            return self
        return replace(self, archived_at=now, updated_at=now, version=self.version + 1)

    def restore(self, *, now: datetime) -> "Task":
        if self.archived_at is None:
            return self
        return replace(self, archived_at=None, updated_at=now, version=self.version + 1)


def derive_domain_id(
    task: Task,
    process_domains: Mapping[UUID, UUID],
    project_domains: Mapping[UUID, UUID],
) -> UUID | None:
    """The Domain a Task belongs to: its own, else its Process's, else its Project's.

    A Task selects exactly one context, so the Domain of a Process or Project is read from the
    given maps (batch-loaded by the caller). A parent missing from its map gives no Domain.
    """

    if task.domain_id is not None:
        return task.domain_id
    if task.process_id is not None:
        return process_domains.get(task.process_id)
    if task.project_id is not None:
        return project_domains.get(task.project_id)
    return None

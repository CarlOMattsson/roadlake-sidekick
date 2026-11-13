"""Pure Process-run entities and the bounded Task template."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.tasks.domain import Priority
from sidekick.tasks.domain.planning import validate_estimated_minutes
from sidekick.work.domain.planning import MAX_ACTION_NOTE_LENGTH, MAX_STEP_INSTRUCTION_LENGTH

if TYPE_CHECKING:
    from .context import Process

MAX_PROCESS_RUN_STEPS = 32
MAX_PROCESS_RUN_ACTIONS_PER_STEP = 32


@dataclass(frozen=True, slots=True)
class ProcessRunActionTemplate:
    """One bounded Action copied into a newly materialized Step."""

    title: str
    note: str | None = None
    due_after_days: int | None = None

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title or len(title) > 200:
            raise ValidationError("run action template title must contain 1-200 characters")
        if self.note is not None and len(self.note) > MAX_ACTION_NOTE_LENGTH:
            raise ValidationError("run action template note is too long")
        if self.due_after_days is not None and not 0 <= self.due_after_days <= 365:
            raise ValidationError("run action due offset must be between 0 and 365 days")
        object.__setattr__(self, "title", title)


@dataclass(frozen=True, slots=True)
class ProcessRunStepTemplate:
    """One bounded Step and its Actions copied into a newly materialized Task."""

    title: str
    instruction: str | None = None
    due_after_days: int | None = None
    actions: tuple[ProcessRunActionTemplate, ...] = ()

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title or len(title) > 200:
            raise ValidationError("run step template title must contain 1-200 characters")
        if self.instruction is not None and len(self.instruction) > MAX_STEP_INSTRUCTION_LENGTH:
            raise ValidationError("run step template instruction is too long")
        if self.due_after_days is not None and not 0 <= self.due_after_days <= 365:
            raise ValidationError("run step due offset must be between 0 and 365 days")
        if len(self.actions) > MAX_PROCESS_RUN_ACTIONS_PER_STEP:
            raise ValidationError("run step template has too many actions")
        if not all(
            isinstance(cast(object, action), ProcessRunActionTemplate) for action in self.actions
        ):
            raise ValidationError("run step template actions are invalid")
        object.__setattr__(self, "title", title)


@dataclass(frozen=True, slots=True)
class ProcessRunTemplate:
    """The Task fields copied into each new Process run."""

    id: UUID
    owner_id: UUID
    process_id: UUID
    title: str
    description: str | None
    priority: Priority
    estimated_minutes: int | None
    due_after_days: int
    version: int
    created_at: datetime
    updated_at: datetime
    steps: tuple[ProcessRunStepTemplate, ...] = ()

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title or len(title) > 200:
            raise ValidationError("run template title must contain 1-200 characters")
        if self.description is not None and len(self.description) > 10_000:
            raise ValidationError("run template description is too long")
        if not isinstance(cast(object, self.priority), Priority):
            raise ValidationError("unsupported run template priority")
        validate_estimated_minutes(self.estimated_minutes)
        if not 0 <= self.due_after_days <= 365:
            raise ValidationError("run template due offset must be between 0 and 365 days")
        if self.version < 1:
            raise ValidationError("run template version must be positive")
        if len(self.steps) > MAX_PROCESS_RUN_STEPS:
            raise ValidationError("run template has too many steps")
        if not all(isinstance(cast(object, step), ProcessRunStepTemplate) for step in self.steps):
            raise ValidationError("run template steps are invalid")
        object.__setattr__(self, "title", title)


@dataclass(frozen=True, slots=True)
class ProcessRun:
    """One immutable link between a scheduled period and its Task instance."""

    id: UUID
    owner_id: UUID
    process_id: UUID
    task_id: UUID
    scheduled_for: datetime
    template_version: int
    created_at: datetime

    def __post_init__(self) -> None:
        if self.template_version < 1:
            raise ValidationError("process run template version must be positive")


@dataclass(frozen=True, slots=True)
class ProcessRunOutbox:
    """One durable scheduled-run intent and its delivery attempt state."""

    id: UUID
    owner_id: UUID
    process_id: UUID
    scheduled_for: datetime
    status: str
    attempts: int
    worker_id: str | None
    claimed_at: datetime | None
    processed_at: datetime | None
    process_run_id: UUID | None
    last_error: str | None

    def __post_init__(self) -> None:
        if self.status not in {"queued", "processing", "delivered", "failed"}:
            raise ValidationError("process run outbox status is invalid")
        if self.attempts < 0:
            raise ValidationError("process run outbox attempts must be non-negative")


MAX_PROCESS_RUNS = 100


class ProcessRunScheduleState(StrEnum):
    """The server-owned schedule marker compared with the current clock."""

    NOT_SCHEDULED = "not_scheduled"
    ON_TRACK = "on_track"
    OVERDUE = "overdue"


@dataclass(frozen=True, slots=True)
class ProcessRunReconciliation:
    """A bounded, read-only explanation of a Process run schedule."""

    state: ProcessRunScheduleState
    expected_next_run_at: datetime | None
    missed_run_count: int
    missed_run_count_is_bounded: bool
    latest_scheduled_for: datetime | None


def reconcile_process_schedule(
    process: "Process",
    latest_scheduled_for: datetime | None,
    *,
    now: datetime,
) -> ProcessRunReconciliation:
    marker = process.next_expected_run_at
    if process.cadence is None or marker is None:
        return ProcessRunReconciliation(
            state=ProcessRunScheduleState.NOT_SCHEDULED,
            expected_next_run_at=marker,
            missed_run_count=0,
            missed_run_count_is_bounded=False,
            latest_scheduled_for=latest_scheduled_for,
        )
    if marker > now:
        return ProcessRunReconciliation(
            state=ProcessRunScheduleState.ON_TRACK,
            expected_next_run_at=marker,
            missed_run_count=0,
            missed_run_count_is_bounded=False,
            latest_scheduled_for=latest_scheduled_for,
        )
    elapsed_periods = (now - marker) // process.cadence.interval
    missed_count = elapsed_periods + 1
    bounded = missed_count > MAX_PROCESS_RUNS
    return ProcessRunReconciliation(
        state=ProcessRunScheduleState.OVERDUE,
        expected_next_run_at=marker,
        missed_run_count=min(missed_count, MAX_PROCESS_RUNS),
        missed_run_count_is_bounded=bounded,
        latest_scheduled_for=latest_scheduled_for,
    )


def run_steps_to_data(steps: tuple[ProcessRunStepTemplate, ...]) -> list[dict[str, object]]:
    return [
        {
            "title": step.title,
            "instruction": step.instruction,
            "due_after_days": step.due_after_days,
            "actions": [
                {
                    "title": action.title,
                    "note": action.note,
                    "due_after_days": action.due_after_days,
                }
                for action in step.actions
            ],
        }
        for step in steps
    ]


def run_steps_from_data(data: object) -> tuple[ProcessRunStepTemplate, ...]:
    if not isinstance(data, list):
        raise ValidationError("run template steps must be a list")
    steps: list[ProcessRunStepTemplate] = []
    for raw_step_value in cast("list[object]", data):
        if not isinstance(raw_step_value, dict):
            raise ValidationError("run template step is invalid")
        raw_step = cast("dict[str, Any]", raw_step_value)
        raw_actions: object = raw_step.get("actions", [])
        if not isinstance(raw_actions, list):
            raise ValidationError("run template actions must be a list")
        action_values = cast("list[object]", raw_actions)
        action_dicts = [
            cast("dict[str, Any]", raw_action)
            for raw_action in action_values
            if isinstance(raw_action, dict)
        ]
        actions = tuple(
            ProcessRunActionTemplate(
                title=str(raw_action.get("title", "")),
                note=raw_action.get("note"),
                due_after_days=raw_action.get("due_after_days"),
            )
            for raw_action in action_dicts
        )
        if len(actions) != len(action_values):
            raise ValidationError("run template action is invalid")
        steps.append(
            ProcessRunStepTemplate(
                title=str(raw_step.get("title", "")),
                instruction=raw_step.get("instruction"),
                due_after_days=raw_step.get("due_after_days"),
                actions=actions,
            )
        )
    return tuple(steps)

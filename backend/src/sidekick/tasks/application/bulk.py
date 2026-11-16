"""Atomic multi-Task writes: reschedule or review several Tasks, create a batch with Steps.

Each runs every Task through the single-Task use cases of `TaskService` inside one transaction,
so validation, versions, status history and audit are the same as for a single write.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.shared.replay import IdRecord, items_replay_record
from sidekick.shared.types import Actor, TxSession, new_uuid7
from sidekick.tasks.application.models import (
    MAX_BATCH_CREATE_TASKS,
    MAX_BATCH_STEPS_PER_TASK,
    MAX_RESCHEDULE_TASKS,
    MAX_REVIEW_DECISIONS,
    BatchCreatedTask,
    BatchStep,
    NewTaskItem,
    RescheduleTaskItem,
    ReviewDecisionItem,
    ReviewedTask,
    ReviewPrevious,
    TaskBatch,
    UpdateTaskCommand,
)
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.tasks.domain.review import ReviewDecision
from sidekick.work.domain import Step

if TYPE_CHECKING:
    from sidekick.tasks.application.service import TaskService


class _CreatedEntry(TypedDict):
    task: IdRecord
    steps: list[BatchStep]


class _BatchResult(TypedDict):
    tasks: list[_CreatedEntry]


class _ReplayEntry(TypedDict):
    task: IdRecord
    steps: NotRequired[list[IdRecord]]
    """Missing in records written before Step ids were kept."""


class _BatchReplay(TypedDict):
    tasks: list[_ReplayEntry]


def task_batch_replay_record(result: _BatchResult) -> _BatchReplay:
    """Idempotency projection of a created batch: Task ids and Step ids; the rest is re-read.

    Records written before Step ids were kept have no `steps` key per entry; the replay reads
    those with a fallback (see `TaskBulkService._replayed_steps`).
    """

    return {
        "tasks": [
            {
                "task": {"id": entry["task"]["id"]},
                "steps": [{"id": step["id"]} for step in entry["steps"]],
            }
            for entry in result["tasks"]
        ]
    }


# A replay record holds no text, so the status a Task had is kept as a fixed code. The codes are
# stored in replay records and must never be renumbered.
_STATUS_CODES: dict[TaskStatus, int] = {
    TaskStatus.TODO: 0,
    TaskStatus.IN_PROGRESS: 1,
    TaskStatus.BLOCKED: 2,
    TaskStatus.COMPLETED: 3,
}
_STATUS_BY_CODE = {code: status for status, code in _STATUS_CODES.items()}


class _StoredPrevious(TypedDict):
    status: int
    due_at: str | None
    waiting_since: str | None
    follow_up_at: str | None
    attention_requested: bool
    last_completed_at: str | None
    archived_at: str | None


class _ReviewEntry(TypedDict):
    """One reviewed Task in the replay record. The decision is not stored: a replay carries the
    same items as the first call, so it is read from them."""

    id: str
    previous: _StoredPrevious


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _stored_previous(task: Task) -> _StoredPrevious:
    """The fields a review decision may change, as `task` has them: what an undo restores."""

    return {
        "status": _STATUS_CODES[task.status],
        "due_at": _iso(task.due_at),
        "waiting_since": _iso(task.waiting_since),
        "follow_up_at": _iso(task.follow_up_at),
        "attention_requested": task.attention_requested,
        "last_completed_at": _iso(task.last_completed_at),
        "archived_at": _iso(task.archived_at),
    }


def _review_previous(stored: _StoredPrevious) -> ReviewPrevious:
    return {**stored, "status": _STATUS_BY_CODE[stored["status"]].value}


def _review_changes(item: ReviewDecisionItem, before: Task, now: datetime) -> dict[str, Any]:
    """The Task fields a decision sets, less those that already have that value.

    `keep` sets none; neither does a decision that would change nothing (waiting on a Task that
    is already waiting, flagging a flagged one), which is then recorded as kept.
    """

    wanted: dict[str, Any] = {}
    if item.decision is ReviewDecision.DONE:
        wanted["status"] = TaskStatus.COMPLETED
    elif item.decision is ReviewDecision.MOVE:
        wanted["due_at"] = item.due_at
    elif item.decision is ReviewDecision.WAITING:
        wanted["waiting_since"] = before.waiting_since or now
        if item.follow_up_at is not None:
            wanted["follow_up_at"] = item.follow_up_at
    elif item.decision is ReviewDecision.FLAG:
        wanted["attention_requested"] = True
    elif item.decision is ReviewDecision.AMBITION:
        return {} if before.ambition_since is not None else {"ambition": True}
    return {field: value for field, value in wanted.items() if getattr(before, field) != value}


def _require_keepable_ambitions(
    items: Sequence[ReviewDecisionItem], befores: Sequence[Task], now: datetime
) -> None:
    """Refuse the whole call, before anything is written, if an `ambition` decision cannot apply.

    A completed or repeating Task cannot be kept as an ambition. The error names the decision's
    position and Task id, never the title.
    """

    for index, (item, before) in enumerate(zip(items, befores, strict=True)):
        if item.decision is not ReviewDecision.AMBITION:
            continue
        try:
            before.ambition_change(True, now=now)
        except ValidationError as error:
            raise ValidationError(
                f"review item {index} (task {item.task_id}) cannot be kept as an ambition",
                reason="not_an_ambition",
            ) from error


def _own_fields(item: NewTaskItem) -> dict[str, str]:
    """The fields an item sets itself, as strings. Absent when unset, so the idempotency payload of
    a batch that sets none is unchanged and a retry of an older key still matches."""

    own: dict[str, str] = {}
    if item.description is not None:
        own["description"] = item.description
    if item.project_id is not None:
        own["project_id"] = str(item.project_id)
    if item.domain_id is not None:
        own["domain_id"] = str(item.domain_id)
    return own


def _placement(
    item: NewTaskItem, project_id: UUID | None, domain_id: UUID | None
) -> tuple[UUID | None, UUID | None]:
    """The (project, domain) an item goes to: its own, or the batch's when it names none.

    A Task has at most one of project, process and domain, so an item's own placement replaces the
    batch's whole, not field by field.
    """

    if item.project_id or item.domain_id:
        return item.project_id, item.domain_id
    return project_id, domain_id


class TaskBulkService:
    def __init__(self, tasks: TaskService) -> None:
        self.tasks = tasks
        self.store = tasks.store
        self.clock = tasks.clock

    def reschedule(
        self,
        actor: Actor,
        items: Sequence[RescheduleTaskItem],
        *,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> list[Task]:
        """Set the due date of several Tasks in one transaction, through `update_in_session`.

        A stale version or any other failure raises before the transaction commits, so no Task in
        the batch changes. The idempotency key covers the whole batch. The rows are locked in id
        order first (`lock_tasks`), so the answer keeps the caller's order without a deadlock.
        """
        actor.require("tasks:write")
        if not items:
            raise ValidationError("at least one task is required")
        if len(items) > MAX_RESCHEDULE_TASKS:
            raise ValidationError(
                f"at most {MAX_RESCHEDULE_TASKS} tasks can be rescheduled at once"
            )
        if len({item.task_id for item in items}) != len(items):
            raise ValidationError("each task may appear only once")
        payload: dict[str, object] = {
            "items": [
                {
                    "task_id": str(item.task_id),
                    "expected_version": item.expected_version,
                    "due_at": item.due_at.isoformat() if item.due_at else None,
                }
                for item in items
            ]
        }

        def operation(session: TxSession) -> list[Task]:
            self.store.lock_tasks(session, actor.user_id, (item.task_id for item in items))
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="reschedule_tasks",
                key=idempotency_key,
                payload=payload,
                execute=lambda: {
                    "tasks": [
                        {
                            "id": str(
                                self.tasks.update_in_session(
                                    session,
                                    actor,
                                    item.task_id,
                                    item.expected_version,
                                    UpdateTaskCommand(due_at=item.due_at),
                                    correlation_id,
                                ).id
                            )
                        }
                        for item in items
                    ]
                },
                replay=lambda result: items_replay_record(result, "tasks"),
            )
            return self.tasks.replayed_tasks(session, actor, result["tasks"])

        return self.store.transaction(operation)

    def review(
        self,
        actor: Actor,
        items: Sequence[ReviewDecisionItem],
        *,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> list[ReviewedTask]:
        """Apply 1 to 20 review decisions in one transaction; every Task is marked reviewed.

        A decision that changes the Task goes through `update_in_session` (or the archive), so it
        has its own activity entry; the Tasks kept unchanged share one summary entry. A stale
        version or any other failure raises before the commit, so no decision of the call is kept.
        The idempotency key covers the whole call, and its record keeps what each Task was before,
        so a retry answers with the same `previous` values. The rows are locked in id order first
        (`lock_tasks`), so each `previous` is read under the lock and the answer keeps the caller's
        order without a deadlock.
        """

        actor.require("tasks:write")
        if not items:
            raise ValidationError("at least one task is required")
        if len(items) > MAX_REVIEW_DECISIONS:
            raise ValidationError(f"at most {MAX_REVIEW_DECISIONS} tasks can be reviewed at once")
        if len({item.task_id for item in items}) != len(items):
            raise ValidationError("each task may appear only once")
        payload: dict[str, object] = {
            "items": [
                {
                    "task_id": str(item.task_id),
                    "expected_version": item.expected_version,
                    "decision": item.decision.value,
                    "due_at": _iso(item.due_at),
                    "follow_up_at": _iso(item.follow_up_at),
                }
                for item in items
            ]
        }

        def operation(session: TxSession) -> list[ReviewedTask]:
            self.store.lock_tasks(session, actor.user_id, (item.task_id for item in items))
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="review_tasks",
                key=idempotency_key,
                payload=payload,
                execute=lambda: {
                    "tasks": self._apply_review(session, actor, items, correlation_id)
                },
                replay=lambda result: {"tasks": list(result["tasks"])},
            )
            entries = cast(list[_ReviewEntry], result["tasks"])
            tasks = self.tasks.replayed_tasks(session, actor, entries)
            return [
                ReviewedTask(
                    task=task,
                    decision=item.decision,
                    previous=_review_previous(entry["previous"]),
                )
                for task, item, entry in zip(tasks, items, entries, strict=True)
            ]

        return self.store.transaction(operation)

    def _apply_review(
        self,
        session: TxSession,
        actor: Actor,
        items: Sequence[ReviewDecisionItem],
        correlation_id: str | None,
    ) -> list[_ReviewEntry]:
        now = self.tasks.clock.now()
        befores = [self.store.get_task(session, actor.user_id, item.task_id) for item in items]
        _require_keepable_ambitions(items, befores, now)
        entries: list[_ReviewEntry] = []
        unchanged: list[Task] = []
        for item, before in zip(items, befores, strict=True):
            if item.decision is ReviewDecision.ARCHIVE:
                self.tasks.archive_in_session(
                    session,
                    actor,
                    item.task_id,
                    item.expected_version,
                    correlation_id,
                    reviewed=True,
                )
            elif changes := _review_changes(item, before, now):
                self.tasks.update_in_session(
                    session,
                    actor,
                    item.task_id,
                    item.expected_version,
                    UpdateTaskCommand(**changes, last_reviewed_at=now),
                    correlation_id,
                )
            else:
                unchanged.append(
                    self.tasks.mark_reviewed_in_session(
                        session, actor, item.task_id, item.expected_version, correlation_id
                    )
                )
            entries.append({"id": str(item.task_id), "previous": _stored_previous(before)})
        if unchanged and self.tasks.activity_ledger is not None:
            self.tasks.activity_ledger.record_unchanged_review(
                session,
                tasks=unchanged,
                actor_id=actor.user_id,
                actor_type="user",
                occurred_at=now,
                correlation_id=correlation_id,
            )
        return entries

    def create_batch(
        self,
        actor: Actor,
        items: Sequence[NewTaskItem],
        *,
        idempotency_key: str,
        project_id: UUID | None = None,
        domain_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> TaskBatch:
        """Create 1 to 20 Tasks, each with its ordered Steps, in one transaction.

        Each Task goes through `create_in_session`, the same path as `create`, and its Steps are
        saved in the same session. A failing item raises before the transaction commits, so no Task
        or Step of the batch is kept. The idempotency key covers the whole batch. `project_id` and
        `domain_id` are the batch's defaults; an item that names its own project or domain goes
        there instead, and each one is checked as the owner's when the item is created.
        """
        actor.require("tasks:write")
        if not items:
            raise ValidationError("at least one task is required")
        if len(items) > MAX_BATCH_CREATE_TASKS:
            raise ValidationError(f"at most {MAX_BATCH_CREATE_TASKS} tasks can be created at once")
        if any(len(item.step_titles) > MAX_BATCH_STEPS_PER_TASK for item in items):
            raise ValidationError(f"at most {MAX_BATCH_STEPS_PER_TASK} steps per task")
        payload: dict[str, object] = {
            "project_id": str(project_id) if project_id else None,
            "domain_id": str(domain_id) if domain_id else None,
            "items": [
                {
                    "title": item.title,
                    "due_at": item.due_at,
                    "priority": item.priority.value,
                    "tags": list(item.tags),
                    "step_titles": list(item.step_titles),
                    **_own_fields(item),
                }
                for item in items
            ],
        }

        def operation(session: TxSession) -> TaskBatch:
            label = self._container_label(session, actor, items, project_id, domain_id)
            result = cast(
                _BatchReplay,
                self.store.idempotent(
                    session,
                    actor_id=actor.user_id,
                    operation="create_tasks",
                    key=idempotency_key,
                    payload=payload,
                    execute=lambda: dict(
                        _BatchResult(
                            tasks=[
                                self._create_batch_item(
                                    session, actor, item, project_id, domain_id, correlation_id
                                )
                                for item in items
                            ]
                        )
                    ),
                    replay=lambda result: dict(
                        task_batch_replay_record(cast(_BatchResult, result))
                    ),
                ),
            )
            created = self.tasks.replayed_tasks(
                session, actor, [entry["task"] for entry in result["tasks"]]
            )
            replayed_steps = [
                self._replayed_steps(session, actor, task.id, entry.get("steps"))
                for task, entry in zip(created, result["tasks"], strict=True)
            ]
            return TaskBatch(
                container_label=label,
                tasks=tuple(
                    BatchCreatedTask(task=task, steps=steps)
                    for task, steps in zip(created, replayed_steps, strict=True)
                ),
            )

        return self.store.transaction(operation)

    def _container_label(
        self,
        session: TxSession,
        actor: Actor,
        items: Sequence[NewTaskItem],
        project_id: UUID | None,
        domain_id: UUID | None,
    ) -> str | None:
        """The title of the one Project, else the name of the one Domain, every Task goes to."""

        placed = [_placement(item, project_id, domain_id) for item in items]
        projects = {project for project, _ in placed}
        domains = {domain for _, domain in placed}
        if len(projects) == 1 and (only_project := next(iter(projects))):
            return self.store.get_project(session, actor.user_id, only_project).title
        if len(domains) == 1 and (only_domain := next(iter(domains))):
            return self.store.get_domain(session, actor.user_id, only_domain).name
        return None

    def _replayed_steps(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        recorded: Sequence[IdRecord] | None,
    ) -> tuple[BatchStep, ...]:
        """The Steps a batch created for one Task, re-read by the ids its record kept.

        The reply lists exactly the recorded Steps in creation order, whatever has happened to
        the Task's Steps since, each as it is now (title, position, version), like a replayed
        Task. A recorded Step that is archived, in the trash or gone is left out: the reply
        schema has no flag for it, and listing it as live would mislead. `recorded` is None for
        a record written before Step ids were kept; those fall back to the Task's first
        `MAX_BATCH_STEPS_PER_TASK` live Steps, which is what such a retry returned until now.
        """

        if recorded is None:
            steps = self.store.list_steps(session, actor.user_id, task_id, MAX_BATCH_STEPS_PER_TASK)
        else:
            step_ids = tuple(UUID(entry["id"]) for entry in recorded)
            live = self.store.list_live_steps_by_ids(session, actor.user_id, step_ids)
            steps = [live[step_id] for step_id in step_ids if step_id in live]
        return tuple(
            {
                "id": str(step.id),
                "title": step.title,
                "position": step.position,
                "version": step.version,
            }
            for step in steps
        )

    def _create_batch_item(
        self,
        session: TxSession,
        actor: Actor,
        item: NewTaskItem,
        project_id: UUID | None,
        domain_id: UUID | None,
        correlation_id: str | None,
    ) -> _CreatedEntry:
        placed_project, placed_domain = _placement(item, project_id, domain_id)
        task = self.tasks.create_in_session(
            session,
            actor,
            {
                "title": item.title,
                "project_id": str(placed_project) if placed_project else None,
                "domain_id": str(placed_domain) if placed_domain else None,
                "process_id": None,
                "description": item.description,
                "priority": item.priority.value,
                "due_at": item.due_at,
                "not_before": None,
                "estimated_minutes": None,
                "blocked_reminder_cadence": None,
                "blocked_reminder_snoozed_until": None,
                "recurrence": None,
                "tags": list(item.tags),
            },
            correlation_id,
        )
        # Flush so each Step row can reference its Task, as process-run materialisation does.
        session.flush()
        task_id = task.id
        now = self.clock.now()
        steps: list[BatchStep] = []
        for position, title in enumerate(item.step_titles):
            step = Step(
                new_uuid7(),
                actor.user_id,
                task_id,
                title,
                TaskStatus.TODO,
                position,
                None,
                False,
                now,
                now,
            )
            self.store.save_step(session, step)
            steps.append(
                {"id": str(step.id), "title": title, "position": position, "version": step.version}
            )
        return {"task": {"id": str(task.id)}, "steps": steps}

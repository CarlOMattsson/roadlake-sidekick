"""Atomic multi-Task writes: reschedule several Tasks, create a batch of Tasks with Steps.

Both run every Task through the single-Task use cases of `TaskService` inside one transaction,
so validation, versions, status history and audit are the same as for a single write.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.shared.replay import items_replay_record
from sidekick.shared.types import Actor, TxSession, new_uuid7
from sidekick.tasks.application.models import (
    MAX_BATCH_CREATE_TASKS,
    MAX_BATCH_STEPS_PER_TASK,
    MAX_RESCHEDULE_TASKS,
    BatchCreatedTask,
    NewTaskItem,
    RescheduleTaskItem,
    TaskBatch,
    UpdateTaskCommand,
)
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.work.domain import Step

if TYPE_CHECKING:
    from sidekick.tasks.application.service import TaskService


def task_batch_replay_record(result: dict[str, Any]) -> dict[str, Any]:
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
        the batch changes. The idempotency key covers the whole batch.
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
        payload: dict[str, Any] = {
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
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="reschedule_tasks",
                key=idempotency_key,
                payload=payload,
                execute=lambda: {
                    "tasks": [
                        self.tasks.update_in_session(
                            session,
                            actor,
                            item.task_id,
                            item.expected_version,
                            UpdateTaskCommand(due_at=item.due_at),
                            correlation_id,
                        )
                        for item in items
                    ]
                },
                replay=lambda result: items_replay_record(result, "tasks"),
            )
            return self.tasks.replayed_tasks(session, actor, result["tasks"])

        return self.store.transaction(operation)

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
        or Step of the batch is kept. The idempotency key covers the whole batch.
        """
        actor.require("tasks:write")
        if not items:
            raise ValidationError("at least one task is required")
        if len(items) > MAX_BATCH_CREATE_TASKS:
            raise ValidationError(f"at most {MAX_BATCH_CREATE_TASKS} tasks can be created at once")
        if any(len(item.step_titles) > MAX_BATCH_STEPS_PER_TASK for item in items):
            raise ValidationError(f"at most {MAX_BATCH_STEPS_PER_TASK} steps per task")
        payload: dict[str, Any] = {
            "project_id": str(project_id) if project_id else None,
            "domain_id": str(domain_id) if domain_id else None,
            "items": [
                {
                    "title": item.title,
                    "due_at": item.due_at,
                    "priority": item.priority.value,
                    "tags": list(item.tags),
                    "step_titles": list(item.step_titles),
                }
                for item in items
            ],
        }

        def operation(session: TxSession) -> TaskBatch:
            label: str | None = None
            if project_id:
                label = self.store.get_project(session, actor.user_id, project_id).title
            elif domain_id:
                label = self.store.get_domain(session, actor.user_id, domain_id).name
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_tasks",
                key=idempotency_key,
                payload=payload,
                execute=lambda: {
                    "tasks": [
                        self._create_batch_item(
                            session, actor, item, project_id, domain_id, correlation_id
                        )
                        for item in items
                    ]
                },
                replay=task_batch_replay_record,
            )
            created = self.tasks.replayed_tasks(
                session, actor, [e["task"] for e in result["tasks"]]
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

    def _replayed_steps(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        recorded: Sequence[dict[str, Any]] | None,
    ) -> tuple[dict[str, Any], ...]:
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
            step_ids = tuple(UUID(str(entry["id"])) for entry in recorded)
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
    ) -> dict[str, Any]:
        task_data = self.tasks.create_in_session(
            session,
            actor,
            {
                "title": item.title,
                "project_id": str(project_id) if project_id else None,
                "domain_id": str(domain_id) if domain_id else None,
                "process_id": None,
                "description": None,
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
        task_id = UUID(str(task_data["id"]))
        now = self.clock.now()
        steps: list[dict[str, Any]] = []
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
        return {"task": task_data, "steps": steps}

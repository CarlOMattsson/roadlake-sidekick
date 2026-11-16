"""Completing a Task completes its open Steps and Actions; reopening it opens them again.

Runs in the Task command's own transaction, so the Task, its Steps and Actions, the runs of AI
Steps and the audit trail commit or fail together, and a retried command repeats none of it.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sidekick.shared.types import TxSession
from sidekick.tasks.domain import StepsMoved, Task
from sidekick.work.application.steps_service import StepsStore
from sidekick.work.domain import Action, Performer, Step
from sidekick.work.domain.ai_runs import AiStepRun
from sidekick.work.domain.task_closing import (
    StepsChanged,
    close_with_task,
    reopen_with_task,
    reset_for_next_run,
)

STEP_BATCH = 1000


class TaskClosingStore(StepsStore, Protocol):
    """The Step and Action reads and writes, plus the run rows an AI Step may have."""

    def list_actions_for_steps(
        self,
        session: TxSession,
        owner_id: UUID,
        step_ids: tuple[UUID, ...],
        per_step_limit: int = 1000,
        include_archived: bool = False,
    ) -> dict[UUID, list[Action]]: ...
    def list_active_ai_runs(
        self, session: TxSession, owner_id: UUID, step_ids: tuple[UUID, ...]
    ) -> list[AiStepRun]: ...
    def save_ai_run(
        self, session: TxSession, run: AiStepRun, expected_version: int | None = None
    ) -> None: ...


class TaskStepClosing:
    """Steps and Actions follow the Task's completion; archived and trashed ones are left alone."""

    def __init__(self, store: TaskClosingStore) -> None:
        self.store = store

    def close(
        self,
        session: TxSession,
        /,
        *,
        actor_id: UUID,
        task: Task,
        now: datetime,
        correlation_id: str | None = None,
    ) -> StepsMoved:
        """Complete the open Steps and their open Actions.

        An AI Step whose run is queued or running has that run cancelled, so the runner learns
        its report is no longer wanted. A result or question already waiting for the owner stays
        on its run: the owner finished the Task, and the answer is still there to read.
        """

        steps, actions = self._load(session, task)
        changed = close_with_task(steps, actions, now=now)
        self._save(
            session,
            actor_id,
            changed,
            correlation_id,
            step_event="step.completed",
            action_event="action.completed",
        )
        self._cancel_active_runs(session, actor_id, changed.steps, now, correlation_id)
        return StepsMoved(len(changed.steps), len(changed.actions))

    def reopen(
        self,
        session: TxSession,
        /,
        *,
        actor_id: UUID,
        task: Task,
        now: datetime,
        correlation_id: str | None = None,
    ) -> StepsMoved:
        """Open again the Steps and Actions the Task's completion closed (`task` as completed)."""

        if task.completed_at is None:
            return StepsMoved()
        steps, actions = self._load(session, task)
        changed = reopen_with_task(steps, actions, completed_at=task.completed_at, now=now)
        self._save(
            session,
            actor_id,
            changed,
            correlation_id,
            step_event="step.updated",
            action_event="action.reopened",
        )
        return StepsMoved(len(changed.steps), len(changed.actions))

    def reset(
        self,
        session: TxSession,
        /,
        *,
        actor_id: UUID,
        task: Task,
        now: datetime,
        correlation_id: str | None = None,
    ) -> StepsMoved:
        """Start a repeating Task's Steps and Actions over for its next run.

        Queued or running AI runs are cancelled; a result or question waiting for the owner
        stays readable on its run while the Step begins again.
        """

        steps, actions = self._load(session, task)
        changed = reset_for_next_run(steps, actions, now=now)
        self._save(
            session,
            actor_id,
            changed,
            correlation_id,
            step_event="step.updated",
            action_event="action.reopened",
        )
        self._cancel_active_runs(session, actor_id, steps, now, correlation_id)
        return StepsMoved(len(changed.steps), len(changed.actions))

    def _load(self, session: TxSession, task: Task) -> tuple[list[Step], dict[UUID, list[Action]]]:
        steps: list[Step] = []
        while True:
            batch = self.store.list_steps(
                session, task.owner_id, task.id, STEP_BATCH, offset=len(steps)
            )
            steps.extend(batch)
            if len(batch) < STEP_BATCH:
                break
        actions = self.store.list_actions_for_steps(
            session, task.owner_id, tuple(step.id for step in steps)
        )
        return steps, actions

    def _save(
        self,
        session: TxSession,
        actor_id: UUID,
        changed: StepsChanged,
        correlation_id: str | None,
        *,
        step_event: str,
        action_event: str,
    ) -> None:
        # Each new version is one past the version it replaced, read in this transaction.
        for step in changed.steps:
            self.store.save_step(session, step, expected_version=step.version - 1)
            self._audit(session, actor_id, step_event, "step", step.id, correlation_id)
        for action in changed.actions:
            self.store.save_action(session, action, expected_version=action.version - 1)
            self._audit(session, actor_id, action_event, "action", action.id, correlation_id)

    def _cancel_active_runs(
        self,
        session: TxSession,
        actor_id: UUID,
        steps: Iterable[Step],
        now: datetime,
        correlation_id: str | None,
    ) -> None:
        ai = [step for step in steps if step.performer is Performer.AI]
        if not ai:
            return
        ai_step_ids = tuple(step.id for step in ai)
        owner_id = ai[0].owner_id
        for run in self.store.list_active_ai_runs(session, owner_id, ai_step_ids):
            self.store.save_ai_run(session, run.cancel(now=now), expected_version=run.version)
            self.store.append_audit(
                session,
                actor_id=actor_id,
                event="ai.run_cancelled",
                outcome="success",
                target_type="ai_step_run",
                target_id=run.id,
                related_id=run.step_id,
                correlation_id=correlation_id,
            )

    def _audit(
        self,
        session: TxSession,
        actor_id: UUID,
        event: str,
        target_type: str,
        target_id: UUID,
        correlation_id: str | None,
    ) -> None:
        self.store.append_audit(
            session,
            actor_id=actor_id,
            event=event,
            outcome="success",
            target_type=target_type,
            target_id=target_id,
            correlation_id=correlation_id,
        )

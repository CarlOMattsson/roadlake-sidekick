"""Process recurrence use cases: durable Task instances, not reopened Tasks."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sidekick.automation.domain import AutomationCategory
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.replay import items_replay_record
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    Clock,
    IdempotentStore,
    TransactionalStore,
    TxSession,
    new_uuid7,
)
from sidekick.tasks.domain import Priority, TaskStatus
from sidekick.work.domain import (
    MAX_PROCESS_RUNS,
    Action,
    ActionStatus,
    Process,
    ProcessRun,
    ProcessRunActionTemplate,
    ProcessRunOutbox,
    ProcessRunReconciliation,
    ProcessRunTemplate,
    ProcessStatus,
    Step,
    reconcile_process_schedule,
)
from sidekick.work.domain.run_ports import RunActivityRecorder, RunTaskCreator

T = TypeVar("T")


class ProcessRunStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def get_process(self, session: TxSession, owner_id: UUID, process_id: UUID) -> Process: ...

    def claim_due_process(self, session: TxSession, now: datetime) -> Process | None: ...

    def get_process_run_template(
        self, session: TxSession, owner_id: UUID, process_id: UUID
    ) -> ProcessRunTemplate | None: ...

    def list_process_runs(
        self, session: TxSession, owner_id: UUID, process_id: UUID, limit: int
    ) -> list[ProcessRun]: ...

    def get_process_runs(
        self, session: TxSession, owner_id: UUID, run_ids: Sequence[UUID]
    ) -> list[ProcessRun]: ...

    def add_process_run(self, session: TxSession, run: ProcessRun) -> None: ...

    def save_process(
        self, session: TxSession, process: Process, expected_version: int | None = None
    ) -> None: ...

    def save_step(self, session: TxSession, step: Step) -> None: ...

    def save_action(self, session: TxSession, action: Action) -> None: ...

    def claim_process_run_outbox(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        process_id: UUID,
        scheduled_for: datetime,
        worker_id: str,
        now: datetime,
    ) -> ProcessRunOutbox | None: ...

    def complete_process_run_outbox(
        self,
        session: TxSession,
        *,
        outbox_id: UUID,
        worker_id: str,
        process_run_id: UUID,
        now: datetime,
    ) -> None: ...

    def recover_stalled_process_run_outbox(self, session: TxSession, *, now: datetime) -> int: ...

    def enqueue_process_run_outbox(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        process_id: UUID,
        scheduled_for: datetime,
        now: datetime,
    ) -> None: ...


class ProcessRunService:
    """Owns recurrence scheduling and its history-preserving materialization."""

    def __init__(
        self,
        store: ProcessRunStore,
        task_service: RunTaskCreator,
        clock: Clock,
        activity_ledger: RunActivityRecorder | None = None,
    ) -> None:
        self.store = store
        self.task_service = task_service
        self.clock = clock
        self.activity_ledger = activity_ledger

    def reconciliation(self, actor: Actor, process_id: UUID) -> ProcessRunReconciliation:
        actor.require("projects:read")

        def operation(session: TxSession) -> ProcessRunReconciliation:
            process = self.store.get_process(session, actor.user_id, process_id)
            latest = self.store.list_process_runs(session, actor.user_id, process_id, 1)
            return reconcile_process_schedule(
                process,
                latest[0].scheduled_for if latest else None,
                now=self.clock.now(),
            )

        return self.store.transaction(operation)

    def run_due(self, worker_id: str, *, max_runs: int = 3) -> list[ProcessRun]:
        """Materialize a bounded backlog so downtime does not silently lose periods."""

        if not worker_id.strip():
            raise ValidationError("worker id is required")
        if not 1 <= max_runs <= MAX_PROCESS_RUNS:
            raise ValidationError("process run recovery bound must be between 1 and 100")

        def operation(session: TxSession) -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            for _ in range(max_runs):
                process = self.store.claim_due_process(session, self.clock.now())
                if process is None or process.next_expected_run_at is None:
                    break
                outbox = self.store.claim_process_run_outbox(
                    session,
                    owner_id=process.owner_id,
                    process_id=process.id,
                    scheduled_for=process.next_expected_run_at,
                    worker_id=worker_id,
                    now=self.clock.now(),
                )
                if outbox is None:
                    break
                run = self._materialize(
                    session,
                    process,
                    process.next_expected_run_at,
                    "worker",
                    None,
                    outbox_id=outbox.id,
                    outbox_worker_id=worker_id,
                    advance_schedule=True,
                )
                updated = self.store.get_process(session, process.owner_id, process.id)
                if updated.cadence is not None and updated.next_expected_run_at is not None:
                    self.store.enqueue_process_run_outbox(
                        session,
                        owner_id=updated.owner_id,
                        process_id=updated.id,
                        scheduled_for=updated.next_expected_run_at,
                        now=self.clock.now(),
                    )
                results.append(run_to_data(run))
            return results

        return [run_from_data(item) for item in self.store.transaction(operation)]

    def recover_stalled_outbox(self) -> int:
        """Return abandoned Process-run intents to the queued state."""

        return self.store.transaction(
            lambda session: self.store.recover_stalled_process_run_outbox(
                session, now=self.clock.now()
            )
        )

    def run_next(self, worker_id: str) -> ProcessRun | None:
        runs = self.run_due(worker_id, max_runs=1)
        return runs[0] if runs else None

    def reconcile(
        self,
        actor: Actor,
        process_id: UUID,
        *,
        max_runs: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> list[ProcessRun]:
        """Let an owner catch up a bounded overdue Process explicitly."""

        actor.require("projects:write")
        if not 1 <= max_runs <= MAX_PROCESS_RUNS:
            raise ValidationError("process reconciliation bound must be between 1 and 100")

        def operation(session: TxSession) -> dict[str, Any]:
            process = self.store.get_process(session, actor.user_id, process_id)
            if process.status is not ProcessStatus.ACTIVE:
                raise ConflictError("only an active Process can be reconciled")
            results: list[dict[str, Any]] = []
            for _ in range(max_runs):
                marker = process.next_expected_run_at
                if process.cadence is None or marker is None or marker > self.clock.now():
                    break
                outbox = self.store.claim_process_run_outbox(
                    session,
                    owner_id=process.owner_id,
                    process_id=process.id,
                    scheduled_for=marker,
                    worker_id=f"owner:{actor.user_id}",
                    now=self.clock.now(),
                )
                if outbox is None:
                    break
                results.append(
                    run_to_data(
                        self._materialize(
                            session,
                            process,
                            marker,
                            "user",
                            correlation_id,
                            actor_id=actor.user_id,
                            outbox_id=outbox.id,
                            outbox_worker_id=f"owner:{actor.user_id}",
                            advance_schedule=True,
                        )
                    )
                )
                self.store.enqueue_process_run_outbox(
                    session,
                    owner_id=process.owner_id,
                    process_id=process.id,
                    scheduled_for=marker + process.cadence.interval,
                    now=self.clock.now(),
                )
                process = self.store.get_process(session, actor.user_id, process_id)
            return {"runs": results}

        def replayed(session: TxSession) -> list[ProcessRun]:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="reconcile_process_runs",
                key=idempotency_key,
                payload={"process_id": str(process_id), "max_runs": max_runs},
                execute=lambda: operation(session),
                replay=lambda result: items_replay_record(result, "runs"),
            )
            return self.store.get_process_runs(
                session, actor.user_id, [UUID(item["id"]) for item in result["runs"]]
            )

        return self.store.transaction(replayed)

    def _materialize(
        self,
        session: TxSession,
        process: Process,
        scheduled_for: datetime,
        actor_type: str,
        correlation_id: str | None,
        *,
        actor_id: UUID | None = None,
        outbox_id: UUID | None = None,
        outbox_worker_id: str | None = None,
        advance_schedule: bool = False,
    ) -> ProcessRun:
        template = self._template_for(session, process)
        worker_actor = Actor(process.owner_id, frozenset({"tasks:write", "projects:read"}))
        now = self.clock.now()
        task_data = self.task_service.create_in_session(
            session,
            worker_actor,
            {
                "title": template.title,
                "project_id": None,
                "domain_id": None,
                "process_id": str(process.id),
                "description": template.description,
                "priority": template.priority.value,
                "due_at": scheduled_for + timedelta(days=template.due_after_days),
                "not_before": scheduled_for,
                "estimated_minutes": template.estimated_minutes,
                "blocked_reminder_cadence": None,
                "blocked_reminder_snoozed_until": None,
                "recurrence": None,
                "tags": [],
            },
            correlation_id,
            actor_type=actor_type,
        )
        # The Task creator returns a serialized command result and the store
        # has no ORM relationship between TaskRow and ProcessRunRow. Flush here so the
        # ProcessRun foreign key can never be inserted before its generated Task.
        session.flush()
        task_id = UUID(str(task_data["id"]))
        self._materialize_steps(
            session, process, template, task_id, scheduled_for, now, correlation_id
        )
        run = ProcessRun(
            id=new_uuid7(),
            owner_id=process.owner_id,
            process_id=process.id,
            task_id=task_id,
            scheduled_for=scheduled_for,
            template_version=template.version,
            created_at=now,
        )
        self.store.add_process_run(session, run)
        if advance_schedule and process.cadence is not None:
            updated = process.update(
                now=now,
                next_expected_run_at=scheduled_for + process.cadence.interval,
            )
            self.store.save_process(session, updated, expected_version=process.version)
        self.store.append_audit(
            session,
            actor_id=process.owner_id,
            event="process.run_materialized",
            outcome="success",
            target_type="process_run",
            target_id=run.id,
            correlation_id=correlation_id,
        )
        self._record_run_activity(session, process, run, actor_type, actor_id, correlation_id, now)
        if outbox_id is not None:
            if outbox_worker_id is None:
                raise ValidationError("process run outbox worker is required")
            self.store.complete_process_run_outbox(
                session,
                outbox_id=outbox_id,
                worker_id=outbox_worker_id,
                process_run_id=run.id,
                now=now,
            )
        return run

    def _template_for(self, session: TxSession, process: Process) -> ProcessRunTemplate:
        """The Process's stored run template, or one derived from the Process itself."""

        template = self.store.get_process_run_template(session, process.owner_id, process.id)
        if template is not None:
            return template
        return ProcessRunTemplate(
            id=new_uuid7(),
            owner_id=process.owner_id,
            process_id=process.id,
            title=process.name,
            description=process.description,
            priority=Priority.NORMAL,
            estimated_minutes=None,
            due_after_days=0,
            version=1,
            created_at=process.created_at,
            updated_at=process.updated_at,
        )

    def _materialize_steps(
        self,
        session: TxSession,
        process: Process,
        template: ProcessRunTemplate,
        task_id: UUID,
        scheduled_for: datetime,
        now: datetime,
        correlation_id: str | None,
    ) -> None:
        """Create the template's Steps, and each Step's Actions, under the generated Task."""

        for step_position, step_template in enumerate(template.steps):
            step = Step(
                id=new_uuid7(),
                owner_id=process.owner_id,
                task_id=task_id,
                title=step_template.title,
                status=TaskStatus.TODO,
                position=step_position,
                due_at=(
                    scheduled_for + timedelta(days=step_template.due_after_days)
                    if step_template.due_after_days is not None
                    else None
                ),
                attention_requested=False,
                created_at=now,
                updated_at=now,
                instruction=step_template.instruction,
            )
            self.store.save_step(session, step)
            session.flush()
            self.store.append_audit(
                session,
                actor_id=process.owner_id,
                event="process.run_step_materialized",
                outcome="success",
                target_type="step",
                target_id=step.id,
                correlation_id=correlation_id,
            )
            for action_position, action_template in enumerate(step_template.actions):
                self._materialize_action(
                    session,
                    process,
                    step,
                    action_template,
                    action_position,
                    scheduled_for,
                    now,
                    correlation_id,
                )

    def _materialize_action(
        self,
        session: TxSession,
        process: Process,
        step: Step,
        action_template: ProcessRunActionTemplate,
        position: int,
        scheduled_for: datetime,
        now: datetime,
        correlation_id: str | None,
    ) -> None:
        action = Action(
            id=new_uuid7(),
            owner_id=process.owner_id,
            step_id=step.id,
            title=action_template.title,
            status=ActionStatus.OPEN,
            position=position,
            due_at=(
                scheduled_for + timedelta(days=action_template.due_after_days)
                if action_template.due_after_days is not None
                else None
            ),
            attention_requested=False,
            created_at=now,
            updated_at=now,
            note=action_template.note,
        )
        self.store.save_action(session, action)
        session.flush()
        self.store.append_audit(
            session,
            actor_id=process.owner_id,
            event="process.run_action_materialized",
            outcome="success",
            target_type="action",
            target_id=action.id,
            correlation_id=correlation_id,
        )

    def _record_run_activity(
        self,
        session: TxSession,
        process: Process,
        run: ProcessRun,
        actor_type: str,
        actor_id: UUID | None,
        correlation_id: str | None,
        now: datetime,
    ) -> None:
        if self.activity_ledger is None:
            return
        self.activity_ledger.append(
            session,
            owner_id=process.owner_id,
            aggregate_type="process_run",
            aggregate_id=run.id,
            aggregate_version=1,
            event_type="process.run_materialized",
            actor_type=actor_type,
            actor_id=actor_id,
            operation="run_process",
            category=AutomationCategory.TASK_MAINTENANCE,
            summary=f"Process run created: {process.name}",
            after_values={
                "process_id": process.id,
                "task_id": run.task_id,
                "scheduled_for": run.scheduled_for,
                "template_version": run.template_version,
            },
            evidence={"run_id": run.id},
            correlation_id=correlation_id,
            occurred_at=now,
        )


def run_to_data(run: ProcessRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "owner_id": str(run.owner_id),
        "process_id": str(run.process_id),
        "task_id": str(run.task_id),
        "scheduled_for": run.scheduled_for.isoformat(),
        "template_version": run.template_version,
        "created_at": run.created_at.isoformat(),
    }


def run_from_data(data: dict[str, Any]) -> ProcessRun:
    return ProcessRun(
        id=UUID(data["id"]),
        owner_id=UUID(data["owner_id"]),
        process_id=UUID(data["process_id"]),
        task_id=UUID(data["task_id"]),
        scheduled_for=datetime.fromisoformat(data["scheduled_for"]),
        template_version=data["template_version"],
        created_at=datetime.fromisoformat(data["created_at"]),
    )

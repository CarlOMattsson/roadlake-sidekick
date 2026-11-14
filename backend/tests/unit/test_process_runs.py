"""Process recurrence keeps one Task instance per scheduled period."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sidekick.shared.cadence import Cadence
from sidekick.shared.errors import ConflictError
from sidekick.shared.types import Actor, new_uuid7
from sidekick.tasks.domain import NewTaskPayload, Priority, Task, TaskStatus
from sidekick.work.application.process_runs import ProcessRunService
from sidekick.work.domain import (
    Process,
    ProcessRun,
    ProcessRunActionTemplate,
    ProcessRunOutbox,
    ProcessRunScheduleState,
    ProcessRunStepTemplate,
    ProcessRunTemplate,
    ProcessStatus,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeTaskService:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create_in_session(
        self,
        _session: Any,
        actor: Actor,
        payload: NewTaskPayload,
        _correlation_id: str | None,
        *,
        actor_type: str,
    ) -> Task:
        self.created.append({**payload, "actor_type": actor_type})
        return Task(
            id=new_uuid7(),
            owner_id=actor.user_id,
            project_id=None,
            title=payload["title"],
            description=payload["description"],
            status=TaskStatus.TODO,
            priority=Priority(payload["priority"]),
            due_at=payload["due_at"],
            completed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )


class FakeSession:
    def flush(self) -> None:
        pass


class FakeActivityLedger:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(self, _session: Any, **event: Any) -> None:
        self.events.append(event)


class FakeStore:
    def __init__(self, process: Process, template: ProcessRunTemplate | None = None) -> None:
        self.process = process
        self.template = template
        self.runs: list[ProcessRun] = []
        self.steps: list[Any] = []
        self.actions: list[Any] = []
        self.outbox: dict[tuple[UUID, datetime], ProcessRunOutbox] = {}
        self.idempotency: dict[tuple[UUID, str, str], tuple[str, dict[str, Any]]] = {}
        self.audits: list[str] = []

    def transaction(self, operation: Callable[[Any], Any]) -> Any:
        return operation(FakeSession())

    def get_process(self, _session: Any, owner_id: UUID, process_id: UUID) -> Process:
        assert self.process.owner_id == owner_id and self.process.id == process_id
        return self.process

    def claim_due_process(self, _session: Any, now: datetime) -> Process | None:
        if self.process.next_expected_run_at is None or self.process.next_expected_run_at > now:
            return None
        return self.process

    def get_process_run_template(
        self, _session: Any, _owner_id: UUID, _process_id: UUID
    ) -> ProcessRunTemplate | None:
        return self.template

    def list_process_runs(
        self, _session: Any, _owner_id: UUID, _process_id: UUID, limit: int
    ) -> list[ProcessRun]:
        return self.runs[:limit]

    def get_process_runs(
        self, _session: Any, _owner_id: UUID, run_ids: Sequence[UUID]
    ) -> list[ProcessRun]:
        by_id = {run.id: run for run in self.runs}
        return [by_id[run_id] for run_id in run_ids if run_id in by_id]

    def add_process_run(self, _session: Any, run: ProcessRun) -> None:
        self.runs.append(run)

    def save_step(self, _session: Any, step: Any) -> None:
        self.steps.append(step)

    def save_action(self, _session: Any, action: Any) -> None:
        self.actions.append(action)

    def claim_process_run_outbox(
        self,
        _session: Any,
        *,
        owner_id: UUID,
        process_id: UUID,
        scheduled_for: datetime,
        worker_id: str,
        now: datetime,
    ) -> ProcessRunOutbox | None:
        key = (process_id, scheduled_for)
        outbox = self.outbox.get(key)
        if outbox is None:
            outbox = ProcessRunOutbox(
                id=new_uuid7(),
                owner_id=owner_id,
                process_id=process_id,
                scheduled_for=scheduled_for,
                status="queued",
                attempts=0,
                worker_id=None,
                claimed_at=None,
                processed_at=None,
                process_run_id=None,
                last_error=None,
            )
        if outbox.status in {"delivered", "processing"}:
            return None
        outbox = replace(
            outbox,
            status="processing",
            attempts=outbox.attempts + 1,
            worker_id=worker_id,
            claimed_at=now,
            last_error=None,
        )
        self.outbox[key] = outbox
        return outbox

    def complete_process_run_outbox(
        self,
        _session: Any,
        *,
        outbox_id: UUID,
        worker_id: str,
        process_run_id: UUID,
        now: datetime,
    ) -> None:
        key, outbox = next(item for item in self.outbox.items() if item[1].id == outbox_id)
        assert outbox.status == "processing" and outbox.worker_id == worker_id
        self.outbox[key] = replace(
            outbox,
            status="delivered",
            worker_id=None,
            claimed_at=None,
            processed_at=now,
            process_run_id=process_run_id,
        )

    def recover_stalled_process_run_outbox(self, _session: Any, *, now: datetime) -> int:
        return 0

    def enqueue_process_run_outbox(
        self,
        _session: Any,
        *,
        owner_id: UUID,
        process_id: UUID,
        scheduled_for: datetime,
        now: datetime,
    ) -> None:
        self.outbox.setdefault(
            (process_id, scheduled_for),
            ProcessRunOutbox(
                id=new_uuid7(),
                owner_id=owner_id,
                process_id=process_id,
                scheduled_for=scheduled_for,
                status="queued",
                attempts=0,
                worker_id=None,
                claimed_at=None,
                processed_at=None,
                process_run_id=None,
                last_error=None,
            ),
        )

    def save_process(
        self, _session: Any, process: Process, expected_version: int | None = None
    ) -> None:
        assert expected_version == self.process.version
        self.process = process

    def idempotent(
        self,
        _session: Any,
        *,
        actor_id: UUID,
        operation: str,
        key: str,
        payload: dict[str, Any],
        execute: Callable[[], dict[str, Any]],
        replay: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        import json

        fingerprint = json.dumps(payload, sort_keys=True, default=str)
        existing = self.idempotency.get((actor_id, operation, key))
        if existing:
            if existing[0] != fingerprint:
                raise ConflictError("idempotency key was reused")
            return existing[1]
        result = execute()
        record = replay(result) if replay else result
        self.idempotency[(actor_id, operation, key)] = (fingerprint, record)
        return record

    def append_audit(self, _session: Any, *, event: str, **_: Any) -> None:
        self.audits.append(event)


def make_process() -> Process:
    owner_id = new_uuid7()
    return Process(
        id=new_uuid7(),
        owner_id=owner_id,
        domain_id=new_uuid7(),
        name="Weekly review",
        description="Review the product work",
        status=ProcessStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
        cadence=Cadence.WEEKLY,
        next_expected_run_at=NOW,
    )


def make_template(process: Process) -> ProcessRunTemplate:
    return ProcessRunTemplate(
        id=new_uuid7(),
        owner_id=process.owner_id,
        process_id=process.id,
        title="Review product signals",
        description="Check the latest evidence",
        priority=Priority.HIGH,
        estimated_minutes=60,
        due_after_days=2,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def make_template_with_children(process: Process) -> ProcessRunTemplate:
    base = make_template(process)
    return ProcessRunTemplate(
        id=base.id,
        owner_id=base.owner_id,
        process_id=base.process_id,
        title=base.title,
        description=base.description,
        priority=base.priority,
        estimated_minutes=base.estimated_minutes,
        due_after_days=base.due_after_days,
        version=base.version,
        created_at=base.created_at,
        updated_at=base.updated_at,
        steps=(
            ProcessRunStepTemplate(
                title="Review evidence",
                instruction="Read the latest product signals",
                due_after_days=1,
                actions=(
                    ProcessRunActionTemplate(
                        title="Check support themes",
                        note="Look for repeated customer language",
                        due_after_days=2,
                    ),
                ),
            ),
        ),
    )


def test_due_process_creates_a_new_task_and_advances_only_its_schedule() -> None:
    process = make_process()
    store = FakeStore(process, make_template(process))
    tasks = FakeTaskService()
    service = ProcessRunService(store, tasks, FixedClock())

    run = service.run_next("worker-1")

    assert run is not None
    assert len(tasks.created) == 1
    assert tasks.created[0]["title"] == "Review product signals"
    assert tasks.created[0]["due_at"] == NOW + timedelta(days=2)
    assert tasks.created[0]["actor_type"] == "worker"
    assert store.process.next_expected_run_at == NOW + timedelta(days=7)
    assert store.runs == [run]
    assert store.audits == ["process.run_materialized"]
    assert [item.status for item in store.outbox.values()] == ["delivered", "queued"]


def test_run_clones_steps_and_actions_with_relative_dates() -> None:
    process = make_process()
    store = FakeStore(process, make_template_with_children(process))
    tasks = FakeTaskService()
    service = ProcessRunService(store, tasks, FixedClock())

    run = service.run_next("worker-1")

    assert run is not None
    assert run.task_id == store.steps[0].task_id
    assert len(store.steps) == 1
    assert store.steps[0].task_id == run.task_id
    assert store.steps[0].due_at == NOW + timedelta(days=1)
    assert len(store.actions) == 1
    assert store.actions[0].step_id == store.steps[0].id
    assert store.actions[0].due_at == NOW + timedelta(days=2)
    assert store.audits[-3:-1] == [
        "process.run_step_materialized",
        "process.run_action_materialized",
    ]


def test_worker_recovers_only_a_bounded_number_of_missed_periods() -> None:
    process = make_process()
    store = FakeStore(process, make_template(process))
    store.process = process.update(
        now=NOW,
        next_expected_run_at=NOW - timedelta(days=21),
    )
    tasks = FakeTaskService()
    service = ProcessRunService(store, tasks, FixedClock())

    recovered = service.run_due("worker-1", max_runs=3)

    assert len(recovered) == 3
    assert [run.scheduled_for for run in recovered] == [
        NOW - timedelta(days=21),
        NOW - timedelta(days=14),
        NOW - timedelta(days=7),
    ]
    assert store.process.next_expected_run_at == NOW
    assert len(service.run_due("worker-1", max_runs=3)) == 1


def test_reconciliation_explains_and_catches_up_a_bounded_backlog() -> None:
    process = make_process()
    store = FakeStore(process, make_template(process))
    store.process = process.update(
        now=NOW,
        next_expected_run_at=NOW - timedelta(days=21),
    )
    service = ProcessRunService(store, FakeTaskService(), FixedClock())
    actor = Actor(process.owner_id, frozenset({"projects:read", "projects:write"}))

    status = service.reconciliation(actor, process.id)
    created = service.reconcile(
        actor,
        process.id,
        max_runs=2,
        idempotency_key="manual-reconcile-1",
    )

    assert status.state is ProcessRunScheduleState.OVERDUE
    assert status.missed_run_count == 4
    assert len(created) == 2
    assert store.process.next_expected_run_at == NOW - timedelta(days=7)


def test_materialized_process_run_is_added_to_activity_ledger() -> None:
    process = make_process()
    store = FakeStore(process, make_template(process))
    ledger = FakeActivityLedger()
    service = ProcessRunService(store, FakeTaskService(), FixedClock(), ledger)  # type: ignore[arg-type]

    service.run_next("worker-1")

    assert ledger.events[0]["aggregate_type"] == "process_run"
    assert ledger.events[0]["operation"] == "run_process"
    assert ledger.events[0]["actor_type"] == "worker"

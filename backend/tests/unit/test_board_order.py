"""Manual board ordering rules without transport or database."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from sidekick.shared.errors import ConflictError, PermissionDeniedError, ValidationError
from sidekick.shared.types import Actor, new_uuid7
from sidekick.tasks.application import MAX_BOARD_COLUMN_REORDER, TaskService
from sidekick.tasks.domain import Priority, Task, TaskStatus
from tests.support.fakes import make_cursor_codec

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def make_task(owner_id: UUID, title: str, status: TaskStatus = TaskStatus.TODO) -> Task:
    return Task(
        id=new_uuid7(),
        owner_id=owner_id,
        project_id=None,
        title=title,
        description=None,
        status=status,
        priority=Priority.NORMAL,
        due_at=None,
        completed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeBoardStore:
    def __init__(self, tasks: list[Task]) -> None:
        self.tasks: dict[UUID, Task] = {task.id: task for task in tasks}
        self.idempotency: dict[tuple[UUID, str, str], tuple[str, dict[str, Any]]] = {}
        self.audit: list[dict[str, Any]] = []

    def append_audit(self, session: Any, **fields: Any) -> None:
        del session
        self.audit.append(fields)

    def transaction(self, operation: Callable[[Any], Any]) -> Any:
        return operation(object())

    def list_board_column_tasks(
        self, session: Any, owner_id: UUID, status: TaskStatus, limit: int
    ) -> list[Task]:
        del session
        column = [
            task
            for task in self.tasks.values()
            if task.owner_id == owner_id and task.status is status and task.archived_at is None
        ]
        column.sort(key=lambda task: (task.board_rank is None, task.board_rank or 0, str(task.id)))
        return column[:limit]

    def save_task(self, session: Any, task: Task, expected_version: int | None = None) -> None:
        del session
        current = self.tasks[task.id]
        if expected_version is not None and current.version != expected_version:
            raise ConflictError("stale task version", reason="stale_version")
        self.tasks[task.id] = task

    def idempotent(
        self,
        session: Any,
        *,
        actor_id: UUID,
        operation: str,
        key: str,
        payload: dict[str, Any],
        execute: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        del session
        fingerprint = json.dumps(payload, sort_keys=True, default=str)
        recorded = self.idempotency.get((actor_id, operation, key))
        if recorded is not None:
            if recorded[0] != fingerprint:
                raise ConflictError("idempotency key was already used with another payload")
            return recorded[1]
        result = execute()
        self.idempotency[(actor_id, operation, key)] = (fingerprint, result)
        return result


def make_service(count: int = 3) -> tuple[TaskService, FakeBoardStore, Actor, list[Task]]:
    owner_id = new_uuid7()
    tasks = [make_task(owner_id, f"Task {index}") for index in range(count)]
    store = FakeBoardStore(tasks)
    service = TaskService(store, FixedClock(), make_cursor_codec())  # type: ignore[arg-type]
    actor = Actor(owner_id, frozenset({"tasks:read", "tasks:write"}))
    return service, store, actor, tasks


def test_reorder_writes_dense_one_based_positions_and_bumps_versions() -> None:
    service, store, actor, tasks = make_service()
    requested = [tasks[2], tasks[0], tasks[1]]

    placements = service.reorder_board_column(
        actor,
        TaskStatus.TODO,
        items=[(task.id, task.version) for task in requested],
        idempotency_key="board-reorder-1",
    )

    assert [item.board_rank for item in placements] == [1, 2, 3]
    assert [item.task_id for item in placements] == [task.id for task in requested]
    assert [store.tasks[task.id].board_rank for task in requested] == [1, 2, 3]
    assert all(store.tasks[task.id].version == task.version + 1 for task in requested)


def test_incomplete_or_duplicated_column_payloads_are_rejected() -> None:
    service, store, actor, tasks = make_service()

    with pytest.raises(ValidationError):
        service.reorder_board_column(
            actor,
            TaskStatus.TODO,
            items=[(tasks[0].id, tasks[0].version)],
            idempotency_key="board-reorder-partial",
        )
    with pytest.raises(ValidationError):
        service.reorder_board_column(
            actor,
            TaskStatus.TODO,
            items=[(task.id, task.version) for task in (tasks[0], tasks[0], tasks[1])],
            idempotency_key="board-reorder-duplicate",
        )
    with pytest.raises(ValidationError):
        service.reorder_board_column(
            actor, TaskStatus.TODO, items=[], idempotency_key="board-reorder-empty"
        )

    assert all(task.board_rank is None for task in store.tasks.values())


def test_reorder_beyond_the_supported_item_count_is_rejected() -> None:
    service, _, actor, _ = make_service()
    oversized = [(new_uuid7(), 1) for _ in range(MAX_BOARD_COLUMN_REORDER + 1)]

    with pytest.raises(ValidationError):
        service.reorder_board_column(
            actor, TaskStatus.TODO, items=oversized, idempotency_key="board-reorder-oversized"
        )


def test_stale_version_is_rejected() -> None:
    service, _, actor, tasks = make_service()

    with pytest.raises(ConflictError):
        service.reorder_board_column(
            actor,
            TaskStatus.TODO,
            items=[
                (tasks[0].id, tasks[0].version + 1),
                (tasks[1].id, tasks[1].version),
                (tasks[2].id, tasks[2].version),
            ],
            idempotency_key="board-reorder-stale",
        )


def test_replayed_key_returns_the_recorded_placement_without_reapplying() -> None:
    service, store, actor, tasks = make_service()
    items = [(task.id, task.version) for task in reversed(tasks)]

    first = service.reorder_board_column(
        actor, TaskStatus.TODO, items=items, idempotency_key="board-reorder-once"
    )
    replayed = service.reorder_board_column(
        actor, TaskStatus.TODO, items=items, idempotency_key="board-reorder-once"
    )

    assert list(first) == list(replayed)
    assert [store.tasks[task_id].version for task_id, _ in items] == [
        version + 1 for _, version in items
    ]


def test_reorder_audits_once_with_ids_only_and_a_replay_adds_none() -> None:
    service, store, actor, tasks = make_service()
    items = [(task.id, task.version) for task in reversed(tasks)]

    for _ in range(2):
        service.reorder_board_column(
            actor,
            TaskStatus.TODO,
            items=items,
            idempotency_key="board-reorder-audit",
            correlation_id="corr-board-0123456789",
        )

    assert store.audit == [
        {
            "actor_id": actor.user_id,
            "event": "task.board_reordered",
            "outcome": "success",
            "target_type": "task_board",
            "correlation_id": "corr-board-0123456789",
        }
    ]
    assert not any(task.title in json.dumps(store.audit, default=str) for task in tasks)


def test_a_refused_reorder_writes_no_audit_event() -> None:
    service, store, actor, tasks = make_service()

    with pytest.raises(ValidationError):
        service.reorder_board_column(
            actor,
            TaskStatus.TODO,
            items=[(tasks[0].id, tasks[0].version)],
            idempotency_key="board-reorder-refused",
        )

    assert store.audit == []


def test_board_rank_never_changes_completion_or_status() -> None:
    service, store, actor, tasks = make_service()

    service.reorder_board_column(
        actor,
        TaskStatus.TODO,
        items=[(task.id, task.version) for task in tasks],
        idempotency_key="board-reorder-status",
    )

    for task in store.tasks.values():
        assert task.status is TaskStatus.TODO
        assert task.completed_at is None


def test_reorder_requires_the_write_scope() -> None:
    service, _, actor, tasks = make_service()
    reader = Actor(actor.user_id, frozenset({"tasks:read"}))

    with pytest.raises(PermissionDeniedError):
        service.reorder_board_column(
            reader,
            TaskStatus.TODO,
            items=[(task.id, task.version) for task in tasks],
            idempotency_key="board-reorder-scope",
        )

"""Completing, archiving and restoring a Task are optimistic-concurrency checked, also on the
no-op path (already completed, archived or active)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from sidekick.shared.errors import ConflictError
from sidekick.shared.types import Actor
from sidekick.tasks.application import TaskService
from sidekick.tasks.domain import TaskStatus
from tests.support.fakes import InMemoryStore, make_cursor_codec

NOW = datetime(2026, 8, 21, 10, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _actor() -> Actor:
    return Actor(UUID(int=1), frozenset({"tasks:read", "tasks:write"}))


def _service() -> TaskService:
    return TaskService(InMemoryStore(), FixedClock(), make_cursor_codec())


def test_stale_version_on_an_already_completed_task_is_a_conflict() -> None:
    service = _service()
    task = service.create(_actor(), title="Pay invoice", idempotency_key="create")
    done = service.complete(_actor(), task.id, version=task.version, idempotency_key="first")
    assert done.status is TaskStatus.COMPLETED

    with pytest.raises(ConflictError) as raised:
        service.complete(_actor(), task.id, version=task.version, idempotency_key="stale")

    assert raised.value.reason == "stale_version"
    assert raised.value.subject == "Pay invoice"
    assert raised.value.subject_kind == "task"


def test_current_version_on_an_already_completed_task_stays_a_no_op() -> None:
    service = _service()
    task = service.create(_actor(), title="Pay invoice", idempotency_key="create")
    done = service.complete(_actor(), task.id, version=task.version, idempotency_key="first")

    again = service.complete(_actor(), task.id, version=done.version, idempotency_key="second")

    assert again.version == done.version
    assert again.status is TaskStatus.COMPLETED


def test_stale_version_on_an_open_task_is_still_a_conflict_and_changes_nothing() -> None:
    service = _service()
    task = service.create(_actor(), title="Pay invoice", idempotency_key="create")

    with pytest.raises(ConflictError) as raised:
        service.complete(_actor(), task.id, version=task.version + 5, idempotency_key="stale")

    assert raised.value.reason == "stale_version"
    assert service.get(_actor(), task.id).status is TaskStatus.TODO


def _archive(service: TaskService, task_id: UUID, version: int) -> dict[str, Any]:
    # `_archive` and `_restore` have no public wrapper yet, so they are exercised as the use case.
    return service.store.transaction(
        lambda session: service._archive(session, _actor(), task_id, version, None)
    )


def _restore(service: TaskService, task_id: UUID, version: int) -> dict[str, Any]:
    return service.store.transaction(
        lambda session: service._restore(session, _actor(), task_id, version, None)
    )


def test_stale_version_on_an_already_archived_task_is_a_conflict() -> None:
    service = _service()
    task = service.create(_actor(), title="Pay invoice", idempotency_key="create")
    _archive(service, task.id, task.version)

    with pytest.raises(ConflictError) as raised:
        _archive(service, task.id, task.version)

    assert raised.value.reason == "stale_version"
    assert raised.value.subject == "Pay invoice"
    assert raised.value.subject_kind == "task"


def test_current_version_on_an_already_archived_task_stays_a_no_op() -> None:
    service = _service()
    task = service.create(_actor(), title="Pay invoice", idempotency_key="create")
    archived = _archive(service, task.id, task.version)

    again = _archive(service, task.id, archived["version"])

    assert again["version"] == archived["version"]
    assert again["archived_at"] is not None


def test_stale_version_on_an_already_active_task_cannot_be_restored() -> None:
    service = _service()
    task = service.create(_actor(), title="Pay invoice", idempotency_key="create")

    with pytest.raises(ConflictError) as raised:
        _restore(service, task.id, task.version + 5)

    assert raised.value.reason == "stale_version"
    assert raised.value.subject_kind == "task"


def test_current_version_on_an_already_active_task_restore_stays_a_no_op() -> None:
    service = _service()
    task = service.create(_actor(), title="Pay invoice", idempotency_key="create")

    again = _restore(service, task.id, task.version)

    assert again["version"] == task.version
    assert again["archived_at"] is None

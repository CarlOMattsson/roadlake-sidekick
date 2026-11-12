"""Given/When/Then examples for Task lifecycle behavior."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from sidekick.projects.application import ProjectService
from sidekick.shared.errors import NotFoundError, ValidationError
from sidekick.shared.types import Actor
from sidekick.tasks.application import TaskService, UpdateTaskCommand
from sidekick.tasks.domain import TaskStatus
from tests.support.fakes import InMemoryStore, make_cursor_codec


class MovingClock:
    value = datetime(2026, 7, 18, 10, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def actor(user_id: int = 1) -> Actor:
    return Actor(
        UUID(int=user_id),
        frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"}),
    )


TEST_DOMAIN_ID = UUID("01900000-0000-7000-8000-000000000099")


def test_project_task_can_be_completed_and_reopened() -> None:
    store = InMemoryStore()
    clock = MovingClock()
    projects = ProjectService(store, clock, make_cursor_codec())
    tasks = TaskService(store, clock, make_cursor_codec())
    project = projects.create(
        actor(), title="Sidekick", domain_id=TEST_DOMAIN_ID, idempotency_key="project-task"
    )
    task = tasks.create(
        actor(), title="Ship feature", project_id=project.id, idempotency_key="task-create"
    )
    completed = tasks.complete(actor(), task.id, version=1, idempotency_key="task-complete")
    reopened = tasks.update(
        actor(),
        completed.id,
        version=2,
        idempotency_key="task-reopen",
        command=UpdateTaskCommand(status=TaskStatus.TODO),
    )
    assert completed.completed_at == clock.value
    assert completed.status == "completed"
    assert reopened.status == "todo"
    assert reopened.completed_at is None
    assert reopened.version == 3


def test_project_task_exposes_derived_domain_without_second_selected_context() -> None:
    store = InMemoryStore()
    clock = MovingClock()
    projects = ProjectService(store, clock, make_cursor_codec())
    tasks = TaskService(store, clock, make_cursor_codec())
    project = projects.create(
        actor(), title="Sidekick", domain_id=TEST_DOMAIN_ID, idempotency_key="derived-project"
    )
    task = tasks.create(
        actor(), title="Derived", project_id=project.id, idempotency_key="derived-task"
    )
    assert task.project_id == project.id
    assert task.domain_id is None
    assert task.derived_domain_id == TEST_DOMAIN_ID


def test_task_cannot_reference_another_users_project() -> None:
    store = InMemoryStore()
    projects = ProjectService(store, MovingClock(), make_cursor_codec())
    tasks = TaskService(store, MovingClock(), make_cursor_codec())
    project = projects.create(
        actor(), title="Private", domain_id=TEST_DOMAIN_ID, idempotency_key="other-project"
    )
    with pytest.raises(NotFoundError):
        tasks.create(actor(2), title="Intrusion", project_id=project.id, idempotency_key="bad-task")


def test_blank_task_title_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskService(InMemoryStore(), MovingClock(), make_cursor_codec()).create(
            actor(), title=" ", idempotency_key="blank-task"
        )

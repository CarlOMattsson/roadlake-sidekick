"""Pure application tests for Contact relationship endpoint policy."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from sidekick.contacts.application.service import ContactService, CreateContactCommand
from sidekick.projects.application import ProjectService, UpdateProjectCommand
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.errors import NotFoundError
from sidekick.shared.types import Actor
from sidekick.tasks.application import TaskService
from tests.support.fakes import InMemoryStore, make_cursor_codec


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 19, 12, tzinfo=UTC)


def actor(user_id: int = 1) -> Actor:
    return Actor(
        UUID(int=user_id),
        frozenset(
            {
                "contacts:read",
                "contacts:write",
                "projects:read",
                "projects:write",
                "tasks:read",
                "tasks:write",
            }
        ),
    )


TEST_DOMAIN_ID = UUID("01900000-0000-7000-8000-000000000099")


def test_completed_or_archived_endpoints_cannot_be_linked_or_unlinked() -> None:
    store = InMemoryStore()
    clock = FixedClock()
    contacts = ContactService(store, clock, make_cursor_codec())
    projects = ProjectService(store, clock, make_cursor_codec())
    tasks = TaskService(store, clock, make_cursor_codec())
    contact = contacts.create(actor(), CreateContactCommand("Rasmus"), "contact-create")
    project = projects.create(
        actor(), title="Done", domain_id=TEST_DOMAIN_ID, idempotency_key="project-create"
    )
    project = projects.update(
        actor(),
        project.id,
        version=project.version,
        idempotency_key="project-done",
        command=UpdateProjectCommand(status=ProjectStatus.COMPLETED),
    )
    task = tasks.create(actor(), title="Open", idempotency_key="task-create")
    task = tasks.complete(actor(), task.id, version=task.version, idempotency_key="task-done")

    with pytest.raises(NotFoundError):
        contacts.link_project(actor(), contact.id, project.id, "link-project")
    with pytest.raises(NotFoundError):
        contacts.link_task(actor(), contact.id, task.id, "link-task")
    with pytest.raises(NotFoundError):
        contacts.unlink_project(actor(), contact.id, uuid4(), "unlink-missing-project")
    with pytest.raises(NotFoundError):
        contacts.unlink_task(actor(), uuid4(), task.id, "unlink-missing-contact")

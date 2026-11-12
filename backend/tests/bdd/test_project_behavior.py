"""Given/When/Then examples for Project behavior."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from sidekick.projects.application import ProjectService, UpdateProjectCommand
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.types import Actor
from tests.support.fakes import InMemoryStore, make_cursor_codec


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 18, 10, tzinfo=UTC)


def actor(user_id: int = 1) -> Actor:
    return Actor(UUID(int=user_id), frozenset({"projects:read", "projects:write"}))


TEST_DOMAIN_ID = UUID("01900000-0000-7000-8000-000000000099")


def test_create_update_and_retry_project() -> None:
    store = InMemoryStore()
    service = ProjectService(store, FixedClock(), make_cursor_codec())
    created = service.create(
        actor(), title=" Sidekick ", domain_id=TEST_DOMAIN_ID, idempotency_key="project-001"
    )
    replay = service.create(
        actor(), title=" Sidekick ", domain_id=TEST_DOMAIN_ID, idempotency_key="project-001"
    )
    updated = service.update(
        actor(),
        created.id,
        version=1,
        idempotency_key="project-002",
        command=UpdateProjectCommand(status=ProjectStatus.PAUSED),
    )
    assert created.id == replay.id
    assert created.title == "Sidekick"
    assert updated.status == "paused"
    assert updated.version == 2


def test_same_key_with_changed_payload_conflicts() -> None:
    service = ProjectService(InMemoryStore(), FixedClock(), make_cursor_codec())
    service.create(actor(), title="One", domain_id=TEST_DOMAIN_ID, idempotency_key="project-key")
    with pytest.raises(ConflictError):
        service.create(
            actor(), title="Two", domain_id=TEST_DOMAIN_ID, idempotency_key="project-key"
        )


def test_cross_user_project_is_not_disclosed() -> None:
    service = ProjectService(InMemoryStore(), FixedClock(), make_cursor_codec())
    project = service.create(
        actor(), title="Private", domain_id=TEST_DOMAIN_ID, idempotency_key="project-private"
    )
    with pytest.raises(NotFoundError):
        service.get(actor(2), project.id)


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_invalid_project_titles_are_rejected(title: str) -> None:
    service = ProjectService(InMemoryStore(), FixedClock(), make_cursor_codec())
    with pytest.raises(ValidationError):
        service.create(
            actor(), title=title, domain_id=TEST_DOMAIN_ID, idempotency_key="invalid-title"
        )


def test_target_date_must_not_precede_start_date() -> None:
    service = ProjectService(InMemoryStore(), FixedClock(), make_cursor_codec())
    with pytest.raises(ValidationError, match="target date"):
        service.create(
            actor(),
            title="Dates",
            domain_id=TEST_DOMAIN_ID,
            start_date=date(2026, 7, 20),
            target_date=date(2026, 7, 19),
            idempotency_key="invalid-dates",
        )


def test_project_update_command_cannot_change_owner() -> None:
    with pytest.raises(TypeError):
        UpdateProjectCommand(owner_id=UUID(int=2))  # pyright: ignore[reportCallIssue]


def test_project_archive_restore_is_versioned_and_idempotent() -> None:
    store = InMemoryStore()
    service = ProjectService(store, FixedClock(), make_cursor_codec())
    project = service.create(
        actor(),
        title="Archive me",
        domain_id=TEST_DOMAIN_ID,
        idempotency_key="project-archive-create",
    )

    archived = service.archive(
        actor(), project.id, version=project.version, idempotency_key="project-archive"
    )
    replay = service.archive(
        actor(), project.id, version=project.version, idempotency_key="project-archive"
    )
    assert archived.archived_at is not None
    assert replay.archived_at == archived.archived_at
    with pytest.raises(NotFoundError):
        service.get(actor(), project.id)

    restored = service.restore(
        actor(), project.id, version=archived.version, idempotency_key="project-restore"
    )
    assert restored.archived_at is None
    assert restored.version == archived.version + 1


def test_project_completion_records_finite_outcome() -> None:
    service = ProjectService(InMemoryStore(), FixedClock(), make_cursor_codec())
    project = service.create(
        actor(), title="Outcome", domain_id=TEST_DOMAIN_ID, idempotency_key="project-outcome-create"
    )
    completed = service.complete(
        actor(), project.id, version=project.version, idempotency_key="project-outcome"
    )
    assert completed.status is ProjectStatus.COMPLETED
    assert completed.version == project.version + 1

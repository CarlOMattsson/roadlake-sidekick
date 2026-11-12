"""Authoritative Project/Task persistence and retry behavior."""

from datetime import UTC

import pytest
from sqlalchemy import func, select

from sidekick.projects.application import ProjectService, UpdateProjectCommand
from sidekick.shared.auth import ALL_SCOPES, AuthService
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.models import AuditEventRow
from sidekick.shared.types import Actor, SystemClock
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.application import TaskService
from sidekick.work.application.service import ContextService
from tests.db import database_factory
from tests.support.fakes import make_cursor_codec


@pytest.mark.integration
def test_project_task_round_trip_idempotency_and_ownership() -> None:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    owner_id = auth.provision_user("owner", "Owner")
    other_id = auth.provision_user("other", "Other")
    owner = Actor(owner_id, ALL_SCOPES)
    other = Actor(other_id, ALL_SCOPES)
    store = SqlAlchemyStore(factory)
    projects = ProjectService(store, SystemClock(), make_cursor_codec())
    tasks = TaskService(store, SystemClock(), make_cursor_codec())
    contexts = ContextService(store, SystemClock(), make_cursor_codec(), owner_timezone=UTC)
    domain = contexts.create_domain(
        owner, name="Operations", description=None, idempotency_key="create-domain"
    )
    project = projects.create(
        owner, title="Sidekick", domain_id=domain.id, idempotency_key="create-project"
    )
    replay = projects.create(
        owner, title="Sidekick", domain_id=domain.id, idempotency_key="create-project"
    )
    task = tasks.create(
        owner, title="Test MCP", project_id=project.id, idempotency_key="create-task"
    )
    assert owner.user_id == owner_id and other.user_id == other_id
    assert replay.id == project.id
    assert tasks.get(owner, task.id).project_id == project.id
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventRow)
                .where(AuditEventRow.event.in_(["project.created", "task.created"]))
            )
            == 2
        )
    with pytest.raises(NotFoundError):
        projects.get(other, project.id)
    with pytest.raises(ConflictError):
        projects.create(
            owner, title="Different", domain_id=domain.id, idempotency_key="create-project"
        )


@pytest.mark.integration
def test_stale_version_is_rejected_without_overwrite() -> None:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    owner_id = auth.provision_user("owner", "Owner")
    actor = Actor(owner_id, ALL_SCOPES)
    projects = ProjectService(SqlAlchemyStore(factory), SystemClock(), make_cursor_codec())
    contexts = ContextService(
        projects.store, SystemClock(), make_cursor_codec(), owner_timezone=UTC
    )
    domain = contexts.create_domain(
        actor, name="Operations", description=None, idempotency_key="original-domain"
    )
    project = projects.create(
        actor, title="Original", domain_id=domain.id, idempotency_key="original-key"
    )
    projects.update(
        actor,
        project.id,
        version=1,
        idempotency_key="first-update",
        command=UpdateProjectCommand(title="First"),
    )
    with pytest.raises(ConflictError):
        projects.update(
            actor,
            project.id,
            version=1,
            idempotency_key="stale-update",
            command=UpdateProjectCommand(title="Stale"),
        )
    assert projects.get(actor, project.id).title == "First"


@pytest.mark.integration
def test_tags_only_project_update_advances_version_and_checks_it() -> None:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    actor = Actor(auth.provision_user("owner", "Owner"), ALL_SCOPES)
    projects = ProjectService(SqlAlchemyStore(factory), SystemClock(), make_cursor_codec())
    contexts = ContextService(
        projects.store, SystemClock(), make_cursor_codec(), owner_timezone=UTC
    )
    domain = contexts.create_domain(
        actor, name="Operations", description=None, idempotency_key="tag-domain"
    )
    project = projects.create(
        actor, title="Tagged", domain_id=domain.id, idempotency_key="tag-project"
    )
    tagged = projects.update(
        actor,
        project.id,
        version=1,
        idempotency_key="tag-first",
        command=UpdateProjectCommand(tags=["alpha"]),
    )
    assert tagged.version == 2
    assert tagged.updated_at >= project.updated_at
    replay = projects.update(
        actor,
        project.id,
        version=1,
        idempotency_key="tag-first",
        command=UpdateProjectCommand(tags=["alpha"]),
    )
    assert replay.version == 2
    with pytest.raises(ConflictError):
        projects.update(
            actor,
            project.id,
            version=1,
            idempotency_key="tag-stale",
            command=UpdateProjectCommand(tags=["beta"]),
        )
    assert projects.get(actor, project.id).version == 2
    with factory() as session:
        slugs = [
            tag.slug
            for tag in SqlAlchemyStore.list_record_tags(
                session, actor.user_id, "project", project.id
            )
        ]
    assert slugs == ["alpha"]


@pytest.mark.integration
def test_domain_accent_and_domain_lookups_are_owner_scoped() -> None:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    owner = Actor(auth.provision_user("owner", "Owner"), ALL_SCOPES)
    other = Actor(auth.provision_user("other", "Other"), ALL_SCOPES)
    store = SqlAlchemyStore(factory)
    projects = ProjectService(store, SystemClock(), make_cursor_codec())
    contexts = ContextService(store, SystemClock(), make_cursor_codec(), owner_timezone=UTC)
    owner_domain = contexts.create_domain(
        owner, name="Jobb", description=None, idempotency_key="owner-domain", accent="teal"
    )
    other_domain = contexts.create_domain(
        other, name="Jobb", description=None, idempotency_key="other-domain", accent="rose"
    )
    owner_process = contexts.create_process(
        owner,
        domain_id=owner_domain.id,
        name="Månadsbokslut",
        description=None,
        idempotency_key="owner-process",
    )
    owner_project = projects.create(
        owner, title="Offert", domain_id=owner_domain.id, idempotency_key="owner-project"
    )
    with factory() as session:
        assert SqlAlchemyStore.domain_accents(
            session, owner.user_id, (owner_domain.id, other_domain.id)
        ) == {owner_domain.id: "teal"}
        assert SqlAlchemyStore.process_domain_ids(session, owner.user_id, (owner_process.id,)) == {
            owner_process.id: owner_domain.id
        }
        assert SqlAlchemyStore.project_domain_ids(session, owner.user_id, (owner_project.id,)) == {
            owner_project.id: owner_domain.id
        }
        assert SqlAlchemyStore.domain_accents(session, owner.user_id, ()) == {}

        assert SqlAlchemyStore.domain_accents(session, other.user_id, (owner_domain.id,)) == {}
        assert SqlAlchemyStore.process_domain_ids(session, other.user_id, (owner_process.id,)) == {}
        assert SqlAlchemyStore.project_domain_ids(session, other.user_id, (owner_project.id,)) == {}

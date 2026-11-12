"""Integration tests for typed relationship persistence and retry policy."""

import pytest
from sqlalchemy import func, select

from sidekick.api.app import create_app
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.models import ProjectContactRow, TaskContactRow
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.integration
def test_contact_relationship_persistence() -> None:
    factory = database_factory()
    app = create_app(make_settings(), factory)
    owner_id = app.state.container.auth.provision_user("relation-owner", "Owner")
    other_id = app.state.container.auth.provision_user("relation-other", "Other")
    scopes = frozenset(
        {
            "contacts:read",
            "contacts:write",
            "projects:read",
            "projects:write",
            "tasks:read",
            "tasks:write",
        }
    )
    owner = Actor(owner_id, scopes)
    other = Actor(other_id, scopes)
    domain = app.state.container.contexts.create_domain(
        owner, name="Operations", description=None, idempotency_key="rel-domain"
    )
    contact = app.state.container.contacts.create(
        owner, CreateContactCommand("Rasmus"), "rel-contact"
    )
    project = app.state.container.projects.create(
        owner, title="Sidekick", domain_id=domain.id, idempotency_key="rel-project"
    )
    task = app.state.container.tasks.create(owner, title="Follow up", idempotency_key="rel-task")

    first = app.state.container.contact_relations.link_project(
        owner, contact.id, project.id, "rel-link-project"
    )
    assert (
        app.state.container.contact_relations.link_project(
            owner, contact.id, project.id, "rel-link-project"
        )
        == first
    )
    app.state.container.contact_relations.link_task(owner, contact.id, task.id, "rel-link-task")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ProjectContactRow)) == 1
        assert session.scalar(select(func.count()).select_from(TaskContactRow)) == 1

    with pytest.raises(ConflictError):
        app.state.container.contact_relations.link_project(
            owner, contact.id, task.id, "rel-link-project"
        )
    with pytest.raises(NotFoundError):
        app.state.container.contact_relations.unlink_project(
            other, contact.id, project.id, "rel-cross-user"
        )

    app.state.container.contact_relations.unlink_project(
        owner, contact.id, project.id, "rel-unlink-project"
    )
    absent = app.state.container.contact_relations.unlink_project(
        owner, contact.id, project.id, "rel-unlink-again"
    )
    assert absent["linked"] is False

"""Restoring into a different owner moves every user reference, not only ``owner_id``.

``domain_events.actor_id`` is a foreign key to users. It must follow the owner to the target;
a nullable reference to a user that cannot exist in the target is cleared, so the plan never says
`ready` for a restore whose apply would fail on a foreign key.
"""

import copy
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.owner_export.document import export_checksum
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.shared.persistence.models import DomainEventRow
from sidekick.shared.types import Actor
from sidekick.store import SqlAlchemyStore
from tests.db import database_factory
from tests.support.settings import make_settings


def _setup() -> tuple[sessionmaker[Session], UUID, UUID, dict[str, Any]]:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    source = container.auth.provision_user("actor-source", "Source")
    target = container.auth.provision_user("actor-target", "Target")
    container.tasks.create(
        Actor(source, frozenset({"tasks:read", "tasks:write"})),
        title="Plan",
        idempotency_key="actor-source-task",
    )
    exported = OwnerExportService(SqlAlchemyStore(factory)).export(Actor(source, frozenset()))
    return factory, source, target, exported


def _actors(factory: sessionmaker[Session], owner: UUID) -> list[UUID | None]:
    with factory() as session:
        return list(
            session.scalars(select(DomainEventRow.actor_id).where(DomainEventRow.owner_id == owner))
        )


def _plan_and_restore(
    factory: sessionmaker[Session], document: dict[str, Any], target: UUID
) -> None:
    plan = build_restore_plan(document, target)
    assert plan.status == "ready"
    OwnerRestoreService(SqlAlchemyStore(factory)).restore(
        document, target_owner_id=target, expected_plan_checksum=plan.plan_checksum
    )


@pytest.mark.integration
def test_a_user_created_event_follows_the_owner_into_a_different_owner() -> None:
    factory, source, target, exported = _setup()
    events = exported["collections"]["domain_events"]
    assert events
    assert {event["actor_id"] for event in events} == {str(source)}

    _plan_and_restore(factory, exported, target)

    assert _actors(factory, target) == [target] * len(events)


@pytest.mark.integration
def test_a_nullable_reference_to_an_unknown_user_is_cleared_and_planned_ready() -> None:
    factory, _, target, exported = _setup()
    document = copy.deepcopy(exported)
    unknown = str(uuid4())
    document["collections"]["domain_events"][0]["actor_id"] = unknown
    document["manifest"]["sha256"] = export_checksum(document)

    _plan_and_restore(factory, document, target)

    actors = _actors(factory, target)
    assert None in actors
    assert UUID(unknown) not in actors

"""A replay record written before Work writes returned typed entities still replays unchanged.

The payload hash and the stored record below were produced by the earlier dict-returning code.
The first test pins that the current code still writes the same hash and record. The second
inserts such a record by hand and checks that a retry is answered from it, without a second write.
"""

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container, create_app
from sidekick.shared.persistence.models import DomainRow, IdempotencyRow
from sidekick.shared.types import Actor, new_uuid7, utc_now
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"projects:read", "projects:write"})
NAME = "Hälsa"
# sha256 of {"accent":null,"description":null,"name":"Hälsa"}, the canonical payload JSON.
RECORDED_PAYLOAD_HASH = "50a2ba5bf11da1c23f49bb454dc0a11fa9682a97dea109d6db9da0999d32d32d"


def _setup() -> tuple[Container, Actor, sessionmaker[Session]]:
    factory = database_factory()
    container: Container = create_app(make_settings(), factory).state.container
    owner = container.auth.provision_user("work-replay", "Owner")
    return container, Actor(owner, SCOPES), factory


def _domain_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return int(session.scalar(select(func.count()).select_from(DomainRow)) or 0)


@pytest.mark.integration
def test_a_domain_write_keeps_the_recorded_hash_and_an_id_only_record() -> None:
    container, actor, factory = _setup()

    domain = container.contexts.create_domain(
        actor, name=NAME, description=None, idempotency_key="recorded-1"
    )

    with factory() as session:
        row = session.scalars(select(IdempotencyRow)).one()
    assert row.operation == "create_domain"
    assert row.payload_hash == RECORDED_PAYLOAD_HASH
    assert row.result == {"id": str(domain.id)}


@pytest.mark.integration
def test_a_record_stored_by_the_earlier_code_answers_a_retry_without_a_second_write() -> None:
    container, actor, factory = _setup()
    first = container.contexts.create_domain(
        actor, name="Tidigare", description=None, idempotency_key="seed"
    )
    recorded_id = UUID(str(first.id))
    with factory() as session, session.begin():
        session.add(
            IdempotencyRow(
                id=new_uuid7(),
                actor_id=actor.user_id,
                operation="create_domain",
                idempotency_key="recorded-2",
                payload_hash=RECORDED_PAYLOAD_HASH,
                result={"id": str(recorded_id)},
                created_at=utc_now(),
            )
        )
    before = _domain_count(factory)

    replayed = container.contexts.create_domain(
        actor, name=NAME, description=None, idempotency_key="recorded-2"
    )

    assert replayed.id == recorded_id
    assert _domain_count(factory) == before

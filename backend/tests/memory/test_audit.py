"""Memory settings and exclusions leave content-free audit events in the same transaction.

The event names the setting or the kind, carries the owner or record id and the correlation id,
and never a title or memory text. A repeat changes nothing and so records nothing.
"""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.memory.application.settings import change_settings, set_exclusion
from sidekick.memory.domain import MemoryKind
from sidekick.memory.infrastructure.store import SqlAlchemyMemoryStore
from sidekick.shared.errors import PermissionDeniedError
from sidekick.shared.persistence.models import AuditEventRow, MemorySettingsRow
from sidekick.shared.types import Actor
from tests.support.memory_sync import KEY, LIVE_NOW, _new_contact, _setup

WRITE_ALL = frozenset({"journal:write", "contacts:write", "projects:write", "tasks:write"})
SECRET_NAME = "Zebulon Quillfeather"


def _events(factory: sessionmaker[Session], owner: UUID) -> list[AuditEventRow]:
    with factory() as session:
        rows = session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.event.like("memory.%"), AuditEventRow.actor_id == owner)
            .order_by(AuditEventRow.occurred_at, AuditEventRow.event)
        ).all()
        session.expunge_all()
        return list(rows)


def _version(factory: sessionmaker[Session], owner: UUID) -> int:
    with factory() as session:
        row = session.get(MemorySettingsRow, owner)
        assert row is not None
        return row.version


def _set(factory: sessionmaker[Session], owner: UUID, version: int, **changes: bool) -> None:
    with factory.begin() as session:
        change_settings(
            SqlAlchemyMemoryStore(factory),
            session,
            Actor(owner, WRITE_ALL),
            changes=changes,
            expected_version=version,
            confirm=True,
            now=LIVE_NOW,
            correlation_id="corr-settings",
        )


def _exclude(
    factory: sessionmaker[Session], owner: UUID, source: UUID, excluded: bool, corr: str
) -> None:
    with factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            Actor(owner, WRITE_ALL),
            kind=MemoryKind.CONTACT,
            source_id=source,
            excluded=excluded,
            id_key=KEY,
            now=LIVE_NOW,
            correlation_id=corr,
        )


@pytest.mark.integration
def test_a_settings_change_records_one_event_per_setting_and_a_repeat_records_none() -> None:
    factory, owner, *_ = _setup()
    version = _version(factory, owner)

    _set(factory, owner, version, journal=False, paused=True)
    _set(factory, owner, version, journal=False, paused=True)  # replay: nothing left to change

    events = _events(factory, owner)
    assert sorted(e.event for e in events) == ["memory.journal_off", "memory.paused_on"]
    for event in events:
        assert (event.target_type, event.target_id) == ("memory_settings", owner)
        assert (event.outcome, event.correlation_id) == ("success", "corr-settings")


@pytest.mark.integration
def test_a_refused_settings_change_records_nothing() -> None:
    factory, owner, *_ = _setup()
    version = _version(factory, owner)

    with pytest.raises(PermissionDeniedError), factory.begin() as session:
        change_settings(
            SqlAlchemyMemoryStore(factory),
            session,
            Actor(owner, frozenset({"journal:read"})),
            changes={"paused": True},
            expected_version=version,
            confirm=True,
            now=LIVE_NOW,
            correlation_id="corr-denied",
        )

    assert _events(factory, owner) == []


@pytest.mark.integration
def test_an_exclusion_audit_row_names_ids_only_and_a_repeat_adds_none() -> None:
    factory, owner, *_ = _setup()
    contact = _new_contact(factory, owner, SECRET_NAME)

    _exclude(factory, owner, contact, True, "corr-out")
    _exclude(factory, owner, contact, True, "corr-out-again")
    _exclude(factory, owner, contact, False, "corr-in")

    events = _events(factory, owner)
    assert [(e.event, e.correlation_id) for e in events] == [
        ("memory.excluded", "corr-out"),
        ("memory.included", "corr-in"),
    ]
    assert {(e.target_type, e.target_id) for e in events} == {("contact", contact)}
    # Nothing the record holds is in the row: no name, no note.
    for event in events:
        dumped = " ".join(str(value) for value in vars(event).values())
        assert "Zebulon" not in dumped
        assert "Quillfeather" not in dumped
        assert "Lund" not in dumped


@pytest.mark.integration
def test_the_audit_row_rolls_back_with_the_write() -> None:
    factory, owner, *_ = _setup()
    contact = _new_contact(factory, owner, SECRET_NAME)

    class Boom(Exception):
        pass

    with pytest.raises(Boom), factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            Actor(owner, WRITE_ALL),
            kind=MemoryKind.CONTACT,
            source_id=contact,
            excluded=True,
            id_key=KEY,
            now=LIVE_NOW,
            correlation_id="corr-rolled-back",
        )
        raise Boom

    assert _events(factory, owner) == []

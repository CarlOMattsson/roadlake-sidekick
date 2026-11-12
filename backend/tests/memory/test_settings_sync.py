"""What the sync pass does with rows written by the settings use cases.

The use cases only change Postgres. These tests run the real reconciler (with the scripted provider
of `test_sync`) after `change_settings` and `set_exclusion` to prove that the documents of a
switched-off domain and of an excluded record are deleted, that a never-synced excluded record is
never sent, and that including it again imports it.
"""

from datetime import timedelta
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.memory.application.settings import change_settings, set_exclusion
from sidekick.memory.application.sync_rules import derive_doc_key
from sidekick.memory.domain import MemoryKind
from sidekick.memory.infrastructure.store import SqlAlchemyMemoryStore
from sidekick.shared.errors import ValidationError
from sidekick.shared.persistence.models import MemorySettingsRow, MemorySourceRow
from sidekick.shared.types import Actor
from tests.support.memory_sync import (
    KEY,
    LIVE_NOW,
    _drive_to_retained,
    _new_contact,
    _row,
    _rows,
    _setup,
)

WRITE_ALL = frozenset({"journal:write", "contacts:write", "projects:write", "tasks:write"})


def _version(factory: sessionmaker[Session], owner: UUID) -> int:
    with factory() as session:
        row = session.get(MemorySettingsRow, owner)
        assert row is not None
        return row.version


@pytest.mark.integration
def test_a_confirmed_switch_off_makes_the_sync_delete_the_domains_documents() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    doc_key = _row(factory, contact).doc_key
    version = _version(factory, owner)

    with factory.begin() as session:
        outcome = change_settings(
            SqlAlchemyMemoryStore(factory),
            session,
            Actor(owner, WRITE_ALL | {"contacts:read"}),
            changes={"contacts": False},
            expected_version=version,
            confirm=True,
            now=clock.current,
        )
    assert outcome.status == "updated"
    assert [(r.domain, r.documents) for r in outcome.turning_off] == [("contacts", 1)]

    clock.advance(timedelta(minutes=1))
    result = reconciler.reconcile_owner(owner)

    assert result.deleted == 1
    assert provider.delete_calls == [(owner, doc_key)]


@pytest.mark.integration
def test_an_unconfirmed_switch_off_leaves_the_document_alone() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    version = _version(factory, owner)

    with factory.begin() as session:
        outcome = change_settings(
            SqlAlchemyMemoryStore(factory),
            session,
            Actor(owner, WRITE_ALL),
            changes={"contacts": False},
            expected_version=version,
            confirm=False,
            now=clock.current,
        )
    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner)

    assert outcome.status == "needs_confirmation"
    assert provider.delete_calls == []


@pytest.mark.integration
def test_excluding_a_retained_record_deletes_its_document_and_including_resends_it() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    doc_key = _row(factory, contact).doc_key
    actor = Actor(owner, WRITE_ALL)

    with factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            actor,
            kind=MemoryKind.CONTACT,
            source_id=contact,
            excluded=True,
            id_key=KEY,
            now=clock.current,
        )
    clock.advance(timedelta(minutes=1))
    gone = reconciler.reconcile_owner(owner)

    assert gone.deleted == 1
    assert provider.delete_calls == [(owner, doc_key)]
    assert _row(factory, contact).excluded is True

    with factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            actor,
            kind=MemoryKind.CONTACT,
            source_id=contact,
            excluded=False,
            id_key=KEY,
            now=clock.current,
        )
    clock.advance(timedelta(minutes=1))
    back = reconciler.reconcile_owner(owner)

    assert (back.queued, back.sent) == (1, 1)
    assert len(provider.retain_calls) == 2


@pytest.mark.integration
def test_a_never_synced_excluded_record_is_never_sent_and_a_marker_survives_passes() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    actor = Actor(owner, WRITE_ALL)

    with factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            actor,
            kind=MemoryKind.CONTACT,
            source_id=contact,
            excluded=True,
            id_key=KEY,
            now=LIVE_NOW,
        )
    marker = _row(factory, contact)
    for _ in range(3):
        clock.advance(timedelta(minutes=30))
        result = reconciler.reconcile_owner(owner)
        assert (result.queued, result.sent, result.deleted) == (0, 0, 0)

    assert provider.retain_calls == []
    assert provider.delete_calls == []
    after = _row(factory, contact)
    assert (after.excluded, after.status, after.doc_key) == (True, "parked", marker.doc_key)


@pytest.mark.integration
def test_including_a_marker_row_imports_the_record() -> None:
    factory, owner, _provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    actor = Actor(owner, WRITE_ALL)
    with factory.begin() as session:
        for excluded in (True, False):
            set_exclusion(
                SqlAlchemyMemoryStore(factory),
                session,
                actor,
                kind=MemoryKind.CONTACT,
                source_id=contact,
                excluded=excluded,
                id_key=KEY,
                now=LIVE_NOW,
            )

    clock.advance(timedelta(minutes=1))
    result = reconciler.reconcile_owner(owner)

    assert (result.queued, result.sent) == (1, 1)
    with factory() as session:
        rows = session.scalars(
            select(MemorySourceRow).where(MemorySourceRow.source_id == contact)
        ).all()
    assert len(rows) == 1 and rows[0].excluded is False


@pytest.mark.integration
def test_excluding_without_a_key_writes_a_marker_with_a_random_id() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)

    with factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            Actor(owner, WRITE_ALL),
            kind=MemoryKind.CONTACT,
            source_id=contact,
            excluded=True,
            id_key=None,
            now=LIVE_NOW,
        )
    marker = _row(factory, contact)
    clock.advance(timedelta(minutes=30))
    result = reconciler.reconcile_owner(owner)

    assert (marker.excluded, marker.status, marker.retained_at) == (True, "parked", None)
    assert marker.doc_key.startswith("d1_")
    assert marker.doc_key != derive_doc_key(KEY, owner, MemoryKind.CONTACT, contact)
    assert (result.queued, result.sent, result.deleted) == (0, 0, 0)
    assert provider.retain_calls == [] and provider.delete_calls == []


@pytest.mark.integration
def test_a_keyless_marker_is_replaced_by_a_derived_candidate_on_include() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    actor = Actor(owner, WRITE_ALL)
    with factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            actor,
            kind=MemoryKind.CONTACT,
            source_id=contact,
            excluded=True,
            id_key=None,
            now=LIVE_NOW,
        )
    with factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            actor,
            kind=MemoryKind.CONTACT,
            source_id=contact,
            excluded=False,
            id_key=KEY,
            now=LIVE_NOW,
        )
    assert _rows(factory, owner) == []

    clock.advance(timedelta(minutes=1))
    result = reconciler.reconcile_owner(owner)

    derived = derive_doc_key(KEY, owner, MemoryKind.CONTACT, contact)
    assert (result.queued, result.sent, result.deleted) == (1, 1, 0)
    assert provider.delete_calls == []
    assert [item.document_id for call in provider.retain_calls for item in call.items] == [derived]
    assert _row(factory, contact).doc_key == derived


@pytest.mark.integration
def test_including_a_previously_sent_row_only_clears_its_flag_and_keeps_its_id() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    doc_key = _row(factory, contact).doc_key
    actor = Actor(owner, WRITE_ALL)
    with factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            actor,
            kind=MemoryKind.CONTACT,
            source_id=contact,
            excluded=True,
            id_key=KEY,
            now=clock.current,
        )
    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner)
    with factory.begin() as session:
        set_exclusion(
            SqlAlchemyMemoryStore(factory),
            session,
            actor,
            kind=MemoryKind.CONTACT,
            source_id=contact,
            excluded=False,
            id_key=KEY,
            now=clock.current,
        )

    rows = _rows(factory, owner)
    assert len(rows) == 1
    assert (rows[0].doc_key, rows[0].excluded) == (doc_key, False)
    assert rows[0].retained_at is not None

    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner)
    assert [item.document_id for call in provider.retain_calls for item in call.items] == [
        doc_key,
        doc_key,
    ]


@pytest.mark.integration
@pytest.mark.parametrize(
    "changes",
    [
        {"observations": True},
        {"fact_types": True},
        {"journal": True, "observations": False},
        {"contacts": "yes"},
        {"paused": 1},
        {"tasks": None},
    ],
)
def test_unknown_setting_names_and_non_boolean_values_are_refused_and_change_nothing(
    changes: dict[str, object],
) -> None:
    factory, owner, _provider, clock, _reconciler = _setup()
    version = _version(factory, owner)

    with pytest.raises(ValidationError), factory.begin() as session:
        change_settings(
            SqlAlchemyMemoryStore(factory),
            session,
            Actor(owner, WRITE_ALL),
            changes=cast(dict[str, bool], changes),
            expected_version=version,
            confirm=True,
            now=clock.current,
        )

    assert _version(factory, owner) == version
    with factory() as session:
        row = session.get(MemorySettingsRow, owner)
        assert row is not None
        assert (row.journal, row.contacts, row.projects, row.tasks, row.paused) == (
            True,
            True,
            True,
            True,
            False,
        )


@pytest.mark.integration
def test_an_unknown_setting_is_refused_before_the_scope_check() -> None:
    factory, owner, _provider, clock, _reconciler = _setup()

    with pytest.raises(ValidationError, match="unknown memory setting"), factory.begin() as session:
        change_settings(
            SqlAlchemyMemoryStore(factory),
            session,
            Actor(owner, frozenset()),
            changes={"observations": True},
            expected_version=_version(factory, owner),
            confirm=False,
            now=clock.current,
        )

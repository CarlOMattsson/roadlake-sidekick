"""PostgreSQL integration tests for the memory candidate and tombstone queries.

Rows are written directly with the ORM so that lifecycle state (trash, archive, replacement,
exclusion, switched-off domains) is explicit. Nothing here sends anything to a memory provider.
"""

from datetime import UTC, date, datetime, tzinfo
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sidekick.journal.domain.entry import KeyPointKind
from sidekick.memory.application.queries import (
    MAX_PAGE_SIZE,
    MemoryCandidate,
    MemoryTombstone,
)
from sidekick.memory.domain import (
    ContactInput,
    JournalEntryInput,
    KeyPointInput,
    LinkedContactInput,
    MemoryKind,
    ProjectInput,
    TaskInput,
)
from sidekick.memory.infrastructure.store import SqlAlchemyMemoryStore
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.persistence.models import (
    ContactAliasRow,
)
from sidekick.shared.types import new_uuid7
from tests.db import database_factory
from tests.support.memory_queries import (
    JOURNAL_DATE,
    LONG_TEXT,
    NOW,
    _contact,
    _domain,
    _enable_all,
    _entry,
    _memory_source,
    _owner,
    _project,
    _settings,
    _source,
    _task,
)

OWNER_ZONE = ZoneInfo("Europe/Stockholm")
MID_TEXT = "y" * 40


def _alias(factory: sessionmaker[Session], owner_id: UUID, contact_id: UUID, value: str) -> None:
    with factory.begin() as session:
        session.add(
            ContactAliasRow(
                id=new_uuid7(),
                owner_id=owner_id,
                contact_id=contact_id,
                display_value=value,
                normalized_key=value.casefold(),
                created_at=NOW,
            )
        )


def _candidates(
    factory: sessionmaker[Session],
    owner_id: UUID,
    kind: MemoryKind,
    *,
    after: UUID | None = None,
    limit: int = 100,
    owner_timezone: tzinfo = OWNER_ZONE,
) -> list[MemoryCandidate]:
    with factory() as session:
        return SqlAlchemyMemoryStore(factory).candidate_page(
            session, owner_id, kind, owner_timezone=owner_timezone, after=after, limit=limit
        )


def _tombstones(
    factory: sessionmaker[Session], owner_id: UUID, kind: MemoryKind
) -> list[MemoryTombstone]:
    with factory() as session:
        return SqlAlchemyMemoryStore(factory).tombstone_page(session, owner_id, kind)


@pytest.mark.integration
def test_journal_candidates_are_live_entries_with_linked_names_and_archive_mark() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, journal=True)
    domain = _domain(factory, owner)
    ada = _contact(factory, owner, "Ada", relationship="syster")
    gone = _contact(factory, owner, "Borta", trashed=True)
    project = _project(factory, owner, domain, "Flytt")
    trashed_project = _project(factory, owner, domain, "Gammalt", trashed=True)
    entry = _entry(
        factory,
        owner,
        _source(factory, owner, "Råtext om flytten."),
        "Flytten",
        summary="Vi beslutade.",
        key_points=[{"kind": "decision", "text": "Flytta i mars"}],
        contacts=(ada, gone),
        projects=(project, trashed_project),
    )
    archived = _entry(factory, owner, _source(factory, owner, "Arkiv"), "Arkiverad", archived=True)
    _entry(factory, owner, _source(factory, owner, "Papperskorg"), "Papperskorgen", trashed=True)
    _entry(
        factory,
        owner,
        _source(factory, owner, "Källa i papperskorg", trashed=True),
        "Bakom källa",
    )

    candidates = {c.source_id: c for c in _candidates(factory, owner, MemoryKind.JOURNAL_ENTRY)}

    assert set(candidates) == {entry, archived}
    assert candidates[entry].record == JournalEntryInput(
        journal_date=JOURNAL_DATE,
        title="Flytten",
        summary="Vi beslutade.",
        key_points=(KeyPointInput(kind=KeyPointKind.DECISION, text="Flytta i mars"),),
        raw_text="Råtext om flytten.",
        contacts=(LinkedContactInput(name="Ada", relationship="syster"),),
        project_titles=("Flytt",),
    )
    assert candidates[entry].archived is False
    assert candidates[entry].is_candidate is True
    assert candidates[archived].archived is True


@pytest.mark.integration
def test_journal_source_replaced_by_a_live_source_is_hidden_and_becomes_a_tombstone() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    old_source = _source(factory, owner, "Gammal text")
    old_entry = _entry(factory, owner, old_source, "Gammal")
    new_source = _source(factory, owner, "Ny text", replaces=old_source)
    new_entry = _entry(factory, owner, new_source, "Ny")
    old_memory = _memory_source(factory, owner, MemoryKind.JOURNAL_ENTRY, old_entry)
    _memory_source(factory, owner, MemoryKind.JOURNAL_ENTRY, new_entry)

    candidate_ids = {c.source_id for c in _candidates(factory, owner, MemoryKind.JOURNAL_ENTRY)}
    tombstone_ids = {
        t.memory_source_id for t in _tombstones(factory, owner, MemoryKind.JOURNAL_ENTRY)
    }

    assert candidate_ids == {new_entry}
    assert tombstone_ids == {old_memory}


@pytest.mark.integration
def test_contact_candidate_needs_qualifying_text_and_trashed_contacts_are_hidden() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    bare = _contact(factory, owner, "Bara namnet")
    described = _contact(
        factory,
        owner,
        "Nina",
        context_note="Kollega från projektet",
        relationship="kollega",
        organization="Acme",
    )
    _alias(factory, owner, described, "Nina K")
    _contact(factory, owner, "Gömd", context_note="Ska inte synas", trashed=True)

    candidates = {c.source_id: c for c in _candidates(factory, owner, MemoryKind.CONTACT)}

    assert set(candidates) == {bare, described}
    assert candidates[bare].is_candidate is False
    assert candidates[described].is_candidate is True
    assert candidates[described].record == ContactInput(
        display_name="Nina",
        aliases=("Nina K",),
        relationship="kollega",
        organization="Acme",
        role=None,
        context_note="Kollega från projektet",
    )


@pytest.mark.integration
def test_project_and_task_candidates_carry_linked_names_completion_day_and_trash_rules() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    domain = _domain(factory, owner)
    ada = _contact(factory, owner, "Ada", context_note="Granne")
    cilla = _contact(factory, owner, "Cilla", context_note="Leverantör")
    bo = _contact(factory, owner, "Bo", context_note="Trashed", trashed=True)
    project = _project(
        factory,
        owner,
        domain,
        "Flytt",
        description=MID_TEXT,
        status="completed",
        contacts=(ada, bo),
        target_date=date(2026, 11, 1),
    )
    trashed_project = _project(factory, owner, domain, "Gammalt", trashed=True)
    done = _task(
        factory,
        owner,
        "Ring",
        project_id=project,
        description=LONG_TEXT,
        completed_at=datetime(2026, 10, 20, 15, 30, tzinfo=UTC),
        waiting_on=cilla,
        contacts=(ada, cilla),
    )
    recurring = _task(factory, owner, "Vecka", description=LONG_TEXT, recurring=True)
    orphaned_project = _task(
        factory, owner, "Gammalt projekt", project_id=trashed_project, description=LONG_TEXT
    )
    _task(factory, owner, "Papperskorg", description=LONG_TEXT, trashed=True)

    projects = {c.source_id: c for c in _candidates(factory, owner, MemoryKind.PROJECT)}
    tasks = {c.source_id: c for c in _candidates(factory, owner, MemoryKind.TASK)}

    assert set(projects) == {project}
    assert projects[project].record == ProjectInput(
        title="Flytt",
        description=MID_TEXT,
        definition_of_done=None,
        status=ProjectStatus.COMPLETED,
        start_date=None,
        target_date=date(2026, 11, 1),
        contact_names=("Ada",),
    )
    assert set(tasks) == {done, recurring, orphaned_project}
    assert tasks[done].record == TaskInput(
        title="Ring",
        description=LONG_TEXT,
        project_title="Flytt",
        contact_names=("Ada", "Cilla"),
        completed_on=date(2026, 10, 20),
        is_recurring=False,
    )
    assert tasks[done].is_candidate is True
    assert tasks[recurring].record == TaskInput(
        title="Vecka",
        description=LONG_TEXT,
        project_title=None,
        contact_names=(),
        completed_on=None,
        is_recurring=True,
    )
    assert tasks[recurring].is_candidate is False
    assert tasks[orphaned_project].record == TaskInput(
        title="Gammalt projekt",
        description=LONG_TEXT,
        project_title=None,
        contact_names=(),
        completed_on=None,
        is_recurring=False,
    )


@pytest.mark.integration
def test_completion_day_is_counted_in_the_owner_zone_around_local_midnight() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    # Stockholm is UTC+2 on 2026-10-20, so local midnight into the 21st is 22:00 UTC.
    before = _task(
        factory,
        owner,
        "Före midnatt",
        description=LONG_TEXT,
        completed_at=datetime(2026, 10, 20, 21, 59, tzinfo=UTC),
    )
    after = _task(
        factory,
        owner,
        "Efter midnatt",
        description=LONG_TEXT,
        completed_at=datetime(2026, 10, 20, 22, 0, tzinfo=UTC),
    )

    def completed_days(zone: tzinfo) -> dict[UUID, date | None]:
        page = _candidates(factory, owner, MemoryKind.TASK, owner_timezone=zone)
        return {c.source_id: c.record.completed_on for c in page if isinstance(c.record, TaskInput)}

    assert completed_days(OWNER_ZONE) == {before: date(2026, 10, 20), after: date(2026, 10, 21)}
    assert completed_days(UTC) == {before: date(2026, 10, 20), after: date(2026, 10, 20)}


@pytest.mark.integration
def test_switched_off_domain_has_no_candidates_and_every_memory_row_is_a_tombstone() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, journal=True, contacts=False)
    contact = _contact(factory, owner, "Ada", context_note="Granne")
    memory = _memory_source(factory, owner, MemoryKind.CONTACT, contact)
    no_settings_owner = _owner(factory)
    _task(factory, no_settings_owner, "Uppgift", description=LONG_TEXT)

    assert _candidates(factory, owner, MemoryKind.CONTACT) == []
    assert [t.memory_source_id for t in _tombstones(factory, owner, MemoryKind.CONTACT)] == [memory]
    assert _candidates(factory, no_settings_owner, MemoryKind.TASK) == []


@pytest.mark.integration
def test_tombstones_cover_missing_and_excluded_but_not_trashed_contact_sources() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    live = _contact(factory, owner, "Ada", context_note="Granne")
    trashed = _contact(factory, owner, "Bo", context_note="Gömd", trashed=True)
    excluded = _contact(factory, owner, "Cilla", context_note="Utesluten")
    live_memory = _memory_source(factory, owner, MemoryKind.CONTACT, live)
    trashed_memory = _memory_source(factory, owner, MemoryKind.CONTACT, trashed)
    excluded_memory = _memory_source(factory, owner, MemoryKind.CONTACT, excluded, excluded=True)
    missing_memory = _memory_source(factory, owner, MemoryKind.CONTACT, uuid4())

    tombstones = _tombstones(factory, owner, MemoryKind.CONTACT)
    candidate_ids = {c.source_id for c in _candidates(factory, owner, MemoryKind.CONTACT)}

    # A trashed contact is hidden, not deleted: its document stays so a restore is free.
    assert {t.memory_source_id for t in tombstones} == {excluded_memory, missing_memory}
    assert all(t.kind is MemoryKind.CONTACT for t in tombstones)
    assert live_memory not in {t.memory_source_id for t in tombstones}
    assert trashed_memory not in {t.memory_source_id for t in tombstones}
    assert candidate_ids == {live}


@pytest.mark.integration
def test_trashed_journal_entries_and_sources_are_hidden_but_not_tombstones() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    live_entry = _entry(factory, owner, _source(factory, owner, "Live"), "Live")
    trashed_entry = _entry(
        factory, owner, _source(factory, owner, "Trashed"), "Trashed", trashed=True
    )
    trashed_source_entry = _entry(
        factory,
        owner,
        _source(factory, owner, "Trashed source", trashed=True),
        "Bakom källa",
    )
    for entry in (live_entry, trashed_entry, trashed_source_entry):
        _memory_source(factory, owner, MemoryKind.JOURNAL_ENTRY, entry)

    tombstone_ids = {
        t.memory_source_id for t in _tombstones(factory, owner, MemoryKind.JOURNAL_ENTRY)
    }

    assert tombstone_ids == set()
    assert {c.source_id for c in _candidates(factory, owner, MemoryKind.JOURNAL_ENTRY)} == {
        live_entry
    }


@pytest.mark.integration
def test_pages_are_keyset_bounded_and_the_limit_is_checked() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    ids = [_contact(factory, owner, f"Kontakt {n}", context_note="Granne") for n in range(3)]

    first = _candidates(factory, owner, MemoryKind.CONTACT, limit=2)
    second = _candidates(factory, owner, MemoryKind.CONTACT, after=first[-1].source_id, limit=2)

    assert len(first) == 2
    assert [c.source_id for c in first] + [c.source_id for c in second] == sorted(ids)
    with factory() as session, pytest.raises(InvalidInputError):
        SqlAlchemyMemoryStore(factory).candidate_page(
            session, owner, MemoryKind.CONTACT, owner_timezone=OWNER_ZONE, limit=0
        )
    with factory() as session, pytest.raises(InvalidInputError):
        SqlAlchemyMemoryStore(factory).tombstone_page(
            session, owner, MemoryKind.CONTACT, limit=MAX_PAGE_SIZE + 1
        )


@pytest.mark.integration
def test_other_owner_records_are_never_returned() -> None:
    factory = database_factory()
    mine = _owner(factory)
    other = _owner(factory)
    _enable_all(factory, mine)
    _enable_all(factory, other)
    other_contact = _contact(factory, other, "Annan", context_note="Granne")
    _memory_source(factory, other, MemoryKind.CONTACT, other_contact)
    mine_missing = _memory_source(factory, mine, MemoryKind.CONTACT, uuid4())

    assert _candidates(factory, mine, MemoryKind.CONTACT) == []
    assert [t.memory_source_id for t in _tombstones(factory, mine, MemoryKind.CONTACT)] == [
        mine_missing
    ]

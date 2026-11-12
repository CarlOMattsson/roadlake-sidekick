"""PostgreSQL search reads: ranking, Swedish inflection, trigram fallback, owner and lifecycle."""

from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_app
from sidekick.contacts.application.service import CreateContactCommand
from sidekick.contacts.persistence import PHONETIC_CANDIDATE_LIMIT
from sidekick.search.persistence import (
    ContactHit,
    JournalHit,
    ProjectHit,
    SearchStore,
    TaskHit,
)
from sidekick.shared.persistence.models import (
    ContactRow,
    JournalEntryRow,
    JournalSourceRow,
    ProjectRow,
    TaskRow,
)
from sidekick.shared.types import Actor, new_uuid7
from tests.db import database_factory
from tests.support.settings import make_settings

ALL_SCOPES = frozenset(
    {
        "tasks:read",
        "tasks:write",
        "projects:read",
        "projects:write",
        "contacts:read",
        "contacts:write",
    }
)


def _provision(container: Any, username: str) -> Actor:
    owner_id = container.auth.provision_user(username, username.title())
    return Actor(owner_id, ALL_SCOPES)


def _domain(container: Any, owner: Actor, key: str) -> UUID:
    return container.contexts.create_domain(
        owner, name="Drift", description=None, idempotency_key=f"domain-{key}"
    ).id


def _task(
    container: Any, owner: Actor, title: str, key: str, description: str | None = None
) -> UUID:
    return container.tasks.create(
        owner, title=title, description=description, idempotency_key=f"task-{key}"
    ).id


def _project(container: Any, owner: Actor, domain_id: UUID, title: str, key: str) -> UUID:
    return container.projects.create(
        owner, title=title, domain_id=domain_id, idempotency_key=f"project-{key}"
    ).id


def _contact(container: Any, owner: Actor, name: str, key: str) -> Any:
    return container.contacts.create(owner, CreateContactCommand(name), f"contact-{key}")


def _source(
    factory: sessionmaker[Session],
    owner_id: UUID,
    raw_text: str,
    *,
    replaces: UUID | None = None,
    trashed: bool = False,
) -> UUID:
    source_id = new_uuid7()
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            JournalSourceRow(
                id=source_id,
                owner_id=owner_id,
                source_type="manual_text",
                journal_date=date(2026, 10, 20),
                raw_text=raw_text,
                content_fingerprint=sha256(raw_text.encode()).hexdigest(),
                replaces_source_id=replaces,
                created_at=now,
                trashed_at=now if trashed else None,
            )
        )
    return source_id


def _entry(
    factory: sessionmaker[Session],
    owner_id: UUID,
    source_id: UUID,
    title: str,
    *,
    archived: bool = False,
    trashed: bool = False,
) -> UUID:
    entry_id = new_uuid7()
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            JournalEntryRow(
                id=entry_id,
                owner_id=owner_id,
                source_id=source_id,
                journal_date=date(2026, 10, 20),
                title=title,
                summary=None,
                key_points=[],
                version=1,
                created_at=now,
                updated_at=now,
                archived_at=now if archived else None,
                trashed_at=now if trashed else None,
            )
        )
    return entry_id


def _set_lifecycle(
    factory: sessionmaker[Session], model: type[Any], record_id: UUID, **values: Any
) -> None:
    with factory.begin() as session:
        session.execute(update(model).where(model.id == record_id).values(**values))


def _run[T](factory: sessionmaker[Session], operation: Callable[[Session], T]) -> T:
    return SearchStore(factory).transaction(operation)


def _task_ids(factory: sessionmaker[Session], owner_id: UUID, *terms: str) -> set[UUID]:
    hits: list[TaskHit] = _run(
        factory,
        lambda session: SearchStore.search_tasks(session, owner_id, list(terms), limit=25),
    )
    return {hit.id for hit in hits}


def _project_ids(factory: sessionmaker[Session], owner_id: UUID, *terms: str) -> set[UUID]:
    hits: list[ProjectHit] = _run(
        factory,
        lambda session: SearchStore.search_projects(session, owner_id, list(terms), limit=25),
    )
    return {hit.id for hit in hits}


def _contact_ids(factory: sessionmaker[Session], owner_id: UUID, *terms: str) -> set[UUID]:
    hits: list[ContactHit] = _run(
        factory,
        lambda session: SearchStore.search_contacts(session, owner_id, list(terms), limit=25),
    )
    return {hit.id for hit in hits}


def _journal_hits(factory: sessionmaker[Session], owner_id: UUID, *terms: str) -> list[JournalHit]:
    return _run(
        factory,
        lambda session: SearchStore.search_journal(session, owner_id, list(terms), limit=25),
    )


@pytest.mark.integration
def test_prefix_and_swedish_inflection_find_records() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-prefix")
    matchklockan = _task(container, owner, "Matchklockan", "prefix")
    flickor = _task(
        container, owner, "Ringa leverantören", "inflection", description="Flickorna väntar på svar"
    )

    assert _task_ids(factory, owner.user_id, "match") == {matchklockan}
    assert _task_ids(factory, owner.user_id, "flicka") == {flickor}


@pytest.mark.integration
def test_misspelled_title_is_found_by_trigram_fallback() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-typo")
    task_id = _task(container, owner, "Matchklockan", "typo")

    assert _task_ids(factory, owner.user_id, "machklockan") == {task_id}


@pytest.mark.integration
def test_ranking_puts_title_match_before_description_match() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-rank")
    in_description = _task(
        container,
        owner,
        "Skriv rapporten",
        "rank-description",
        description="Fakturan skickas i dag",
    )
    in_title = _task(container, owner, "Fakturan", "rank-title")

    hits: list[TaskHit] = _run(
        factory,
        lambda session: SearchStore.search_tasks(session, owner.user_id, ["faktura"], limit=10),
    )

    assert [hit.id for hit in hits][:2] == [in_title, in_description]


@pytest.mark.integration
def test_other_owners_records_never_come_back() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-owner")
    other = _provision(container, "search-other")
    own_domain = _domain(container, owner, "owner")
    other_domain = _domain(container, other, "other")
    own_task = _task(container, owner, "Matchklockan", "own-task")
    _task(container, other, "Matchklockan", "other-task")
    own_project = _project(container, owner, own_domain, "Matchprojekt", "own")
    _project(container, other, other_domain, "Matchprojekt", "other")
    own_contact = _contact(container, owner, "Matilda Match", "own")
    _contact(container, other, "Matilda Match", "other")

    assert _task_ids(factory, owner.user_id, "match") == {own_task}
    assert _project_ids(factory, owner.user_id, "match") == {own_project}
    assert _contact_ids(factory, owner.user_id, "match") == {own_contact.id}


@pytest.mark.integration
def test_trashed_and_archived_records_are_excluded() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-lifecycle")
    domain_id = _domain(container, owner, "lifecycle")
    live_task = _task(container, owner, "Ordförande", "live-task")
    trashed_task = _task(container, owner, "Ordförande", "trashed-task")
    archived_task = _task(container, owner, "Ordförande", "archived-task")
    live_project = _project(container, owner, domain_id, "Ordförandeprojekt", "live")
    archived_project = _project(container, owner, domain_id, "Ordförandeprojekt", "archived")
    live_contact = _contact(container, owner, "Ordförande Ek", "live")
    archived_contact = _contact(container, owner, "Ordförande Ek", "archived")
    now = datetime.now(UTC)
    _set_lifecycle(factory, TaskRow, trashed_task, trashed_at=now)
    _set_lifecycle(factory, TaskRow, archived_task, archived_at=now)
    _set_lifecycle(factory, ProjectRow, archived_project, archived_at=now)
    _set_lifecycle(factory, ContactRow, archived_contact.id, archived=True, archived_at=now)

    assert _task_ids(factory, owner.user_id, "ordförande") == {live_task}
    assert _project_ids(factory, owner.user_id, "ordförande") == {live_project}
    assert _contact_ids(factory, owner.user_id, "ordförande") == {live_contact.id}


@pytest.mark.integration
def test_contact_alias_matches_but_alias_text_is_not_returned() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-alias")
    contact = _contact(container, owner, "Anna Svensson", "alias")
    contact = container.contacts.add_alias(
        owner, contact.id, "Annie", contact.version, "alias-annie"
    )

    hits: list[ContactHit] = _run(
        factory,
        lambda session: SearchStore.search_contacts(session, owner.user_id, ["annie"], limit=10),
    )

    assert [hit.id for hit in hits] == [contact.id]
    assert [field.name for field in fields(ContactHit)] == ["id", "display_name", "version"]
    assert hits[0].display_name == "Anna Svensson"


@pytest.mark.integration
def test_misheard_name_finds_contact_by_phonetic_key_in_search_and_list() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-phonetic")
    kjell = _contact(container, owner, "Kjell", "phonetic-kjell")
    _contact(container, owner, "Anna Lind", "phonetic-anna")

    # "Shell" shares too few trigrams with "Kjell" for the typo tolerance, so only the phonetic
    # fallback can find the Contact, on the first try.
    result = container.search.search(owner, "Shell", ["contact"])
    assert [hit.id for hit in result.contacts.hits] == [kjell.id]
    assert result.contacts.hits[0].display_name == "Kjell"
    assert result.contacts.next_cursor is None

    page = container.contacts.list(owner, q="Shell")
    assert [item.id for item in page.items] == [kjell.id]

    # A name that is phonetically unrelated still finds nothing.
    assert container.search.search(owner, "Stella", ["contact"]).contacts.hits == []
    assert container.contacts.list(owner, q="Stella").items == []


@pytest.mark.integration
def test_phonetic_fallback_skips_archived_contacts_unless_asked() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-phonetic-archived")
    archived = _contact(container, owner, "Kjell", "phonetic-archived")
    _set_lifecycle(factory, ContactRow, archived.id, archived=True, archived_at=datetime.now(UTC))

    assert container.search.search(owner, "Shell", ["contact"]).contacts.hits == []
    assert container.contacts.list(owner, q="Shell").items == []
    # The flag is honoured on the list path, so the archived Contact is found only when asked for.
    shown = container.contacts.list(owner, q="Shell", include_archived=True).items
    assert [item.id for item in shown] == [archived.id]


@pytest.mark.integration
def test_phonetic_fallback_skips_trashed_contacts() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-phonetic-trashed")
    trashed = _contact(container, owner, "Kjell", "phonetic-trashed")
    _set_lifecycle(factory, ContactRow, trashed.id, trashed_at=datetime.now(UTC))

    assert container.search.search(owner, "Shell", ["contact"]).contacts.hits == []
    assert container.contacts.list(owner, q="Shell", include_archived=True).items == []


@pytest.mark.integration
def test_phonetic_fallback_never_finds_another_owners_contact() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-phonetic-owner")
    other = _provision(container, "search-phonetic-other")
    _contact(container, other, "Kjell", "phonetic-other")

    assert container.search.search(owner, "Shell", ["contact"]).contacts.hits == []
    assert container.contacts.list(owner, q="Shell").items == []

    # Positive control: the owner's own Kjell is found by the same query.
    own = _contact(container, owner, "Kjell", "phonetic-own")
    hits = container.search.search(owner, "Shell", ["contact"]).contacts.hits
    assert [hit.id for hit in hits] == [own.id]


@pytest.mark.integration
def test_phonetic_fallback_reads_only_the_newest_200_contacts() -> None:
    assert PHONETIC_CANDIDATE_LIMIT == 200
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-phonetic-limit")
    # The match is created first, so it is the oldest Contact and the last candidate in the read.
    match = _contact(container, owner, "Kjell", "phonetic-limit-match")
    for number in range(PHONETIC_CANDIDATE_LIMIT - 1):
        _contact(container, owner, f"Gunnar Berg {number}", f"phonetic-limit-{number}")

    # Exactly 200 Contacts are read, so the match, at position 200, is still found.
    hits = container.search.search(owner, "Shell", ["contact"]).contacts.hits
    assert [hit.id for hit in hits] == [match.id]

    # One newer Contact pushes the match to position 201, outside the bounded read.
    _contact(container, owner, "Olle Ek", "phonetic-limit-extra")
    assert container.search.search(owner, "Shell", ["contact"]).contacts.hits == []


@pytest.mark.integration
def test_journal_source_hit_has_null_title_and_no_excerpt() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-source")
    source_only = _source(factory, owner.user_id, "Bilmekanik och oljebyte idag")
    backed_source = _source(factory, owner.user_id, "Mekanikern sa att bromsarna är slitna")
    backed_entry = _entry(factory, owner.user_id, backed_source, "Verkstadsbesök")

    hits = _journal_hits(factory, owner.user_id, "bilmekanik")
    assert [(hit.id, hit.id_type, hit.matched_in) for hit in hits] == [
        (source_only, "source", "source_text")
    ]
    assert {field.name for field in fields(JournalHit)} == {
        "id",
        "id_type",
        "journal_date",
        "matched_in",
        "title",
    }
    assert hits[0].title is None
    assert not hasattr(hits[0], "summary")
    assert not hasattr(hits[0], "text")

    entry_hits = _journal_hits(factory, owner.user_id, "broms")
    assert [(hit.id, hit.id_type, hit.matched_in, hit.title) for hit in entry_hits] == [
        (backed_entry, "entry", "source_text", "Verkstadsbesök")
    ]


@pytest.mark.integration
def test_journal_excludes_trashed_replaced_and_archived_content() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-journal-lifecycle")
    _source(factory, owner.user_id, "kvarnstensbrott", trashed=True)
    replaced = _source(factory, owner.user_id, "gammaltord hos ägaren")
    _source(factory, owner.user_id, "nyare text", replaces=replaced)
    archived_source = _source(factory, owner.user_id, "arkivtext om fiskeläge")
    _entry(factory, owner.user_id, archived_source, "Arkiverad", archived=True)
    trashed_entry_source = _source(factory, owner.user_id, "papperskorgstext om hamnar")
    _entry(factory, owner.user_id, trashed_entry_source, "Borttagen", trashed=True)

    assert _journal_hits(factory, owner.user_id, "kvarnstensbrott") == []
    assert _journal_hits(factory, owner.user_id, "gammaltord") == []
    assert _journal_hits(factory, owner.user_id, "fiskeläge") == []
    assert _journal_hits(factory, owner.user_id, "hamnar") == []


@pytest.mark.integration
def test_journal_search_is_owner_scoped() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-journal-owner")
    other = _provision(container, "search-journal-other")
    own_source = _source(factory, owner.user_id, "Hemligt ord tuppkött")
    _source(factory, other.user_id, "Hemligt ord tuppkött")

    hits = _journal_hits(factory, owner.user_id, "tuppkött")

    assert [hit.id for hit in hits] == [own_source]


@pytest.mark.integration
def test_journal_entry_title_hit_is_reported_as_entry_match() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-journal-entry-match")
    source_id = _source(factory, owner.user_id, "Mötesanteckningar från dagen")
    entry_id = _entry(factory, owner.user_id, source_id, "Revisionsmötet")

    hits = _journal_hits(factory, owner.user_id, "revision")

    assert [(hit.id, hit.id_type, hit.matched_in, hit.title) for hit in hits] == [
        (entry_id, "entry", "entry", "Revisionsmötet")
    ]


@pytest.mark.integration
def test_trashed_project_and_contact_are_excluded() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-trashed-project-contact")
    domain_id = _domain(container, owner, "trashed-project-contact")
    live_project = _project(container, owner, domain_id, "Tömningsprojekt", "live")
    trashed_project = _project(container, owner, domain_id, "Tömningsprojekt", "trashed")
    live_contact = _contact(container, owner, "Tömning Ek", "live")
    trashed_contact = _contact(container, owner, "Tömning Ek", "trashed")
    _set_lifecycle(factory, ProjectRow, trashed_project, trashed_at=datetime.now(UTC))
    _set_lifecycle(factory, ContactRow, trashed_contact.id, trashed_at=datetime.now(UTC))

    assert _project_ids(factory, owner.user_id, "tömning") == {live_project}
    assert _contact_ids(factory, owner.user_id, "tömning") == {live_contact.id}


@pytest.mark.integration
def test_foreign_alias_and_foreign_journal_entry_never_come_back() -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner = _provision(container, "search-foreign-alias-owner")
    other = _provision(container, "search-foreign-alias-other")
    own_contact = _contact(container, owner, "Annie Lind", "foreign-own")
    foreign_contact = _contact(container, other, "Anna Svensson", "foreign-other")
    container.contacts.add_alias(
        other, foreign_contact.id, "Annie", foreign_contact.version, "foreign-alias-annie"
    )
    foreign_source = _source(factory, other.user_id, "Mötesanteckningar från en annan ägare")
    _entry(factory, other.user_id, foreign_source, "Annie-möte")

    assert _contact_ids(factory, owner.user_id, "annie") == {own_contact.id}
    assert _journal_hits(factory, owner.user_id, "annie") == []

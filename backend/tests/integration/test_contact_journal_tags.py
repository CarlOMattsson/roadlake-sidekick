"""Contacts and Journal entries carry tags from the owner's one vocabulary (PostgreSQL).

The use cases keep the rules: the complete intended set replaces the tags, the version moves with
them, a replay is idempotent, a filter lists by tag, and one owner never sees or links another's
tags. The database keeps the last line of defence: a link can only join two records of one owner.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from sidekick.api.app import Container, create_container
from sidekick.contacts.application.models import CreateContactCommand, UpdateContactCommand
from sidekick.contacts.domain.contact import Contact
from sidekick.journal.application.models import RelationChange
from sidekick.journal.domain.entry import JournalEntry, KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.shared.errors import (
    IdempotencyKeyReusedError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

DAY = date(2026, 7, 21)
SCOPES = frozenset(
    {"contacts:read", "contacts:write", "journal:read", "journal:write", "projects:read"}
)
POINT = KeyPoint(KeyPointKind.FACT, "Talked it through")


def _setup(name: str = "owner") -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    return container, Actor(container.auth.provision_user(name, name.title()), SCOPES)


def _contact(
    container: Container, actor: Actor, name: str, *tags: str, key: str | None = None
) -> Contact:
    return container.contacts.create(
        actor,
        CreateContactCommand(display_name=name, tags=tags),
        idempotency_key=key or f"create-{name}",
    )


def _entry(
    container: Container, actor: Actor, title: str, *tags: str, key: str | None = None
) -> JournalEntry:
    _, entry = container.journal_capture.write_entry(
        actor,
        source_type=SourceType.TRANSCRIPT_TEXT,
        journal_date=DAY,
        occurred_at=None,
        raw_text=f"Words for {title}",
        language=None,
        title=title,
        summary=None,
        key_points=(POINT,),
        tags=tags,
        idempotency_key=key or f"write-{title}",
    )
    return entry


def _slugs(container: Container, actor: Actor, kind: str, record_id: UUID) -> list[str]:
    return sorted(tag.slug for tag in container.work_tags.for_record(actor, kind, record_id))


# --- Contacts ---------------------------------------------------------------------------------


@pytest.mark.integration
def test_a_contact_is_created_with_tags_that_join_the_vocabulary() -> None:
    container, actor = _setup()

    contact = _contact(container, actor, "Anna", "Viktig", "familj", "viktig")

    assert _slugs(container, actor, "contact", contact.id) == ["familj", "viktig"]
    vocabulary = [tag.slug for tag in container.work_tags.list(actor).items]
    assert vocabulary == ["familj", "viktig"]


@pytest.mark.integration
def test_updating_a_contacts_tags_replaces_the_set_and_advances_the_version() -> None:
    container, actor = _setup()
    contact = _contact(container, actor, "Anna", "viktig")

    only_tags = container.contacts.update(
        actor,
        contact.id,
        contact.version,
        UpdateContactCommand(tags=("vänta", "familj")),
        "retag-1",
    )

    assert only_tags.version == contact.version + 1
    assert only_tags.display_name == "Anna"
    assert _slugs(container, actor, "contact", contact.id) == ["familj", "vänta"]

    cleared = container.contacts.update(
        actor, contact.id, only_tags.version, UpdateContactCommand(tags=()), "retag-2"
    )
    assert cleared.version == only_tags.version + 1
    assert _slugs(container, actor, "contact", contact.id) == []


@pytest.mark.integration
def test_leaving_tags_out_of_an_update_keeps_them() -> None:
    container, actor = _setup()
    contact = _contact(container, actor, "Anna", "viktig")

    renamed = container.contacts.update(
        actor, contact.id, contact.version, UpdateContactCommand(display_name="Anna Lind"), "name"
    )

    assert renamed.display_name == "Anna Lind"
    assert _slugs(container, actor, "contact", contact.id) == ["viktig"]


@pytest.mark.integration
def test_a_tag_update_checks_the_expected_version_and_is_idempotent() -> None:
    container, actor = _setup()
    contact = _contact(container, actor, "Anna")
    command = UpdateContactCommand(tags=("viktig",))

    first = container.contacts.update(actor, contact.id, contact.version, command, "retag")
    replay = container.contacts.update(actor, contact.id, contact.version, command, "retag")

    assert replay.version == first.version == contact.version + 1
    with pytest.raises(IdempotencyKeyReusedError):
        container.contacts.update(
            actor, contact.id, contact.version, UpdateContactCommand(tags=("annat",)), "retag"
        )
    with pytest.raises(Exception, match="stale"):
        container.contacts.update(
            actor, contact.id, contact.version, UpdateContactCommand(tags=("nytt",)), "retag-late"
        )
    assert _slugs(container, actor, "contact", contact.id) == ["viktig"]


@pytest.mark.integration
def test_an_archived_contact_cannot_be_retagged() -> None:
    container, actor = _setup()
    contact = _contact(container, actor, "Anna", "viktig")
    archived = container.contacts.archive(actor, contact.id, contact.version, "archive")

    with pytest.raises(NotFoundError):
        container.contacts.update(
            actor, contact.id, archived.version, UpdateContactCommand(tags=()), "retag"
        )
    assert _slugs(container, actor, "contact", contact.id) == ["viktig"]


@pytest.mark.integration
def test_too_many_tags_roll_the_whole_contact_write_back() -> None:
    container, actor = _setup()

    with pytest.raises(ValidationError, match="at most"):
        _contact(container, actor, "Anna", *(f"t{n}" for n in range(11)))

    assert container.contacts.list(actor).items == []


@pytest.mark.integration
def test_contacts_are_listed_by_tag_with_any_or_all_matching() -> None:
    container, actor = _setup()
    anna = _contact(container, actor, "Anna", "viktig", "familj")
    bo = _contact(container, actor, "Bo", "viktig")
    _contact(container, actor, "Cia")

    def names(**filters: Any) -> list[str]:
        return [item.display_name for item in container.contacts.list(actor, **filters).items]

    assert names(tags=["viktig"]) == ["Anna", "Bo"]
    assert names(tags=["Familj"]) == ["Anna"]
    assert names(tags=["viktig", "familj"]) == ["Anna", "Bo"]
    assert names(tags=["viktig", "familj"], tag_match="all") == ["Anna"]
    assert names(tags=["okänd"]) == []
    assert names() == ["Anna", "Bo", "Cia"]
    assert {item.id for item in container.contacts.list(actor, tags=["viktig"]).items} == {
        anna.id,
        bo.id,
    }


@pytest.mark.integration
def test_a_tag_filter_pages_with_its_own_cursor() -> None:
    container, actor = _setup()
    for name in ("Anna", "Bo", "Cia"):
        _contact(container, actor, name, "viktig")

    first = container.contacts.list(actor, tags=["viktig"], limit=2)
    second = container.contacts.list(actor, tags=["viktig"], limit=2, cursor=first.next_cursor)

    assert [c.display_name for c in first.items] == ["Anna", "Bo"]
    assert [c.display_name for c in second.items] == ["Cia"]
    # A cursor made for one filter is not valid for another.
    with pytest.raises(Exception, match="cursor"):
        container.contacts.list(actor, tags=["familj"], limit=2, cursor=first.next_cursor)


@pytest.mark.integration
def test_a_misheard_name_search_does_not_widen_a_tag_filter() -> None:
    container, actor = _setup()
    _contact(container, actor, "Kjell")

    assert container.contacts.list(actor, q="Shell").items  # the phonetic fallback finds him
    assert container.contacts.list(actor, q="Shell", tags=["viktig"]).items == []


# --- Journal entries --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_journal_entry_is_written_with_tags() -> None:
    container, actor = _setup()

    entry = _entry(container, actor, "Dag", "Viktig", "familj")

    assert _slugs(container, actor, "journal_entry", entry.id) == ["familj", "viktig"]


@pytest.mark.integration
def test_a_replayed_entry_write_with_other_tags_is_refused() -> None:
    container, actor = _setup()
    entry = _entry(container, actor, "Dag", "viktig", key="same")

    again = _entry(container, actor, "Dag", "viktig", key="same")

    assert again.id == entry.id
    with pytest.raises(IdempotencyKeyReusedError):
        _entry(container, actor, "Dag", "annat", key="same")


@pytest.mark.integration
def test_a_tags_only_update_keeps_the_content_and_advances_the_version() -> None:
    container, actor = _setup()
    entry = _entry(container, actor, "Dag", "viktig")

    updated = container.journal.change_entry_relations(
        actor,
        entry_id=entry.id,
        expected_version=entry.version,
        change=_no_link_change(),
        tags=("vänta",),
        idempotency_key="retag",
    )

    assert updated.version == entry.version + 1
    assert updated.title == entry.title
    assert updated.key_points == entry.key_points
    assert _slugs(container, actor, "journal_entry", entry.id) == ["vänta"]


def _no_link_change() -> RelationChange:
    return RelationChange()


@pytest.mark.integration
def test_replacing_and_appending_to_an_entry_can_set_its_tags() -> None:
    container, actor = _setup()
    entry = _entry(container, actor, "Dag", "viktig")

    appended = container.journal.append_to_entry(
        actor,
        entry_id=entry.id,
        expected_version=entry.version,
        append_key_points=(KeyPoint(KeyPointKind.FACT, "More"),),
        append_text=None,
        tags=("familj",),
        idempotency_key="append",
    )
    assert _slugs(container, actor, "journal_entry", entry.id) == ["familj"]

    replaced = container.journal.update_entry(
        actor,
        entry_id=entry.id,
        expected_version=appended.version,
        title="Ny titel",
        summary=None,
        key_points=(POINT,),
        tags=(),
        idempotency_key="replace",
    )
    assert replaced.title == "Ny titel"
    assert _slugs(container, actor, "journal_entry", entry.id) == []


@pytest.mark.integration
def test_an_update_that_names_no_tags_leaves_them_alone() -> None:
    container, actor = _setup()
    entry = _entry(container, actor, "Dag", "viktig")

    container.journal.update_entry(
        actor,
        entry_id=entry.id,
        expected_version=entry.version,
        title="Ny titel",
        summary=None,
        key_points=(POINT,),
        idempotency_key="no-tags",
    )

    assert _slugs(container, actor, "journal_entry", entry.id) == ["viktig"]


@pytest.mark.integration
def test_entries_are_listed_by_tag() -> None:
    container, actor = _setup()
    _entry(container, actor, "Ett", "viktig", "familj")
    _entry(container, actor, "Två", "viktig")
    _entry(container, actor, "Tre")

    def titles(**filters: Any) -> list[str]:
        page = container.journal.list_entries(actor, start_date=DAY, end_date=DAY, **filters)
        return sorted(entry.title for entry in page.items)

    assert titles(tags=["viktig"]) == ["Ett", "Två"]
    assert titles(tags=["viktig", "familj"], tag_match="all") == ["Ett"]
    assert titles(tags=["saknas"]) == []
    assert titles() == ["Ett", "Tre", "Två"]


# --- The vocabulary across kinds, and the owner boundary --------------------------------------


@pytest.mark.integration
def test_the_vocabulary_counts_use_across_every_kind() -> None:
    container, actor = _setup()
    _contact(container, actor, "Anna", "viktig")
    _contact(container, actor, "Bo", "viktig")
    _entry(container, actor, "Dag", "viktig", "familj")
    container.tasks.create(
        Actor(actor.user_id, SCOPES | {"tasks:write", "projects:read"}),
        title="Task",
        idempotency_key="task",
        tags=("viktig",),
    )

    tags = container.work_tags.list(actor).items
    usage = container.work_tags.usage(actor, [tag.id for tag in tags])
    by_slug = {tag.slug: usage[tag.id] for tag in tags}

    assert by_slug["viktig"] == {
        "domain": 0,
        "process": 0,
        "project": 0,
        "task": 1,
        "contact": 2,
        "journal_entry": 1,
    }
    assert by_slug["familj"]["journal_entry"] == 1
    assert sum(by_slug["familj"].values()) == 1


@pytest.mark.integration
def test_tags_never_cross_owners() -> None:
    container, alice = _setup("alice")
    bob = Actor(container.auth.provision_user("bob", "Bob"), SCOPES)
    anna = _contact(container, alice, "Anna", "hemlig")
    entry = _entry(container, alice, "Dag", "hemlig")

    # Bob's vocabulary and lists know nothing of Alice's tags.
    assert container.work_tags.list(bob).items == []
    assert container.contacts.list(bob, tags=["hemlig"]).items == []
    assert (
        container.journal.list_entries(bob, start_date=DAY, end_date=DAY, tags=["hemlig"]).items
        == []
    )
    # Bob tagging with the same word makes his own entry, not a link to Alice's.
    _contact(container, bob, "Anna", "hemlig")
    assert len(container.work_tags.list(bob).items) == 1
    assert len(container.work_tags.list(alice).items) == 1
    assert _slugs(container, alice, "contact", anna.id) == ["hemlig"]
    assert _slugs(container, alice, "journal_entry", entry.id) == ["hemlig"]
    # Bob reading the tags of Alice's contact finds none: the read is owner-scoped.
    assert container.work_tags.for_record(bob, "contact", anna.id) == []


@pytest.mark.integration
def test_the_database_refuses_a_link_between_two_owners_records() -> None:
    container, alice = _setup("alice")
    bob = Actor(container.auth.provision_user("bob", "Bob"), SCOPES)
    anna = _contact(container, alice, "Anna")
    entry = _entry(container, alice, "Dag")
    _contact(container, bob, "Bo", "hans")
    bobs_tag = container.work_tags.list(bob).items[0].id
    store = container.contacts.store

    for table, column, record_id in (
        ("contact_tags", "contact_id", anna.id),
        ("journal_entry_tags", "journal_entry_id", entry.id),
    ):
        # Alice's record, Bob's tag, written as Bob: the composite foreign keys refuse it.
        statement = text(
            f"INSERT INTO sidekick.{table} (owner_id, tag_id, {column}, created_at) "  # noqa: S608
            "VALUES (:owner, :tag, :record, now())"
        )
        with pytest.raises(IntegrityError):
            store.transaction(
                lambda session, statement=statement, record_id=record_id: session.execute(
                    statement, {"owner": bob.user_id, "tag": bobs_tag, "record": record_id}
                )
            )


@pytest.mark.integration
def test_reading_the_tags_of_a_kind_needs_that_kinds_read_scope() -> None:
    container, actor = _setup()
    contact = _contact(container, actor, "Anna", "viktig")
    entry = _entry(container, actor, "Dag", "viktig")
    work_only = Actor(actor.user_id, frozenset({"projects:read"}))

    with pytest.raises(PermissionDeniedError):
        container.work_tags.for_record(work_only, "contact", contact.id)
    with pytest.raises(PermissionDeniedError):
        container.work_tags.slugs_for(work_only, "journal_entry", [entry.id])
    with pytest.raises(PermissionDeniedError):
        container.contacts.list(work_only)
    contacts_only = Actor(actor.user_id, frozenset({"contacts:read"}))
    assert container.work_tags.for_record(contacts_only, "contact", contact.id)
    with pytest.raises(PermissionDeniedError):
        container.work_tags.for_record(contacts_only, "journal_entry", entry.id)


@pytest.mark.integration
def test_tagging_needs_the_write_scope_of_the_record() -> None:
    container, actor = _setup()
    reader = Actor(actor.user_id, frozenset({"contacts:read", "journal:read"}))

    with pytest.raises(PermissionDeniedError):
        _contact(container, reader, "Anna", "viktig")
    with pytest.raises(PermissionDeniedError):
        _entry(container, reader, "Dag", "viktig")


def test_every_tagged_kind_has_a_link_table_and_a_listed_filter() -> None:
    from sidekick.work.application.tags_service import TAGGED_KINDS
    from sidekick.work.persistence.tags import _LISTED, TAG_LINKS

    assert set(TAGGED_KINDS) == set(TAG_LINKS) == set(_LISTED)

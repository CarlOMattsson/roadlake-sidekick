"""Tag assignment for any tagged record, without a database: the rules sit in the domain."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from sidekick.contacts.domain.contact import Contact
from sidekick.shared.errors import ValidationError
from sidekick.work.domain.planning import MAX_TAGS_PER_RECORD, WorkTag
from sidekick.work.domain.tag_assignment import apply_record_tags

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
OWNER = uuid4()


class FakeTagStore:
    """The three operations tag assignment needs, over plain dictionaries."""

    def __init__(self) -> None:
        self.tags: dict[str, WorkTag] = {}
        self.links: dict[tuple[str, UUID], tuple[UUID, ...]] = {}

    def find_work_tag_by_slug(self, session: Any, owner_id: UUID, slug: str) -> WorkTag | None:
        return self.tags.get(slug)

    def save_work_tag(
        self, session: Any, tag: WorkTag, expected_version: int | None = None
    ) -> None:
        self.tags[tag.slug] = tag

    def replace_record_tags(
        self, session: Any, owner_id: UUID, kind: str, record_id: UUID, tag_ids: tuple[UUID, ...]
    ) -> None:
        self.links[(kind, record_id)] = tag_ids


def _apply(store: FakeTagStore, kind: str, record_id: UUID, values: list[str] | None) -> Any:
    return apply_record_tags(
        store, None, owner_id=OWNER, kind=kind, record_id=record_id, values=values, now=NOW
    )


@pytest.mark.parametrize("kind", ["contact", "journal_entry"])
def test_the_complete_set_is_normalized_and_linked_for_any_kind(kind: str) -> None:
    store = FakeTagStore()
    record = uuid4()

    slugs = _apply(store, kind, record, ["  Viktig ", "viktig", "Vänta här"])

    assert slugs == ("viktig", "vänta-här")
    assert [store.tags[slug].id for slug in slugs] == list(store.links[(kind, record)])


def test_one_vocabulary_entry_serves_every_kind() -> None:
    store = FakeTagStore()
    contact, entry = uuid4(), uuid4()

    _apply(store, "contact", contact, ["familj"])
    _apply(store, "journal_entry", entry, ["familj"])

    assert len(store.tags) == 1
    assert store.links[("contact", contact)] == store.links[("journal_entry", entry)]


def test_an_empty_or_missing_set_removes_every_link() -> None:
    store = FakeTagStore()
    record = uuid4()
    _apply(store, "contact", record, ["viktig"])

    assert _apply(store, "contact", record, []) == ()
    assert store.links[("contact", record)] == ()
    assert _apply(store, "contact", record, None) == ()


def test_the_same_set_twice_leaves_one_vocabulary_entry() -> None:
    store = FakeTagStore()
    record = uuid4()

    _apply(store, "contact", record, ["viktig", "vänta"])
    first = dict(store.tags)
    _apply(store, "contact", record, ["vänta", "viktig"])

    assert store.tags == first


def test_more_tags_than_a_record_may_carry_are_refused_before_anything_is_written() -> None:
    store = FakeTagStore()

    with pytest.raises(ValidationError, match="at most"):
        _apply(store, "contact", uuid4(), [f"tag{n}" for n in range(MAX_TAGS_PER_RECORD + 1)])

    assert store.tags == {}
    assert store.links == {}


@pytest.mark.parametrize("value", ["", "   ", "-"])
def test_a_tag_without_a_visible_character_is_refused(value: str) -> None:
    with pytest.raises(ValidationError, match="visible character"):
        _apply(FakeTagStore(), "journal_entry", uuid4(), [value])


def _contact(**changes: Any) -> Contact:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "owner_id": OWNER,
        "display_name": "Anna",
        "display_name_key": "anna",
        "context_note": None,
        "email": None,
        "email_key": None,
        "phone": None,
        "phone_key": None,
        "aliases": [],
        "archived": False,
        "created_at": NOW,
        "updated_at": NOW,
        "archived_at": None,
        "version": 1,
    }
    return Contact(**{**fields, **changes})


def test_retagging_a_contact_advances_its_version_only() -> None:
    contact = _contact()
    later = datetime(2026, 11, 2, tzinfo=UTC)

    retagged = contact.retag(now=later)

    assert retagged.version == 2
    assert retagged.updated_at == later
    assert retagged.display_name == contact.display_name


def test_an_archived_contact_cannot_be_retagged() -> None:
    archived = _contact(archived=True, archived_at=NOW)

    with pytest.raises(ValidationError, match="archived"):
        archived.retag(now=NOW)

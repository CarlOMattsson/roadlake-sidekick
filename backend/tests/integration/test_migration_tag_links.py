"""Migration 107 adds the tag links of Contacts and Journal entries, and nothing else.

Each test builds the database as an installation that ran up to migration 106 has it, then applies
`migrations/`. The links are new tables, so an existing installation keeps every row it has, and a
rollback drops only the links: the vocabulary, the contacts and the entries stay.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from yoyo import get_backend, read_migrations

from tests.support.migration_baseline import (
    BASELINE,
    DROP_AUTOMATION,
    MIGRATIONS_PATH,
    TAG_LINKS,
    _admin_url,
    _applied_ids,
    _apply,
    _migration_url,
    _reset_schema,
    _run,
    _snapshot,
    _tables,
    rebuilt_schema,  # noqa: F401  (a fixture, used through `usefixtures`)
)

LINK_TABLES = ("contact_tags", "journal_entry_tags")
OWNER = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
CONTACT = "00000000-0000-4000-8000-0000000000c1"
SOURCE = "00000000-0000-4000-8000-0000000000a1"
ENTRY = "00000000-0000-4000-8000-0000000000e1"
TAG = "00000000-0000-4000-8000-0000000000f1"
OTHER_TAG = "00000000-0000-4000-8000-0000000000f2"
IDS: dict[str, object] = {
    "owner": OWNER,
    "other": OTHER,
    "contact": CONTACT,
    "source": SOURCE,
    "entry": ENTRY,
    "tag": TAG,
    "other_tag": OTHER_TAG,
}
ROWS = (
    "INSERT INTO sidekick.users (id, username, display_name, created_at) "
    "VALUES (:owner, 'kept', 'Kept', now()), (:other, 'other', 'Other', now())",
    "INSERT INTO sidekick.contacts "
    "(id, owner_id, display_name, display_name_key, created_at, updated_at, version) "
    "VALUES (:contact, :owner, 'Anna', 'anna', now(), now(), 1)",
    "INSERT INTO sidekick.journal_sources "
    "(id, owner_id, source_type, journal_date, raw_text, content_fingerprint, created_at) "
    "VALUES (:source, :owner, 'manual_text', current_date, 'Words', repeat('a', 64), now())",
    "INSERT INTO sidekick.journal_entries "
    "(id, owner_id, source_id, journal_date, title, key_points, version, created_at, updated_at) "
    "VALUES (:entry, :owner, :source, current_date, 'Day', '[]'::jsonb, 1, now(), now())",
    "INSERT INTO sidekick.work_tags (id, owner_id, slug, label, created_at, updated_at, version) "
    "VALUES (:tag, :owner, 'viktig', 'viktig', now(), now(), 1), "
    "(:other_tag, :other, 'viktig', 'viktig', now(), now(), 1)",
)
LINK_CONTACT = (
    "INSERT INTO sidekick.contact_tags (owner_id, tag_id, contact_id, created_at) "
    "VALUES (:owner, :tag, :contact, now())"
)
LINK_ENTRY = (
    "INSERT INTO sidekick.journal_entry_tags (owner_id, tag_id, journal_entry_id, created_at) "
    "VALUES (:owner, :tag, :entry, now())"
)


def _chain_before_the_links(tmp_path: Path) -> Path:
    """A migrations directory with every migration up to 106, which is the chain before 107."""

    directory = tmp_path / "before-the-links"
    directory.mkdir()
    for name in (BASELINE, DROP_AUTOMATION):
        (directory / f"{name}.py").write_text(
            (MIGRATIONS_PATH / f"{name}.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
    return directory


def _installation_before_the_links(tmp_path: Path) -> None:
    _reset_schema()
    _apply(_chain_before_the_links(tmp_path))
    for statement in ROWS:
        _run(statement, IDS)


def _scalar(sql: str) -> object:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return connection.scalar(text(sql))
    finally:
        engine.dispose()


def _tables_now() -> set[str]:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return _tables(connection)
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_links_are_added_and_every_existing_row_is_kept(tmp_path: Path) -> None:
    _installation_before_the_links(tmp_path)
    before = _tables_now()
    assert set(LINK_TABLES).isdisjoint(before)

    _apply(MIGRATIONS_PATH)

    assert _tables_now() == before | set(LINK_TABLES)
    assert _applied_ids() == {BASELINE, DROP_AUTOMATION, TAG_LINKS}
    assert _scalar("SELECT count(*) FROM sidekick.contacts") == 1
    assert _scalar("SELECT count(*) FROM sidekick.journal_entries") == 1
    assert _scalar("SELECT count(*) FROM sidekick.work_tags") == 2
    backend = get_backend(_migration_url())
    assert not list(backend.to_apply(read_migrations(str(MIGRATIONS_PATH))))


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_end_state_equals_a_fresh_install(tmp_path: Path) -> None:
    _reset_schema()
    _apply(MIGRATIONS_PATH)
    fresh = _snapshot()

    _installation_before_the_links(tmp_path)
    _run("DELETE FROM sidekick.users")
    _apply(MIGRATIONS_PATH)

    assert _snapshot() == fresh


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_link_only_joins_one_owners_tag_and_record(tmp_path: Path) -> None:
    _installation_before_the_links(tmp_path)
    _apply(MIGRATIONS_PATH)

    _run(LINK_CONTACT, IDS)
    _run(LINK_ENTRY, IDS)
    assert _scalar("SELECT count(*) FROM sidekick.contact_tags") == 1
    assert _scalar("SELECT count(*) FROM sidekick.journal_entry_tags") == 1
    # The other owner's tag cannot be put on this owner's records.
    with pytest.raises(IntegrityError):
        _run(LINK_CONTACT.replace(":tag", ":other_tag"), IDS)
    with pytest.raises(IntegrityError):
        _run(LINK_ENTRY.replace(":tag", ":other_tag"), IDS)
    # The same link twice is one link.
    with pytest.raises(IntegrityError):
        _run(LINK_CONTACT, IDS)


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_links_follow_their_tag_and_their_record(tmp_path: Path) -> None:
    _installation_before_the_links(tmp_path)
    _apply(MIGRATIONS_PATH)
    _run(LINK_CONTACT, IDS)
    _run(LINK_ENTRY, IDS)

    _run("DELETE FROM sidekick.journal_entries WHERE id = :entry", IDS)
    assert _scalar("SELECT count(*) FROM sidekick.journal_entry_tags") == 0
    assert _scalar("SELECT count(*) FROM sidekick.contact_tags") == 1
    _run("DELETE FROM sidekick.work_tags WHERE id = :tag", IDS)
    assert _scalar("SELECT count(*) FROM sidekick.contact_tags") == 0
    assert _scalar("SELECT count(*) FROM sidekick.contacts") == 1


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_rollback_drops_only_the_links(tmp_path: Path) -> None:
    _installation_before_the_links(tmp_path)
    _apply(MIGRATIONS_PATH)
    _run(LINK_CONTACT, IDS)
    backend = get_backend(_migration_url())
    migration = next(item for item in read_migrations(str(MIGRATIONS_PATH)) if item.id == TAG_LINKS)

    with backend.lock():
        backend.rollback_one(migration)

    assert set(LINK_TABLES).isdisjoint(_tables_now())
    assert _applied_ids() == {BASELINE, DROP_AUTOMATION}
    assert _scalar("SELECT count(*) FROM sidekick.contacts") == 1
    assert _scalar("SELECT count(*) FROM sidekick.work_tags") == 2
    # And it applies again.
    _apply(MIGRATIONS_PATH)
    assert set(LINK_TABLES) <= _tables_now()

"""Migration 117 adds the metadata table of Journal photos, and nothing else.

Each test builds the database as an installation that ran up to migration 116 has it, then applies
the chain through 117. The table is new, so an installation keeps every row it has, a rollback drops
only the photo metadata, and the application role may erase a photo row (unlike a Journal entry)
but never change the table's shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from yoyo import get_backend, read_migrations

from tests.db import require_test_database_url
from tests.support.migration_baseline import (
    AUTOMATIONS,
    JOURNAL_ATTACHMENTS,
    MIGRATIONS_PATH,
    _admin_url,
    _applied_ids,
    _apply,
    _migration_url,
    _reset_schema,
    _run,
    _snapshot,
    _tables,
    chain_through,
    ids_through,
    rebuilt_schema,  # noqa: F401  (a fixture, used through `usefixtures`)
)

OWNER = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
SOURCE = "00000000-0000-4000-8000-0000000000a1"
ENTRY = "00000000-0000-4000-8000-0000000000e1"
PHOTO = "00000000-0000-4000-8000-0000000000b1"
IDS: dict[str, object] = {
    "owner": OWNER,
    "other": OTHER,
    "source": SOURCE,
    "entry": ENTRY,
    "photo": PHOTO,
}
ROWS = (
    "INSERT INTO sidekick.users (id, username, display_name, created_at) "
    "VALUES (:owner, 'kept', 'Kept', now()), (:other, 'other', 'Other', now())",
    "INSERT INTO sidekick.journal_sources "
    "(id, owner_id, source_type, journal_date, raw_text, content_fingerprint, created_at) "
    "VALUES (:source, :owner, 'manual_text', current_date, 'Words', repeat('a', 64), now())",
    "INSERT INTO sidekick.journal_entries "
    "(id, owner_id, source_id, journal_date, title, key_points, version, created_at, updated_at) "
    "VALUES (:entry, :owner, :source, current_date, 'Day', '[]'::jsonb, 1, now(), now())",
)
# A valid photo row on the entry; the tests change one field at a time.
PHOTO_COLUMNS = (
    "id, owner_id, entry_id, journal_date, media_type, byte_size, width, height, content_digest, "
    "thumb_digest, thumb_size, alt_text, alt_text_by, taken_at, position, version, created_at, "
    "updated_at"
)
PHOTO_VALUES = {
    "id": ":photo",
    "owner_id": ":owner",
    "entry_id": ":entry",
    "journal_date": "NULL",
    "media_type": "'image/jpeg'",
    "byte_size": "1000",
    "width": "800",
    "height": "600",
    "content_digest": "repeat('a', 64)",
    "thumb_digest": "repeat('b', 64)",
    "thumb_size": "900",
    "alt_text": "NULL",
    "alt_text_by": "NULL",
    "taken_at": "NULL",
    "position": "0",
    "version": "1",
    "created_at": "now()",
    "updated_at": "now()",
}


def _insert_photo(**changes: str) -> str:
    values = {**PHOTO_VALUES, **changes}
    names = [name.strip() for name in PHOTO_COLUMNS.split(",")]
    # Only constants and the test's own SQL literals go in, never a value from outside.
    return (
        f"INSERT INTO sidekick.journal_attachments ({PHOTO_COLUMNS}) "  # noqa: S608
        f"VALUES ({', '.join(values[name] for name in names)})"
    )


def _installation_before_the_photos(tmp_path: Path) -> None:
    _reset_schema()
    _apply(chain_through(tmp_path, AUTOMATIONS))
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
def test_the_table_is_added_and_every_existing_row_is_kept(tmp_path: Path) -> None:
    _installation_before_the_photos(tmp_path)
    before = _tables_now()
    assert "journal_attachments" not in before

    through = chain_through(tmp_path, JOURNAL_ATTACHMENTS)
    _apply(through)

    assert _tables_now() == before | {"journal_attachments"}
    assert _applied_ids() == ids_through(JOURNAL_ATTACHMENTS)
    assert _scalar("SELECT count(*) FROM sidekick.journal_entries") == 1
    assert _scalar("SELECT count(*) FROM sidekick.journal_attachments") == 0
    backend = get_backend(_migration_url())
    assert not list(backend.to_apply(read_migrations(str(through))))


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_end_state_equals_a_fresh_install(tmp_path: Path) -> None:
    _reset_schema()
    _apply(MIGRATIONS_PATH)
    fresh = _snapshot()

    _installation_before_the_photos(tmp_path)
    _run("DELETE FROM sidekick.users")
    _apply(MIGRATIONS_PATH)

    assert _snapshot() == fresh


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_rollback_drops_only_the_photo_metadata_and_it_applies_again(tmp_path: Path) -> None:
    _installation_before_the_photos(tmp_path)
    _apply(chain_through(tmp_path, JOURNAL_ATTACHMENTS))
    _run(_insert_photo(), IDS)
    before = _tables_now()
    backend = get_backend(_migration_url())
    migration = next(
        item for item in read_migrations(str(MIGRATIONS_PATH)) if item.id == JOURNAL_ATTACHMENTS
    )

    with backend.lock():
        backend.rollback_one(migration)

    assert _tables_now() == before - {"journal_attachments"}
    assert JOURNAL_ATTACHMENTS not in _applied_ids()
    assert _scalar("SELECT count(*) FROM sidekick.journal_entries") == 1
    _apply(MIGRATIONS_PATH)
    assert "journal_attachments" in _tables_now()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_photo_belongs_to_exactly_one_of_an_entry_and_a_day(tmp_path: Path) -> None:
    _installation_before_the_photos(tmp_path)
    _apply(MIGRATIONS_PATH)

    _run(_insert_photo(), IDS)
    _run(
        _insert_photo(
            id="'00000000-0000-4000-8000-0000000000b2'",
            entry_id="NULL",
            journal_date="current_date",
        ),
        IDS,
    )
    for neither_or_both in (
        {"entry_id": "NULL", "id": "'00000000-0000-4000-8000-0000000000b3'"},
        {"journal_date": "current_date", "id": "'00000000-0000-4000-8000-0000000000b4'"},
    ):
        with pytest.raises(IntegrityError, match="ck_journal_attachments_target"):
            _run(_insert_photo(**neither_or_both), IDS)


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ({"media_type": "'image/png'"}, "ck_journal_attachments_media_type"),
        ({"media_type": "'image/gif'"}, "ck_journal_attachments_media_type"),
        ({"byte_size": "4194305"}, "ck_journal_attachments_byte_size"),
        ({"byte_size": "0"}, "ck_journal_attachments_byte_size"),
        ({"width": "4097"}, "ck_journal_attachments_dimensions"),
        ({"height": "0"}, "ck_journal_attachments_dimensions"),
        ({"content_digest": "repeat('A', 64)"}, "ck_journal_attachments_content_digest"),
        ({"thumb_digest": "repeat('b', 63)"}, "ck_journal_attachments_thumb_digest"),
        ({"thumb_size": "131073"}, "ck_journal_attachments_thumb_size"),
        ({"alt_text": "'  '", "alt_text_by": "'you'"}, "ck_journal_attachments_alt_text"),
        ({"alt_text": "'A cat'"}, "ck_journal_attachments_alt_text_by"),
        ({"alt_text_by": "'you'"}, "ck_journal_attachments_alt_text_by"),
        ({"alt_text": "'A cat'", "alt_text_by": "'model'"}, "ck_journal_attachments_alt_text_by"),
        ({"position": "-1"}, "ck_journal_attachments_position"),
        ({"version": "0"}, "ck_journal_attachments_version"),
    ],
)
def test_the_database_refuses_a_photo_outside_its_limits(
    tmp_path: Path, change: dict[str, str], constraint: str
) -> None:
    _installation_before_the_photos(tmp_path)
    _apply(MIGRATIONS_PATH)

    with pytest.raises(IntegrityError, match=constraint):
        _run(_insert_photo(**change), IDS)
    # The same row, valid, goes in; the bounds themselves are allowed.
    _run(
        _insert_photo(
            byte_size="4194304",
            width="4096",
            height="4096",
            thumb_size="131072",
            alt_text="'A cat'",
            alt_text_by="'claude'",
        ),
        IDS,
    )


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_photo_cannot_name_another_owners_entry_and_follows_its_entry_and_owner(
    tmp_path: Path,
) -> None:
    _installation_before_the_photos(tmp_path)
    _apply(MIGRATIONS_PATH)

    with pytest.raises(IntegrityError, match="fk_journal_attachments_entry_owner"):
        _run(_insert_photo(owner_id=":other"), IDS)
    _run(_insert_photo(), IDS)

    _run("DELETE FROM sidekick.users WHERE id = :owner", IDS)
    assert _scalar("SELECT count(*) FROM sidekick.journal_attachments") == 0


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_application_role_may_erase_a_photo_but_not_change_the_table(
    tmp_path: Path,
) -> None:
    """DELETE is granted on this table, unlike `journal_entries`; DDL and TRUNCATE are not."""

    _installation_before_the_photos(tmp_path)
    _apply(MIGRATIONS_PATH)
    _run(_insert_photo(), IDS)
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            privileges = {
                table: connection.scalar(
                    text(
                        "SELECT string_agg(p, ',' ORDER BY p) FROM unnest(ARRAY['SELECT', "
                        "'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) "
                        "AS p WHERE has_table_privilege('sidekick_app', :table, p)"
                    ),
                    {"table": f"sidekick.{table}"},
                )
                for table in ("journal_attachments", "journal_entries")
            }
    finally:
        engine.dispose()
    assert privileges["journal_attachments"] == "DELETE,INSERT,SELECT,UPDATE"
    assert privileges["journal_entries"] == "INSERT,SELECT,UPDATE"

    app = create_engine(require_test_database_url())
    try:
        with app.begin() as connection:
            assert connection.scalar(text("SELECT current_user")) == "sidekick_app"
            erased = connection.execute(
                text("DELETE FROM sidekick.journal_attachments WHERE id = :photo"), IDS
            )
            assert erased.rowcount == 1
        for statement in (
            "ALTER TABLE sidekick.journal_attachments ADD COLUMN gps text",
            "DROP TABLE sidekick.journal_attachments",
            "TRUNCATE sidekick.journal_attachments",
            "CREATE INDEX ix_not_allowed ON sidekick.journal_attachments (width)",
        ):
            with (
                pytest.raises(ProgrammingError, match=r"must be owner|permission denied"),
                app.begin() as connection,
            ):
                connection.execute(text(statement))
    finally:
        app.dispose()

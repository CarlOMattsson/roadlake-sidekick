"""Migration 124 gives a photo the fields the client sends beside the image, and nothing else.

Each test builds the database as an installation that ran up to migration 117 has it, with a photo
already stored, then applies the chain through 124. The columns are all nullable, so a stored photo
keeps every value it had and reads as one with no place, camera or orientation; the database
bounds the new values; and a rollback drops only the new columns.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from yoyo import get_backend, read_migrations

from tests.support.migration_baseline import (
    ATTACHMENT_DETAILS,
    JOURNAL_ATTACHMENTS,
    MIGRATIONS_PATH,
    _admin_url,
    _applied_ids,
    _apply,
    _migration_url,
    _reset_schema,
    _run,
    _snapshot,
    chain_through,
    ids_through,
    rebuilt_schema,  # noqa: F401  (a fixture, used through `usefixtures`)
)
from tests.support.migration_photos import IDS, ROWS, _insert_photo, _scalar

NEW_COLUMNS = {"location_lat", "location_lon", "location_name", "camera", "orientation"}


def _columns() -> set[str]:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return set(
                connection.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'sidekick' AND table_name = 'journal_attachments'"
                    )
                )
            )
    finally:
        engine.dispose()


def _installation_with_a_photo(tmp_path: Path) -> None:
    _reset_schema()
    _apply(chain_through(tmp_path, JOURNAL_ATTACHMENTS))
    for statement in ROWS:
        _run(statement, IDS)
    _run(_insert_photo(), IDS)


def _photo_with(**fields: str) -> str:
    """The photo insert with the new columns named, in the order given."""

    base = _insert_photo(id="'00000000-0000-4000-8000-0000000000c1'")
    names = ", ".join(fields)
    values = ", ".join(fields.values())
    start = base.index(") VALUES (")
    return f"{base[:start]}, {names}{base[start:-1]}, {values})"


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_columns_are_added_empty_and_a_stored_photo_is_kept(tmp_path: Path) -> None:
    _installation_with_a_photo(tmp_path)
    assert not NEW_COLUMNS & _columns()

    through = chain_through(tmp_path, ATTACHMENT_DETAILS)
    _apply(through)

    assert _columns() >= NEW_COLUMNS
    assert _applied_ids() == ids_through(ATTACHMENT_DETAILS)
    assert _scalar("SELECT count(*) FROM sidekick.journal_attachments") == 1
    assert (
        _scalar(
            "SELECT count(*) FROM sidekick.journal_attachments WHERE location_lat IS NULL "
            "AND location_lon IS NULL AND location_name IS NULL AND camera IS NULL "
            "AND orientation IS NULL AND media_type = 'image/jpeg' AND version = 1"
        )
        == 1
    )
    backend = get_backend(_migration_url())
    assert not list(backend.to_apply(read_migrations(str(through))))


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_end_state_equals_a_fresh_install(tmp_path: Path) -> None:
    _reset_schema()
    _apply(MIGRATIONS_PATH)
    fresh = _snapshot()

    _installation_with_a_photo(tmp_path)
    _run("DELETE FROM sidekick.users")
    _apply(MIGRATIONS_PATH)

    assert _snapshot() == fresh


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_rollback_drops_only_the_new_columns_and_it_applies_again(tmp_path: Path) -> None:
    _installation_with_a_photo(tmp_path)
    _apply(chain_through(tmp_path, ATTACHMENT_DETAILS))
    _run(_photo_with(location_lat="59.3", location_lon="18.0", camera="'Pixel'"), IDS)
    backend = get_backend(_migration_url())
    migration = next(
        item for item in read_migrations(str(MIGRATIONS_PATH)) if item.id == ATTACHMENT_DETAILS
    )

    with backend.lock():
        backend.rollback_one(migration)

    assert not NEW_COLUMNS & _columns()
    assert ATTACHMENT_DETAILS not in _applied_ids()
    assert _scalar("SELECT count(*) FROM sidekick.journal_attachments") == 2
    _apply(MIGRATIONS_PATH)
    assert _columns() >= NEW_COLUMNS


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"location_lat": "59.3"}, "ck_journal_attachments_location"),
        ({"location_lon": "18.0"}, "ck_journal_attachments_location"),
        ({"location_lat": "90.1", "location_lon": "0"}, "ck_journal_attachments_location"),
        ({"location_lat": "-90.1", "location_lon": "0"}, "ck_journal_attachments_location"),
        ({"location_lat": "0", "location_lon": "180.1"}, "ck_journal_attachments_location"),
        ({"location_lat": "0", "location_lon": "-180.1"}, "ck_journal_attachments_location"),
        ({"location_name": "'Home'"}, "ck_journal_attachments_location_name"),
        (
            {"location_lat": "1", "location_lon": "2", "location_name": "'  '"},
            "ck_journal_attachments_location_name",
        ),
        ({"camera": "'   '"}, "ck_journal_attachments_camera"),
        ({"orientation": "0"}, "ck_journal_attachments_orientation"),
        ({"orientation": "9"}, "ck_journal_attachments_orientation"),
    ],
)
def test_the_database_refuses_details_outside_their_bounds(
    tmp_path: Path, fields: dict[str, str], constraint: str
) -> None:
    _installation_with_a_photo(tmp_path)
    _apply(MIGRATIONS_PATH)

    with pytest.raises(IntegrityError, match=constraint):
        _run(_photo_with(**fields), IDS)
    # The edges themselves go in, in one valid row.
    _run(
        _photo_with(
            location_lat="-90",
            location_lon="180",
            location_name="'Pole'",
            camera="'Pixel 9'",
            orientation="8",
        ),
        IDS,
    )

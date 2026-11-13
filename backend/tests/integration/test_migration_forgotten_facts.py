"""Migration 108 adds the forgotten-statement tables and the owner's salt, and nothing else.

Each test builds the database as an installation that ran up to migration 107 has it, then applies
`migrations/`. The tables are new and the salt column is nullable, so an existing installation keeps
every row it has, and a rollback drops only what 108 added.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError
from yoyo import get_backend, read_migrations

from tests.db import require_test_database_url
from tests.support.migration_baseline import (
    BASELINE,
    DROP_AUTOMATION,
    FORGOTTEN_FACTS,
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

DENIED = r"permission denied|must be owner"
NEW_TABLES = ("memory_forgotten_facts", "memory_forgotten_units")
OWNER = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
SOURCE = "00000000-0000-4000-8000-0000000000a1"
OTHER_SOURCE = "00000000-0000-4000-8000-0000000000a2"
FORGOTTEN = "00000000-0000-4000-8000-0000000000f1"
OTHER_FORGOTTEN = "00000000-0000-4000-8000-0000000000f2"
UNIT = "00000000-0000-4000-8000-0000000000b1"
KEY = "a" * 64
IDS: dict[str, object] = {
    "owner": OWNER,
    "other": OTHER,
    "source": SOURCE,
    "other_source": OTHER_SOURCE,
    "forgotten": FORGOTTEN,
    "other_forgotten": OTHER_FORGOTTEN,
    "unit": UNIT,
    "key": KEY,
}
ROWS = (
    "INSERT INTO sidekick.users (id, username, display_name, created_at) "
    "VALUES (:owner, 'kept', 'Kept', now()), (:other, 'other', 'Other', now())",
    "INSERT INTO sidekick.memory_settings (owner_id, created_at, updated_at) "
    "VALUES (:owner, now(), now())",
    "INSERT INTO sidekick.memory_sources "
    "(id, owner_id, source_kind, source_id, doc_key, fingerprint, pipeline_version, status, "
    "source_updated_at) VALUES "
    "(:source, :owner, 'journal_entry', :source, 'doc-1', repeat('b', 64), 1, 'pending', now()), "
    "(:other_source, :other, 'journal_entry', :other_source, 'doc-2', repeat('c', 64), 1, "
    "'pending', now())",
)
INSERT_FACT = (
    "INSERT INTO sidekick.memory_forgotten_facts "
    "(id, owner_id, text_key, created_at, origin_source_id) "
    "VALUES (:forgotten, :owner, :key, now(), :source)"
)
INSERT_OTHER_FACT = (
    "INSERT INTO sidekick.memory_forgotten_facts (id, owner_id, text_key, created_at) "
    "VALUES (:other_forgotten, :other, :key, now())"
)
INSERT_UNIT = (
    "INSERT INTO sidekick.memory_forgotten_units "
    "(id, owner_id, forgotten_id, memory_source_id, provider_fact_id, state) "
    "VALUES (:unit, :owner, :forgotten, :source, 'fact-1', 'pending')"
)


def _chain_before_the_forgotten_facts(tmp_path: Path) -> Path:
    """A migrations directory with every migration up to 107, which is the chain before 108."""

    directory = tmp_path / "before-the-forgotten-facts"
    directory.mkdir()
    for name in (BASELINE, DROP_AUTOMATION, TAG_LINKS):
        (directory / f"{name}.py").write_text(
            (MIGRATIONS_PATH / f"{name}.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
    return directory


def _installation_before_the_forgotten_facts(tmp_path: Path) -> None:
    _reset_schema()
    _apply(_chain_before_the_forgotten_facts(tmp_path))
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


def _migrated(tmp_path: Path) -> None:
    _installation_before_the_forgotten_facts(tmp_path)
    _apply(MIGRATIONS_PATH)


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_tables_are_added_and_every_existing_row_is_kept(tmp_path: Path) -> None:
    _installation_before_the_forgotten_facts(tmp_path)
    before = _tables_now()
    assert set(NEW_TABLES).isdisjoint(before)

    _apply(MIGRATIONS_PATH)

    assert _tables_now() == before | set(NEW_TABLES)
    assert _applied_ids() == {BASELINE, DROP_AUTOMATION, TAG_LINKS, FORGOTTEN_FACTS}
    assert _scalar("SELECT count(*) FROM sidekick.users") == 2
    assert _scalar("SELECT count(*) FROM sidekick.memory_sources") == 2
    assert _scalar("SELECT count(*) FROM sidekick.memory_settings") == 1
    # The salt column starts empty; the salt is made when the owner first forgets a statement.
    assert _scalar("SELECT forget_salt FROM sidekick.memory_settings") is None
    backend = get_backend(_migration_url())
    assert not list(backend.to_apply(read_migrations(str(MIGRATIONS_PATH))))


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_end_state_equals_a_fresh_install(tmp_path: Path) -> None:
    _reset_schema()
    _apply(MIGRATIONS_PATH)
    fresh = _snapshot()

    _installation_before_the_forgotten_facts(tmp_path)
    _run("DELETE FROM sidekick.users")
    _apply(MIGRATIONS_PATH)

    assert _snapshot() == fresh


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_no_column_can_hold_the_text_of_a_forgotten_statement(tmp_path: Path) -> None:
    _migrated(tmp_path)

    columns = set(
        _rows(
            "SELECT column_name || ' ' || data_type FROM information_schema.columns "
            "WHERE table_schema = 'sidekick' AND table_name IN "
            "('memory_forgotten_facts', 'memory_forgotten_units')"
        )
    )

    assert columns == {
        "id uuid",
        "owner_id uuid",
        "text_key character",
        "created_at timestamp with time zone",
        "released_at timestamp with time zone",
        "origin_source_id uuid",
        "forgotten_id uuid",
        "memory_source_id uuid",
        "provider_fact_id character varying",
        "state character varying",
        "attempts integer",
        "next_attempt_at timestamp with time zone",
        "failure_category character varying",
    }
    # The one free-text-shaped column is a provider id, which the database limits in length.
    assert (
        _scalar(
            "SELECT character_maximum_length FROM information_schema.columns WHERE table_schema = "
            "'sidekick' AND table_name = 'memory_forgotten_units' "
            "AND column_name = 'provider_fact_id'"
        )
        == 200
    )


def _rows(sql: str) -> list[str]:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return [str(value) for value in connection.scalars(text(sql))]
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
@pytest.mark.parametrize(
    "statement",
    [
        INSERT_FACT.replace(":key", "'ABC'"),
        INSERT_FACT.replace(":key", "'" + "a" * 63 + "'"),
        INSERT_FACT.replace(":key", "'" + "A" * 64 + "'"),
    ],
    ids=["not-hex", "too-short", "upper-case"],
)
def test_a_forgotten_statement_needs_a_lower_case_sha256_key(
    tmp_path: Path, statement: str
) -> None:
    _migrated(tmp_path)

    with pytest.raises(IntegrityError):
        _run(statement, IDS)


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_key_is_forgotten_once_per_owner_and_a_release_cannot_precede_the_creation(
    tmp_path: Path,
) -> None:
    _migrated(tmp_path)

    _run(INSERT_FACT, IDS)
    _run(INSERT_OTHER_FACT, IDS)
    assert _scalar("SELECT count(*) FROM sidekick.memory_forgotten_facts") == 2
    # One owner forgets a statement once.
    with pytest.raises(IntegrityError):
        _run(INSERT_FACT.replace(":forgotten", ":other_forgotten"), IDS)
    _run(
        "UPDATE sidekick.memory_forgotten_facts SET released_at = created_at WHERE id = :forgotten",
        IDS,
    )
    with pytest.raises(IntegrityError):
        _run(
            "UPDATE sidekick.memory_forgotten_facts "
            "SET released_at = created_at - interval '1 second' WHERE id = :forgotten",
            IDS,
        )


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
@pytest.mark.parametrize(
    "refused",
    [
        "UPDATE sidekick.memory_forgotten_units SET state = 'unknown'",
        "UPDATE sidekick.memory_forgotten_units SET state = 'parked', failure_category = NULL",
        "UPDATE sidekick.memory_forgotten_units SET attempts = -1",
        "UPDATE sidekick.memory_forgotten_units SET provider_fact_id = '  '",
    ],
    ids=["state", "parked-needs-category", "attempts", "blank-fact-id"],
)
def test_a_unit_keeps_to_its_vocabulary(tmp_path: Path, refused: str) -> None:
    _migrated(tmp_path)
    _run(INSERT_FACT, IDS)
    _run(INSERT_UNIT, IDS)

    with pytest.raises(IntegrityError):
        _run(refused, IDS)
    for state in ("invalidated", "reverting"):
        _run(
            "UPDATE sidekick.memory_forgotten_units SET state = :state WHERE id = :unit",
            {**IDS, "state": state},
        )
    _run(
        "UPDATE sidekick.memory_forgotten_units "
        "SET state = 'parked', failure_category = 'rejected' WHERE id = :unit",
        IDS,
    )


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_provider_fact_has_one_unit(tmp_path: Path) -> None:
    _migrated(tmp_path)
    _run(INSERT_FACT, IDS)
    _run(INSERT_UNIT, IDS)

    with pytest.raises(IntegrityError):
        _run(INSERT_UNIT.replace(":unit", "'00000000-0000-4000-8000-0000000000b2'"), IDS)


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_unit_only_joins_one_owners_statement_and_source_row(tmp_path: Path) -> None:
    _migrated(tmp_path)
    _run(INSERT_FACT, IDS)
    _run(INSERT_OTHER_FACT, IDS)

    # Another owner's source row, or another owner's statement, cannot carry this owner's unit.
    with pytest.raises(IntegrityError):
        _run(INSERT_UNIT.replace(":source", ":other_source"), IDS)
    with pytest.raises(IntegrityError):
        _run(INSERT_UNIT.replace(":forgotten", ":other_forgotten"), IDS)
    _run(INSERT_UNIT, IDS)
    assert _scalar("SELECT count(*) FROM sidekick.memory_forgotten_units") == 1


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_statements_origin_is_one_of_its_owners_source_rows(tmp_path: Path) -> None:
    _migrated(tmp_path)

    with pytest.raises(IntegrityError):
        _run(INSERT_FACT.replace(":source", ":other_source"), IDS)
    _run(INSERT_FACT, IDS)
    assert _scalar("SELECT origin_source_id FROM sidekick.memory_forgotten_facts") is not None
    with pytest.raises(IntegrityError):
        _run("UPDATE sidekick.memory_forgotten_facts SET origin_source_id = :other_source", IDS)
    # Deleting the origin clears the origin only; the statement and its owner stay.
    _run("DELETE FROM sidekick.memory_sources WHERE id = :source", IDS)
    assert _scalar("SELECT origin_source_id FROM sidekick.memory_forgotten_facts") is None
    assert _scalar("SELECT owner_id FROM sidekick.memory_forgotten_facts") is not None


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_units_follow_their_statement_and_their_source_row(tmp_path: Path) -> None:
    _migrated(tmp_path)
    _run(INSERT_FACT, IDS)
    _run(INSERT_UNIT, IDS)

    # Deleting the source row ends its units but keeps the statement, whose origin is forgotten.
    _run("DELETE FROM sidekick.memory_sources WHERE id = :source", IDS)
    assert _scalar("SELECT count(*) FROM sidekick.memory_forgotten_units") == 0
    assert _scalar("SELECT count(*) FROM sidekick.memory_forgotten_facts") == 1
    assert _scalar("SELECT origin_source_id FROM sidekick.memory_forgotten_facts") is None

    # Deleting the statement ends its units too.
    _run(
        "INSERT INTO sidekick.memory_sources "
        "(id, owner_id, source_kind, source_id, doc_key, fingerprint, pipeline_version, status, "
        "source_updated_at) VALUES (:source, :owner, 'journal_entry', :source, 'doc-1', "
        "repeat('b', 64), 1, 'pending', now())",
        IDS,
    )
    _run(INSERT_UNIT, IDS)
    _run("DELETE FROM sidekick.memory_forgotten_facts WHERE id = :forgotten", IDS)
    assert _scalar("SELECT count(*) FROM sidekick.memory_forgotten_units") == 0
    assert _scalar("SELECT count(*) FROM sidekick.memory_sources") == 2


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_removing_an_owner_removes_the_statements_and_the_salt(tmp_path: Path) -> None:
    _migrated(tmp_path)
    _run("UPDATE sidekick.memory_settings SET forget_salt = repeat('0', 32)", IDS)
    _run(INSERT_FACT, IDS)
    _run(INSERT_UNIT, IDS)
    _run(INSERT_OTHER_FACT, IDS)

    _run("DELETE FROM sidekick.users WHERE id = :owner", IDS)

    assert _scalar("SELECT count(*) FROM sidekick.memory_forgotten_units") == 0
    assert _scalar("SELECT count(*) FROM sidekick.memory_forgotten_facts") == 1
    assert _scalar("SELECT count(*) FROM sidekick.memory_settings") == 0


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
@pytest.mark.parametrize("salt", ["", "z" * 32, "A" * 32, "0" * 31, "0" * 33])
def test_the_salt_is_thirty_two_lower_case_hex_characters(tmp_path: Path, salt: str) -> None:
    _migrated(tmp_path)

    with pytest.raises((IntegrityError, DataError)):
        _run("UPDATE sidekick.memory_settings SET forget_salt = :salt", {**IDS, "salt": salt})
    _run("UPDATE sidekick.memory_settings SET forget_salt = :salt", {**IDS, "salt": "ab" * 16})
    assert _scalar("SELECT forget_salt FROM sidekick.memory_settings") == "ab" * 16


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_runtime_role_can_use_the_tables_but_not_change_them(tmp_path: Path) -> None:
    _migrated(tmp_path)
    engine = create_engine(require_test_database_url())
    try:
        with engine.begin() as connection:
            params = {**IDS, "salt": "cd" * 16}
            connection.execute(text(INSERT_FACT), params)
            connection.execute(text(INSERT_UNIT), params)
            connection.execute(
                text("UPDATE sidekick.memory_settings SET forget_salt = :salt"), params
            )
            connection.execute(
                text("UPDATE sidekick.memory_forgotten_units SET state = 'invalidated'")
            )
            assert connection.scalar(text("SELECT count(*) FROM sidekick.memory_forgotten_units"))
            connection.execute(text("DELETE FROM sidekick.memory_forgotten_units"))
            connection.execute(text("DELETE FROM sidekick.memory_forgotten_facts"))
        for table in NEW_TABLES:
            with (
                pytest.raises(ProgrammingError, match=DENIED),
                engine.begin() as c,
            ):
                c.execute(text(f"ALTER TABLE sidekick.{table} ADD COLUMN fact_text text"))
            with (
                pytest.raises(ProgrammingError, match=DENIED),
                engine.begin() as c,
            ):
                c.execute(text(f"DROP TABLE sidekick.{table}"))
            with (
                pytest.raises(ProgrammingError, match=DENIED),
                engine.begin() as c,
            ):
                c.execute(text(f"TRUNCATE sidekick.{table}"))
        with (
            pytest.raises(ProgrammingError, match=DENIED),
            engine.begin() as c,
        ):
            c.execute(text("ALTER TABLE sidekick.memory_settings DROP COLUMN forget_salt"))
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_rollback_drops_only_what_the_migration_added(tmp_path: Path) -> None:
    _migrated(tmp_path)
    _run("UPDATE sidekick.memory_settings SET forget_salt = repeat('0', 32)", IDS)
    _run(INSERT_FACT, IDS)
    backend = get_backend(_migration_url())
    migration = next(
        item for item in read_migrations(str(MIGRATIONS_PATH)) if item.id == FORGOTTEN_FACTS
    )

    with backend.lock():
        backend.rollback_one(migration)

    assert set(NEW_TABLES).isdisjoint(_tables_now())
    assert _applied_ids() == {BASELINE, DROP_AUTOMATION, TAG_LINKS}
    assert _scalar("SELECT count(*) FROM sidekick.memory_sources") == 2
    assert _scalar("SELECT count(*) FROM sidekick.memory_settings") == 1
    assert (
        _scalar(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'sidekick' "
            "AND table_name = 'memory_settings' AND column_name = 'forget_salt'"
        )
        == 0
    )
    # The database is as it was before 108, and the migration applies again.
    assert (
        _scalar("SELECT count(*) FROM pg_constraint WHERE conname = 'uq_memory_sources_id_owner'")
        == 0
    )
    _apply(MIGRATIONS_PATH)
    assert set(NEW_TABLES) <= _tables_now()

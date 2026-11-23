"""Migration 121 adds the three repetition tables and nothing else, and its constraints hold.

The upgrade keeps every existing row, the rollback returns the schema to exactly what migration 124
built, and the rows the application writes are bound by the closed value sets, the limits and the
owner-scoped foreign keys of the tables. The row tests run as the runtime role in a transaction
that is rolled back.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError
from yoyo import get_backend, read_migrations

from tests.db import database_factory, require_test_database_url
from tests.support.automation_rows import insert_owner
from tests.support.migration_baseline import (
    ATTACHMENT_DETAILS,
    REVIEW,
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
from tests.support.review_rows import insert_card, insert_log, insert_settings

NEW_TABLES = {"review_settings", "review_cards", "review_log"}
OWNER = "00000000-0000-4000-8000-000000000001"


def _chain_before_review(tmp_path: Path) -> Path:
    """The migrations an installation has when `121_review` is the only one still to apply: the
    chain through `124_journal_attachment_details` (which it follows) without it."""

    directory = tmp_path / "chain-before-review"
    directory.mkdir(exist_ok=True)
    for source in chain_through(tmp_path, ATTACHMENT_DETAILS).glob("*.py"):
        if source.stem != REVIEW:
            (directory / source.name).write_text(source.read_text(encoding="utf-8"))
    return directory


def _tables_now() -> set[str]:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return _tables(connection)
    finally:
        engine.dispose()


def _users() -> int:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM sidekick.users")).scalar_one()
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_tables_are_added_empty_and_every_existing_row_is_kept(tmp_path: Path) -> None:
    _reset_schema()
    _apply(_chain_before_review(tmp_path))
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, created_at) "
        "VALUES (:id, 'kept', 'Kept', now())",
        {"id": OWNER},
    )
    before = _tables_now()
    assert NEW_TABLES.isdisjoint(before)

    _apply(chain_through(tmp_path, ATTACHMENT_DETAILS))

    assert _tables_now() == before | NEW_TABLES
    assert _applied_ids() == ids_through(ATTACHMENT_DETAILS)
    assert _users() == 1
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            counts = [
                connection.execute(text(f"SELECT count(*) FROM sidekick.{table}")).scalar_one()  # noqa: S608
                for table in sorted(NEW_TABLES)
            ]
    finally:
        engine.dispose()
    assert counts == [0] * len(NEW_TABLES)


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_rollback_returns_the_schema_to_what_migration_124_built(tmp_path: Path) -> None:
    _reset_schema()
    _apply(_chain_before_review(tmp_path))
    expected = _snapshot()

    _reset_schema()
    through = chain_through(tmp_path, ATTACHMENT_DETAILS)
    _apply(through)
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, created_at) "
        "VALUES (:id, 'kept', 'Kept', now())",
        {"id": OWNER},
    )
    engine = create_engine(_admin_url())
    try:
        with engine.begin() as connection:
            insert_settings(connection, OWNER)
            insert_log(connection, OWNER, insert_card(connection, OWNER))
    finally:
        engine.dispose()
    backend = get_backend(_migration_url())
    migration = next(item for item in read_migrations(str(through)) if item.id == REVIEW)

    with backend.lock():
        backend.rollback_one(migration)

    assert _snapshot() == expected
    assert _applied_ids() == ids_through(ATTACHMENT_DETAILS) - {REVIEW}
    assert _users() == 1
    # The migration applies again.
    _apply(through)
    assert _tables_now() >= NEW_TABLES


@contextmanager
def _owner_with_card(**card: Any) -> Iterator[tuple[Connection, str, str]]:
    """An owner and a card written by the runtime role; nothing is committed."""

    database_factory()
    engine = create_engine(require_test_database_url())
    owner = str(uuid4())
    try:
        with engine.connect() as connection:
            insert_owner(connection, owner)
            card_id = insert_card(connection, owner, **card)
            try:
                yield connection, owner, card_id
            finally:
                connection.rollback()
    finally:
        engine.dispose()


def _expect_card_refused(**card: Any) -> None:
    with pytest.raises(IntegrityError), _owner_with_card(**card):
        pass


@pytest.mark.integration
def test_a_card_starts_new_with_no_schedule_and_no_answers() -> None:
    with _owner_with_card() as (connection, _, card):
        row = (
            connection.execute(
                text(
                    "SELECT fsrs_state, reps, lapses, due_at, stability, difficulty, step, "
                    "introduced_on, suspended_at, retired_at FROM sidekick.review_cards "
                    "WHERE id = :id"
                ),
                {"id": card},
            )
            .tuples()
            .one()
        )

    assert row == ("new", 0, 0, None, None, None, None, None, None, None)


@pytest.mark.integration
@pytest.mark.parametrize(
    "card",
    [
        # The key must match the kind, and exactly one is set.
        {"source_kind": "library_fact", "library_fact_id": None},
        {"source_kind": "contact_face", "library_fact_id": str(uuid4())},
        {"source_kind": "contact_photo"},
        {"source_kind": "library_fact", "contact_id": str(uuid4())},
        # A card that has been answered has a due time; a new one has no schedule.
        {"fsrs_state": "review"},
        {"fsrs_state": "new", "due_at": "2026-11-23T09:00:00+00:00"},
        {"fsrs_state": "learned", "due_at": "2026-11-23T09:00:00+00:00"},
        {"step": -1},
        {"reps": -1},
        {"lapses": -1},
        {"version": 0},
    ],
)
def test_a_card_that_breaks_a_rule_of_the_table_is_refused(card: dict[str, Any]) -> None:
    _expect_card_refused(**card)


@pytest.mark.integration
def test_a_contact_of_another_owner_cannot_have_a_card() -> None:
    other = str(uuid4())
    with (
        pytest.raises(IntegrityError),
        _owner_with_card(source_kind="contact_face", library_fact_id=None, contact_id=other),
    ):
        pass


@pytest.mark.integration
def test_a_source_has_at_most_one_card_per_owner() -> None:
    fact = str(uuid4())
    with _owner_with_card(library_fact_id=fact) as (connection, owner, _):
        with pytest.raises(IntegrityError):
            insert_card(connection, owner, library_fact_id=fact)
        connection.rollback()


@pytest.mark.integration
@pytest.mark.parametrize(
    "log",
    [
        {"rating": 0},
        {"rating": 5},
        {"channel": "email"},
        {"duration_ms": -1},
        {"duration_ms": 600_001},
        {"client_review_id": ""},
    ],
)
def test_an_answer_that_breaks_a_rule_of_the_table_is_refused(log: dict[str, Any]) -> None:
    with _owner_with_card() as (connection, owner, card), pytest.raises(IntegrityError):
        insert_log(connection, owner, card, **log)


@pytest.mark.integration
def test_the_same_answer_key_twice_on_one_card_is_refused_but_not_on_another() -> None:
    with _owner_with_card() as (connection, owner, card):
        insert_log(connection, owner, card, client_review_id="phone-1")
        other_card = insert_card(connection, owner)
        insert_log(connection, owner, other_card, client_review_id="phone-1")

        with pytest.raises(IntegrityError):
            insert_log(connection, owner, card, client_review_id="phone-1")
        connection.rollback()


@pytest.mark.integration
def test_an_answer_cannot_name_a_card_of_another_owner() -> None:
    with _owner_with_card() as (connection, _, card):
        stranger = str(uuid4())
        insert_owner(connection, stranger)

        with pytest.raises(IntegrityError):
            insert_log(connection, stranger, card)
        connection.rollback()


@pytest.mark.integration
@pytest.mark.parametrize(
    "settings",
    [
        {"new_per_day": -1},
        {"new_per_day": 51},
        {"max_reviews_per_day": 9},
        {"max_reviews_per_day": 1001},
        {"desired_retention": 0.79},
        {"desired_retention": 0.98},
        {"version": 0},
    ],
)
def test_settings_outside_the_ranges_are_refused(settings: dict[str, Any]) -> None:
    with _owner_with_card() as (connection, owner, _), pytest.raises(IntegrityError):
        insert_settings(connection, owner, **settings)


@pytest.mark.integration
def test_the_settings_default_to_off_with_ten_new_cards_a_day_and_ninety_percent() -> None:
    with _owner_with_card() as (connection, owner, _):
        insert_settings(connection, owner)
        row = (
            connection.execute(
                text(
                    "SELECT enabled, include_contacts, include_library, new_per_day, "
                    "max_reviews_per_day, push_enabled, push_local_time, desired_retention "
                    "FROM sidekick.review_settings WHERE owner_id = :owner"
                ),
                {"owner": owner},
            )
            .tuples()
            .one()
        )

    assert str(row[6]) == "18:00:00"
    assert (*row[:6], float(row[7])) == (False, True, True, 10, 200, True, 0.90)

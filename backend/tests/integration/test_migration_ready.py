"""Migration 123 adds the two ready conversation tables and nothing else, and its constraints hold.

The upgrade keeps every existing row, the rollback returns the schema to exactly what migration 121
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
    READY,
    _admin_url,
    _applied_ids,
    _apply,
    _migration_url,
    _reset_schema,
    _run,
    _snapshot,
    _tables,
    chain_through_without,
    ids_through,
    rebuilt_schema,  # noqa: F401  (a fixture, used through `usefixtures`)
)
from tests.support.ready_rows import insert_conversation, insert_day

NEW_TABLES = {"ready_conversations", "ready_conversation_days"}
OWNER = "00000000-0000-4000-8000-000000000001"


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
    _apply(chain_through_without(tmp_path, ATTACHMENT_DETAILS, READY))
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, created_at) "
        "VALUES (:id, 'kept', 'Kept', now())",
        {"id": OWNER},
    )
    before = _tables_now()
    assert NEW_TABLES.isdisjoint(before)

    _apply(chain_through_without(tmp_path, ATTACHMENT_DETAILS))

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
def test_a_rollback_returns_the_schema_to_what_migration_121_built(tmp_path: Path) -> None:
    _reset_schema()
    _apply(chain_through_without(tmp_path, ATTACHMENT_DETAILS, READY))
    expected = _snapshot()

    _reset_schema()
    through = chain_through_without(tmp_path, ATTACHMENT_DETAILS)
    _apply(through)
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, created_at) "
        "VALUES (:id, 'kept', 'Kept', now())",
        {"id": OWNER},
    )
    engine = create_engine(_admin_url())
    try:
        with engine.begin() as connection:
            insert_day(connection, OWNER, insert_conversation(connection, OWNER), "2026-11-23")
    finally:
        engine.dispose()
    backend = get_backend(_migration_url())
    migration = next(item for item in read_migrations(str(through)) if item.id == READY)

    with backend.lock():
        backend.rollback_one(migration)

    assert _snapshot() == expected
    assert _applied_ids() == ids_through(ATTACHMENT_DETAILS) - {READY}
    assert _users() == 1
    # The migration applies again.
    _apply(through)
    assert _tables_now() >= NEW_TABLES


@contextmanager
def _owner_with_conversation(**conversation: Any) -> Iterator[tuple[Connection, str, str]]:
    """An owner and a conversation written by the runtime role; nothing is committed."""

    database_factory()
    engine = create_engine(require_test_database_url())
    owner = str(uuid4())
    try:
        with engine.connect() as connection:
            insert_owner(connection, owner)
            conversation_id = insert_conversation(connection, owner, **conversation)
            try:
                yield connection, owner, conversation_id
            finally:
                connection.rollback()
    finally:
        engine.dispose()


def _expect_refused(**conversation: Any) -> None:
    with pytest.raises(IntegrityError), _owner_with_conversation(**conversation):
        pass


@pytest.mark.integration
def test_a_conversation_starts_active_with_no_ingredients_and_no_instruction() -> None:
    with _owner_with_conversation() as (connection, _, conversation):
        row = (
            connection.execute(
                text(
                    "SELECT state, ingredients, instruction FROM sidekick.ready_conversations "
                    "WHERE id = :id"
                ),
                {"id": conversation},
            )
            .tuples()
            .one()
        )

    assert row == ("active", [], None)


@pytest.mark.integration
@pytest.mark.parametrize(
    "conversation",
    [
        {"title": ""},
        {"kind": "monthly_review"},
        {"state": "deleted"},
        {"instruction": "", "instruction_written_by": "you"},
        {"instruction": "i" * 2001, "instruction_written_by": "you"},
        # The instruction carries who wrote it, and nothing else carries a writer.
        {"instruction": "Review my day."},
        {"instruction": "Review my day.", "instruction_written_by": "robot"},
        {"instruction_written_by": "you"},
        {"instruction_edited_by_model": True},
        {"ingredients": ["tasks_done_today", "not_an_ingredient"]},
        {"ingredients": ["overdue"] * 11},
        {"cadence": []},
        {"cadence": "daily"},
        {"version": 0},
    ],
)
def test_a_conversation_that_breaks_a_rule_of_the_table_is_refused(
    conversation: dict[str, Any],
) -> None:
    _expect_refused(**conversation)


@pytest.mark.integration
def test_a_conversation_may_hold_every_ingredient_of_the_closed_set() -> None:
    every = [
        "tasks_done_today",
        "tasks_due_today",
        "tasks_due_tomorrow",
        "overdue",
        "waiting",
        "suggestions",
        "journal_today",
        "review",
        "automation_report",
        "shopping_open",
    ]
    with _owner_with_conversation(
        ingredients=every,
        instruction="i" * 2000,
        instruction_written_by="claude",
        instruction_edited_by_model=True,
        title="t" * 80,
    ):
        pass


@pytest.mark.integration
def test_a_day_names_its_conversation_of_the_same_owner_once() -> None:
    with _owner_with_conversation() as (connection, owner, conversation):
        insert_day(connection, owner, conversation, "2026-11-23")
        insert_day(connection, owner, conversation, "2026-11-24", state="started")

        with pytest.raises(IntegrityError):
            insert_day(connection, owner, conversation, "2026-11-23", state="open")
        connection.rollback()


@pytest.mark.integration
def test_a_day_cannot_name_a_conversation_of_another_owner() -> None:
    with _owner_with_conversation() as (connection, _, conversation):
        stranger = str(uuid4())
        insert_owner(connection, stranger)

        with pytest.raises(IntegrityError):
            insert_day(connection, stranger, conversation, "2026-11-23")
        connection.rollback()


@pytest.mark.integration
@pytest.mark.parametrize("day", [{"state": "done"}, {"version": 0}])
def test_a_day_that_breaks_a_rule_of_the_table_is_refused(day: dict[str, Any]) -> None:
    with _owner_with_conversation() as (connection, owner, conversation):
        with pytest.raises(IntegrityError):
            insert_day(connection, owner, conversation, "2026-11-23", **day)
        connection.rollback()

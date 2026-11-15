"""Migrations 109 and 110 each add a nullable timestamp to `tasks`; existing Tasks read it as NULL.

109 adds `last_reviewed_at` (never reviewed), 110 adds `ambition_since` (no ambition). Each
rollback drops only its column and leaves the Task row and every other column as they were.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from yoyo import get_backend, read_migrations

from tests.support.migration_baseline import (
    MIGRATIONS_PATH,
    TASK_AMBITION,
    TASK_REVIEW,
    _admin_url,
    _applied_ids,
    _apply,
    _migration_url,
    _reset_schema,
    _run,
    _snapshot,
    rebuilt_schema,  # noqa: F401  (a fixture, used through `usefixtures`)
)

OWNER = "00000000-0000-4000-8000-000000000001"
TASK = "00000000-0000-4000-8000-0000000000c1"
COLUMNS = {TASK_REVIEW: "last_reviewed_at", TASK_AMBITION: "ambition_since"}
VALUE_QUERIES = {
    "last_reviewed_at": "SELECT last_reviewed_at FROM sidekick.tasks WHERE id = :id",
    "ambition_since": "SELECT ambition_since FROM sidekick.tasks WHERE id = :id",
}


def _scalar(query: str, params: dict[str, str]) -> object:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            row = connection.execute(text(query), params).one_or_none()
            return tuple(row) if row is not None else None
    finally:
        engine.dispose()


def _column(name: str) -> object:
    return _scalar(
        "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'sidekick' AND table_name = 'tasks' AND column_name = :name",
        {"name": name},
    )


def _value(name: str) -> object:
    return _scalar(VALUE_QUERIES[name], {"id": TASK})


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
@pytest.mark.parametrize("migration_id", sorted(COLUMNS))
def test_the_column_is_nullable_without_a_default_and_the_rollback_drops_only_it(
    migration_id: str,
) -> None:
    column = COLUMNS[migration_id]
    _reset_schema()
    _apply(MIGRATIONS_PATH)
    assert migration_id in _applied_ids()
    assert _column(column) == ("timestamp with time zone", "YES", None)
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, created_at) "
        "VALUES (:owner, 'kept', 'Kept', now())",
        {"owner": OWNER},
    )
    _run(
        "INSERT INTO sidekick.tasks "
        "(id, owner_id, title, status, priority, created_at, updated_at, version) "
        "VALUES (:task, :owner, 'Task', 'todo', 'normal', now(), now(), 1)",
        {"task": TASK, "owner": OWNER},
    )
    assert _value(column) == (None,)
    at_head = _snapshot()

    backend = get_backend(_migration_url())
    migration = next(
        item for item in read_migrations(str(MIGRATIONS_PATH)) if item.id == migration_id
    )
    backend.rollback_one(migration)

    assert migration_id not in _applied_ids()
    assert _column(column) is None
    assert [
        line for line in at_head["columns"] if not line.startswith(f"tasks.{column} ")
    ] == _snapshot()["columns"]

    _apply(MIGRATIONS_PATH)
    assert _column(column) == ("timestamp with time zone", "YES", None)
    assert _value(column) == (None,)

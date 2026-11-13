"""Migration 106 drops the four tables of the retired automation engine, only when they are empty.

Each test builds the database as an installation that applied only the baseline has it (the four
tables exist), then applies `migrations/`. A table that holds a row stops the migration and nothing
is dropped or recorded.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
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

RETIRED = (
    "assistant_task_review_findings",
    "assistant_automation_runs",
    "assistant_automation_policies",
    "assistant_automation_control",
)
OWNER = "00000000-0000-4000-8000-000000000001"
RUN = "00000000-0000-4000-8000-0000000000b1"
TASK = "00000000-0000-4000-8000-0000000000c1"

IDS: dict[str, object] = {"owner": OWNER, "run": RUN, "task": TASK}
# One row per retired table (the findings need a task and, like the others, a user and a run).
SEED_ROWS = {
    "assistant_automation_control": (
        "INSERT INTO sidekick.assistant_automation_control (owner_id, updated_at) "
        "VALUES (:owner, now())"
    ),
    "assistant_automation_policies": (
        "INSERT INTO sidekick.assistant_automation_policies "
        "(owner_id, category, mode, created_at, updated_at) "
        "VALUES (:owner, 'tasks', 'review', now(), now())"
    ),
    "assistant_automation_runs": (
        "INSERT INTO sidekick.assistant_automation_runs "
        "(id, owner_id, kind, trigger, status, scheduled_for, created_at) "
        "VALUES (:run, :owner, 'review', 'manual', 'queued', now(), now())"
    ),
    "assistant_task_review_findings": (
        "INSERT INTO sidekick.assistant_task_review_findings "
        "(id, owner_id, run_id, task_id, finding_code, severity, title, detail, created_at, "
        "updated_at) "
        "VALUES (:task, :owner, :run, :task, 'stale', 'low', 't', 'd', now(), now())"
    ),
}
TASK_ROW = (
    "INSERT INTO sidekick.tasks "
    "(id, owner_id, title, status, priority, created_at, updated_at, version) "
    "VALUES (:task, :owner, 'Task', 'todo', 'normal', now(), now(), 1)"
)


def _baseline_only(tmp_path: Path) -> Path:
    """A migrations directory with only the baseline, which creates the four tables."""

    directory = tmp_path / "baseline-only"
    directory.mkdir()
    (directory / f"{BASELINE}.py").write_text(
        (MIGRATIONS_PATH / f"{BASELINE}.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return directory


def _installation_on_the_baseline(tmp_path: Path) -> None:
    _reset_schema()
    _apply(_baseline_only(tmp_path))
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, created_at) "
        "VALUES (:owner, 'kept', 'Kept', now())",
        IDS,
    )


def _seed(table: str) -> None:
    """One row in `table`, after the rows it references."""

    if table == "assistant_task_review_findings":
        _run(TASK_ROW, IDS)
        _run(SEED_ROWS["assistant_automation_runs"], IDS)
    _run(SEED_ROWS[table], IDS)


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
def test_empty_retired_tables_are_dropped_and_nothing_else_is(tmp_path: Path) -> None:
    _installation_on_the_baseline(tmp_path)
    before = _tables_now()
    assert set(RETIRED) <= before

    _apply(MIGRATIONS_PATH)

    # The retired tables go; migration 107 adds the two tag link tables.
    assert _tables_now() == (before - set(RETIRED)) | {"contact_tags", "journal_entry_tags"}
    assert _applied_ids() == {BASELINE, DROP_AUTOMATION, TAG_LINKS}
    # The ledger keeps its history of automation runs.
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_schema = "
                        "'sidekick' AND table_name = 'domain_events' AND column_name = "
                        "'automation_run_id'"
                    )
                )
                == 1
            )
            assert connection.scalar(text("SELECT username FROM sidekick.users")) == "kept"
    finally:
        engine.dispose()
    backend = get_backend(_migration_url())
    assert not list(backend.to_apply(read_migrations(str(MIGRATIONS_PATH))))


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_end_state_equals_a_fresh_install(tmp_path: Path) -> None:
    _reset_schema()
    _apply(MIGRATIONS_PATH)
    fresh = _snapshot()

    _installation_on_the_baseline(tmp_path)
    _run("DELETE FROM sidekick.users")
    _apply(MIGRATIONS_PATH)

    assert _snapshot() == fresh


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
@pytest.mark.parametrize("table", RETIRED)
def test_a_retired_table_with_a_row_stops_the_migration_and_drops_nothing(
    table: str, tmp_path: Path
) -> None:
    _installation_on_the_baseline(tmp_path)
    _seed(table)
    before = _snapshot()

    with pytest.raises(Exception, match=rf"sidekick\.{table} holds rows") as refused:
        _apply(MIGRATIONS_PATH)

    assert "Nothing was changed" in str(refused.value)
    assert _snapshot() == before
    assert set(RETIRED) <= _tables_now()
    assert _applied_ids() == {BASELINE}
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            count = connection.scalar(
                text(f"SELECT count(*) FROM sidekick.{table}")  # noqa: S608  (a RETIRED name)
            )
            assert count == 1
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_migration_refuses_a_rollback() -> None:
    _reset_schema()
    _apply(MIGRATIONS_PATH)
    backend = get_backend(_migration_url())
    migration = next(
        item for item in read_migrations(str(MIGRATIONS_PATH)) if item.id == DROP_AUTOMATION
    )

    with pytest.raises(backend.DatabaseError, match="cannot be rolled back"):
        backend.rollback_one(migration)

    assert DROP_AUTOMATION in _applied_ids()
    assert _tables_now().isdisjoint(RETIRED)

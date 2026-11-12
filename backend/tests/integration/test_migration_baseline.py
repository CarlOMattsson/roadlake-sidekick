"""The 0.1.0 schema baseline (100_baseline_0_1_0): the schema of a new installation.

Two guards:

* the catalogue of a fresh install equals the checked-in fingerprint
  `fixtures/baseline-catalogue.json`
  (every table, column, constraint, index, grant and default privilege), so any schema change is a
  deliberate edit of that file (regenerate: see the docstring of
  `test_a_fresh_install_matches_the_checked_in_schema_fingerprint`);
* the migrations carry no name from before the rename.

There is no upgrade path from the old chain: a database that already has the schema is refused.
"""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from yoyo import get_backend, read_migrations

from tests.support.migration_baseline import (
    BASELINE,
    MIGRATIONS_PATH,
    OLD_NAME,
    _admin_url,
    _apply,
    _migration_url,
    _reset_schema,
    _run,
    _snapshot,
    rebuilt_schema,  # noqa: F401  (a fixture)
)

# Migrations after the baseline; the snapshot is the baseline plus these.
LATER_MIGRATIONS = frozenset(
    {
        "101_tasks_project_and_due_indexes",
        "102_event_ledger_append_only",
        "103_trash_sweep_delete_grants",
        "104_audit_event_source",
        "105_drop_sessions_and_password_hash",
    }
)
SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "baseline-catalogue.json"

# The tables of removed features (chat, live voice, proposals and others), which Sidekick no longer
# has. The baseline never creates them.
RETIRED_TABLES = frozenset(
    {
        "chat_action_proposal_sources",
        "chat_action_proposals",
        "chat_conversations",
        "chat_disambiguation_candidates",
        "chat_disambiguations",
        "chat_memory_documents",
        "chat_message_record_references",
        "chat_messages",
        "chat_run_events",
        "chat_tool_invocations",
        "chat_turns",
        "conversation_extraction_runs",
        "conversation_live_sessions",
        "conversation_proposal_dependencies",
        "conversation_proposal_sources",
        "conversation_proposals",
        "agent_job_events",
        "agent_jobs",
        "agent_proposal_dependencies",
        "agent_proposals",
        "entity_origins",
        "assistant_autonomy_actions",
        "user_assistant_settings",
        "user_key_bindings",
        "user_ui_preferences",
    }
)

# What the app role may do on every table of the head: S(elect) I(nsert) U(pdate) D(elete).
# Pinned so that a grant change is a deliberate edit here.
APP_PRIVILEGES = {
    "actions": "SIUD",
    "activity_entries": "SI",
    "assistant_automation_control": "SIUD",
    "assistant_automation_policies": "SIUD",
    "assistant_automation_runs": "SIUD",
    "assistant_task_review_findings": "SIUD",
    "audit_events": "SI",
    "companion_pairings": "SIU",
    "contact_aliases": "SIUD",
    "contacts": "SIUD",
    "daily_journal_summaries": "SIU",
    "daily_journal_summary_entries": "SID",
    "domain_events": "SI",
    "domain_tags": "SIUD",
    "domains": "SIUD",
    "external_references": "SIUD",
    "idempotency_operations": "SIUD",
    "instance_license": "SIU",
    "journal_drafts": "SIU",
    "journal_entries": "SIU",
    "journal_entry_contacts": "SID",
    "journal_entry_projects": "SID",
    "journal_entry_tasks": "SID",
    "journal_processing_runs": "SIU",
    "journal_sources": "SI",
    "journal_summary_proposals": "SIU",
    "memory_settings": "SIU",
    "memory_sources": "SIUD",
    "memory_usage_daily": "SIU",
    "personal_access_tokens": "SIUD",
    "process_run_outbox": "SIUD",
    "process_run_templates": "SIUD",
    "process_runs": "SIUD",
    "process_tags": "SIUD",
    "processes": "SIUD",
    "project_contacts": "SIUD",
    "project_tags": "SIUD",
    "projects": "SIUD",
    "push_outbox": "SIU",
    "push_reminders": "SIU",
    "push_subscriptions": "SIU",
    "saved_work_views": "SIUD",
    "shopping_item_status_history": "SI",
    "shopping_items": "SIU",
    "shopping_lists": "SIU",
    "steps": "SIUD",
    "task_contacts": "SIUD",
    "task_external_references": "SID",
    "task_status_history": "SIUD",
    "task_tags": "SIUD",
    "tasks": "SIUD",
    "users": "SIUD",
    "work_tags": "SIUD",
}

PRIVILEGES_QUERY = text(
    "SELECT c.relname, "
    "CASE WHEN has_table_privilege('sidekick_app', c.oid, 'SELECT') THEN 'S' ELSE '' END || "
    "CASE WHEN has_table_privilege('sidekick_app', c.oid, 'INSERT') THEN 'I' ELSE '' END || "
    "CASE WHEN has_table_privilege('sidekick_app', c.oid, 'UPDATE') THEN 'U' ELSE '' END || "
    "CASE WHEN has_table_privilege('sidekick_app', c.oid, 'DELETE') THEN 'D' ELSE '' END "
    "FROM pg_class c WHERE c.relnamespace = 'sidekick'::regnamespace AND c.relkind = 'r'"
)


def _applied_ids() -> set[str]:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return set(connection.scalars(text("SELECT migration_id FROM public._yoyo_migration")))
    finally:
        engine.dispose()


def _tables(connection: Connection) -> set[str]:
    return set(
        connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'sidekick'"))
    )


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_fresh_install_has_the_head_without_retired_tables_and_the_pinned_grants() -> None:
    _reset_schema()
    _apply(MIGRATIONS_PATH)

    assert _applied_ids() == {BASELINE, *LATER_MIGRATIONS}
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            tables = _tables(connection)
            privileges = dict(connection.execute(PRIVILEGES_QUERY).tuples().all())
    finally:
        engine.dispose()
    assert tables.isdisjoint(RETIRED_TABLES)
    assert privileges == APP_PRIVILEGES
    # A second apply has nothing left to do.
    backend = get_backend(_migration_url())
    assert not list(backend.to_apply(read_migrations(str(MIGRATIONS_PATH))))


def _fingerprint_diff(expected: dict[str, list[str]], fresh: dict[str, list[str]]) -> str:
    """A unified diff of the two fingerprints, one `section: row` per line, `-` = checked in."""

    def flat(fingerprint: dict[str, list[str]]) -> list[str]:
        return [
            f"{section}: {row}" for section, rows in sorted(fingerprint.items()) for row in rows
        ]

    return "\n".join(
        difflib.unified_diff(
            flat(expected),
            flat(fresh),
            fromfile="checked in: fixtures/baseline-catalogue.json",
            tofile="schema built by `migrations/`",
            lineterm="",
            n=0,
        )
    )


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_fresh_install_matches_the_checked_in_schema_fingerprint() -> None:
    """The schema `migrations/` builds on an empty database equals the checked-in fingerprint.

    The fingerprint is `fixtures/baseline-catalogue.json`: sorted catalogue rows (tables, columns
    with type, nullability and default, constraints, indexes, functions, triggers, policies, owners,
    grants and default privileges) read through `pg_catalog`, with no OIDs. A migration that
    changes the schema fails this test with a diff of the rows that differ. If the change is
    intended, regenerate the file and commit it with the migration.

    The environment variable `SIDEKICK_UPDATE_BASELINE_SNAPSHOT` does not work: the
    `backend/conftest.py` deletes every `SIDEKICK_*` variable except the test-database ones at
    collection time, before this test reads it. Regenerate with a script that imports the helpers
    of this module instead. From `backend/`, with a test database slot exported first
    (`eval "$(bash tools/test-db-pool.sh env N)"`):

        cd backend && .venv/bin/python -c "import json; \
            from tests.integration import test_migration_baseline as m; \
            m._reset_schema(); m._apply(m.MIGRATIONS_PATH); \
            m.SNAPSHOT_PATH.write_text(json.dumps(m._snapshot(), indent=0, \
            ensure_ascii=False, sort_keys=True) + '\\n', encoding='utf-8')"

    The script writes without asserting, so read the `git diff` of the fixture before committing.
    """

    _reset_schema()
    _apply(MIGRATIONS_PATH)
    fresh = _snapshot()

    if os.getenv("SIDEKICK_UPDATE_BASELINE_SNAPSHOT") == "1":
        SNAPSHOT_PATH.write_text(
            json.dumps(fresh, indent=0, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert fresh == expected, (
        "The schema built by migrations/ differs from the checked-in fingerprint. If the change "
        "is intended, regenerate with SIDEKICK_UPDATE_BASELINE_SNAPSHOT=1 (see this test's "
        "docstring). Differences:\n" + _fingerprint_diff(expected, fresh)
    )
    # The whole catalogue is in the new names; nothing of the old product name is left in it.
    assert OLD_NAME not in json.dumps(fresh).lower()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_task_indexes_serve_the_project_and_due_lookups() -> None:
    """The Project reads and the Project foreign-key check use `ix_tasks_owner_project`, and the
    due windows use `ix_tasks_owner_due`. The plan, not wall-clock time, is what is asserted:
    with sequential scans disabled the planner picks these indexes only if they match the
    predicates the application queries use."""

    _reset_schema()
    _apply(MIGRATIONS_PATH)
    plans = {
        "project": (
            "SELECT count(id) FROM sidekick.tasks "
            "WHERE owner_id = '00000000-0000-0000-0000-000000000001' "
            "AND project_id = '00000000-0000-0000-0000-000000000002' "
            "AND archived_at IS NULL AND trashed_at IS NULL",
            "ix_tasks_owner_project",
        ),
        "foreign key check": (
            "SELECT 1 FROM ONLY sidekick.tasks x "
            "WHERE project_id = '00000000-0000-0000-0000-000000000002' "
            "AND owner_id = '00000000-0000-0000-0000-000000000001' FOR KEY SHARE OF x",
            "ix_tasks_owner_project",
        ),
        "due window": (
            "SELECT id FROM sidekick.tasks WHERE owner_id = '00000000-0000-0000-0000-000000000001' "
            "AND due_at IS NOT NULL AND due_at >= now() AND due_at < now() + interval '1 day'",
            "ix_tasks_owner_due",
        ),
    }
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            connection.execute(text("SET enable_seqscan = off"))
            for label, (query, index) in plans.items():
                plan = "\n".join(connection.scalars(text("EXPLAIN " + query)))
                assert index in plan, f"{label}: {plan}"
    finally:
        engine.dispose()


def test_the_migrations_carry_no_name_from_before_the_rename() -> None:
    for path in sorted(MIGRATIONS_PATH.glob("*.py")):
        assert OLD_NAME not in path.read_text(encoding="utf-8").lower(), path.name


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_baseline_refuses_a_database_that_already_has_the_schema() -> None:
    _reset_schema()
    _run(
        "SET LOCAL ROLE sidekick_owner; CREATE SCHEMA sidekick; "
        "CREATE TABLE sidekick.users (id uuid PRIMARY KEY)"
    )

    with pytest.raises(Exception, match=r'schema "sidekick" already exists'):
        _apply(MIGRATIONS_PATH)

    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            assert _tables(connection) == {"users"}
            recorded = connection.scalar(
                text("SELECT count(*) FROM public._yoyo_migration WHERE migration_id = :id"),
                {"id": BASELINE},
            )
    finally:
        engine.dispose()
    assert recorded == 0


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_baseline_refuses_a_rollback() -> None:
    _reset_schema()
    _apply(MIGRATIONS_PATH)
    backend = get_backend(_migration_url())
    migration = next(item for item in read_migrations(str(MIGRATIONS_PATH)) if item.id == BASELINE)

    with pytest.raises(backend.DatabaseError, match="cannot be rolled back"):
        backend.rollback_one(migration)

    assert BASELINE in _applied_ids()


DROP_MIGRATION = "105_drop_sessions_and_password_hash"


def _columns(connection: Connection, table: str) -> set[str]:
    return set(
        connection.scalars(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'sidekick' AND table_name = :table"
            ),
            {"table": table},
        )
    )


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_sign_in_remnants_are_dropped_and_come_back_empty_on_rollback(tmp_path: Path) -> None:
    """Upgrading from head 104 removes `sessions` and `users.password_hash` and keeps the users.

    Rolling the drop back recreates the table, empty and writable by the app role, and the column
    with an empty string for the existing user.
    """

    before = tmp_path / "chain-104"
    before.mkdir()
    for path in MIGRATIONS_PATH.glob("*.py"):
        if path.stem != DROP_MIGRATION:
            (before / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    _reset_schema()
    _apply(before)
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, password_hash, created_at) "
        "VALUES ('00000000-0000-4000-8000-000000000001', 'kept', 'Kept', 'old-hash', now())"
    )
    _run(
        "INSERT INTO sidekick.sessions "
        "(id, user_id, token_digest, csrf_digest, expires_at, created_at) VALUES "
        "('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001', "
        "repeat('a', 64), repeat('b', 64), now(), now())"
    )
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            assert "sessions" in _tables(connection)
            assert "password_hash" in _columns(connection, "users")
    finally:
        engine.dispose()

    _apply(MIGRATIONS_PATH)

    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            assert "sessions" not in _tables(connection)
            assert "password_hash" not in _columns(connection, "users")
            assert connection.scalar(text("SELECT username FROM sidekick.users")) == "kept"
    finally:
        engine.dispose()
    assert DROP_MIGRATION in _applied_ids()

    backend = get_backend(_migration_url())
    migration = next(
        item for item in read_migrations(str(MIGRATIONS_PATH)) if item.id == DROP_MIGRATION
    )
    with backend.lock():
        backend.rollback_one(migration)

    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            assert "sessions" in _tables(connection)
            assert connection.scalar(text("SELECT count(*) FROM sidekick.sessions")) == 0
            assert connection.scalar(text("SELECT password_hash FROM sidekick.users")) == ""
            granted = connection.scalar(
                text(
                    "SELECT string_agg(privilege_type, ',' ORDER BY privilege_type) "
                    "FROM information_schema.role_table_grants WHERE table_schema = 'sidekick' "
                    "AND table_name = 'sessions' AND grantee = 'sidekick_app'"
                )
            )
            assert granted == "DELETE,INSERT,SELECT,UPDATE"
    finally:
        engine.dispose()

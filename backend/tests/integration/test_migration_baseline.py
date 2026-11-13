"""The 0.1.0 schema baseline (100_schema_baseline_0_1_0): the schema of a new installation.

Two guards:

* the catalogue of a fresh install equals the checked-in fingerprint
  `fixtures/baseline-catalogue.json`
  (every table, column, constraint, index, grant and default privilege), so any schema change is a
  deliberate edit of that file (regenerate: see the docstring of
  `test_a_fresh_install_matches_the_checked_in_schema_fingerprint`);
* the migrations carry no name from before the rename.

The baseline folded the development chain `100_baseline_0_1_0` to
`105_drop_sessions_and_password_hash`. A database that applied all of it (the owner's installation)
is recognised and left unchanged; a database on an earlier step of that chain is brought to the head
(tested against the real old chain in `tests/ops/test_baseline_upgrades_folded_chain.py`); any other
database that already has the schema is refused.
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
    DROP_AUTOMATION,
    FORGOTTEN_FACTS,
    MIGRATIONS_PATH,
    OLD_NAME,
    TAG_LINKS,
    _admin_url,
    _applied_ids,
    _apply,
    _migration_url,
    _reset_schema,
    _run,
    _snapshot,
    _tables,
    rebuilt_schema,  # noqa: F401  (a fixture)
)

# The ids of the folded development chain, as an installation that applied it has them recorded.
FOLDED_BASELINE = "100_baseline_0_1_0"
FOLDED_HEAD = "105_drop_sessions_and_password_hash"
FOLDED_CHAIN = (
    FOLDED_BASELINE,
    "101_tasks_project_and_due_indexes",
    "102_event_ledger_append_only",
    "103_trash_sweep_delete_grants",
    "104_audit_event_source",
    FOLDED_HEAD,
)
SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "baseline-catalogue.json"

# The tables of removed features (chat, live voice, proposals and others), which Sidekick no longer
# has. The baseline never creates the chat tables, and migration 106 drops the four automation
# tables that it does create, so a fresh install has none of them.
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
        "assistant_automation_control",
        "assistant_automation_policies",
        "assistant_automation_runs",
        "assistant_task_review_findings",
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
    "audit_events": "SI",
    "companion_pairings": "SIU",
    "contact_aliases": "SIUD",
    "contact_tags": "SIUD",
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
    "journal_entry_tags": "SIUD",
    "journal_entry_tasks": "SID",
    "journal_processing_runs": "SIU",
    "journal_sources": "SI",
    "journal_summary_proposals": "SIU",
    "memory_forgotten_facts": "SIUD",
    "memory_forgotten_units": "SIUD",
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


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_fresh_install_has_the_head_without_retired_tables_and_the_pinned_grants() -> None:
    _reset_schema()
    _apply(MIGRATIONS_PATH)

    assert _applied_ids() == {BASELINE, DROP_AUTOMATION, TAG_LINKS, FORGOTTEN_FACTS}
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

    with pytest.raises(Exception, match=r"sidekick schema already exists but is not at a revision"):
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


def _stamp_as_folded_chain(upto: str) -> None:
    """Make the bookkeeping read as if the folded development chain had been applied up to `upto`.

    The schema of the database is the one the baseline builds, which is what the chain's head built
    too (the fingerprint test pins that), so this is what the owner's installation looks like.
    """

    _stamp(list(FOLDED_CHAIN[: FOLDED_CHAIN.index(upto) + 1]))


OWNER_ID = "00000000-0000-4000-8000-000000000001"


def _insert_owner() -> None:
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, created_at) "
        "VALUES (:id, 'kept', 'Kept', now())",
        {"id": OWNER_ID},
    )


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_database_on_the_folded_chain_head_is_adopted_unchanged_with_its_data() -> None:
    """The owner's installation applied `100_baseline_0_1_0`..`105`; the new baseline is then
    recorded without running anything: the schema and the rows stay as they were."""

    _reset_schema()
    _apply(MIGRATIONS_PATH)
    _insert_owner()
    before = _snapshot()
    # A database on the folded chain has not applied migrations 107 and 108 either.
    _run(
        "SET LOCAL ROLE sidekick_owner; "
        "DROP TABLE sidekick.contact_tags, sidekick.journal_entry_tags, "
        "sidekick.memory_forgotten_units, sidekick.memory_forgotten_facts; "
        "ALTER TABLE sidekick.memory_sources DROP CONSTRAINT uq_memory_sources_id_owner; "
        "ALTER TABLE sidekick.memory_settings DROP COLUMN forget_salt"
    )
    _stamp_as_folded_chain(FOLDED_HEAD)

    _apply(MIGRATIONS_PATH)

    assert _snapshot() == before
    assert _applied_ids() == {
        *FOLDED_CHAIN,
        BASELINE,
        DROP_AUTOMATION,
        TAG_LINKS,
        FORGOTTEN_FACTS,
    }
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT username FROM sidekick.users")) == "kept"
    finally:
        engine.dispose()
    backend = get_backend(_migration_url())
    assert not list(backend.to_apply(read_migrations(str(MIGRATIONS_PATH))))


def _stamp(ids: list[str]) -> None:
    """Replace the record of the new migrations with `ids`; the migrations after the baseline are
    forgotten too, because a database on the folded chain has not applied them."""

    for migration_id in (BASELINE, DROP_AUTOMATION, TAG_LINKS, FORGOTTEN_FACTS):
        _run("DELETE FROM public._yoyo_migration WHERE migration_id = :id", {"id": migration_id})
    for migration_id in ids:
        _run(
            "INSERT INTO public._yoyo_migration (migration_hash, migration_id, applied_at_utc) "
            "VALUES (md5(:id), :id, now())",
            {"id": migration_id},
        )


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
@pytest.mark.parametrize(
    "ids",
    [
        # a hole in the chain
        [FOLDED_CHAIN[0], FOLDED_CHAIN[2]],
        [FOLDED_CHAIN[0], FOLDED_CHAIN[1], FOLDED_CHAIN[3]],
        # the chain without its first migration
        list(FOLDED_CHAIN[1:3]),
        # an id the chain did not have
        [*FOLDED_CHAIN[:3], "999_unknown"],
        [*FOLDED_CHAIN, "106_unknown"],
        # no migration recorded at all, but a schema
        [],
    ],
    ids=["hole-101", "hole-102", "no-first", "unknown-id", "unknown-after-head", "none"],
)
def test_a_database_whose_applied_ids_are_not_a_prefix_of_the_folded_chain_is_refused(
    ids: list[str],
) -> None:
    """A gap, a missing first migration or an id from outside the chain means the schema is not one
    the chain built, so it is refused with what to do; nothing is changed or recorded."""

    _reset_schema()
    _apply(MIGRATIONS_PATH)
    _insert_owner()
    _stamp(ids)
    before = _snapshot()

    with pytest.raises(Exception, match=r"not at a revision this baseline replaces") as refused:
        _apply(MIGRATIONS_PATH)

    assert "restore a backup" in str(refused.value)
    assert _snapshot() == before
    assert BASELINE not in _applied_ids()
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT username FROM sidekick.users")) == "kept"
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
@pytest.mark.parametrize(
    ("damage", "failed_check"),
    [
        ("ALTER TABLE sidekick.audit_events DROP COLUMN source", "audit_events.source exists"),
        (
            "CREATE TABLE sidekick.sessions (id uuid PRIMARY KEY)",
            "sessions is dropped",
        ),
        (
            "ALTER TABLE sidekick.users ADD COLUMN password_hash text",
            "users.password_hash is dropped",
        ),
        (
            "GRANT UPDATE ON sidekick.domain_events TO sidekick_app",
            "the event ledger is append-only for the app role",
        ),
        (
            "REVOKE DELETE ON sidekick.domains FROM sidekick_app",
            "the app role may delete domains",
        ),
    ],
)
def test_a_105_database_whose_schema_does_not_match_is_refused_and_not_stamped(
    damage: str, failed_check: str
) -> None:
    """The bookkeeping says 105, but the schema is not the one 105 built (a hand edit, a restore
    of mixed state): adopting it would stamp a wrong schema, so it is refused and nothing is
    recorded."""

    _reset_schema()
    _apply(MIGRATIONS_PATH)
    _insert_owner()
    _run("SET LOCAL ROLE sidekick_owner; " + damage)
    _stamp_as_folded_chain(FOLDED_HEAD)
    before = _snapshot()

    with pytest.raises(Exception, match=r"does not match the schema this baseline") as refused:
        _apply(MIGRATIONS_PATH)

    assert failed_check in str(refused.value)
    assert _snapshot() == before
    assert BASELINE not in _applied_ids()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_baseline_has_no_sign_in_remnants_and_the_final_grants() -> None:
    """What migrations 101 to 105 changed is in the baseline: no `sessions`, no
    `users.password_hash`, `audit_events.source`, the two `tasks` indexes, append-only history
    and delete rights on `domains` and `processes`."""

    _reset_schema()
    _apply(MIGRATIONS_PATH)
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            assert "sessions" not in _tables(connection)
            assert "password_hash" not in _columns(connection, "users")
            assert "source" in _columns(connection, "audit_events")
            privileges = dict(connection.execute(PRIVILEGES_QUERY).tuples().all())
    finally:
        engine.dispose()
    assert privileges["domain_events"] == privileges["activity_entries"] == "SI"
    assert privileges["domains"] == privileges["processes"] == "SIUD"


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

"""Direct PostgreSQL tests for Journal integrity and finalize race guards."""

# SQL strings intentionally preserve schema-level readability.
# ruff: noqa: E501

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from sidekick.shared.types import new_uuid7
from tests.db import database_factory, require_test_database_url


def test_baseline_exists_before_constraint_tests() -> None:
    migration = Path(__file__).resolve().parents[3] / "migrations" / "100_schema_baseline_0_1_0.py"
    assert migration.is_file()


@pytest.fixture(scope="module")
def engine():
    database_factory()
    app_engine = create_engine(require_test_database_url())
    yield app_engine
    owner_engine = create_engine(require_test_database_url("SIDEKICK_TEST_MIGRATION_DATABASE_URL"))
    with owner_engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE sidekick_owner"))
        conn.execute(text("TRUNCATE sidekick.journal_sources CASCADE"))
    with app_engine.begin() as conn:
        conn.execute(text("DELETE FROM sidekick.users WHERE username LIKE 'journal_%'"))


def _insert_user(conn, owner_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO sidekick.users (id, username, display_name, created_at) "
            "VALUES (:id, :username, 'Journal Owner', now())"
        ),
        {"id": owner_id, "username": f"journal_{owner_id}"},
    )


def _insert_source(
    conn, source_id: UUID, owner_id: UUID, *, replacement: UUID | None = None
) -> None:
    conn.execute(
        text(
            "INSERT INTO sidekick.journal_sources "
            "(id, owner_id, source_type, journal_date, raw_text, content_fingerprint, "
            "replaces_source_id, created_at) VALUES (:id, :owner, 'manual_text', "
            "DATE '2026-07-21', 'Syntetisk journaltext', repeat('a', 64), :replacement, now())"
        ),
        {"id": source_id, "owner": owner_id, "replacement": replacement},
    )


def _insert_entry(conn, entry_id: UUID, owner_id: UUID, source_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO sidekick.journal_entries "
            "(id, owner_id, source_id, journal_date, title, key_points, version, "
            "created_at, updated_at) VALUES (:id, :owner, :source, DATE '2026-07-21', "
            "'Syntetisk titel', '[]'::jsonb, 1, now(), now())"
        ),
        {"id": entry_id, "owner": owner_id, "source": source_id},
    )


@pytest.mark.integration
def test_sources_are_insert_only_and_replacements_are_same_owner_nonself(engine) -> None:
    owner_1, owner_2 = new_uuid7(), new_uuid7()
    source_1, source_2 = new_uuid7(), new_uuid7()
    with engine.begin() as conn:
        _insert_user(conn, owner_1)
        _insert_user(conn, owner_2)
        _insert_source(conn, source_1, owner_1)
        _insert_source(conn, source_2, owner_1, replacement=source_1)
        before = conn.execute(
            text(
                "SELECT raw_text, replaces_source_id FROM sidekick.journal_sources WHERE id = :id"
            ),
            {"id": source_1},
        ).one()
        assert before == ("Syntetisk journaltext", None)

        with pytest.raises(IntegrityError), conn.begin_nested():
            _insert_source(conn, new_uuid7(), owner_2, replacement=source_1)
        self_id = new_uuid7()
        with pytest.raises(IntegrityError), conn.begin_nested():
            _insert_source(conn, self_id, owner_1, replacement=self_id)

        assert (
            conn.execute(
                text(
                    "SELECT raw_text, replaces_source_id FROM sidekick.journal_sources WHERE id = :id"
                ),
                {"id": source_1},
            ).one()
            == before
        )


@pytest.mark.integration
def test_status_length_version_archive_and_summary_checks(engine) -> None:
    owner_id, source_id = new_uuid7(), new_uuid7()
    with engine.begin() as conn:
        _insert_user(conn, owner_id)
        _insert_source(conn, source_id, owner_id)

        invalid_statements = (
            (
                "INSERT INTO sidekick.journal_processing_runs "
                "(id, owner_id, source_id, operation, journal_date, status, provider, model_id, "
                "prompt_version, schema_version, input_fingerprint, candidate_catalog, attempt_count, "
                "created_at) VALUES (:id, :owner, :source, 'unknown', DATE '2026-07-21', "
                "'pending', 'fake', 'fake', 'v1', 'v1', repeat('a',64), '{}'::jsonb, 1, now())",
                {"id": new_uuid7(), "owner": owner_id, "source": source_id},
            ),
            (
                "INSERT INTO sidekick.journal_processing_runs "
                "(id, owner_id, operation, journal_date, status, provider, model_id, prompt_version, "
                "schema_version, input_fingerprint, candidate_catalog, attempt_count, created_at) "
                "VALUES (:id, :owner, 'daily_summary', DATE '2026-07-21', 'invalid', 'fake', "
                "'fake', 'v1', 'v1', repeat('a',64), '{}'::jsonb, 1, now())",
                {"id": new_uuid7(), "owner": owner_id},
            ),
            (
                "INSERT INTO sidekick.journal_entries "
                "(id, owner_id, source_id, journal_date, title, key_points, version, created_at, "
                "updated_at, archived_at) VALUES (:id, :owner, :source, DATE '2026-07-21', '', "
                "'[]'::jsonb, 0, now(), now(), now())",
                {"id": new_uuid7(), "owner": owner_id, "source": source_id},
            ),
            (
                "INSERT INTO sidekick.daily_journal_summaries "
                "(id, owner_id, journal_date, origin, status, overview, content, source_fingerprint, "
                "version, generated_at, updated_at) VALUES (:id, :owner, DATE '2026-07-21', "
                "'manual', 'failed', '', '{}'::jsonb, repeat('a',64), 0, now(), now())",
                {"id": new_uuid7(), "owner": owner_id},
            ),
        )
        for statement, params in invalid_statements:
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(text(statement), params)

        entry_id = new_uuid7()
        _insert_entry(conn, entry_id, owner_id, source_id)
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text(
                    "UPDATE sidekick.journal_entries SET archived_at = created_at - interval '1 second' WHERE id = :id"
                ),
                {"id": entry_id},
            )


@pytest.mark.integration
def test_individual_run_draft_proposal_and_entry_checks(engine) -> None:
    owner_id, source_id = new_uuid7(), new_uuid7()
    run_id, summary_run_id = new_uuid7(), new_uuid7()
    with engine.begin() as conn:
        _insert_user(conn, owner_id)
        _insert_source(conn, source_id, owner_id)
        run_values = {
            "id": run_id,
            "owner": owner_id,
            "source": source_id,
        }
        conn.execute(
            text(
                "INSERT INTO sidekick.journal_processing_runs "
                "(id, owner_id, source_id, operation, journal_date, status, provider, model_id, "
                "prompt_version, schema_version, input_fingerprint, candidate_catalog, "
                "attempt_count, started_at, created_at) VALUES (:id, :owner, :source, "
                "'entry_draft', DATE '2026-07-21', 'running', 'fake', 'fake-model', 'v1', "
                "'v1', repeat('a',64), '{}'::jsonb, 1, now(), now())"
            ),
            run_values,
        )
        run_assignments = (
            "operation = 'unknown'",
            "status = 'unknown'",
            "provider = ''",
            "model_id = ''",
            "prompt_version = ''",
            "schema_version = ''",
            "input_fingerprint = 'bad'",
            "candidate_catalog = '[]'::jsonb",
            "attempt_count = 0",
            "input_tokens = -1",
            "output_tokens = -1",
            "finished_at = started_at - interval '1 second'",
            "source_id = NULL",
        )
        for assignment in run_assignments:
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(
                    text(
                        f"UPDATE sidekick.journal_processing_runs SET {assignment} WHERE id = :id"
                    ),
                    {"id": run_id},
                )

        draft_base = (
            "INSERT INTO sidekick.journal_drafts "
            "(id, owner_id, source_id, processing_run_id, catalog_run_id, state, title, "
            "summary, key_points, relation_suggestions, task_proposals, version, created_at, "
            "updated_at) VALUES (:id, :owner, :source, :run, :run, {state}, {title}, NULL, "
            "{key_points}, '{{}}'::jsonb, {task_proposals}, {version}, now(), now())"
        )
        invalid_drafts = (
            {
                "state": "'unknown'",
                "title": "'Titel'",
                "key_points": "'[]'::jsonb",
                "task_proposals": "'[]'::jsonb",
                "version": "1",
            },
            {
                "state": "'pending_review'",
                "title": "''",
                "key_points": "'[]'::jsonb",
                "task_proposals": "'[]'::jsonb",
                "version": "1",
            },
            {
                "state": "'pending_review'",
                "title": "'Titel'",
                "key_points": "'{}'::jsonb",
                "task_proposals": "'[]'::jsonb",
                "version": "1",
            },
            {
                "state": "'pending_review'",
                "title": "'Titel'",
                "key_points": "'[]'::jsonb",
                "task_proposals": "'{}'::jsonb",
                "version": "1",
            },
            {
                "state": "'pending_review'",
                "title": "'Titel'",
                "key_points": "'[]'::jsonb",
                "task_proposals": "'[]'::jsonb",
                "version": "0",
            },
        )
        for fields in invalid_drafts:
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(
                    text(draft_base.format(**fields)),
                    {"id": new_uuid7(), "owner": owner_id, "source": source_id, "run": run_id},
                )

        conn.execute(
            text(
                "INSERT INTO sidekick.journal_processing_runs "
                "(id, owner_id, operation, journal_date, status, provider, model_id, "
                "prompt_version, schema_version, input_fingerprint, candidate_catalog, "
                "attempt_count, created_at) VALUES (:id, :owner, 'daily_summary', "
                "DATE '2026-07-21', 'succeeded', 'fake', 'fake-model', 'v1', 'v1', "
                "repeat('b',64), '{}'::jsonb, 1, now())"
            ),
            {"id": summary_run_id, "owner": owner_id},
        )
        proposal_base = (
            "INSERT INTO sidekick.journal_summary_proposals "
            "(id, owner_id, run_id, journal_date, entry_fingerprint, content, state, version, "
            "created_at, updated_at) VALUES (:id, :owner, :run, DATE '2026-07-21', "
            "{fingerprint}, {content}, {state}, {version}, now(), now())"
        )
        invalid_proposals = (
            {
                "fingerprint": "repeat('c',64)",
                "content": "'{}'::jsonb",
                "state": "'unknown'",
                "version": "1",
            },
            {
                "fingerprint": "'bad'",
                "content": "'{}'::jsonb",
                "state": "'pending_review'",
                "version": "1",
            },
            {
                "fingerprint": "repeat('c',64)",
                "content": "'[]'::jsonb",
                "state": "'pending_review'",
                "version": "1",
            },
            {
                "fingerprint": "repeat('c',64)",
                "content": "'{}'::jsonb",
                "state": "'pending_review'",
                "version": "0",
            },
        )
        for fields in invalid_proposals:
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(
                    text(proposal_base.format(**fields)),
                    {"id": new_uuid7(), "owner": owner_id, "run": summary_run_id},
                )

        entry_base = (
            "INSERT INTO sidekick.journal_entries "
            "(id, owner_id, source_id, journal_date, title, summary, key_points, version, "
            "created_at, updated_at) VALUES (:id, :owner, :source, DATE '2026-07-21', "
            "{title}, {summary}, {key_points}, {version}, now(), now())"
        )
        invalid_entries = (
            {"title": "''", "summary": "NULL", "key_points": "'[]'::jsonb", "version": "1"},
            {
                "title": "'Titel'",
                "summary": "repeat('x',10001)",
                "key_points": "'[]'::jsonb",
                "version": "1",
            },
            {"title": "'Titel'", "summary": "NULL", "key_points": "'{}'::jsonb", "version": "1"},
            {"title": "'Titel'", "summary": "NULL", "key_points": "'[]'::jsonb", "version": "0"},
        )
        for fields in invalid_entries:
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(
                    text(entry_base.format(**fields)),
                    {"id": new_uuid7(), "owner": owner_id, "source": source_id},
                )


@pytest.mark.integration
def test_owner_composite_fks_and_typed_relations(engine) -> None:
    owner_1, owner_2 = new_uuid7(), new_uuid7()
    source_id, entry_id = new_uuid7(), new_uuid7()
    project_id, task_id, contact_id = new_uuid7(), new_uuid7(), new_uuid7()
    with engine.begin() as conn:
        _insert_user(conn, owner_1)
        _insert_user(conn, owner_2)
        _insert_source(conn, source_id, owner_1)
        _insert_entry(conn, entry_id, owner_1, source_id)
        domain_id = new_uuid7()
        # Every Project needs an owner-consistent Domain ancestry.
        conn.execute(
            text(
                "INSERT INTO sidekick.domains (id, owner_id, name, status, version, created_at, updated_at) VALUES (:id, :owner, 'Domän', 'active', 1, now(), now())"
            ),
            {"id": domain_id, "owner": owner_1},
        )
        conn.execute(
            text(
                "INSERT INTO sidekick.projects (id, owner_id, domain_id, title, status, version, created_at, updated_at) VALUES (:id, :owner, :domain, 'Projekt', 'active', 1, now(), now())"
            ),
            {"id": project_id, "owner": owner_1, "domain": domain_id},
        )
        conn.execute(
            text(
                "INSERT INTO sidekick.tasks (id, owner_id, title, status, priority, version, created_at, updated_at) VALUES (:id, :owner, 'Uppgift', 'todo', 'normal', 1, now(), now())"
            ),
            {"id": task_id, "owner": owner_1},
        )
        conn.execute(
            text(
                "INSERT INTO sidekick.contacts (id, owner_id, display_name, display_name_key, created_at, updated_at, archived, version) VALUES (:id, :owner, 'Kontakt', 'kontakt', now(), now(), false, 1)"
            ),
            {"id": contact_id, "owner": owner_1},
        )
        for table, target_column, target_id in (
            ("journal_entry_projects", "project_id", project_id),
            ("journal_entry_tasks", "task_id", task_id),
            ("journal_entry_contacts", "contact_id", contact_id),
        ):
            conn.execute(
                text(
                    f"INSERT INTO sidekick.{table} (owner_id, entry_id, {target_column}, created_at) VALUES (:owner, :entry, :target, now())"
                ),
                {"owner": owner_1, "entry": entry_id, "target": target_id},
            )
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(
                    text(
                        f"INSERT INTO sidekick.{table} (owner_id, entry_id, {target_column}, created_at) VALUES (:owner, :entry, :target, now())"
                    ),
                    {"owner": owner_2, "entry": entry_id, "target": target_id},
                )

        with pytest.raises(IntegrityError), conn.begin_nested():
            _insert_entry(conn, new_uuid7(), owner_2, source_id)


@pytest.mark.integration
def test_summary_owner_day_uniqueness_and_exact_provenance(engine) -> None:
    owner_1, owner_2 = new_uuid7(), new_uuid7()
    source_id, entry_id = new_uuid7(), new_uuid7()
    second_source_id, second_entry_id = new_uuid7(), new_uuid7()
    summary_id = new_uuid7()
    with engine.begin() as conn:
        _insert_user(conn, owner_1)
        _insert_user(conn, owner_2)
        _insert_source(conn, source_id, owner_1)
        _insert_entry(conn, entry_id, owner_1, source_id)
        _insert_source(conn, second_source_id, owner_1)
        _insert_entry(conn, second_entry_id, owner_1, second_source_id)
        conn.execute(
            text(
                "INSERT INTO sidekick.daily_journal_summaries "
                "(id, owner_id, journal_date, origin, status, overview, content, source_fingerprint, "
                "version, generated_at, updated_at) VALUES (:id, :owner, DATE '2026-07-21', "
                "'manual', 'current', 'Syntetisk översikt', '{}'::jsonb, repeat('b',64), 1, now(), now())"
            ),
            {"id": summary_id, "owner": owner_1},
        )
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO sidekick.daily_journal_summaries "
                    "(id, owner_id, journal_date, origin, status, overview, content, source_fingerprint, "
                    "version, generated_at, updated_at) VALUES (:id, :owner, DATE '2026-07-21', "
                    "'manual', 'current', 'Annan', '{}'::jsonb, repeat('c',64), 1, now(), now())"
                ),
                {"id": new_uuid7(), "owner": owner_1},
            )
        conn.execute(
            text(
                "INSERT INTO sidekick.daily_journal_summary_entries "
                "(owner_id, summary_id, entry_id, entry_version, ordinal) "
                "VALUES (:owner, :summary, :entry, 1, 0)"
            ),
            {"owner": owner_1, "summary": summary_id, "entry": entry_id},
        )
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO sidekick.daily_journal_summary_entries "
                    "(owner_id, summary_id, entry_id, entry_version, ordinal) "
                    "VALUES (:owner, :summary, :entry, 1, 1)"
                ),
                {"owner": owner_1, "summary": summary_id, "entry": entry_id},
            )
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO sidekick.daily_journal_summary_entries "
                    "(owner_id, summary_id, entry_id, entry_version, ordinal) "
                    "VALUES (:owner, :summary, :entry, 1, 0)"
                ),
                {"owner": owner_1, "summary": summary_id, "entry": second_entry_id},
            )
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO sidekick.daily_journal_summary_entries "
                    "(owner_id, summary_id, entry_id, entry_version, ordinal) "
                    "VALUES (:owner, :summary, :entry, 1, 2)"
                ),
                {"owner": owner_2, "summary": summary_id, "entry": entry_id},
            )


@pytest.mark.integration
@pytest.mark.parametrize("first_path", ["manual", "draft", "equal_retry"])
def test_source_entry_unique_guard_for_sequential_finalize_paths(engine, first_path: str) -> None:
    owner_id, source_id = new_uuid7(), new_uuid7()
    with engine.begin() as conn:
        _insert_user(conn, owner_id)
        _insert_source(conn, source_id, owner_id)
        first_id = new_uuid7()
        _insert_entry(conn, first_id, owner_id, source_id)
        second_id = first_id if first_path == "equal_retry" else new_uuid7()
        with pytest.raises(IntegrityError), conn.begin_nested():
            _insert_entry(conn, second_id, owner_id, source_id)
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM sidekick.journal_entries WHERE owner_id = :owner AND source_id = :source"
                ),
                {"owner": owner_id, "source": source_id},
            )
            == 1
        )


@pytest.mark.integration
def test_concurrent_finalize_race_creates_exactly_one_entry(engine) -> None:
    owner_id, source_id = new_uuid7(), new_uuid7()
    with engine.begin() as conn:
        _insert_user(conn, owner_id)
        _insert_source(conn, source_id, owner_id)

    def finalize(entry_id: UUID) -> bool:
        try:
            with engine.begin() as conn:
                _insert_entry(conn, entry_id, owner_id, source_id)
            return True
        except IntegrityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finalize, (new_uuid7(), new_uuid7())))
    assert sorted(results) == [False, True]
    with engine.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM sidekick.journal_entries WHERE owner_id = :owner AND source_id = :source"
                ),
                {"owner": owner_id, "source": source_id},
            )
            == 1
        )

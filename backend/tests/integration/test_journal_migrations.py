"""Runtime-role grants on the journal tables at the schema head."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from tests.db import database_factory, require_test_database_url


@pytest.mark.integration
def test_runtime_journal_grants_actual_dml_and_ddl_denial() -> None:
    # A fresh worker database has no schema yet; database_factory() migrates it to the head first.
    database_factory()
    migration_url = require_test_database_url("SIDEKICK_TEST_MIGRATION_DATABASE_URL")
    app_url = require_test_database_url()

    app_engine = create_engine(app_url)
    owner_id = "018af000-0000-7000-8000-000000000711"
    source_id = "018af000-0000-7000-8000-000000000712"
    entry_id = "018af000-0000-7000-8000-000000000713"
    with app_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sidekick.users "
                "(id, username, display_name, created_at) "
                "VALUES (:id, 'journal-runtime-owner', 'Runtime Owner', now())"
            ),
            {"id": owner_id},
        )
        conn.execute(
            text(
                "INSERT INTO sidekick.journal_sources "
                "(id, owner_id, source_type, journal_date, raw_text, content_fingerprint, "
                "created_at) VALUES (:id, :owner, 'manual_text', DATE '2026-07-21', "
                "'Syntetisk journaltext', repeat('a', 64), now())"
            ),
            {"id": source_id, "owner": owner_id},
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM sidekick.journal_sources WHERE id = :id"),
                {"id": source_id},
            )
            == 1
        )
        conn.execute(
            text(
                "INSERT INTO sidekick.journal_entries "
                "(id, owner_id, source_id, journal_date, title, key_points, version, "
                "created_at, updated_at) VALUES (:id, :owner, :source, DATE '2026-07-21', "
                "'Syntetisk titel', '[]'::jsonb, 1, now(), now())"
            ),
            {"id": entry_id, "owner": owner_id, "source": source_id},
        )
        conn.execute(
            text("UPDATE sidekick.journal_entries SET title = 'Uppdaterad' WHERE id = :id"),
            {"id": entry_id},
        )

    with app_engine.connect() as conn:
        for statement in (
            "UPDATE sidekick.journal_sources SET raw_text = 'förbjudet' WHERE id = "
            f"'{source_id}'::uuid",
            f"DELETE FROM sidekick.journal_sources WHERE id = '{source_id}'::uuid",
            f"DELETE FROM sidekick.journal_entries WHERE id = '{entry_id}'::uuid",
            "ALTER TABLE sidekick.journal_entries ADD COLUMN forbidden integer",
            "DROP TABLE sidekick.journal_entries",
            "CREATE TABLE sidekick.forbidden_journal(id integer)",
        ):
            with pytest.raises(ProgrammingError), conn.begin_nested():
                conn.execute(text(statement))

    owner_engine = create_engine(migration_url)
    with owner_engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE sidekick_owner"))
        conn.execute(text("TRUNCATE sidekick.journal_sources CASCADE"))
    with app_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM sidekick.users WHERE username IN "
                "('journal-migration-owner', 'journal-runtime-owner')"
            )
        )

"""Memory sync state, settings and usage counters: vocabulary, uniqueness and limits."""

from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from yoyo import get_backend, read_migrations

from tests.db import database_factory, invalidate_migration_head_cache, require_test_database_url

MIGRATIONS_PATH = str(Path(__file__).resolve().parents[3] / "migrations")
OWNER_ID = "018af000-0000-7000-8000-000000000c01"
VALID_FINGERPRINT = "a" * 64
INSERT_SOURCE = text(
    "INSERT INTO sidekick.memory_sources "
    "(id, owner_id, source_kind, source_id, doc_key, fingerprint, pipeline_version, status, "
    "attempts, operation_id, source_updated_at, retained_at, failure_category, excluded) "
    "VALUES (:id, :owner, :kind, :source, :doc_key, :fingerprint, 1, :status, 0, :operation, "
    "now(), :retained_at, :failure, false)"
)


def _source_params(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "id": uuid4(),
        "owner": UUID(OWNER_ID),
        "kind": "journal_entry",
        "source": uuid4(),
        "doc_key": f"doc-{uuid4()}",
        "fingerprint": VALID_FINGERPRINT,
        "status": "pending",
        "operation": None,
        "retained_at": None,
        "failure": None,
    }
    params.update(overrides)
    return params


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
def test_memory_tables_enforce_their_vocabulary_uniqueness_and_limits() -> None:
    migration_url = require_test_database_url("SIDEKICK_TEST_MIGRATION_DATABASE_URL")
    app_url = require_test_database_url()
    backend = get_backend(migration_url)
    migrations = read_migrations(MIGRATIONS_PATH)
    database_factory()
    engine = create_engine(app_url)
    invalidate_migration_head_cache()
    backend.apply_migrations(backend.to_apply(migrations))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sidekick.users "
                    "(id, username, display_name, created_at) "
                    "VALUES (:id, 'memory-owner', 'Owner', now())"
                ),
                {"id": OWNER_ID},
            )
            valid = _source_params(status="submitted", operation="op-1")
            conn.execute(INSERT_SOURCE, valid)
            conn.execute(
                text("DELETE FROM sidekick.memory_sources WHERE id = :id"), {"id": valid["id"]}
            )

        refused: list[dict[str, object]] = [
            _source_params(kind="shopping"),
            _source_params(fingerprint="ABC"),
            _source_params(status="submitted", operation=None),
            _source_params(status="retained", retained_at=None),
            _source_params(status="parked", failure=None),
            _source_params(status="unknown"),
        ]
        for params in refused:
            with pytest.raises(IntegrityError), engine.begin() as conn:
                conn.execute(INSERT_SOURCE, params)

        with engine.begin() as conn:
            first = _source_params(doc_key="doc-shared")
            conn.execute(INSERT_SOURCE, first)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(INSERT_SOURCE, _source_params(doc_key="doc-shared"))
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                INSERT_SOURCE,
                _source_params(source=first["source"], doc_key="doc-other-key"),
            )

        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sidekick.memory_settings "
                    "(owner_id, version, created_at, updated_at) "
                    "VALUES (:owner, 0, now(), now())"
                ),
                {"owner": UUID(OWNER_ID)},
            )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sidekick.memory_settings "
                    "(owner_id, journal, created_at, updated_at) "
                    "VALUES (:owner, true, now(), now())"
                ),
                {"owner": UUID(OWNER_ID)},
            )
            settings = conn.execute(
                text(
                    "SELECT journal, contacts, projects, tasks, paused, version "
                    "FROM sidekick.memory_settings WHERE owner_id = :owner"
                ),
                {"owner": UUID(OWNER_ID)},
            ).one()
            # Absent domains default to on (baseline); the owner's choice is stored as given.
            assert tuple(settings) == (True, True, True, True, False, 1)

        usage = {"owner": UUID(OWNER_ID), "day": date(2026, 10, 28)}
        upsert = text(
            "INSERT INTO sidekick.memory_usage_daily "
            "(owner_id, usage_date, retain_documents, characters) "
            "VALUES (:owner, :day, 1, 120) "
            "ON CONFLICT (owner_id, usage_date) DO UPDATE SET "
            "retain_documents = sidekick.memory_usage_daily.retain_documents + 1, "
            "characters = sidekick.memory_usage_daily.characters + 120"
        )
        with engine.begin() as conn:
            conn.execute(upsert, usage)
            conn.execute(upsert, usage)
            counts = conn.execute(
                text(
                    "SELECT retain_documents, backfill_documents, characters "
                    "FROM sidekick.memory_usage_daily WHERE owner_id = :owner AND usage_date = :day"
                ),
                usage,
            ).one()
            assert tuple(counts) == (2, 0, 240)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sidekick.memory_usage_daily (owner_id, usage_date, characters) "
                    "VALUES (:owner, :day, -1)"
                ),
                {"owner": UUID(OWNER_ID), "day": date(2026, 10, 29)},
            )
    finally:
        engine.dispose()
        backend.apply_migrations(backend.to_apply(migrations))
        invalidate_migration_head_cache()

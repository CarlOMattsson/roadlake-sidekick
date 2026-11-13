"""Shared test helpers moved out of `tests/integration/test_migration_baseline.py`."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from yoyo import get_backend, read_migrations

from tests.db import (
    database_factory,
    ensure_migration_chain_head,
    invalidate_migration_head_cache,
    require_test_database_url,
)
from tests.db_guard import validate_test_database_url

ROOT = Path(__file__).resolve().parents[3]


MIGRATIONS_PATH = ROOT / "migrations"


BASELINE = "100_schema_baseline_0_1_0"
DROP_AUTOMATION = "106_drop_retired_automation_tables"
TAG_LINKS = "107_contact_and_journal_entry_tags"


# The catalogue facts a migration can change, each as sorted text rows. Deparsed definitions
# (pg_get_constraintdef, pg_get_indexdef, ...) differ when the stored expression trees differ, so
# equal snapshots mean equal schemas, not just equal names.
SNAPSHOT_QUERIES = {
    "relations": "SELECT c.relname || ' ' || c.relkind::text || ' owner=' || "
    "pg_get_userbyid(c.relowner)"
    " || ' rls=' || c.relrowsecurity || ' acl=' || coalesce((SELECT string_agg(a::text, ',' "
    "ORDER BY a::text) FROM unnest(c.relacl) a), '') FROM pg_class c "
    "WHERE c.relnamespace = 'sidekick'::regnamespace",
    "columns": "SELECT c.relname || '.' || a.attname || ' ' || format_type(a.atttypid, a.atttypmod)"
    " || ' notnull=' || a.attnotnull || ' generated=' || a.attgenerated::text || ' identity=' || "
    "a.attidentity::text || ' default=' || coalesce(pg_get_expr(d.adbin, d.adrelid), '') "
    "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
    "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE c.relnamespace = 'sidekick'::regnamespace AND a.attnum > 0 AND NOT a.attisdropped",
    "constraints": "SELECT conrelid::regclass || ' ' || conname || ' ' || "
    "pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace = 'sidekick'::regnamespace",
    "indexes": "SELECT indexname || ' ' || indexdef FROM pg_indexes WHERE schemaname = 'sidekick'",
    "functions": "SELECT p.oid::regprocedure || ' ' || pg_get_functiondef(p.oid) FROM pg_proc p "
    "WHERE p.pronamespace = 'sidekick'::regnamespace",
    "triggers": "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c "
    "ON c.oid = t.tgrelid WHERE c.relnamespace = 'sidekick'::regnamespace AND NOT t.tgisinternal",
    "policies": "SELECT tablename || ' ' || policyname || ' ' || cmd || ' ' || "
    "coalesce(qual, '') || ' ' || coalesce(with_check, '') FROM pg_policies "
    "WHERE schemaname = 'sidekick'",
    "types": "SELECT typname || ' ' || typtype::text FROM pg_type WHERE typnamespace = "
    "'sidekick'::regnamespace AND typtype NOT IN ('c', 'b')",
    "schema": "SELECT nspname || ' owner=' || pg_get_userbyid(nspowner) || ' acl=' || "
    "coalesce((SELECT string_agg(a::text, ',' ORDER BY a::text) FROM unnest(nspacl) a), '') "
    "FROM pg_namespace WHERE nspname = 'sidekick'",
    "default_privileges": "SELECT pg_get_userbyid(defaclrole) || ' ' || "
    "defaclobjtype::text || ' ' || "
    "(SELECT string_agg(a::text, ',' ORDER BY a::text) FROM unnest(defaclacl) a) "
    "FROM pg_default_acl WHERE defaclnamespace = 'sidekick'::regnamespace",
    "extensions": "SELECT extname FROM pg_extension",
    "migration_table_acl": "SELECT coalesce((SELECT string_agg(a::text, ',' ORDER BY a::text) "
    "FROM unnest(relacl) a), '') FROM pg_class WHERE oid = 'public._yoyo_migration'::regclass",
}


def _migration_url() -> str:
    return require_test_database_url("SIDEKICK_TEST_MIGRATION_DATABASE_URL")


def _admin_url() -> str:
    url = os.getenv("SIDEKICK_TEST_ADMIN_DATABASE_URL") or _migration_url()
    validate_test_database_url(url, variable="SIDEKICK_TEST_ADMIN_DATABASE_URL")
    return url


def _run(sql: str, params: dict[str, object] | None = None) -> None:
    engine = create_engine(_admin_url())
    try:
        with engine.begin() as connection:
            connection.execute(text(sql), params or {})
    finally:
        engine.dispose()


def _reset_schema() -> None:
    """An empty database: no sidekick schema and no yoyo bookkeeping (extensions stay)."""

    invalidate_migration_head_cache()
    _run("SET LOCAL ROLE sidekick_owner; DROP SCHEMA IF EXISTS sidekick CASCADE")
    for table in ("_yoyo_migration", "_yoyo_log", "_yoyo_version", "yoyo_lock"):
        _run(f"DROP TABLE IF EXISTS public.{table} CASCADE")


def _apply(path: Path) -> None:
    backend = get_backend(_migration_url())
    migrations = read_migrations(str(path))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))


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


def _snapshot() -> dict[str, list[str]]:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return {
                name: sorted(str(value) for value in connection.scalars(text(query)))
                for name, query in SNAPSHOT_QUERIES.items()
            }
    finally:
        engine.dispose()


@pytest.fixture
def rebuilt_schema() -> Iterator[None]:
    """Each test may reset the shared schema; afterwards the head is rebuilt for later tests."""

    database_factory()
    try:
        yield
    finally:
        invalidate_migration_head_cache()
        ensure_migration_chain_head()
        invalidate_migration_head_cache()


# The product name before the rename, assembled so that the old name never appears as a literal.
OLD_NAME = "char" + "lie"

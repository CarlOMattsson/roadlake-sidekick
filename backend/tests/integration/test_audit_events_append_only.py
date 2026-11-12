"""The audit trail, the domain event ledger and the activity projection are append-only for the app
role: it may insert and read them, never change or erase them."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from tests.db import database_factory, require_test_database_url

APPEND_ONLY_TABLES = ("audit_events", "domain_events", "activity_entries")
PRIVILEGES_QUERY = text(
    "SELECT privilege, has_table_privilege('sidekick_app', :relation, privilege) "
    "FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) AS privilege ORDER BY privilege"
)
APPEND_ONLY = {"DELETE": False, "INSERT": True, "SELECT": True, "UPDATE": False}


@pytest.mark.integration
@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_history_tables_are_append_only_for_the_app_role(table: str) -> None:
    database_factory()
    engine = create_engine(require_test_database_url())
    try:
        with engine.connect() as conn:
            rows = conn.execute(PRIVILEGES_QUERY, {"relation": f"sidekick.{table}"})
            assert {row[0]: row[1] for row in rows} == APPEND_ONLY
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
@pytest.mark.parametrize(
    "statement", ["UPDATE sidekick.{table} SET id = id WHERE false", "DELETE FROM sidekick.{table}"]
)
def test_the_app_role_is_refused_update_and_delete_on_history_tables(
    table: str, statement: str
) -> None:
    database_factory()
    engine = create_engine(require_test_database_url())
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT current_user")).scalar_one() == "sidekick_app"
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text(statement.format(table=table)))
    finally:
        engine.dispose()

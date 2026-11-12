"""Runtime-role privileges on the contact tables at the schema head."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from tests.db import database_factory, require_test_database_url


@pytest.mark.integration
def test_runtime_role_dml_grants_and_ddl_denial() -> None:
    # The runtime role (sidekick_app) can read the contact tables but cannot run DDL on them.
    database_factory()
    app_url = require_test_database_url()

    app_engine = create_engine(app_url)

    with app_engine.connect() as conn:
        # Test SELECT works on contacts
        conn.execute(text("SELECT * FROM sidekick.contacts LIMIT 1"))

        ddl_statements = (
            "CREATE TABLE sidekick.forbidden(id integer)",
            "ALTER TABLE sidekick.contacts ADD COLUMN forbidden integer",
            "DROP TABLE sidekick.contacts CASCADE",
            "CREATE SCHEMA forbidden_schema",
            "CREATE EXTENSION IF NOT EXISTS citext",
            "CREATE ROLE forbidden_role",
        )
        for statement in ddl_statements:
            with (
                pytest.raises(
                    ProgrammingError, match=r"permission denied|must be owner|not allowed"
                ),
                conn.begin_nested(),
            ):
                conn.execute(text(statement))

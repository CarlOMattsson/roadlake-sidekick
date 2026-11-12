"""PostgreSQL 18 schema constraints and runtime-role boundaries."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from tests.db import database_factory, require_test_database_url


@pytest.mark.integration
def test_runtime_role_can_use_schema_but_cannot_run_ddl() -> None:
    factory = database_factory()
    with factory() as session:
        assert session.scalar(text("SELECT count(*) FROM sidekick.projects")) == 0
    engine = create_engine(require_test_database_url())
    with pytest.raises(ProgrammingError, match="permission denied"), engine.begin() as connection:
        connection.execute(text("CREATE TABLE sidekick.forbidden(id integer)"))


@pytest.mark.integration
def test_runtime_role_has_no_database_or_role_administration() -> None:
    factory = database_factory()
    with pytest.raises(ProgrammingError), factory.begin() as session:
        session.execute(text("CREATE ROLE forbidden_role"))

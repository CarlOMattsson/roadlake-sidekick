"""The production role check against real PostgreSQL roles (app, migrator/owner, superuser)."""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from sidekick.shared.persistence import create_session_factory
from sidekick.shared.persistence.runtime_role import UnsafeRuntimeRoleError
from tests.db import database_factory, require_test_database_url


def _psycopg(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.mark.integration
def test_the_application_role_passes_the_check() -> None:
    database_factory()  # a safe, migrated test database
    factory = create_session_factory(require_test_database_url(), require_unprivileged_role=True)
    with factory() as session:
        assert session.connection() is not None


@pytest.mark.integration
def test_the_migration_role_is_refused_as_a_runtime_role() -> None:
    database_factory()
    url = os.getenv("SIDEKICK_TEST_MIGRATION_DATABASE_URL")
    if not url:
        pytest.skip("SIDEKICK_TEST_MIGRATION_DATABASE_URL is not configured")
    with pytest.raises(UnsafeRuntimeRoleError, match="refusing to start in production"):
        create_session_factory(_psycopg(url), require_unprivileged_role=True)


@pytest.mark.integration
def test_a_superuser_is_refused_as_a_runtime_role() -> None:
    database_factory()
    url = os.getenv("SIDEKICK_TEST_ADMIN_DATABASE_URL")
    if not url:
        pytest.skip("SIDEKICK_TEST_ADMIN_DATABASE_URL is not configured")
    with pytest.raises(UnsafeRuntimeRoleError, match="superuser"):
        create_session_factory(_psycopg(url), require_unprivileged_role=True)


_PASSWORD = "role-check-throwaway"


@contextmanager
def _throwaway_login_role(
    *, attributes: str = "", owns_table: bool = False, via_group: bool = False
) -> Iterator[str]:
    """Create a login role (optionally owning a table), yield its URL, drop it afterwards."""

    admin_url = os.getenv("SIDEKICK_TEST_ADMIN_DATABASE_URL")
    if not admin_url:
        pytest.skip("SIDEKICK_TEST_ADMIN_DATABASE_URL is not configured")
    suffix = uuid.uuid4().hex[:10]
    role, group, table = (
        f"rolecheck_{suffix}",
        f"rolecheck_grp_{suffix}",
        f"rolecheck_probe_{suffix}",
    )
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(
                text(f"CREATE ROLE {role} LOGIN NOINHERIT PASSWORD '{_PASSWORD}' {attributes}")
            )
            if via_group:
                connection.execute(text(f"CREATE ROLE {group} NOLOGIN"))
                connection.execute(text(f"GRANT {group} TO {role}"))
            if owns_table:
                connection.execute(text(f"CREATE TABLE sidekick.{table} (id integer)"))
                owner = group if via_group else role
                connection.execute(text(f"ALTER TABLE sidekick.{table} OWNER TO {owner}"))
        yield (
            make_url(admin_url)
            .set(drivername="postgresql+psycopg", username=role, password=_PASSWORD)
            .render_as_string(hide_password=False)
        )
    finally:
        with engine.connect() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS sidekick.{table}"))
            connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
            connection.execute(text(f"DROP ROLE IF EXISTS {group}"))
        engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"owns_table": True}, "owns objects in the application schema"),
        ({"owns_table": True, "via_group": True}, "owns objects in the application schema"),
        ({"attributes": "BYPASSRLS"}, "bypasses row-level security"),
        ({"attributes": "CREATEROLE"}, "can create roles"),
        ({"attributes": "CREATEDB"}, "can create databases"),
    ],
)
def test_a_role_with_extra_privileges_is_refused(kwargs: dict[str, object], message: str) -> None:
    database_factory()
    with (
        _throwaway_login_role(**kwargs) as url,  # type: ignore[arg-type]
        pytest.raises(UnsafeRuntimeRoleError, match=message) as caught,
    ):
        create_session_factory(url, require_unprivileged_role=True)
    assert "rolecheck_" not in str(caught.value)
    assert _PASSWORD not in str(caught.value)


@pytest.mark.integration
def test_a_plain_login_role_is_not_refused_for_the_new_rules() -> None:
    """A role without any of the listed privileges does not trip the owner/BYPASSRLS rules."""

    database_factory()
    with _throwaway_login_role() as url:
        try:
            create_session_factory(url, require_unprivileged_role=True)
        except UnsafeRuntimeRoleError as error:
            assert "refusing to start" not in str(error)

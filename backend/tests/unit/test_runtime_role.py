"""Production start-up hardening: explicit database URL, no docs routes, a plain runtime role."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_app
from sidekick.shared.config import Settings
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.persistence.runtime_role import (
    RuntimeRoleFacts,
    UnsafeRuntimeRoleError,
    require_unprivileged_runtime_role,
    runtime_role_violation,
)

_SECRET = "secret-for-the-production-tests-1234567"
_PEPPER = "pepper-for-the-production-tests-1234567"
_URL = "postgresql+psycopg://sidekick_app:not-a-real-password@db.invalid:5432/sidekick"


@pytest.fixture(autouse=True)
def _no_ambient_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIDEKICK_DATABASE_URL", raising=False)


def production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "production",
        "cursor_signing_secret": _SECRET,
        "token_pepper": _PEPPER,
        "database_url": _URL,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_refuses_to_start_without_an_explicit_database_url() -> None:
    with pytest.raises(ValidationError, match="SIDEKICK_DATABASE_URL must be set explicitly"):
        Settings(
            _env_file=None,
            environment="production",
            cursor_signing_secret=_SECRET,
            token_pepper=_PEPPER,
        )


def test_production_takes_the_database_url_from_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_DATABASE_URL", _URL)
    settings = Settings(
        _env_file=None,
        environment="production",
        cursor_signing_secret=_SECRET,
        token_pepper=_PEPPER,
    )
    assert settings.database_url == _URL


def test_the_missing_database_url_error_does_not_echo_other_settings() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            environment="production",
            cursor_signing_secret=_SECRET,
            token_pepper=_PEPPER,
        )
    assert _SECRET not in str(caught.value)
    assert _PEPPER not in str(caught.value)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_development_and_test_keep_the_default_database_url(environment: str) -> None:
    settings = Settings(_env_file=None, environment=environment)  # type: ignore[arg-type]
    assert settings.database_url.startswith("postgresql+psycopg://sidekick_app:")


@pytest.mark.parametrize(
    "path", ["/api/docs", "/api/openapi.json", "/redoc", "/docs", "/openapi.json"]
)
def test_production_serves_no_interactive_docs_or_schema(path: str) -> None:
    app = create_app(production_settings(), sessionmaker())
    assert TestClient(app).get(path).status_code == 404


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
def test_development_still_serves_the_docs(path: str) -> None:
    app = create_app(Settings(_env_file=None, environment="development"), sessionmaker())
    assert TestClient(app).get(path).status_code == 200


def test_the_schema_is_still_built_in_process_in_production() -> None:
    app = create_app(production_settings(), sessionmaker())
    assert "paths" in app.openapi()


def test_a_superuser_an_owner_and_a_schema_creator_are_each_refused() -> None:
    assert runtime_role_violation(RuntimeRoleFacts(True, False, False)) == (
        "the database role is a superuser"
    )
    assert runtime_role_violation(RuntimeRoleFacts(False, True, False)) == (
        "the database role owns the application schema"
    )
    assert runtime_role_violation(RuntimeRoleFacts(False, False, True)) == (
        "the database role can create objects in the application schema"
    )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("owns_schema_objects", "the database role owns objects in the application schema"),
        ("bypasses_row_level_security", "the database role bypasses row-level security"),
        ("can_create_roles", "the database role can create roles"),
        ("can_create_databases", "the database role can create databases"),
    ],
)
def test_each_extra_privilege_is_refused_by_name(field: str, message: str) -> None:
    facts = RuntimeRoleFacts(False, False, False, **{field: True})
    assert runtime_role_violation(facts) == message


def test_a_plain_data_role_is_accepted() -> None:
    assert runtime_role_violation(RuntimeRoleFacts(False, False, False)) is None


class _FakeSession:
    def __init__(self, row: tuple[bool, ...] | None, error: Exception | None) -> None:
        self._row = row
        self._error = error

    def execute(self, *_args: Any, **_kwargs: Any) -> "_FakeSession":
        if self._error is not None:
            raise self._error
        return self

    def one_or_none(self) -> tuple[bool, ...] | None:
        return self._row


def _factory(
    row: tuple[bool, ...] | None = None, error: Exception | None = None
) -> sessionmaker[Session]:
    @contextmanager
    def session() -> Iterator[_FakeSession]:
        yield _FakeSession(row, error)

    return session  # type: ignore[return-value]


def test_the_check_passes_for_a_plain_role() -> None:
    require_unprivileged_runtime_role(_factory((False,) * 7))


@pytest.mark.parametrize("index", range(7))
def test_the_check_refuses_a_privileged_role(index: int) -> None:
    row = tuple(position == index for position in range(7))
    with pytest.raises(UnsafeRuntimeRoleError, match="refusing to start in production"):
        require_unprivileged_runtime_role(_factory(row))


def test_the_check_refuses_when_the_schema_is_missing() -> None:
    with pytest.raises(UnsafeRuntimeRoleError, match="schema is missing"):
        require_unprivileged_runtime_role(_factory(None))


def test_the_check_refusal_leaks_no_driver_detail() -> None:
    driver_error = RuntimeError(f"could not connect to {_URL}")
    with pytest.raises(UnsafeRuntimeRoleError) as caught:
        require_unprivileged_runtime_role(_factory(error=driver_error))
    assert "not-a-real-password" not in str(caught.value)
    assert "db.invalid" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_an_unreachable_database_refuses_start_with_a_content_free_error() -> None:
    url = "postgresql+psycopg://secret_user:not-a-real-password@127.0.0.1:1/sidekick"
    with pytest.raises(UnsafeRuntimeRoleError) as caught:
        create_session_factory(url, require_unprivileged_role=True)
    message = str(caught.value)
    assert "not-a-real-password" not in message
    assert "secret_user" not in message
    assert "127.0.0.1" not in message

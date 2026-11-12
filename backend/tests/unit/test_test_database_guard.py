"""The test-database URL validation: pure string checks, no connection is ever opened."""

import pytest
from sqlalchemy.engine import URL

from tests import db as test_db
from tests.db_guard import (
    EXTRA_PORTS_VARIABLE,
    RESERVED_PORTS,
    RESERVED_PORTS_VARIABLE,
    _guard_connection,
    allowed_test_ports,
    reserved_ports,
    validate_test_database_url,
)

APP = "postgresql+psycopg://sidekick_app:sidekick_app@127.0.0.1:55433/sidekick_test"
ADMIN = "postgresql://postgres:postgres@127.0.0.1:55433/sidekick_test"


@pytest.fixture(autouse=True)
def _no_extra_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EXTRA_PORTS_VARIABLE, raising=False)


@pytest.mark.parametrize(
    "url",
    [
        APP,
        ADMIN,
        APP.replace("sidekick_test", "sidekick_test_3"),
        APP.replace("sidekick_test", "sidekick_test_3_w7"),
        ADMIN.replace("sidekick_test", "sidekick_test_w0"),
        APP.replace("127.0.0.1", "localhost"),
        APP.replace("127.0.0.1", "[::1]"),
    ],
)
def test_the_test_container_port_is_accepted(url: str) -> None:
    assert validate_test_database_url(url).port == 55433


@pytest.mark.parametrize("port", sorted(RESERVED_PORTS))
def test_protected_ports_are_refused_for_every_role(port: int) -> None:
    for url in (APP, ADMIN):
        with pytest.raises(RuntimeError, match="protected database port"):
            validate_test_database_url(url.replace("55433", str(port)))


@pytest.mark.parametrize("port", sorted(RESERVED_PORTS))
def test_protected_ports_stay_refused_even_when_listed_as_extra(
    monkeypatch: pytest.MonkeyPatch, port: int
) -> None:
    monkeypatch.setenv(EXTRA_PORTS_VARIABLE, f"55440,{port}")
    with pytest.raises(RuntimeError, match="protected port"):
        allowed_test_ports()
    with pytest.raises(RuntimeError, match="protected database port"):
        validate_test_database_url(APP.replace("55433", str(port)))


@pytest.mark.parametrize("port", ["5432", "6543", "65432"])
def test_a_port_outside_the_allowlist_is_refused(port: str) -> None:
    with pytest.raises(RuntimeError, match="allowed ports"):
        validate_test_database_url(APP.replace("55433", port))


def test_admin_url_with_the_wrong_port_or_name_is_refused() -> None:
    with pytest.raises(RuntimeError, match="protected database port"):
        validate_test_database_url(ADMIN.replace("55433", "55432"), variable="admin")
    with pytest.raises(RuntimeError, match="sidekick_test"):
        validate_test_database_url(ADMIN.replace("sidekick_test", "sidekick"), variable="admin")
    with pytest.raises(RuntimeError, match="sidekick_test"):
        validate_test_database_url(ADMIN.replace("sidekick_test", "postgres"), variable="admin")


def test_a_missing_port_is_refused_because_the_driver_default_is_5432() -> None:
    with pytest.raises(RuntimeError, match="explicit port"):
        validate_test_database_url(APP.replace(":55433", ""))


def test_default_5432_needs_an_explicit_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    url = APP.replace("55433", "5432")
    with pytest.raises(RuntimeError, match="allowed ports"):
        validate_test_database_url(url)
    monkeypatch.setenv(EXTRA_PORTS_VARIABLE, "5432")
    assert validate_test_database_url(url).port == 5432


def test_an_extra_port_is_allowed_only_when_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    dev_url = APP.replace("55433", "55440")
    with pytest.raises(RuntimeError, match="allowed ports"):
        validate_test_database_url(dev_url)
    monkeypatch.setenv(EXTRA_PORTS_VARIABLE, " 55440 , 55441,")
    assert allowed_test_ports() == frozenset({55433, 55440, 55441})
    assert validate_test_database_url(dev_url).port == 55440


def test_the_extra_variable_cannot_remove_the_default_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EXTRA_PORTS_VARIABLE, "55440")
    assert 55433 in allowed_test_ports()


@pytest.mark.parametrize("value", ["abc", "0", "70000", "-1", "55433;55440", "5543.3"])
def test_a_malformed_extra_port_list_fails_closed(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(EXTRA_PORTS_VARIABLE, value)
    with pytest.raises(RuntimeError, match="comma-separated TCP ports"):
        validate_test_database_url(APP)


@pytest.mark.parametrize("host", ["10.0.0.5", "db.example.com", "postgres", "db", "0.0.0.0"])
def test_a_non_loopback_host_is_refused(host: str) -> None:
    with pytest.raises(RuntimeError, match="loopback"):
        validate_test_database_url(APP.replace("127.0.0.1", host))


@pytest.mark.parametrize("query", ["?port=55432", "?host=10.0.0.5", "?options=-c%20x%3Dy"])
def test_query_parameters_cannot_override_the_checked_target(query: str) -> None:
    with pytest.raises(RuntimeError, match="query parameters"):
        validate_test_database_url(APP + query)


def test_assert_safe_test_database_applies_the_same_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_ENVIRONMENT", "test")
    monkeypatch.setenv("SIDEKICK_TEST_ADMIN_DATABASE_URL", ADMIN.replace("55433", "55436"))
    with pytest.raises(RuntimeError, match="protected database port"):
        test_db.assert_safe_test_database(
            ADMIN.replace("55433", "55436"), variable="SIDEKICK_TEST_ADMIN_DATABASE_URL"
        )


def test_session_factory_refuses_before_building_an_engine() -> None:
    before = len(test_db._TEST_ENGINES)
    with pytest.raises(RuntimeError, match="protected database port"):
        test_db.create_test_session_factory(APP.replace("55433", "55432"))
    assert len(test_db._TEST_ENGINES) == before


def test_cleanup_factory_refuses_an_unsafe_admin_url() -> None:
    with pytest.raises(RuntimeError, match="protected database port"):
        test_db._cleanup_factory_for(ADMIN.replace("55433", "55434"))
    assert ADMIN.replace("55433", "55434") not in test_db._CLEANUP_FACTORIES


def test_the_connection_hook_refuses_a_driver_target_without_port() -> None:
    dialect = URL.create("postgresql+psycopg").get_dialect()()
    params = {"host": "127.0.0.1", "dbname": "sidekick_test"}
    with pytest.raises(RuntimeError, match="explicit port"):
        _guard_connection(dialect, None, (), params)
    with pytest.raises(RuntimeError, match="protected database port"):
        _guard_connection(dialect, None, (), {**params, "port": 55432})
    _guard_connection(dialect, None, (), {**params, "port": "55433"})


def test_default_reserved_ports_need_no_configuration() -> None:
    assert reserved_ports({}) == RESERVED_PORTS == {55432, 55434, 55436}


def test_reserved_ports_can_only_be_extended(monkeypatch: pytest.MonkeyPatch) -> None:
    assert reserved_ports({RESERVED_PORTS_VARIABLE: " 9000, ,9001 "}) == RESERVED_PORTS | {
        9000,
        9001,
    }
    monkeypatch.setenv(RESERVED_PORTS_VARIABLE, "55440")
    with pytest.raises(RuntimeError, match="protected database port"):
        validate_test_database_url(APP.replace("55433", "55440"))
    monkeypatch.setenv(EXTRA_PORTS_VARIABLE, "55440")
    with pytest.raises(RuntimeError, match="protected port"):
        allowed_test_ports()


@pytest.mark.parametrize("value", ["abc", "0", "70000", "55436,x", "9000\n9001", "9000\n"])
def test_malformed_reserved_ports_are_refused(value: str) -> None:
    with pytest.raises(RuntimeError, match=RESERVED_PORTS_VARIABLE):
        reserved_ports({RESERVED_PORTS_VARIABLE: value})


def test_reserved_ports_are_normalised_to_decimal() -> None:
    assert 30000 in reserved_ports({RESERVED_PORTS_VARIABLE: "030000"})

"""The connection-time guard: what a driver would really dial, checked before it dials.

Every negative case here must raise before any socket is opened. They use a throwaway role and
password, so that even a regression in the guard could not authenticate anywhere. The positive
cases run against stub drivers that record the call instead of connecting.
"""

import asyncio
import socket
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy import create_engine
from yoyo import get_backend

from tests import db_guard
from tests.db_guard import (
    LIBPQ_ENVIRONMENT,
    child_process_environment,
    guard_asyncpg,
    guard_psycopg,
    strip_libpq_environment,
    validate_effective_conninfo,
)

GOOD = {"host": "127.0.0.1", "port": 55433, "dbname": "sidekick_test"}
PROBE = "user=guard_probe password=x connect_timeout=1"
PROTECTED = "postgresql://guard_probe:x@127.0.0.1:55432/sidekick_test"


class OutboundAttempted(Exception):
    """Raised by the stub below when something tries to dial."""


@pytest.fixture(autouse=True)
def outbound_attempts(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Forbid every outbound connection in this module, at the lowest level there is.

    Python sockets are blocked, and so is the entry into libpq (`PGconn.connect`/`connect_start`),
    the point below the guard where a driver would really dial. The
    attempt is recorded and an exception is raised. The negative tests therefore prove that the
    guard refuses *before* this stub is reached, and a regression in the guard fails the test
    here without a socket having been opened. A test that deliberately lets a target through
    clears the list itself.
    """

    attempts: list[str] = []

    def blocked(name: str) -> Callable[..., Any]:
        def refuse(*args: Any, **kwargs: Any) -> Any:
            attempts.append(name)
            raise OutboundAttempted(name)

        return refuse

    monkeypatch.setattr(socket.socket, "connect", blocked("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", blocked("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", blocked("socket.create_connection"))
    for key in list(db_guard._LOWEST_DIALERS):
        monkeypatch.setitem(db_guard._LOWEST_DIALERS, key, blocked(key))
    yield attempts
    assert attempts == [], "the guard let a target through to the dial"


@pytest.fixture(autouse=True)
def _clean_libpq_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in LIBPQ_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def test_the_stub_records_and_stops_a_target_the_guard_admits(
    outbound_attempts: list[str],
) -> None:
    """The counterpart of every refusal below: an allowed target does reach the (stubbed) dial."""

    good = "host=127.0.0.1 port=55433 dbname=sidekick_test user=guard_probe password=x"
    with pytest.raises(OutboundAttempted):
        psycopg.connect(good)
    with pytest.raises(OutboundAttempted):
        asyncio.run(psycopg.AsyncConnection.connect(good))
    with pytest.raises(OutboundAttempted):
        create_engine("postgresql+psycopg://guard_probe:x@127.0.0.1:55433/sidekick_test").connect()
    with pytest.raises(OutboundAttempted):
        psycopg.pq.PGconn.connect(good.encode())
    with pytest.raises(OutboundAttempted):
        get_backend("postgresql+psycopg://guard_probe:x@127.0.0.1:55433/sidekick_test")
    with pytest.raises(OutboundAttempted):
        socket.create_connection(("127.0.0.1", 1))
    with pytest.raises(OutboundAttempted):
        socket.socket().connect(("127.0.0.1", 1))
    assert outbound_attempts == [
        "psycopg.generators.connect",
        "psycopg.generators.connect",
        "psycopg.generators.connect",
        "psycopg.pq.PGconn.connect",
        "psycopg.generators.connect",
        "socket.create_connection",
        "socket.connect",
    ]
    outbound_attempts.clear()


@pytest.mark.parametrize(
    "conninfo",
    [
        b"host=127.0.0.1 port=55432 dbname=sidekick_test",
        b"host=127.0.0.1 port=55433 hostaddr=10.0.0.5 dbname=sidekick_test",
        b"host=127.0.0.1 port=55432 hostaddr=127.0.0.1 dbname=sidekick_test",
        b"host=127.0.0.1 dbname=sidekick_test",
        b"host=10.0.0.5 port=55433 dbname=sidekick_test",
        b"service=personal",
        b"",
    ],
)
def test_the_lower_entry_points_refuse_before_dialing(conninfo: bytes) -> None:
    with pytest.raises(RuntimeError):
        psycopg.pq.PGconn.connect_start(conninfo)
    with pytest.raises(RuntimeError):
        psycopg.pq.PGconn.connect(conninfo)
    with pytest.raises(RuntimeError):
        psycopg.generators.connect(conninfo.decode())


def test_the_lower_entry_points_refuse_a_libpq_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGHOSTADDR", "10.0.0.5")
    good = b"host=127.0.0.1 port=55433 dbname=sidekick_test"
    with pytest.raises(RuntimeError, match="PGHOSTADDR"):
        psycopg.pq.PGconn.connect_start(good)


def test_the_session_installed_the_driver_wrappers() -> None:
    marker = db_guard._GUARD_MARKER
    assert getattr(psycopg.Connection.__dict__["connect"].__func__, marker, False)
    assert getattr(psycopg.AsyncConnection.__dict__["connect"].__func__, marker, False)
    assert getattr(psycopg.connect.__func__, marker, False)


def test_installing_twice_does_not_wrap_twice() -> None:
    before = psycopg.Connection.__dict__["connect"].__func__
    db_guard.install_connection_guard()
    assert psycopg.Connection.__dict__["connect"].__func__ is before


def test_session_start_removed_the_libpq_variables_from_the_process() -> None:
    import os

    assert not set(LIBPQ_ENVIRONMENT) & set(os.environ)


def test_strip_libpq_environment_removes_every_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for name in LIBPQ_ENVIRONMENT:
        monkeypatch.setenv(name, "x")
    strip_libpq_environment()
    assert not set(LIBPQ_ENVIRONMENT) & set(os.environ)


# --- effective connection parameters ------------------------------------------------------


def test_good_parameters_are_accepted() -> None:
    assert validate_effective_conninfo(GOOD).port == 55433
    assert validate_effective_conninfo({**GOOD, "hostaddr": None, "user": "u"}).port == 55433


@pytest.mark.parametrize(
    "extra",
    [
        {"hostaddr": "127.0.0.1"},
        {"hostaddr": "10.0.0.5"},
        {"service": "personal"},
        {"servicefile": "/tmp/pg_service.conf"},
        {"passfile": "/tmp/pgpass"},
        {"options": "-c search_path=x"},
        {"load_balance_hosts": "random"},
        {"conninfo": "host=10.0.0.5"},
        {"dsn": "host=10.0.0.5"},
    ],
)
def test_destination_changing_parameters_are_refused(extra: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="destination-changing"):
        validate_effective_conninfo({**GOOD, **extra})


@pytest.mark.parametrize("name", sorted(LIBPQ_ENVIRONMENT))
def test_libpq_environment_variables_set_after_import_are_refused(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "1")
    with pytest.raises(RuntimeError, match=name):
        validate_effective_conninfo(GOOD)


@pytest.mark.parametrize(
    "params",
    [
        {**GOOD, "port": 55432},
        {**GOOD, "port": "55436"},
        {**GOOD, "port": None},
        {**GOOD, "port": "55433,55432"},
        {**GOOD, "host": "127.0.0.1,10.0.0.5"},
        {**GOOD, "host": "/var/run/postgresql"},
        {**GOOD, "host": None},
        {**GOOD, "dbname": "sidekick"},
        {**GOOD, "dbname": None},
    ],
)
def test_wrong_host_port_or_database_is_refused(params: dict[str, Any]) -> None:
    with pytest.raises(RuntimeError):
        validate_effective_conninfo(params)


# --- the real connection paths, each aborted by the guard ------------------------------------


def test_sqlalchemy_connect_args_hostaddr_is_refused() -> None:
    engine = create_engine(
        "postgresql+psycopg://guard_probe:x@127.0.0.1:55433/sidekick_test",
        connect_args={"hostaddr": "127.0.0.1"},
    )
    with pytest.raises(RuntimeError, match="destination-changing"), engine.connect():
        pass
    engine.dispose()


def test_sqlalchemy_environment_set_after_engine_creation_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("postgresql+psycopg://guard_probe:x@127.0.0.1:55433/sidekick_test")
    monkeypatch.setenv("PGHOST", "10.0.0.5")
    with pytest.raises(RuntimeError, match="PGHOST"), engine.connect():
        pass
    engine.dispose()


def test_direct_psycopg_connect_to_a_protected_port_is_refused() -> None:
    with pytest.raises(RuntimeError, match="protected database port"):
        psycopg.connect(PROTECTED)
    with pytest.raises(RuntimeError, match="protected database port"):
        psycopg.connect(host="127.0.0.1", port=55432, dbname="sidekick_test", user="guard_probe")
    with pytest.raises(RuntimeError, match="protected database port"):
        psycopg.Connection.connect(f"host=127.0.0.1 port=55434 dbname=sidekick_test {PROBE}")


def test_direct_psycopg_connect_with_hostaddr_in_the_conninfo_string_is_refused() -> None:
    conninfo = f"host=127.0.0.1 hostaddr=127.0.0.1 port=55433 dbname=sidekick_test {PROBE}"
    with pytest.raises(RuntimeError, match="destination-changing"):
        psycopg.connect(conninfo)
    with pytest.raises(RuntimeError, match="destination-changing"):
        psycopg.connect("postgresql://guard_probe:x@127.0.0.1:55433/sidekick_test?service=x")


def test_direct_psycopg_connect_without_a_port_is_refused() -> None:
    with pytest.raises(RuntimeError, match="explicit port"):
        psycopg.connect(host="127.0.0.1", dbname="sidekick_test", user="guard_probe")


def test_direct_psycopg_connect_with_environment_set_after_import_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGSERVICE", "personal")
    with pytest.raises(RuntimeError, match="PGSERVICE"):
        psycopg.connect(host="127.0.0.1", port=55433, dbname="sidekick_test", user="guard_probe")


def test_async_psycopg_connect_to_a_protected_port_is_refused() -> None:
    with pytest.raises(RuntimeError, match="protected database port"):
        asyncio.run(psycopg.AsyncConnection.connect(PROTECTED))


def test_creator_that_calls_psycopg_is_refused() -> None:
    def creator() -> Any:
        return psycopg.connect(PROTECTED)

    engine = create_engine("postgresql+psycopg://", creator=creator)
    with pytest.raises(RuntimeError, match="protected database port"), engine.connect():
        pass
    engine.dispose()


def test_the_yoyo_path_is_refused() -> None:
    with pytest.raises(RuntimeError, match="protected database port"):
        get_backend(PROTECTED.replace("postgresql://", "postgresql+psycopg://"))


# --- the child process environment ------------------------------------------------------------


def test_child_environment_drops_the_libpq_variables() -> None:
    base = {"PATH": "/usr/bin", "PGHOST": "10.0.0.5", "PGSERVICE": "personal", "KEEP": "1"}
    assert child_process_environment(base) == {"PATH": "/usr/bin", "KEEP": "1"}


def test_child_environment_validates_the_database_url() -> None:
    good = "postgresql+psycopg://sidekick_app:x@127.0.0.1:55433/sidekick_test"
    assert (
        child_process_environment({"SIDEKICK_DATABASE_URL": good})["SIDEKICK_DATABASE_URL"] == good
    )
    for bad in (good.replace("55433", "55432"), good.replace("sidekick_test", "sidekick")):
        with pytest.raises(RuntimeError):
            child_process_environment({"SIDEKICK_DATABASE_URL": bad})


def test_the_stdio_child_environment_is_clean_even_when_the_parent_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.support.mcp_stdio import _environment

    monkeypatch.setenv("PGHOST", "10.0.0.5")
    environment = _environment(None)
    assert not set(LIBPQ_ENVIRONMENT) & set(environment)
    db_guard.validate_test_database_url(environment["SIDEKICK_DATABASE_URL"])


GOOD_URL = "postgresql+psycopg://sidekick_app:x@127.0.0.1:55433/sidekick_test"


def test_validate_child_env_file_checks_the_database_url_and_libpq_names(
    tmp_path: Path,
) -> None:
    ok = tmp_path / "ok.env"
    ok.write_text(
        f"# comment\nSIDEKICK_ENVIRONMENT=test\nexport SIDEKICK_DATABASE_URL='{GOOD_URL}'\n"
    )
    assert db_guard.validate_child_env_file(ok) == GOOD_URL
    assert db_guard.validate_child_env_file(tmp_path / "missing.env") is None
    for line in (
        f"SIDEKICK_DATABASE_URL={GOOD_URL.replace('55433', '55432')}",
        f"SIDEKICK_DATABASE_URL={GOOD_URL.replace('55433', '1')}",
        "PGHOST=10.0.0.5",
        "PGSERVICE=personal",
    ):
        bad = tmp_path / "bad.env"
        bad.write_text(line + "\n")
        with pytest.raises(RuntimeError):
            db_guard.validate_child_env_file(bad)


def test_the_stdio_runner_refuses_an_unsafe_child_before_spawning_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from tests.support.mcp_stdio import _run

    spawned: list[Any] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: spawned.append(a))
    env_file = tmp_path / "sidekick.env"
    env_file.write_text(f"SIDEKICK_DATABASE_URL={GOOD_URL.replace('55433', '55432')}\n")
    with pytest.raises(RuntimeError, match="protected database port"):
        _run({"PATH": "/usr/bin"}, tmp_path, "--env-file", str(env_file))
    with pytest.raises(RuntimeError, match="protected database port"):
        _run({"SIDEKICK_DATABASE_URL": GOOD_URL.replace("55433", "55436")}, tmp_path)
    with pytest.raises(RuntimeError, match="without an explicit database URL"):
        _run({"PATH": "/usr/bin"}, tmp_path)
    (tmp_path / ".env").write_text("SIDEKICK_DATABASE_URL=x\n")
    with pytest.raises(RuntimeError, match=r"\.env"):
        _run({"SIDEKICK_DATABASE_URL": GOOD_URL}, tmp_path)
    assert spawned == []


# --- positive paths, against stub drivers that never connect ---------------------------------


def _stub_psycopg() -> tuple[types.SimpleNamespace, list[str]]:
    calls: list[str] = []

    class Connection:
        @classmethod
        def connect(cls, conninfo: str = "", **kwargs: Any) -> str:
            calls.append("sync")
            return "connection"

    class AsyncConnection:
        @classmethod
        async def connect(cls, conninfo: str = "", **kwargs: Any) -> str:
            calls.append("async")
            return "connection"

    return types.SimpleNamespace(Connection=Connection, AsyncConnection=AsyncConnection), calls


def test_psycopg_wrapper_passes_a_good_target_through_and_stops_a_bad_one() -> None:
    module, calls = _stub_psycopg()
    guard_psycopg(module)
    assert module.Connection.connect("host=127.0.0.1 port=55433 dbname=sidekick_test") == (
        "connection"
    )
    assert module.connect(host="127.0.0.1", port=55433, dbname="sidekick_test_3") == "connection"
    assert asyncio.run(
        module.AsyncConnection.connect("host=127.0.0.1 port=55433 dbname=sidekick_test")
    ) == ("connection")
    assert calls == ["sync", "sync", "async"]
    with pytest.raises(RuntimeError):
        module.connect("host=127.0.0.1 port=55432 dbname=sidekick_test")
    with pytest.raises(RuntimeError):
        asyncio.run(module.AsyncConnection.connect("host=127.0.0.1 hostaddr=1.1.1.1 port=55433"))
    assert calls == ["sync", "sync", "async"]


def test_asyncpg_wrapper_passes_a_good_target_through_and_stops_a_bad_one() -> None:
    calls: list[Any] = []

    async def connect(dsn: str | None = None, **kwargs: Any) -> str:
        calls.append(dsn)
        return "connection"

    module = types.SimpleNamespace(connect=connect)
    guard_asyncpg(module)
    good = "postgresql://u:p@127.0.0.1:55433/sidekick_test"
    assert asyncio.run(module.connect(good)) == "connection"
    assert asyncio.run(module.connect(host="127.0.0.1", port=55433, database="sidekick_test"))
    for bad in (
        good.replace("55433", "55432"),
        good + "?hostaddr=10.0.0.5",
        good.replace("sidekick_test", "sidekick"),
    ):
        with pytest.raises(RuntimeError):
            asyncio.run(module.connect(bad))
    with pytest.raises(RuntimeError):
        asyncio.run(module.connect(host="127.0.0.1", port=55436, database="sidekick_test"))
    assert calls == [good, None]

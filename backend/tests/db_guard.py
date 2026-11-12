"""The one place that decides whether a database URL may be used by the test suite.

Every URL the suite connects with (the application URL, the migrator URL, the admin URL that
runs `DELETE`/`DROP SCHEMA`, and the per-xdist-worker rewrites of all three) goes through
`validate_test_database_url` before anything is connected. The checks are pure string checks:
this module opens no connection and imports no driver.

A URL is accepted only when all of these hold:

* the host is a loopback address,
* the database name is `sidekick_test`, `sidekick_test_<slot>` or a per-worker variant of those,
* the port is written in the URL and is on the allowlist (the test container's 55433, which CI
  also uses, plus ports added through `SIDEKICK_TEST_EXTRA_ALLOWED_PORTS`),
* the port is not one of the reserved ports of non-test databases, whatever the allowlist says,
* the URL carries no query string, so `?port=` or `?host=` cannot override what was checked.

The URL check alone is not enough, because libpq decides the real destination later, from
parameters and environment variables the URL never mentioned (`hostaddr`, `service`, `PGHOST`,
...). The second half of this module therefore validates the *effective* connection parameters
at the driver boundary (`psycopg`, `asyncpg` and SQLAlchemy's `do_connect`), which
also covers `creator=`, a hand-made pool and yoyo (through psycopg 3), and it strips the
ambient libpq variables.
"""

import functools
import importlib
import importlib.util
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from sqlalchemy import event
from sqlalchemy.engine import URL, Engine, make_url

SAFE_TEST_DATABASE_NAME = re.compile(r"sidekick_test(_[1-9][0-9]?)?(_w[0-9]{1,2})?")

#: Loopback only. A compose service name such as `db` resolves to whatever the network says.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: The test container (`deploy/compose.test.yaml`, tools/test-db-pool.sh). CI publishes its
#: PostgreSQL service on the same port (`.github/workflows/ci.yml`).
DEFAULT_TEST_PORTS = frozenset({55433})

#: A comma-separated list of further test ports. It can only add to the allowlist; it cannot
#: remove a port from the reserved ports.
EXTRA_PORTS_VARIABLE = "SIDEKICK_TEST_EXTRA_ALLOWED_PORTS"

#: Names a comma-separated list of further ports of instances that tests must never touch. It can
#: only add to `RESERVED_PORTS`, never remove from it.
RESERVED_PORTS_VARIABLE = "SIDEKICK_RESERVED_PORTS"

#: Default ports of instances that tests must never touch (non-test PostgreSQL databases that
#: may run next to the test container). Never reachable from a test, not even if
#: `EXTRA_PORTS_VARIABLE` lists them.
RESERVED_PORTS = frozenset({55432, 55434, 55436})


def reserved_ports(environ: Mapping[str, str] | None = None) -> frozenset[int]:
    """`RESERVED_PORTS` plus whatever `SIDEKICK_RESERVED_PORTS` explicitly adds."""

    source = os.environ if environ is None else environ
    ports = set(RESERVED_PORTS)
    value = source.get(RESERVED_PORTS_VARIABLE) or ""
    if not re.fullmatch(r"[0-9, ]*", value):
        raise RuntimeError(f"{RESERVED_PORTS_VARIABLE} must be comma-separated TCP ports")
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        port = int(item)
        if not 1 <= port <= 65535:
            raise RuntimeError(f"{RESERVED_PORTS_VARIABLE} must be comma-separated TCP ports")
        ports.add(port)
    return frozenset(ports)


def allowed_test_ports(environ: Mapping[str, str] | None = None) -> frozenset[int]:
    """The default test port plus whatever `SIDEKICK_TEST_EXTRA_ALLOWED_PORTS` explicitly adds."""

    source = os.environ if environ is None else environ
    ports = set(DEFAULT_TEST_PORTS)
    for raw in (source.get(EXTRA_PORTS_VARIABLE) or "").split(","):
        item = raw.strip()
        if not item:
            continue
        if not item.isascii() or not item.isdigit() or not 1 <= int(item) <= 65535:
            raise RuntimeError(f"{EXTRA_PORTS_VARIABLE} must be comma-separated TCP ports")
        port = int(item)
        if port in reserved_ports(source):
            raise RuntimeError(f"{EXTRA_PORTS_VARIABLE} may not list protected port {port}")
        ports.add(port)
    return frozenset(ports)


def validate_test_database_url(
    url: str | URL, *, variable: str = "SIDEKICK_TEST_DATABASE_URL"
) -> URL:
    """Return the parsed URL, or raise `RuntimeError` before anything has been connected."""

    parsed = make_url(url) if isinstance(url, str) else url
    if parsed.database is None or not SAFE_TEST_DATABASE_NAME.fullmatch(parsed.database):
        raise RuntimeError(
            f"Refusing destructive test cleanup outside the sidekick_test database ({variable})"
        )
    if parsed.host not in LOOPBACK_HOSTS:
        raise RuntimeError(
            f"Refusing test database host outside the loopback allowlist: {parsed.host} "
            f"({variable})"
        )
    if parsed.query:
        raise RuntimeError(f"Refusing test database URL with query parameters ({variable})")
    if parsed.port is None:
        raise RuntimeError(
            f"Refusing test database URL without an explicit port ({variable}); "
            "the driver default 5432 is never a test database"
        )
    if parsed.port in reserved_ports():
        raise RuntimeError(f"Refusing protected database port {parsed.port} ({variable})")
    if parsed.port not in allowed_test_ports():
        raise RuntimeError(
            f"Refusing test database port {parsed.port} ({variable}); allowed ports are "
            f"{sorted(allowed_test_ports())}. Add one with {EXTRA_PORTS_VARIABLE}."
        )
    return parsed


#: Environment variables libpq reads after the URL was checked. Any of them can move a connection
#: (or supply the host, port, database or service file the URL left out).
LIBPQ_ENVIRONMENT = frozenset(
    {
        "PGHOST",
        "PGHOSTADDR",
        "PGPORT",
        "PGDATABASE",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGSYSCONFDIR",
        "PGPASSFILE",
        "PGLOADBALANCEHOSTS",
        "PGOPTIONS",
    }
)

#: Connection parameters that redirect, extend or re-describe the destination. `host`, `port`
#: and `dbname` are the only ones the suite uses, and they are validated, not forbidden.
REDIRECTING_PARAMETERS = frozenset(
    {
        "hostaddr",
        "service",
        "servicefile",
        "passfile",
        "options",
        "load_balance_hosts",
        "conninfo",
        "dsn",
    }
)

#: The numeric forms of `LOOPBACK_HOSTS`, as psycopg's own name resolution produces them.
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1"})

_GUARD_MARKER = "_sidekick_test_database_guard"

#: The lowest-level dial of each guarded driver (`psycopg.pq.PGconn.connect_start`, ...), looked up
#: at call time by the guard that sits in front of it. Tests replace an entry to record an
#: attempt instead of dialing, which proves the guard refused (or admitted) a target without a
#: socket ever being opened.
_LOWEST_DIALERS: dict[str, Callable[..., Any]] = {}


def ambient_libpq_variables(environ: Mapping[str, str] | None = None) -> list[str]:
    """The libpq environment variables that are set, by name only."""

    source = os.environ if environ is None else environ
    return sorted(name for name in LIBPQ_ENVIRONMENT if name in source)


def strip_libpq_environment() -> None:
    """Remove every libpq destination variable from this process, at session start."""

    for name in LIBPQ_ENVIRONMENT:
        os.environ.pop(name, None)


def child_process_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """An environment for a test-spawned child process: no libpq variables, a checked database.

    A child runs without the in-process guard, so what it inherits is all that protects the real
    databases. `SIDEKICK_DATABASE_URL`, when present, must pass the same validation as any test URL.
    """

    environment = {
        name: value
        for name, value in (os.environ if base is None else base).items()
        if name not in LIBPQ_ENVIRONMENT
    }
    database_url = environment.get("SIDEKICK_DATABASE_URL")
    if database_url:
        validate_test_database_url(database_url, variable="SIDEKICK_DATABASE_URL")
    return environment


def validate_child_env_file(path: Path) -> str | None:
    """Check a `--env-file` a test hands to a child process, which has no in-process guard.

    A missing file is left to the child to complain about. Otherwise the file may not set a libpq
    variable, and any `SIDEKICK_DATABASE_URL` in it must pass `validate_test_database_url`.
    Returns the validated URL, or None when the file does not exist or does not set one.
    """

    database_url: str | None = None
    if not path.is_file():
        return database_url
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().removeprefix("export ").strip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or line.startswith("#"):
            continue
        if name in LIBPQ_ENVIRONMENT:
            raise RuntimeError(f"Refusing libpq variable {name} in a child env file")
        if name == "SIDEKICK_DATABASE_URL":
            database_url = value.strip().strip("'\"")
            validate_test_database_url(database_url, variable=name)
    return database_url


def validate_effective_conninfo(
    params: Mapping[str, Any],
    *,
    variable: str = "connection about to be opened",
    loopback_hostaddr: bool = False,
) -> URL:
    """Validate what a driver is really about to dial, before it dials.

    `params` is the merged keyword/conninfo dictionary. Libpq environment variables, redirecting
    parameters, a multi-host or non-loopback `host`, a missing or protected port and a foreign
    database name are all refused. An unset (`None`) value counts as absent, as it does in libpq.
    """

    ambient = ambient_libpq_variables()
    if ambient:
        raise RuntimeError(
            f"Refusing to connect while libpq environment variables are set: {ambient} ({variable})"
        )
    # psycopg resolves `host` itself and passes the result on as `hostaddr` to its lowest dial;
    # there, and only there, a loopback address literal is the expected shape.
    resolved_loopback = loopback_hostaddr and params.get("hostaddr") in LOOPBACK_ADDRESSES
    redirecting = sorted(
        key
        for key in REDIRECTING_PARAMETERS
        if params.get(key) is not None and not (key == "hostaddr" and resolved_loopback)
    )
    if redirecting:
        raise RuntimeError(
            f"Refusing destination-changing connection parameters: {redirecting} ({variable})"
        )
    port = params.get("port")
    if port is None:
        parsed_port = None
    elif str(port).isascii() and str(port).isdigit():
        parsed_port = int(str(port))
    else:
        raise RuntimeError(f"Refusing test database URL without an explicit port ({variable})")
    host = params.get("host")
    database = params.get("dbname") if params.get("dbname") is not None else params.get("database")
    return validate_test_database_url(
        URL.create(
            "postgresql",
            host=None if host is None else str(host),
            port=parsed_port,
            database=None if database is None else str(database),
        ),
        variable=variable,
    )


def _guard_connection(
    dialect: Any, _connection_record: Any, _args: Any, connect_params: dict[str, Any]
) -> None:
    """`do_connect` hook: the SQLAlchemy-level check, on what the driver will dial."""

    if dialect.name != "postgresql":
        return
    validate_effective_conninfo(connect_params)


def _psycopg_effective_params(conninfo: str, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    from psycopg.conninfo import conninfo_to_dict

    return dict(conninfo_to_dict(conninfo or "", **kwargs))


def guard_psycopg(module: Any) -> None:
    """Wrap `Connection.connect` and `AsyncConnection.connect` (and `module.connect`).

    Everything psycopg 3 dials goes through these, whether it comes from SQLAlchemy, a custom
    `creator=`, a pool or a direct call.
    """

    connection_class = module.Connection
    original = connection_class.__dict__["connect"].__func__
    if getattr(original, _GUARD_MARKER, False):
        return

    @functools.wraps(original)
    def connect(cls: Any, conninfo: str = "", **kwargs: Any) -> Any:
        validate_effective_conninfo(_psycopg_effective_params(conninfo, kwargs))
        return original(cls, conninfo, **kwargs)

    setattr(connect, _GUARD_MARKER, True)
    connection_class.connect = classmethod(connect)
    module.connect = connection_class.connect

    async_class = module.AsyncConnection
    async_original = async_class.__dict__["connect"].__func__

    @functools.wraps(async_original)
    async def async_connect(cls: Any, conninfo: str = "", **kwargs: Any) -> Any:
        validate_effective_conninfo(_psycopg_effective_params(conninfo, kwargs))
        return await async_original(cls, conninfo, **kwargs)

    setattr(async_connect, _GUARD_MARKER, True)
    async_class.connect = classmethod(async_connect)


def guard_psycopg_pq(pq_module: Any) -> None:
    """Replace `psycopg.pq.PGconn` by a subclass whose `connect` and `connect_start` validate.

    The binary implementation is an immutable C type, so its methods cannot be wrapped in place.
    This covers direct use of `pq.PGconn` and the pure-Python generators; the compiled generator
    that psycopg uses with the binary build never touches `pq.PGconn`, which is why
    `guard_psycopg_generators` exists as well.
    """

    base = pq_module.PGconn
    if getattr(base, _GUARD_MARKER, False):
        return
    for name in ("connect", "connect_start"):
        _LOWEST_DIALERS.setdefault(f"psycopg.pq.PGconn.{name}", getattr(base, name))

    def checked(name: str, conninfo: bytes) -> Any:
        validate_effective_conninfo(
            _psycopg_effective_params(bytes(conninfo).decode(), {}), loopback_hostaddr=True
        )
        return _LOWEST_DIALERS[f"psycopg.pq.PGconn.{name}"](conninfo)

    class GuardedPGconn(base):  # type: ignore[misc]
        @classmethod
        def connect(cls, conninfo: bytes) -> Any:
            return checked("connect", conninfo)

        @classmethod
        def connect_start(cls, conninfo: bytes) -> Any:
            return checked("connect_start", conninfo)

    setattr(GuardedPGconn, _GUARD_MARKER, True)
    pq_module.PGconn = GuardedPGconn


def guard_psycopg_generators(generators_module: Any) -> None:
    """Wrap `psycopg.generators.connect`, the generator both `Connection` classes dial through.

    With psycopg's binary build it is a compiled function that calls libpq directly, so this is
    the real lowest point of a psycopg connection. It is looked up as `generators.connect` on
    every connection, so replacing the module attribute is enough.
    """

    original = generators_module.connect
    if getattr(original, _GUARD_MARKER, False):
        return
    key = "psycopg.generators.connect"
    _LOWEST_DIALERS.setdefault(key, original)

    def connect(conninfo: str, *, timeout: float = 0.0) -> Any:
        validate_effective_conninfo(_psycopg_effective_params(conninfo, {}), loopback_hostaddr=True)
        return _LOWEST_DIALERS[key](conninfo, timeout=timeout)

    setattr(connect, _GUARD_MARKER, True)
    generators_module.connect = connect


def guard_asyncpg(module: Any) -> None:
    """Wrap `asyncpg.connect`; asyncpg takes a URL `dsn` plus keyword arguments."""

    original = module.connect
    if getattr(original, _GUARD_MARKER, False):
        return

    @functools.wraps(original)
    async def connect(dsn: str | None = None, **kwargs: Any) -> Any:
        params: dict[str, Any] = {}
        if dsn:
            parts = urlsplit(dsn)
            params.update(
                host=parts.hostname,
                port=parts.port,
                dbname=unquote(parts.path.lstrip("/")) or None,
            )
            params.update(parse_qsl(parts.query))
        params.update({k: v for k, v in kwargs.items() if v is not None})
        if "database" in params:
            params["dbname"] = params.pop("database")
        validate_effective_conninfo(params)
        return await original(dsn, **kwargs)

    setattr(connect, _GUARD_MARKER, True)
    module.connect = connect


def install_connection_guard() -> None:
    """Make every PostgreSQL connection in this process pass the validation. Idempotent.

    Covers SQLAlchemy engines (including the ones application code builds from
    `SIDEKICK_DATABASE_URL`, which the suite points at the test database), direct `psycopg`
    calls, `creator=`, yoyo (psycopg 3), and `asyncpg` where installed.
    """

    if not event.contains(Engine, "do_connect", _guard_connection):
        event.listen(Engine, "do_connect", _guard_connection)
    guard_psycopg(importlib.import_module("psycopg"))
    guard_psycopg_pq(importlib.import_module("psycopg.pq"))
    guard_psycopg_generators(importlib.import_module("psycopg.generators"))
    if importlib.util.find_spec("asyncpg") is not None:
        guard_asyncpg(importlib.import_module("asyncpg"))

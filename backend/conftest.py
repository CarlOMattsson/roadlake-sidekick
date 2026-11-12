"""Test environment isolation.

The suite asserts what the code does, not what the developer's shell happens to
contain. A machine that exports the repository `.env` (real provider keys, a
development database, a live model provider) must not change a single result, so
this module removes every ambient `SIDEKICK_*` variable except the ones that
address the test database, and stops `Settings` from reading a dotenv file.

This runs at collection time, before any test module imports application
configuration.
"""

import os
import re

from pydantic_settings import SettingsConfigDict
from sqlalchemy.engine import make_url

from sidekick.shared.config import Settings
from tests.db_guard import (
    EXTRA_PORTS_VARIABLE,
    allowed_test_ports,
    install_connection_guard,
    strip_libpq_environment,
    validate_test_database_url,
)

#: `pytester` lets a unit test run a nested pytest session (tests/unit/test_database_required.py).
pytest_plugins = ["pytester"]

#: The only configuration the suite is allowed to inherit from the environment.
TEST_ENVIRONMENT_VARIABLES = frozenset(
    {
        "SIDEKICK_ENVIRONMENT",
        "SIDEKICK_DATABASE_URL",
        "SIDEKICK_TEST_DATABASE_URL",
        "SIDEKICK_TEST_MIGRATION_DATABASE_URL",
        "SIDEKICK_TEST_ADMIN_DATABASE_URL",
        "SIDEKICK_TEST_DB_BIND",
        EXTRA_PORTS_VARIABLE,
    }
)

#: The default bind for `deploy/compose.test.yaml`, which the compose file itself uses.
DEFAULT_TEST_DB_BIND = "127.0.0.1:55433"

#: Role and password per test-database variable, exactly as `deploy/postgres-init.sql`
#: creates them and `deploy/compose.test.yaml` configures the superuser.
TEST_DATABASE_ROLES = {
    "SIDEKICK_TEST_DATABASE_URL": ("postgresql+psycopg", "sidekick_app", "sidekick_app"),
    "SIDEKICK_TEST_MIGRATION_DATABASE_URL": (
        "postgresql+psycopg",
        "sidekick_migrator",
        "sidekick_migrator",
    ),
    "SIDEKICK_TEST_ADMIN_DATABASE_URL": ("postgresql+psycopg", "postgres", "postgres"),
}


def _use_psycopg_driver() -> None:
    """Rewrite a plain `postgresql://` test URL to `postgresql+psycopg://`.

    psycopg 3 is the only PostgreSQL driver installed. SQLAlchemy and yoyo both treat a bare
    `postgresql://` as psycopg2, so an older export of the migrator or admin URL would fail
    to import a driver. Only the scheme changes; host, port, database and credentials are
    left exactly as exported, and the validation that follows still sees the same target.
    """

    for variable in TEST_DATABASE_ROLES:
        value = os.environ.get(variable)
        if value and value.startswith("postgresql://"):
            os.environ[variable] = "postgresql+psycopg://" + value[len("postgresql://") :]


def _default_test_database_urls() -> None:
    """Point the suite at the repository's own test database when nothing else did.

    The three URLs are not a secret and not a choice: `deploy/compose.test.yaml` fixes the
    database, the roles, and the bind, and `tests/db.py` already hardcodes the same
    application URL as its safe constant. Requiring the operator to export them anyway
    meant an integration test skipped silently on a shell that happened not to have them,
    and a suite that looks green while a quarter of it did not run is worse than a red one.

    This defaults, it never overrides: an explicitly exported variable, as continuous
    integration sets, is left exactly as it is. The safety checks in `tests/db.py` are
    untouched and still refuse any database other than `sidekick_test` on an allowlisted
    host, and a database that is simply not running still skips with a clear reason.
    """

    bind = os.environ.get("SIDEKICK_TEST_DB_BIND") or DEFAULT_TEST_DB_BIND
    host, _, port = bind.rpartition(":")
    authority = f"{host or '127.0.0.1'}:{port}"
    for variable, (scheme, role, password) in TEST_DATABASE_ROLES.items():
        if not os.environ.get(variable):
            os.environ[variable] = f"{scheme}://{role}:{password}@{authority}/sidekick_test"


#: pytest-xdist worker ids are `gw0`, `gw1`, ...; worker N uses `sidekick_test_w<N>` on the base
#: `sidekick_test` and `sidekick_test_<K>_w<N>` on the pool base `sidekick_test_<K>`.
_XDIST_WORKER = re.compile(r"gw(0|[1-9][0-9]*)")
_POOL_DATABASE = re.compile(r"sidekick_test(_[1-9][0-9]?)?(_w[0-9]{1,2})?")
_WORKER_SUFFIX = re.compile(r"_w[0-9]{1,2}")


def _worker_database(base: str, worker_index: int) -> str:
    """`sidekick_test` -> `sidekick_test_w<N>`; `sidekick_test_<K>` -> `sidekick_test_<K>_w<N>`."""

    if base == "sidekick_test":
        return f"sidekick_test_w{worker_index}"
    return f"{base}_w{worker_index}"


def _per_worker_test_databases() -> None:
    """Give each pytest-xdist worker its own database from tools/test-db-pool.sh.

    Every test run empties its database, so two workers sharing one would erase each
    other's rows, and two agents sharing a worker name would erase each other's rows too.
    Under xdist, worker `gwN` rewrites the database name of the three test URLs to the
    worker database of the base the URL names: `sidekick_test` gives `sidekick_test_wN`,
    and `sidekick_test_<K>` gives `sidekick_test_<K>_wN`, so an agent on slot K only touches
    its own `sidekick_test_<K>_w*`. Only URLs on an allowlisted test port (tests/db_guard.py) whose
    database is `sidekick_test` or a pool slot are rewritten; a URL that already names a
    worker database is refused, since it would make every worker share one database.
    Anything else is left as is and the guard in `tests/db.py` refuses it. Without
    `PYTEST_XDIST_WORKER` this does nothing.
    """

    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    match = _XDIST_WORKER.fullmatch(worker)
    if match is None:
        raise RuntimeError(f"Unexpected pytest-xdist worker id: {worker!r}")
    worker_index = int(match.group(1))
    for variable in TEST_DATABASE_ROLES:
        value = os.environ.get(variable)
        if not value:
            continue
        url = make_url(value)
        if (
            url.port not in allowed_test_ports()
            or url.database is None
            or not _POOL_DATABASE.fullmatch(url.database)
        ):
            continue
        if _WORKER_SUFFIX.search(url.database):
            raise RuntimeError(
                f"{variable} names the worker database {url.database!r}; under pytest-xdist "
                "it must name the base database 'sidekick_test' or 'sidekick_test_<K>'"
            )
        database = _worker_database(url.database, worker_index)
        os.environ[variable] = url.set(database=database).render_as_string(hide_password=False)


def _refuse_unsafe_test_database_urls() -> None:
    """Fail the whole run, before any test, when a test URL points outside the test databases.

    `tests/db.py` and a `do_connect` hook validate again at connection time; this makes a bad
    export (for example a bind on the owner's port) stop the run with one clear message.
    """

    for variable in TEST_DATABASE_ROLES:
        value = os.environ.get(variable)
        if value:
            validate_test_database_url(value, variable=variable)


def _isolate_test_environment() -> None:
    # libpq reads PGHOST, PGSERVICE, ... after any URL check, so none may survive into the run.
    strip_libpq_environment()
    for name in [
        name
        for name in os.environ
        if name.startswith("SIDEKICK_") and name not in TEST_ENVIRONMENT_VARIABLES
    ]:
        del os.environ[name]

    os.environ["SIDEKICK_ENVIRONMENT"] = "test"
    _default_test_database_urls()
    _use_psycopg_driver()
    _per_worker_test_databases()
    _refuse_unsafe_test_database_urls()
    install_connection_guard()

    # The application under test must reach the test database, never a
    # development one that a shell happened to export.
    test_database_url = os.environ.get("SIDEKICK_TEST_DATABASE_URL")
    if test_database_url:
        os.environ["SIDEKICK_DATABASE_URL"] = test_database_url

    # A dotenv file is deployment configuration. Reading one here would make the
    # result depend on the directory the suite was started from.
    Settings.model_config = SettingsConfigDict(
        env_prefix="SIDEKICK_", env_file=None, extra="forbid"
    )


_isolate_test_environment()

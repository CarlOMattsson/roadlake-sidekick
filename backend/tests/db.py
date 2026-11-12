"""PostgreSQL test helpers; never substitutes SQLite."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NoReturn

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from yoyo import get_backend, read_migrations

from tests.db_guard import LOOPBACK_HOSTS, validate_test_database_url

MIGRATIONS_PATH = Path(__file__).resolve().parents[2] / "migrations"

SAFE_TEST_DATABASE_URL = (
    "postgresql+psycopg://sidekick_app:sidekick_app@127.0.0.1:55433/sidekick_test"
)
ALLOWED_TEST_HOSTS = LOOPBACK_HOSTS

# This safe, non-persistent URL only lets non-integration tests construct Settings. Any
# database connection or destructive cleanup still requires the environment variable below.
DATABASE_URL = os.getenv("SIDEKICK_TEST_DATABASE_URL", SAFE_TEST_DATABASE_URL)


def assert_safe_test_database(
    url: str | URL, *, variable: str = "SIDEKICK_TEST_DATABASE_URL"
) -> URL:
    """Fail closed before a test can connect to or mutate a non-test database."""

    if os.environ.get("SIDEKICK_ENVIRONMENT") != "test":
        raise RuntimeError("Integration tests require SIDEKICK_ENVIRONMENT=test")
    if not os.environ.get(variable):
        raise RuntimeError(f"Integration tests require {variable}")

    # Name, loopback host, explicit allowlisted port, protected-port blocklist and no query
    # string are all decided in tests/db_guard.py, the single validation every URL goes through.
    # `sidekick_test` is CI's database; `sidekick_test_<n>` are the local pool slots from
    # tools/test-db-pool.sh, and `sidekick_test(_<n>)?_w<m>` are the per-xdist-worker databases
    # of such a base, so parallel agents never empty each other's data.
    return validate_test_database_url(url, variable=variable)


# Set by `configure_database_requirement` when the run is `--full` (or SIDEKICK_FULL_TESTS=1).
_DATABASE_REQUIRED_BY_RUN = False


def configure_database_requirement(full_run: bool) -> None:
    """Record whether this pytest run must have a reachable test database."""

    global _DATABASE_REQUIRED_BY_RUN
    _DATABASE_REQUIRED_BY_RUN = full_run


def database_required() -> bool:
    """True in a `--full` run and in CI (`CI=true`), where a missing database is an error."""

    return _DATABASE_REQUIRED_BY_RUN or os.environ.get("CI", "").lower() == "true"


def skip_or_fail_without_database(reason: str) -> NoReturn:
    """Skip a database test in a quick local run; fail it in `--full` and in CI.

    A skipped test makes a run without PostgreSQL look green, so where the whole suite is
    expected to run the missing database is a failure with the reason spelled out.
    """

    if database_required():
        pytest.fail(
            f"{reason}. This run (--full or CI=true) requires the test database, so the test "
            "fails instead of being skipped; start deploy/compose.test.yaml or "
            "tools/test-db-pool.sh and run again.",
            pytrace=False,
        )
    pytest.skip(reason)


def require_test_database_url(variable: str = "SIDEKICK_TEST_DATABASE_URL") -> str:
    """Return an explicitly configured safe URL; without one, skip (quick) or fail (--full/CI)."""

    value = os.getenv(variable)
    if not value:
        skip_or_fail_without_database(
            f"{variable} is not configured; start deploy/compose.test.yaml first"
        )
    assert_safe_test_database(value, variable=variable)
    return value


# Every engine built by this module, so that the test teardown can close its idle connections.
_TEST_ENGINES: list[Engine] = []


def create_test_session_factory(url: str) -> sessionmaker[Session]:
    """A session factory whose idle connections are closed after every test.

    Every integration test builds its own engine, and the suite has hundreds of them.
    With the default pool each engine keeps its checked-in connections open for the
    rest of the session, so the run eventually asked PostgreSQL for more connection
    slots than it has and a late test failed for a reason that had nothing to do with
    the behaviour it asserts. `NullPool` avoided that by closing a connection on every
    return, but then each query paid for a new connection (about 1 460 per test).

    The default is now a pool of at most two idle connections per engine, plus two
    overflow connections, and `dispose_test_engines()` closes them when each test ends,
    so the number of open connections stays bounded by the tests running at once.
    `SIDEKICK_TEST_DB_POOL=null` restores the `NullPool` behaviour as a fallback.
    """

    validate_test_database_url(url, variable="test session factory URL")
    if os.getenv("SIDEKICK_TEST_DB_POOL") == "null":
        engine = create_engine(url, poolclass=NullPool, pool_pre_ping=True, hide_parameters=True)
    else:
        engine = create_engine(
            url,
            pool_size=2,
            max_overflow=2,
            pool_pre_ping=False,
            hide_parameters=True,
            # Without this, psycopg keeps server-side prepared statements per pooled connection,
            # and a test that drops and recreates the schema would hit stale cached plans.
            connect_args={"prepare_threshold": None},
        )
    _TEST_ENGINES.append(engine)
    return sessionmaker(engine, expire_on_commit=False)


def dispose_test_engines() -> None:
    """Close the idle connections of every engine this module created; called after each test.

    `Engine.dispose()` keeps the engine usable, so a cached factory still works afterwards.
    """

    for engine in _TEST_ENGINES:
        engine.dispose()
    _TEST_ENGINES.clear()


# Migration URLs whose chain head this process has already verified. database_factory() runs
# for every test, and each head check opens a fresh engine and queries the catalogue. Any test
# that rolls migrations back must call invalidate_migration_head_cache() before it does so.
_VERIFIED_MIGRATION_HEADS: set[str] = set()


def invalidate_migration_head_cache() -> None:
    """Forget verified chain heads so the next database_factory() checks the schema again."""

    _VERIFIED_MIGRATION_HEADS.clear()


def database_factory() -> sessionmaker[Session]:
    url = require_test_database_url()
    assert_safe_test_database(url)
    factory = create_test_session_factory(url)
    try:
        with factory() as session:
            session.execute(text("SELECT 1"))
    except OperationalError as error:
        skip_or_fail_without_database(f"PostgreSQL integration database unavailable: {error}")
    migration_url = os.getenv("SIDEKICK_TEST_MIGRATION_DATABASE_URL")
    if migration_url and migration_url not in _VERIFIED_MIGRATION_HEADS:
        ensure_migration_chain_head()
        _VERIFIED_MIGRATION_HEADS.add(migration_url)
    clean_database(factory)
    return factory


# Tables that only exist when the complete repository migration chain is applied.
CHAIN_HEAD_TABLES = (
    "domains",
    "instance_license",
    "work_tags",
    "shopping_items",
    "external_references",
)


def latest_migration_id() -> str:
    """The id of the newest migration file, e.g. `101_tasks_project_and_due_indexes`."""

    numbered = []
    for path in MIGRATIONS_PATH.glob("*.py"):
        number, separator, _ = path.stem.partition("_")
        if separator and number.isdigit():
            numbered.append((int(number), path.stem))
    if not numbered:
        raise RuntimeError(f"No numbered migrations found in {MIGRATIONS_PATH}")
    return max(numbered)[1]


def ensure_migration_chain_head() -> None:
    """Rebuild the shared test schema when a destructive migration test left it behind,
    or when the database is not migrated to the newest file in `migrations/`.

    Migration tests intentionally rebuild the schema (for example the pre-baseline chain in
    `test_migration_baseline.py`), or roll back a migration, while yoyo's records in `public`
    survive. Later tests would then run against a partially migrated database. The check
    compares the newest migration id with yoyo's `public._yoyo_migration` and also requires
    the tables of the chain head; it is one cheap query. The rebuild only runs when one of
    these is missing, and then drops the schema and applies `migrations/` again.
    """

    migration_url = os.getenv("SIDEKICK_TEST_MIGRATION_DATABASE_URL")
    if not migration_url:
        return
    assert_safe_test_database(migration_url, variable="SIDEKICK_TEST_MIGRATION_DATABASE_URL")
    admin_url = os.getenv("SIDEKICK_TEST_ADMIN_DATABASE_URL") or migration_url
    # Validated before create_engine(): the admin role runs DROP SCHEMA ... CASCADE below.
    validate_test_database_url(admin_url, variable="SIDEKICK_TEST_ADMIN_DATABASE_URL")
    head = latest_migration_id()
    engine = create_engine(admin_url)
    try:
        with engine.begin() as connection:
            present = set(
                connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'sidekick'"
                    )
                )
            )
            applied: set[str] = set()
            if connection.scalar(text("SELECT to_regclass('public._yoyo_migration') IS NOT NULL")):
                applied = set(
                    connection.scalars(text("SELECT migration_id FROM public._yoyo_migration"))
                )
            if set(CHAIN_HEAD_TABLES) <= present and head in applied:
                return
            connection.execute(text("SET LOCAL ROLE sidekick_owner"))
            connection.execute(text("DROP SCHEMA IF EXISTS sidekick CASCADE"))
        with engine.begin() as connection:
            for table in ("_yoyo_migration", "_yoyo_log", "_yoyo_version", "yoyo_lock"):
                connection.execute(text(f"DROP TABLE IF EXISTS public.{table} CASCADE"))
    finally:
        engine.dispose()

    backend = get_backend(migration_url)
    migrations = read_migrations(str(MIGRATIONS_PATH))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))


# One admin session factory per URL, reused by every clean_database() call in the process.
_CLEANUP_FACTORIES: dict[str, sessionmaker[Session]] = {}


def _cleanup_factory_for(admin_url: str) -> sessionmaker[Session]:
    validate_test_database_url(admin_url, variable="SIDEKICK_TEST_ADMIN_DATABASE_URL")
    factory = _CLEANUP_FACTORIES.get(admin_url)
    if factory is None:
        factory = create_test_session_factory(admin_url)
        _CLEANUP_FACTORIES[admin_url] = factory
    return factory


def clean_database(factory: sessionmaker[Session]) -> None:
    assert_safe_test_database(DATABASE_URL)
    admin_url = os.getenv("SIDEKICK_TEST_ADMIN_DATABASE_URL")
    if not admin_url:
        # The app role has no DELETE on sidekick.audit_events (baseline grants), so the cleanup
        # needs the owner-side admin URL that tools/test-db-pool.sh exports.
        raise RuntimeError(
            "Test cleanup requires SIDEKICK_TEST_ADMIN_DATABASE_URL: the app role may not DELETE "
            "sidekick.audit_events (0.1.0 baseline grant). Export it with "
            '`eval "$(bash tools/test-db-pool.sh env K)"` before running the tests.'
        )
    assert_safe_test_database(admin_url, variable="SIDEKICK_TEST_ADMIN_DATABASE_URL")
    cleanup_factory = _cleanup_factory_for(admin_url)
    tables = (
        "shopping_item_status_history",
        "shopping_items",
        "shopping_lists",
        "task_external_references",
        "external_references",
        "domain_tags",
        "process_tags",
        "project_tags",
        "task_tags",
        "work_tags",
        "actions",
        "steps",
        "saved_work_views",
        # An entry's links to Projects, Tasks and Contacts are ON DELETE RESTRICT.
        "journal_entry_projects",
        "journal_entry_tasks",
        "journal_entry_contacts",
        "project_contacts",
        "task_contacts",
        # A Process run keeps its Task (ON DELETE RESTRICT), so the runs go before the Tasks.
        "process_run_outbox",
        "process_runs",
        "process_run_templates",
        # Tasks first: a waiting Contact reference is ON DELETE RESTRICT.
        "tasks",
        "contact_aliases",
        "contacts",
        "audit_events",
        "instance_license",
        "idempotency_operations",
        "projects",
        "processes",
        "domains",
        # A subscription belongs to a pairing; a pairing references the device credential it
        # created (ON DELETE SET NULL).
        "push_reminders",
        "push_outbox",
        "push_subscriptions",
        "companion_pairings",
        "personal_access_tokens",
        "users",
    )
    with cleanup_factory.begin() as session:
        for table in tables:
            session.execute(text(f"DELETE FROM sidekick.{table}"))


@contextmanager
def count_statements(factory: sessionmaker[Session]) -> Iterator[list[str]]:
    """Collect the SQL statements the engine of `factory` executes inside the block.

    Used by tests that guard a read against doing work that grows with the data (a statement per
    row, a scan per call). Counting statements is deterministic where wall-clock time is not.
    """

    engine: Engine = factory.kw["bind"]
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)

"""Shared pytest fixtures for the Sidekick test suite."""

from collections.abc import Callable, Iterator, Mapping
from typing import Any
from uuid import UUID

import pytest

from sidekick.mcp.schema_cache import install_schema_cache
from sidekick.shared.observability import configure_observability
from sidekick.shared.types import Actor
from tests.db import configure_database_requirement, database_factory, dispose_test_engines
from tests.support.fakes import JournalProviderSpy, journal_candidate_snapshot


def pytest_configure(config: pytest.Config) -> None:
    # Tests build the MCP server hundreds of times; production builds it once at startup and
    # keeps fastmcp's own parsing. The cache's byte-identity is checked in test_schema_cache.py.
    install_schema_cache()
    # In --full and in CI an unreachable database fails its tests instead of skipping them.
    configure_database_requirement(_full_run(config))


@pytest.fixture(autouse=True)
def sidekick_logging_configured() -> None:
    """Configure Sidekick's logging before a test attaches its own handler to a `sidekick` logger.

    `configure_observability` runs once per process, from the first `create_app`, and then
    replaces the `sidekick` logger's handlers, sets `propagate = False` and resets its level. A test
    that attached a capture handler first and built the app inside its body lost the handler if it
    happened to be the first such test on its xdist worker, so the outcome depended on how tests
    were spread over workers. Running the (idempotent) configuration up front gives every test
    the same logger state regardless of order.
    """

    configure_observability("test")


@pytest.fixture(autouse=True)
def close_test_database_connections() -> Iterator[None]:
    """Close idle pooled connections when each test ends, so engines do not pile up per worker."""

    yield
    dispose_test_engines()


@pytest.fixture
def contact_read_scope() -> str:
    return "contacts:read"


@pytest.fixture
def contact_write_scope() -> str:
    return "contacts:write"


@pytest.fixture
def contact_actor() -> Actor:
    return Actor(
        user_id=UUID("018af000-0000-7000-8000-000000000001"),
        scopes=frozenset({"contacts:read", "contacts:write", "projects:read", "tasks:read"}),
    )


@pytest.fixture
def contact_read_actor() -> Actor:
    return Actor(
        user_id=UUID("018af000-0000-7000-8000-000000000001"),
        scopes=frozenset({"contacts:read"}),
    )


@pytest.fixture
def contact_write_actor() -> Actor:
    return Actor(
        user_id=UUID("018af000-0000-7000-8000-000000000001"),
        scopes=frozenset({"contacts:write"}),
    )


@pytest.fixture
def second_owner_actor() -> Actor:
    return Actor(
        user_id=UUID("018af000-0000-7000-8000-000000000002"),
        scopes=frozenset({"contacts:read", "contacts:write"}),
    )


@pytest.fixture
def journal_read_scope() -> str:
    return "journal:read"


@pytest.fixture
def journal_write_scope() -> str:
    return "journal:write"


@pytest.fixture
def journal_actor() -> Actor:
    return Actor(
        user_id=UUID("018af000-0000-7000-8000-000000000001"),
        scopes=frozenset(
            {
                "journal:read",
                "journal:write",
                "projects:read",
                "tasks:read",
                "contacts:read",
            }
        ),
    )


@pytest.fixture
def journal_read_actor() -> Actor:
    return Actor(
        user_id=UUID("018af000-0000-7000-8000-000000000001"),
        scopes=frozenset({"journal:read"}),
    )


@pytest.fixture
def journal_second_owner_actor() -> Actor:
    return Actor(
        user_id=UUID("018af000-0000-7000-8000-000000000002"),
        scopes=frozenset({"journal:read", "journal:write"}),
    )


@pytest.fixture
def journal_pat_scopes() -> frozenset[str]:
    return frozenset(
        {"journal:read", "journal:write", "projects:read", "tasks:read", "contacts:read"}
    )


@pytest.fixture
def journal_csrf_headers() -> dict[str, str]:
    return {
        "Origin": "https://sidekick.test",
        "X-CSRF-Token": "csrf-journal-" + "x" * 32,
    }


@pytest.fixture
def journal_idempotency_key() -> str:
    return "journal-operation-0001"


@pytest.fixture
def journal_provider_spy() -> JournalProviderSpy:
    return JournalProviderSpy()


@pytest.fixture
def journal_candidate_catalog() -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    return journal_candidate_snapshot()


@pytest.fixture
def journal_database_factory() -> Callable[..., Any]:
    """Fully migrated PostgreSQL session factory, created only for integration users."""

    return database_factory()


@pytest.fixture
def journal_http_actor(journal_actor: Actor) -> Actor:
    """Cookie/CSRF HTTP actor with the complete Journal relation-read authority."""

    return journal_actor


@pytest.fixture
def journal_mcp_actor(journal_actor: Actor) -> Actor:
    """PAT-backed MCP actor for the reviewed manual Journal subset."""

    return journal_actor


@pytest.fixture
def hindsight_http_stub() -> Any:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "healthy"}, request=request)
        if request.method == "DELETE":
            return httpx.Response(204, request=request)
        if request.url.path.endswith("/recall"):
            return httpx.Response(200, json={"results": []}, request=request)
        return httpx.Response(202, json={"operation_id": "synthetic-operation"}, request=request)

    return httpx.MockTransport(handler)


# The slow suites run only before a push or in CI. A plain `pytest`
# runs the fast tier; `pytest --full` (or SIDEKICK_FULL_TESTS=1) runs everything. An explicit path
# argument always runs what it names.
_FULL_ONLY_DIRS = ("api", "integration", "bdd", "contract", "mcp", "ops", "selfhost")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--full",
        action="store_true",
        default=False,
        help="Run the slow suites too (api, integration, bdd, contract, mcp, ops, selfhost).",
    )


def _full_run(config: pytest.Config) -> bool:
    import os

    return bool(config.getoption("--full")) or os.environ.get("SIDEKICK_FULL_TESTS") == "1"


def pytest_ignore_collect(collection_path: Any, config: pytest.Config) -> bool | None:
    if _full_run(config) or config.option.file_or_dir:
        return None
    if collection_path.parent.name == "tests" and collection_path.name in _FULL_ONLY_DIRS:
        return True
    return None

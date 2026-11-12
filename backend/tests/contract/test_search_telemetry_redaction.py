"""Search telemetry, logs and errors exclude the query text and Journal text (D-058)."""

import logging
from collections.abc import Iterator
from datetime import date
from uuid import UUID

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.search_fixtures import insert_entry
from tests.support.settings import make_settings
from tests.support.telemetry import CaptureTelemetry

JOURNAL_SENTINEL = "zetajournaltextkappa"
QUERY_SENTINEL = "bankkortet"
TITLE_SENTINEL = "zetaentrytitelkappa"
JOURNAL_TEXT = f"Hemlig {JOURNAL_SENTINEL} anteckning om {QUERY_SENTINEL} i september."
SOURCE_ARGS = {
    "source_type": "manual_text",
    "journal_date": "2026-07-21",
    "occurred_at": "2026-07-21T09:00:00Z",
    "source_recorded_at": "2026-07-24T08:00:00Z",
    "raw_text": JOURNAL_TEXT,
    "language": "sv",
    "idempotency_key": "search-telemetry-source-1",
}


@pytest.fixture
def search_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Capture the `sidekick.search` records. That logger does not propagate to the root logger."""
    caplog.set_level(logging.DEBUG)
    logger = logging.getLogger("sidekick.search")
    logger.addHandler(caplog.handler)
    yield caplog
    logger.removeHandler(caplog.handler)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_telemetry_logs_and_errors_exclude_query_and_journal_text(
    search_log: pytest.LogCaptureFixture,
) -> None:
    telemetry = CaptureTelemetry()
    factory = database_factory()
    container = create_container(make_settings(), factory, telemetry)
    user_id = container.auth.provision_user("search-telemetry-owner", "Owner")
    actor = Actor(user_id, frozenset({"journal:read", "journal:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        created = await client.call_tool("create_journal_source", SOURCE_ARGS)
        assert created.structured_content is not None
        insert_entry(
            factory,
            user_id,
            UUID(created.structured_content["source"]["id"]),
            TITLE_SENTINEL,
            journal_date=date.fromisoformat(SOURCE_ARGS["journal_date"]),
        )
        found = await client.call_tool("search", {"query": QUERY_SENTINEL, "kinds": ["journal"]})
        assert found.structured_content is not None
        hits = found.structured_content["journal"]["hits"]
        assert hits, "the search must hit the source"
        assert hits[0]["title"] == TITLE_SENTINEL, "the title must be present in the hit itself"

        with pytest.raises(ToolError) as too_long:
            await client.call_tool("search", {"query": QUERY_SENTINEL + "a" * 100})

    log_text = "\n".join(
        f"{record.getMessage()} {record.__dict__!r}" for record in search_log.records
    )
    assert "search_completed" in log_text, "the search log line should be emitted"
    surfaces = {
        "telemetry": str(telemetry.records),
        "logs": log_text,
        "error": str(too_long.value),
    }
    for name, serialized in surfaces.items():
        assert QUERY_SENTINEL not in serialized, f"query text leaked into {name}"
        assert JOURNAL_SENTINEL not in serialized, f"journal text leaked into {name}"
        assert TITLE_SENTINEL not in serialized, f"journal title leaked into {name}"

"""Invalid MCP tool arguments never write their values to a log sink."""

from uuid import uuid4

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401  (the `all_logs` fixture)
    _Collector,
)
from tests.support.settings import make_settings

TITLE_SENTINEL = "sentinel-task-title-7f3a"
PROJECT_SENTINEL = "sentinel-project-id-91bc"


def _server_with_actor():
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"tasks:read", "tasks:write"}))
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_invalid_tool_arguments_leave_no_argument_value_in_any_log(
    all_logs: _Collector,
) -> None:
    server = _server_with_actor()
    async with Client(server) as client:
        response = await client.call_tool_mcp(
            "create_task",
            {
                "title": TITLE_SENTINEL,
                "idempotency_key": "mcp-log-probe-001",
                # Passes the JSON schema, fails pydantic's UUID parse: FastMCP logs the input.
                "project_id": PROJECT_SENTINEL,
            },
        )

    assert response.isError
    rendered = all_logs.rendered()
    assert PROJECT_SENTINEL not in rendered
    assert TITLE_SENTINEL not in rendered
    # The record itself is kept, only its content is withheld.
    assert "fastmcp tool warning record (content withheld)" in rendered
    assert all(record.exc_info is None for record in all_logs.records)
    assert all(not record.args for record in all_logs.records)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidekick_tool_failure_returns_a_correlated_error_without_content(
    all_logs: _Collector,
) -> None:
    server = _server_with_actor()
    async with Client(server) as client:
        response = await client.call_tool_mcp(
            "create_task",
            {
                "title": TITLE_SENTINEL,
                "idempotency_key": "mcp-log-probe-002",
                "project_id": str(uuid4()),
            },
        )

    assert response.isError
    assert response.structuredContent is not None
    assert response.structuredContent["correlation_id"]
    assert TITLE_SENTINEL not in str(response.structuredContent)
    assert TITLE_SENTINEL not in all_logs.rendered()

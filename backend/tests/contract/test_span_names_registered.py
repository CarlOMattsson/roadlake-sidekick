"""Every tool, resource and prompt of the real MCP server is on the span allowlist.

`create_mcp_server` hands the allowlist the server's own names by reading FastMCP's local provider.
If a FastMCP upgrade changes that store, the names would silently fall back to `unknown` in traces;
this test fails instead.
"""

import pytest

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.observability.span_allowlist import normalize_span_name
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_real_server_tool_resource_and_prompt_names_keep_their_span_names() -> None:
    server = create_mcp_server(
        create_container(make_settings(), database_factory()), enable_auth=False
    )
    tools = await server.list_tools()
    resources = await server.list_resources()
    assert tools and resources
    for tool in tools:
        assert normalize_span_name(f"tools/call {tool.name}") == f"tools/call {tool.name}"
    for resource in resources:
        name = f"resources/read {resource.uri}"
        assert normalize_span_name(name) == name
    assert normalize_span_name("tools/call anna.svensson@example.com") == "tools/call tool:unknown"

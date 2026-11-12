"""The Control MCP App: trash, recent changes and memory open one inline card, and no other tool."""

import re

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.shared.types import Actor, new_uuid7
from tests.support.settings import make_settings

# The tools that open the Control card. They are the only four; the rest open no view.
OPENING_TOOLS = (
    "list_trash",
    "list_recent_changes",
    "get_memory_status",
    "list_assistant_activity",
)

# Tools that act on trash or memory but must not open a view of their own.
NON_OPENING_TOOLS = (
    "restore_from_trash",
    "set_memory_settings",
    "move_to_trash",
    "exclude_from_memory",
    "recall_memory",
)


@pytest.mark.asyncio
async def test_control_tools_open_the_sidekick_app() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}
    for name in OPENING_TOOLS:
        assert tools[name].meta["ui"]["resourceUri"] == SIDEKICK_APP_URI, name
    for name in NON_OPENING_TOOLS:
        assert "resourceUri" not in (tools[name].meta or {}).get("ui", {}), name


@pytest.mark.asyncio
async def test_the_app_resource_is_the_built_bundle_and_loads_nothing_external() -> None:
    reader = Actor(new_uuid7(), frozenset({"journal:read"}))
    server = create_mcp_server(
        create_container(make_settings()), actor_provider=lambda: reader, enable_auth=False
    )
    async with Client(server) as client:
        html = (await client.read_resource(SIDEKICK_APP_URI))[0].text
    # The served document is the built app, not the not-built placeholder.
    assert "is not available" not in html
    # The SVG and MathML namespace strings in the bundled React runtime are not fetches.
    assert not re.search(r'(?:src|href)=["\']https?://', html)
    urls = re.findall(r"https?://[^\s\"'`)]*", html)
    external = [url for url in urls if not url.startswith("http://www.w3.org/")]
    assert external == []

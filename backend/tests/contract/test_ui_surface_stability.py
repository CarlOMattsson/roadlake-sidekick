"""The curated MCP surface stays exactly what contracts/mcp-tools.generated.json records.

The tool count is read from that snapshot, never hardcoded. On top of the count, this module
secures what the interface layer must never leak into MCP:
- no tool manages interface preferences, and no tool schema carries `board_rank`, `theme_mode`,
  `default_workspace_view` or `priority_badges`;
- the board tools are an allowlist: the read-only `get_work_board` and the app-only
  `reorder_work_board_column`, which the model never sees;
- tags are read with `list_tags` and assigned inside record updates, so no `*_tag` tool exists;
- the preference scopes are session-only: the MCP token verifier never advertises them."""

import json

import pytest
from fastmcp import Client

from sidekick.api.app import create_app
from sidekick.mcp.auth import PersonalTokenVerifier
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import ALL_SCOPES
from sidekick.shared.types import Actor, new_uuid7
from tests.contract_counts import curated_tool_count
from tests.support.settings import make_settings

CURATED_TOOL_COUNT = curated_tool_count()
TAG_READ_TOOL = "list_tags"
READ_ONLY_BOARD_TOOL = "get_work_board"
# The only board write is app-only: the model never sees it, and it carries no board_rank.
APP_ONLY_BOARD_WRITE_TOOL = "reorder_work_board_column"


def _server() -> object:
    app = create_app(make_settings(), None)
    actor = Actor(new_uuid7(), frozenset({"projects:read", "tasks:read"}))
    return create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)


@pytest.mark.asyncio
async def test_public_mcp_surface_stays_at_the_curated_tool_count() -> None:
    async with Client(_server()) as client:
        tools = await client.list_tools()

    assert len(tools) == CURATED_TOOL_COUNT
    assert not [tool for tool in tools if "preference" in tool.name]
    # Board tools are an allowlist: the read of the status columns, which stays read-only,
    # and the app-only column reorder, which the model must not see.
    board_tools = {tool.name: tool for tool in tools if "board" in tool.name}
    assert set(board_tools) == {READ_ONLY_BOARD_TOOL, APP_ONLY_BOARD_WRITE_TOOL}
    annotations = board_tools[READ_ONLY_BOARD_TOOL].annotations
    assert annotations is not None and annotations.readOnlyHint is True
    write_meta = board_tools[APP_ONLY_BOARD_WRITE_TOOL].meta
    assert write_meta is not None and write_meta["ui"]["visibility"] == ["app"]
    names = {tool.name for tool in tools}
    assert TAG_READ_TOOL in names
    assert not {name for name in names if name.endswith("_tag")}, (
        "tag assignment stays inside record updates; no tag mutation tool ships"
    )


@pytest.mark.asyncio
async def test_no_public_tool_schema_exposes_board_rank_or_interface_preferences() -> None:
    async with Client(_server()) as client:
        tools = await client.list_tools()

    serialized = json.dumps(
        [
            {
                "name": tool.name,
                "input": tool.inputSchema,
                "output": getattr(tool, "outputSchema", None),
            }
            for tool in tools
        ],
        default=str,
    )
    assert "board_rank" not in serialized
    assert "theme_mode" not in serialized
    assert "default_workspace_view" not in serialized
    assert "priority_badges" not in serialized


def test_mcp_advertises_no_interface_preference_scopes() -> None:
    app = create_app(make_settings(), None)
    verifier = PersonalTokenVerifier(app.state.container.auth)

    preferences = {"preferences:read", "preferences:write"}
    assert not preferences & ALL_SCOPES
    assert not preferences & set(verifier.scopes_supported)

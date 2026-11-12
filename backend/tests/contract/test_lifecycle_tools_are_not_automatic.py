"""The three trash tools are explicit owner commands.

`move_to_trash` hides a record and `restore_from_trash` brings it back. This file pins the exact
set of lifecycle tools, and that the whole surface stays free of permanent removal (D-031).
"""

import pytest

from sidekick.api.app import create_container
from sidekick.mcp.lifecycle import LIFECYCLE_TOOL_NAMES
from sidekick.mcp.server import create_mcp_server
from tests.support.settings import make_settings

TOOLS = ("list_trash", "move_to_trash", "restore_from_trash")


def test_the_lifecycle_tool_names_are_exactly_the_three_pinned_here() -> None:
    assert LIFECYCLE_TOOL_NAMES == TOOLS


@pytest.mark.asyncio
async def test_the_public_surface_has_no_tool_reaching_permanent_removal() -> None:
    tools = await create_mcp_server(
        create_container(make_settings()), enable_auth=False
    ).list_tools()

    names = {tool.name for tool in tools}
    assert set(TOOLS) <= names
    for tool in tools:
        text = f"{tool.name} {tool.description} {tool.parameters} {tool.output_schema}".lower()
        assert "permanent-remove" not in text and "permanently_remove" not in text
        assert "purge" not in text and "empty_trash" not in text

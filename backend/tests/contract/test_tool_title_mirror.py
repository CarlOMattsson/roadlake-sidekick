"""Every MCP tool carries its display title in `annotations.title` as well as `title`.

Claude.ai showed raw tool names for tools whose annotations carried no title. Whether the host reads
`annotations.title` is a working hypothesis. The server mirrors the title centrally when it lists
tools; this pins that for the whole curated surface.
"""

import pytest

from sidekick.mcp.export_contract import export as export_mcp


@pytest.mark.asyncio
async def test_every_tool_mirrors_its_title_into_annotations() -> None:
    tools = await export_mcp()

    assert tools
    for tool in tools:
        assert tool["title"], tool["name"]
        assert tool["annotations"] is not None, tool["name"]
        assert tool["annotations"]["title"] == tool["title"], tool["name"]

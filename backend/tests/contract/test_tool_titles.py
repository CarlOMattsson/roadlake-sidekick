"""Tool titles follow the app language (`SIDEKICK_MCP_APP_LOCALE`); names and descriptions do not.

The titles live in one table, `sidekick.mcp.titles.TOOL_TITLES`, a `{"sv": ..., "en": ...}` pair per
tool name. Swedish is the default and must read as before; English must be complete and free of
Swedish letters.
"""

import pytest

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.titles import TOOL_TITLES
from tests.db import database_factory
from tests.support.settings import make_settings

SWEDISH_LETTERS = set("åäöÅÄÖ")


async def _tools(locale: str) -> dict[str, dict[str, str | None]]:
    settings = make_settings().model_copy(update={"mcp_app_locale": locale})
    server = create_mcp_server(create_container(settings, database_factory()), enable_auth=False)
    return {
        tool.name: {
            "title": tool.title,
            "annotation_title": tool.annotations.title if tool.annotations else None,
            "description": tool.description,
        }
        for tool in await server.list_tools()
    }


def test_every_title_is_a_complete_pair_with_a_clean_english_side() -> None:
    assert TOOL_TITLES
    for name, titles in TOOL_TITLES.items():
        assert set(titles) == {"sv", "en"}, name
        assert titles["sv"].strip() and titles["en"].strip(), name
        assert not SWEDISH_LETTERS & set(titles["en"]), (name, titles["en"])


@pytest.mark.asyncio
async def test_swedish_is_the_default_and_every_tool_has_a_table_row() -> None:
    tools = await _tools("sv")

    assert set(tools) == set(TOOL_TITLES), "a tool needs a row in sidekick.mcp.titles.TOOL_TITLES"
    for name, tool in tools.items():
        assert tool["title"] == TOOL_TITLES[name]["sv"], name
        assert tool["annotation_title"] == tool["title"], name


@pytest.mark.asyncio
async def test_english_gives_every_tool_an_english_title_and_leaves_descriptions_alone() -> None:
    swedish = await _tools("sv")
    english = await _tools("en")

    assert set(english) == set(swedish)
    for name, tool in english.items():
        assert tool["title"] == TOOL_TITLES[name]["en"], name
        assert tool["annotation_title"] == tool["title"], name
        assert not SWEDISH_LETTERS & set(tool["title"] or ""), (name, tool["title"])
        assert tool["description"] == swedish[name]["description"], name

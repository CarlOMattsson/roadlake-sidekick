"""MCP `search`: read-only schema, two text blocks, and no Journal text in any result (D-058)."""

import json
from datetime import date
from typing import Any, cast
from uuid import UUID

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import MAX_CURSOR_LENGTH, Actor
from tests.db import database_factory
from tests.mcp.harness import SwitchableServer
from tests.support.search_fixtures import insert_entry
from tests.support.settings import make_settings

JOURNAL_WORD = "zephyrquokka"
JOURNAL_TEXT = f"Anteckning om {JOURNAL_WORD} och budgeten för hösten."
JOURNAL_DATE = "2026-07-21"
SOURCE_ARGS: dict[str, Any] = {
    "source_type": "manual_text",
    "journal_date": JOURNAL_DATE,
    "occurred_at": "2026-07-21T09:00:00Z",
    "source_recorded_at": "2026-07-24T08:00:00Z",
    "raw_text": JOURNAL_TEXT,
    "language": "sv",
    "idempotency_key": "search-mcp-source-1",
}


def _open_objects(node: Any, path: str = "$") -> list[str]:
    """Paths of object schemas that accept extra keys (FastMCP inlines the output schema)."""
    found: list[str] = []
    if isinstance(node, dict):
        mapping = cast(dict[str, Any], node)
        if "properties" in mapping and mapping.get("additionalProperties") is not False:
            found.append(path)
        for key, value in mapping.items():
            found.extend(_open_objects(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(cast(list[Any], node)):
            found.extend(_open_objects(value, f"{path}[{index}]"))
    return found


def make_actor_and_container() -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user("search-mcp-owner", "Search MCP Owner")
    actor = Actor(
        user_id,
        frozenset(
            {"journal:read", "journal:write", "tasks:read", "projects:read", "contacts:read"}
        ),
    )
    return container, actor


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_tool_schema_is_read_only_and_bounded() -> None:
    container, actor = make_actor_and_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    tool = tools["search"]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.inputSchema["additionalProperties"] is False
    assert tool.inputSchema["required"] == ["query"]
    properties = tool.inputSchema["properties"]
    assert properties["query"]["minLength"] == 2
    assert properties["query"]["maxLength"] == 100
    assert properties["limit"]["minimum"] == 1
    assert properties["limit"]["maximum"] == 25
    assert f'"maxLength": {MAX_CURSOR_LENGTH}' in json.dumps(properties["cursor"])
    kinds_schema = json.dumps(properties["kinds"])
    for kind in ("task", "project", "contact", "journal"):
        assert f'"{kind}"' in kinds_schema

    assert tool.outputSchema is not None
    assert "owner_id" not in json.dumps(tool.outputSchema)
    assert _open_objects(tool.outputSchema) == []
    journal_page = tool.outputSchema["properties"]["journal"]["anyOf"][0]
    journal_hit = journal_page["properties"]["hits"]["items"]["properties"]
    assert set(journal_hit) == {"id", "id_type", "journal_date", "matched_in", "title"}
    assert set(journal_page["properties"]["hits"]["items"]["required"]) == set(journal_hit)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_returns_two_text_blocks_without_journal_text() -> None:
    container, actor = make_actor_and_container()
    switchable = SwitchableServer.build(container, actor)

    async with switchable.client(actor) as client:
        created = await client.call_tool("create_journal_source", SOURCE_ARGS)
        assert created.structured_content is not None
        found = await client.call_tool("search", {"query": JOURNAL_WORD, "kinds": ["journal"]})

    assert found.is_error is not True
    assert len(found.content) == 2, "expected a summary block and a compact JSON block"
    first, second = found.content
    assert isinstance(first, TextContent) and isinstance(second, TextContent)
    summary = first.text
    block_two = second.text
    assert summary.startswith("Found 1 journal note")

    assert found.structured_content is not None
    hits = found.structured_content["journal"]["hits"]
    assert len(hits) == 1
    assert set(hits[0]) == {"id", "id_type", "journal_date", "matched_in", "title"}
    assert hits[0]["journal_date"] == JOURNAL_DATE
    assert hits[0]["title"] is None, "a source without an entry has a null title"

    decoded = json.loads(block_two)
    assert decoded["journal"]["hits"][0]["id"] == hits[0]["id"]

    serialized_structured = json.dumps(found.structured_content, ensure_ascii=False)
    for surface in (summary, block_two, serialized_structured):
        assert JOURNAL_WORD not in surface
        assert "budgeten" not in surface
        assert "Anteckning" not in surface


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_enforces_kind_scope_and_reports_searched_kinds() -> None:
    container, actor = make_actor_and_container()
    no_journal = Actor(actor.user_id, frozenset({"tasks:read"}))
    switchable = SwitchableServer.build(container, no_journal)

    async with switchable.client(no_journal) as client:
        with pytest.raises(ToolError):
            await client.call_tool("search", {"query": JOURNAL_WORD, "kinds": ["journal"]})
        omitted = await client.call_tool("search", {"query": JOURNAL_WORD})

    assert omitted.is_error is not True
    assert omitted.structured_content is not None
    assert omitted.structured_content["searched"] == ["task"]
    assert "journal" not in omitted.structured_content


@pytest.mark.asyncio
@pytest.mark.integration
async def test_journal_entry_hit_carries_its_title_and_no_summary_or_text() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("search-mcp-title-owner", "Owner")
    actor = Actor(user_id, frozenset({"journal:read", "journal:write"}))
    switchable = SwitchableServer.build(container, actor)
    entry_title = "Budgetmötet"

    async with switchable.client(actor) as client:
        created = await client.call_tool("create_journal_source", SOURCE_ARGS)
        assert created.structured_content is not None
        source_id = UUID(created.structured_content["source"]["id"])
        entry_id = insert_entry(
            factory,
            user_id,
            source_id,
            entry_title,
            summary="Sammanfattningssentinel",
            journal_date=date.fromisoformat(JOURNAL_DATE),
        )
        found = await client.call_tool("search", {"query": JOURNAL_WORD, "kinds": ["journal"]})

    assert found.is_error is not True
    assert found.structured_content is not None
    [hit] = found.structured_content["journal"]["hits"]
    assert hit["id"] == str(entry_id)
    assert hit["id_type"] == "entry"
    assert hit["title"] == entry_title

    assert len(found.content) == 2
    summary = cast(TextContent, found.content[0]).text
    block_two = cast(TextContent, found.content[1]).text
    assert json.loads(block_two)["journal"]["hits"][0]["title"] == entry_title
    serialized_structured = json.dumps(found.structured_content, ensure_ascii=False)
    for surface in (summary, block_two, serialized_structured):
        assert "Sammanfattningssentinel" not in surface
        assert JOURNAL_WORD not in surface
        assert "budgeten" not in surface


@pytest.mark.asyncio
@pytest.mark.integration
async def test_task_hit_carries_version_and_text_row_ends_with_it() -> None:
    container, _ = make_actor_and_container()
    user_id = container.auth.provision_user("search-mcp-version-owner", "Owner")
    actor = Actor(user_id, frozenset({"tasks:read", "tasks:write"}))
    task = container.tasks.create(
        actor, title="Betala hyran", idempotency_key="search-mcp-version-task"
    )
    switchable = SwitchableServer.build(container, actor)

    async with switchable.client(actor) as client:
        found = await client.call_tool("search", {"query": "hyran", "kinds": ["task"]})

    assert found.is_error is not True
    assert found.structured_content is not None
    [hit] = found.structured_content["tasks"]["hits"]
    assert hit["id"] == str(task.id)
    assert hit["version"] == task.version

    summary = cast(TextContent, found.content[0]).text
    [row] = [line for line in summary.splitlines() if line.startswith(f"- task {task.id}")]
    assert row.endswith(f"| v{task.version}")

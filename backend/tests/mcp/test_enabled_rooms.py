"""A room that is switched off (`SIDEKICK_ENABLED_ROOMS`) takes its MCP tools with it.

Nothing here needs a database: the server is built and its listing read, no tool is called.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import FastMCP

from sidekick.api.app import create_container
from sidekick.lifecycle import RecordKind
from sidekick.mcp.lifecycle import _READ_SCOPE_BY_KIND
from sidekick.mcp.rooms import ROOM_TOOLS, TOOL_ROOM, tool_is_enabled
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.config import Settings
from sidekick.shared.rooms import ROOMS, disabled_scopes
from tests.contract_counts import MCP_TOOLS_SNAPSHOT
from tests.support.settings import make_settings

SNAPSHOT_TOOLS = frozenset(
    tool["name"] for tool in json.loads(MCP_TOOLS_SNAPSHOT.read_text(encoding="utf-8"))
)


def _settings(rooms: str) -> Settings:
    """The test settings with the rooms set directly, so the validator is not what is under test."""
    return make_settings().model_copy(update={"enabled_rooms": rooms})


def _server(rooms: str) -> FastMCP:
    return create_mcp_server(create_container(_settings(rooms)), enable_auth=False)


async def _names(rooms: str) -> frozenset[str]:
    return frozenset(tool.name for tool in await _server(rooms).list_tools())


def test_every_tool_of_the_contract_has_exactly_one_room() -> None:
    assert frozenset(TOOL_ROOM) == SNAPSHOT_TOOLS
    assert sum(len(tools) for tools in ROOM_TOOLS.values()) == len(SNAPSHOT_TOOLS)
    assert set(ROOM_TOOLS) == set(ROOMS)


def test_a_tool_outside_the_table_is_kept() -> None:
    assert tool_is_enabled("a_tool_outside_the_table", {"work"})
    assert not tool_is_enabled("write_journal_entry", {"work"})
    assert tool_is_enabled("write_journal_entry", {"work", "journal"})


@pytest.mark.asyncio
async def test_a_work_only_instance_can_still_delete_and_undo() -> None:
    names = await _names("work")

    assert {"list_trash", "move_to_trash", "restore_from_trash"} <= names


def test_the_trash_skips_the_records_of_a_room_that_is_off() -> None:
    """The trash lists a kind only to an actor who reads it; an off room's scopes are taken off."""
    off = disabled_scopes({"work", "control"})
    for kind, scope in _READ_SCOPE_BY_KIND.items():
        if kind in {RecordKind.CONTACT, RecordKind.JOURNAL_ENTRY, RecordKind.SHOPPING_ITEM}:
            assert scope in off, kind


@pytest.mark.asyncio
async def test_with_every_room_on_the_tools_are_the_contract() -> None:
    assert await _names(",".join(ROOMS)) == SNAPSHOT_TOOLS


@pytest.mark.asyncio
async def test_a_work_only_instance_registers_the_work_tools_and_nothing_else() -> None:
    names = await _names("work")

    assert names == frozenset(ROOM_TOOLS["work"])
    for room in ("journal", "shopping", "contacts", "control"):
        assert not names & frozenset(ROOM_TOOLS[room]), room


@pytest.mark.asyncio
@pytest.mark.parametrize("room", ["journal", "shopping", "contacts", "control"])
async def test_each_room_brings_back_only_its_own_tools(room: str) -> None:
    names = await _names(f"work,{room}")

    assert names == frozenset(ROOM_TOOLS["work"]) | frozenset(ROOM_TOOLS[room])


@pytest.mark.asyncio
async def test_the_journal_cannot_be_written_when_the_journal_is_off() -> None:
    names = await _names("work,shopping,contacts,control")

    assert "write_journal_entry" not in names
    assert "get_journal_day" not in names
    assert "add_shopping_items" in names
    assert "create_contact" in names


@pytest.mark.asyncio
async def test_the_instructions_name_only_the_rooms_that_are_on() -> None:
    work_only = _server("work").instructions or ""
    everything = _server(",".join(ROOMS)).instructions or ""

    for name in ("write_journal_entry", "add_shopping_items", "create_contact", "journal"):
        assert name not in work_only, name
        assert name in everything, name
    assert "Always a card" not in work_only
    assert "Always a card: add_shopping_items" in everything


@pytest.mark.asyncio
async def test_the_instructions_keep_the_rooms_that_stay() -> None:
    text = _server("work,journal").instructions or ""

    assert "tasks, projects, agenda, journal." in text
    assert "(att göra, idag, projekt, dagbok)" in text
    assert "Always a card: write_journal_entry." in text
    assert "add_contact_alias" not in text

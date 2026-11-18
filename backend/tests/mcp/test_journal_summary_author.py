"""Whose words an entry's summary holds: the owner's own, or Claude's.

An entry written by hand in the app has no summary of Claude's: her text is the entry's text, so the
entry shows it and she can correct it. The record says `summary_by: "you"` while it is hers.
"""

from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client

from sidekick.api.app import Container, create_container
from sidekick.mcp.change_source import APP_ORIGIN_META
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

APP = {APP_ORIGIN_META: "app"}
DAY = date(2026, 11, 2).isoformat()


def _setup() -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    owner_id = container.auth.provision_user("summary-owner", "Summary Owner")
    return container, Actor(owner_id, frozenset(MCP_SCOPES))


def _client(container: Container, actor: Actor) -> Client[Any]:
    return Client(create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False))


async def _write(client: Client[Any], meta: dict[str, str] | None, **fields: Any) -> dict[str, Any]:
    result = await client.call_tool(
        "write_journal_entry",
        {"journal_date": DAY, "title": "Dag", "idempotency_key": f"w-{uuid4()}", **fields},
        meta=meta,
    )
    assert result.structured_content is not None
    return result.structured_content["entry"]


async def _update(
    client: Client[Any], meta: dict[str, str] | None, entry: dict[str, Any], **fields: Any
) -> dict[str, Any]:
    result = await client.call_tool(
        "update_journal_entry",
        {
            "entry_id": entry["id"],
            "expected_version": entry["version"],
            "idempotency_key": f"u-{uuid4()}",
            **fields,
        },
        meta=meta,
    )
    assert result.structured_content is not None
    return result.structured_content["entry"]


async def _read(client: Client[Any], entry: dict[str, Any]) -> dict[str, Any]:
    result = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
    assert result.structured_content is not None
    return result.structured_content["entry"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_text_written_by_hand_is_the_entrys_own_text() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        written = await _write(client, APP, title="Tacksam", source_text="Sov dåligt i natt.")
        read = await _read(client, written)
    assert written["summary"] == "Sov dåligt i natt."
    assert written["summary_by"] == "you"
    assert read["summary"] == "Sov dåligt i natt."
    assert read["summary_by"] == "you"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_summary_claude_wrote_is_not_the_owners() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        written = await _write(client, None, source_text="Lång text.", summary="Kort version.")
        read = await _read(client, written)
    assert written["summary"] == "Kort version."
    assert read["summary_by"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_text_too_long_for_a_summary_stays_in_the_original() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        written = await _write(client, APP, source_text="ord " * 3_000)
    assert written["summary"] is None
    assert written["summary_by"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_correcting_the_summary_by_hand_makes_it_hers_and_a_title_change_does_not() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        written = await _write(client, None, source_text="Original.", summary="Claudes text.")
        replace = {"key_points": []}
        retitled = await _update(
            client, APP, written, title="Ny rubrik", summary="Claudes text.", **replace
        )
        assert (await _read(client, retitled))["summary_by"] is None
        corrected = await _update(
            client, APP, retitled, title="Ny rubrik", summary="Min rättade text.", **replace
        )
        assert (await _read(client, corrected))["summary_by"] == "you"
        rewritten = await _update(
            client, None, corrected, title="Ny rubrik", summary="Claude skrev om.", **replace
        )
        assert (await _read(client, rewritten))["summary_by"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_text_added_to_an_entry_with_her_own_words_shows_in_the_entry() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        written = await _write(client, APP, source_text="Morgon.")
        added = await _update(client, APP, written, append_text="Kväll.")
        read = await _read(client, added)
    assert read["summary"] == "Morgon.\n\nKväll."
    assert read["summary_by"] == "you"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_text_added_to_claudes_summary_stays_in_the_original() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        written = await _write(client, None, source_text="Original.", summary="Claudes text.")
        added = await _update(client, APP, written, append_text="Tillägg.")
        read = await _read(client, added)
    assert read["summary"] == "Claudes text."
    assert read["summary_by"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_entry_kept_out_of_memory_says_so_and_can_be_brought_back() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        kept = await _write(client, APP, title="Känsligt", source_text="Orolig.")
        other = await _write(client, APP, title="Annat", source_text="Lugn.")
        before = await _read(client, kept)
        await client.call_tool(
            "exclude_from_memory", {"kind": "journal_entry", "id": kept["id"]}, meta=APP
        )
        after = await _read(client, kept)
        day = await client.call_tool("get_journal_day", {"journal_date": DAY})
        await client.call_tool(
            "exclude_from_memory",
            {"kind": "journal_entry", "id": kept["id"], "excluded": False},
            meta=APP,
        )
        restored = await _read(client, kept)
    assert day.structured_content is not None
    flags = {e["id"]: e["memory_excluded"] for e in day.structured_content["entries"]}
    assert (before["memory_excluded"], after["memory_excluded"]) == (False, True)
    assert flags == {kept["id"]: True, other["id"]: False}
    assert restored["memory_excluded"] is False

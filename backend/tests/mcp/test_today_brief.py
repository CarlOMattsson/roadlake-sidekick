"""get_today_brief: one read-only summary of the owner's day, zone-aware and scope-aware.

The brief reads the same application use cases as the Work agenda, the Journal day and the shopping
lists. Each part needs its own read scope and is left out without an error when that scope is
missing. The clock is fixed so the owner's day in `Settings.owner_zone` is deterministic.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

OWNER_ZONE = ZoneInfo("Europe/Stockholm")
TODAY = "2026-10-29"
NOON = datetime(2026, 10, 29, 12, 0, tzinfo=OWNER_ZONE)
ALL_SCOPES = frozenset(
    {
        "tasks:read",
        "tasks:write",
        "projects:read",
        "journal:read",
        "journal:write",
        "contacts:read",
        "shopping:read",
        "shopping:write",
    }
)
READ_SCOPES = frozenset({"tasks:read", "journal:read", "shopping:read"})


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _setup(now: datetime) -> tuple[Container, UUID]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("brief-owner", "Brief Owner")
    # The agenda reads the clock of the Work context service, so the day is fixed through it.
    container.contexts.clock = FixedClock(now)
    return container, owner


def _server(container: Container, actor: Actor) -> Any:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _data(result: Any) -> dict[str, Any]:
    assert result.structured_content is not None
    return result.structured_content


def _text(result: Any) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def _task(client: Client, title: str, due_at: str, key: str) -> dict[str, Any]:
    created = await client.call_tool(
        "create_task",
        {"title": title, "due_at": due_at, "idempotency_key": f"brief-task-{key}"},
    )
    return _data(created)["task"]


async def _seed_shopping(client: Client) -> None:
    created = await client.call_tool(
        "create_shopping_list", {"name": "Veckohandel", "idempotency_key": "brief-list-1"}
    )
    list_id = _data(created)["shopping_list"]["id"]
    added = await client.call_tool(
        "add_shopping_items",
        {
            "list_id": list_id,
            "items": [
                {"client_ref": "mjolk", "name": "Mjolk"},
                {"client_ref": "brod", "name": "Brod"},
            ],
            "idempotency_key": "brief-items-1",
        },
    )
    milk = _data(added)["items"][0]["item"]
    await client.call_tool(
        "set_shopping_item_purchased",
        {
            "item_id": milk["id"],
            "purchased": True,
            "version": milk["version"],
            "idempotency_key": "brief-purchase-1",
        },
    )


async def _seed_journal_today(client: Client) -> None:
    source = await client.call_tool(
        "create_journal_source",
        {
            "source_type": "manual_text",
            "journal_date": TODAY,
            "occurred_at": f"{TODAY}T09:00:00+01:00",
            "source_recorded_at": f"{TODAY}T09:05:00+01:00",
            "raw_text": "En kort dagboksanteckning.",
            "language": "sv",
            "idempotency_key": "brief-source-1",
        },
    )
    await client.call_tool(
        "create_manual_journal_entry",
        {
            "source_id": _data(source)["source"]["id"],
            "title": "Dagens post",
            "summary": "Kort sammanfattning.",
            "key_points": [{"kind": "decision", "text": "Följ upp."}],
            "project_ids": [],
            "task_ids": [],
            "contact_ids": [],
            "idempotency_key": "brief-entry-1",
        },
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_empty_day_reports_zero_counts_and_an_empty_diary() -> None:
    container, owner = _setup(NOON)
    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        brief = await client.call_tool("get_today_brief", {})

    structured = _data(brief)
    assert structured["day"] == TODAY
    assert structured["tasks"] == {
        "overdue_count": 0,
        "today_count": 0,
        "upcoming_7d_count": 0,
        "items": [],
        "truncated": False,
        "capped": False,
    }
    assert structured["diary"] == {"entry_count": 0, "has_summary": False, "truncated": False}
    assert structured["shopping"] == {"open_list_count": 0, "open_item_count": 0, "lists": []}
    assert _text(brief) == (
        "Du har inga försenade uppgifter och inga uppgifter idag, och inga uppgifter inom 7 dagar. "
        "Dagboken är tom idag. Inga öppna inköpslistor."
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_overdue_and_today_come_first_with_ids_versions_and_counts() -> None:
    container, owner = _setup(NOON)
    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        overdue = await _task(client, "Forsenad uppgift", "2026-10-27T09:00:00+01:00", "b-overdue")
        today = await _task(client, "Dagens uppgift", "2026-10-29T18:00:00+01:00", "b-today")
        await _task(client, "Kommande uppgift", "2026-11-01T09:00:00+01:00", "b-upcoming")
        await _seed_journal_today(client)
        await _seed_shopping(client)

    async with Client(_server(container, Actor(owner, READ_SCOPES))) as client:
        brief = await client.call_tool("get_today_brief", {})

    structured = _data(brief)
    tasks = structured["tasks"]
    assert (tasks["overdue_count"], tasks["today_count"], tasks["upcoming_7d_count"]) == (1, 1, 1)
    assert [(row["id"], row["agenda_group"]) for row in tasks["items"]] == [
        (overdue["id"], "overdue"),
        (today["id"], "today"),
    ]
    for row, source in zip(tasks["items"], (overdue, today), strict=True):
        assert row["version"] == source["version"]
        assert row["kind"] == "task"
    assert tasks["truncated"] is False
    assert structured["diary"] == {"entry_count": 1, "has_summary": False, "truncated": False}
    shopping = structured["shopping"]
    assert shopping["open_list_count"] == 1
    assert shopping["open_item_count"] == 1
    assert shopping["lists"][0]["name"] == "Veckohandel"
    assert shopping["lists"][0]["open_item_count"] == 1
    assert "owner_id" not in str(structured)

    summary = _text(brief)
    assert summary.startswith(
        "Du har 1 försenad uppgift och 1 uppgift idag, och 1 uppgift inom 7 dagar."
    )
    assert "Dagboken har 1 post idag, utan dagssammanfattning." in summary
    assert "Du har 1 öppen inköpslista med 1 ej köpt vara." in summary
    # The summary is read aloud, so it names no record titles.
    assert "Forsenad uppgift" not in summary
    assert "Dagens uppgift" not in summary


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rows_are_capped_at_ten_and_the_count_stays_complete() -> None:
    container, owner = _setup(NOON)
    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        for index in range(12):
            await _task(client, f"Forsenad {index}", "2026-10-25T09:00:00+01:00", f"b-cap-{index}")

    async with Client(_server(container, Actor(owner, READ_SCOPES))) as client:
        brief = await client.call_tool("get_today_brief", {})

    tasks = _data(brief)["tasks"]
    assert tasks["overdue_count"] == 12
    assert len(tasks["items"]) == 10
    assert tasks["truncated"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_missing_scope_leaves_its_part_out_without_an_error() -> None:
    container, owner = _setup(NOON)
    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        await _task(client, "Dagens uppgift", "2026-10-29T18:00:00+01:00", "b-scope")
        await _seed_journal_today(client)
        await _seed_shopping(client)

    async with Client(_server(container, Actor(owner, frozenset({"tasks:read"})))) as client:
        tasks_only = await client.call_tool("get_today_brief", {})
    assert set(_data(tasks_only)) == {"day", "tasks"}
    assert _data(tasks_only)["tasks"]["today_count"] == 1
    assert not tasks_only.is_error

    async with Client(_server(container, Actor(owner, frozenset()))) as client:
        no_scope = await client.call_tool("get_today_brief", {})
    assert set(_data(no_scope)) == {"day"}
    assert _data(no_scope)["day"] == TODAY
    assert _text(no_scope) == ("Inga delar av dagens läge är tillgängliga med dina behörigheter.")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_day_and_today_follow_the_owner_zone_not_utc() -> None:
    # 23:30 UTC on 28 October is 00:30 on 29 October in Stockholm: the owner's day is already 29.
    container, owner = _setup(datetime(2026, 10, 28, 23, 30, tzinfo=UTC))
    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        late_today = await _task(
            client, "Sen dagens uppgift", "2026-10-29T23:30:00+01:00", "b-zone-today"
        )
        await _task(client, "Tidig i morgon", "2026-10-30T00:30:00+01:00", "b-zone-tomorrow")

    async with Client(_server(container, Actor(owner, READ_SCOPES))) as client:
        brief = await client.call_tool("get_today_brief", {})

    structured = _data(brief)
    assert structured["day"] == TODAY
    tasks = structured["tasks"]
    assert (tasks["overdue_count"], tasks["today_count"], tasks["upcoming_7d_count"]) == (0, 1, 1)
    assert [row["id"] for row in tasks["items"]] == [late_today["id"]]
    assert tasks["items"][0]["agenda_group"] == "today"

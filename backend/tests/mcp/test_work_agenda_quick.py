"""`get_work_agenda` with `max_minutes` and `include_undated`: "I have a quarter of an hour" and
"who do I call". Both are optional; without them the agenda is unchanged."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

WRITE_SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
READ_SCOPES = frozenset({"tasks:read"})


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _in(days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


async def _seed(container: Container, owner: Any) -> dict[str, str]:
    """Ring mamma (10 min, undated, telefon), Ring elektrikern (5 min, due, telefon),
    Skriv rapport (60 min, due), Städa (undated, no estimate, telefon), Klar (completed)."""

    ids: dict[str, str] = {}
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:

        async def create(name: str, **extra: Any) -> dict[str, Any]:
            created = await client.call_tool(
                "create_task", {"title": name, "idempotency_key": f"quick-{name}", **extra}
            )
            task = created.structured_content["task"]
            ids[name] = task["id"]
            return task

        await create("Ring mamma", estimated_minutes=10, tags=["telefon"])
        await create("Ring elektrikern", estimated_minutes=5, due_at=_in(1), tags=["telefon"])
        await create("Skriv rapport", estimated_minutes=60, due_at=_in(2))
        await create("Städa", tags=["telefon"])
        done = await create("Klar", estimated_minutes=10)
        await client.call_tool(
            "update_task",
            {
                "task_id": done["id"],
                "version": done["version"],
                "idempotency_key": "quick-Klar-done",
                "changes": {"status": "completed"},
            },
        )
    return ids


async def _agenda(container: Container, owner: Any, **args: Any) -> Any:
    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        return await client.call_tool("get_work_agenda", {"limit": 100, **args})


@pytest.mark.asyncio
@pytest.mark.integration
async def test_plain_agenda_is_unchanged_and_leaves_out_undated_tasks() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    ids = await _seed(container, owner)

    plain = await _agenda(container, owner)

    got = {item["id"] for item in plain.structured_content["items"]}
    assert got == {ids["Ring elektrikern"], ids["Skriv rapport"]}
    assert plain.structured_content["filters"] == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_include_undated_lists_open_undated_tasks() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    ids = await _seed(container, owner)

    agenda = await _agenda(container, owner, include_undated=True, tags=["telefon"])

    items = agenda.structured_content["items"]
    assert [item["id"] for item in items] == [
        ids["Ring elektrikern"],
        ids["Ring mamma"],
        ids["Städa"],
    ]
    assert agenda.structured_content["filters"]["include_undated"] == "True"
    first_line = agenda.content[0].text.splitlines()[0]
    assert "Ring mamma" in first_line
    assert ids["Ring mamma"] not in first_line


@pytest.mark.asyncio
@pytest.mark.integration
async def test_max_minutes_keeps_only_estimated_tasks_that_fit() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    ids = await _seed(container, owner)

    quarter = await _agenda(
        container, owner, max_minutes=15, include_undated=True, actionable="now"
    )

    items = quarter.structured_content["items"]
    assert [item["id"] for item in items] == [ids["Ring elektrikern"], ids["Ring mamma"]]
    assert all(item["estimated_minutes"] <= 15 for item in items)
    text = quarter.content[0].text
    first_line = text.splitlines()[0]
    assert first_line.startswith("2 tasks that fit in 15 minutes: ")
    assert ids["Ring mamma"] not in first_line
    assert f"{ids['Ring mamma']} v1 | Ring mamma | 10 min | no date" in text
    assert quarter.structured_content["filters"]["max_minutes"] == "15"

    dated_only = await _agenda(container, owner, max_minutes=15)
    assert [item["id"] for item in dated_only.structured_content["items"]] == [
        ids["Ring elektrikern"]
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_max_minutes_with_nothing_that_fits_says_so() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    await _seed(container, owner)

    agenda = await _agenda(container, owner, max_minutes=1, include_undated=True)

    assert agenda.structured_content["items"] == []
    assert agenda.content[0].text.splitlines()[0] == "No open tasks that fit in 1 minute."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_max_minutes_is_bounded_and_paging_keeps_the_filters() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    await _seed(container, owner)

    with pytest.raises(ToolError):
        await _agenda(container, owner, max_minutes=0)

    first = await _agenda(container, owner, max_minutes=15, include_undated=True, limit=1)
    cursor = first.structured_content["next_cursor"]
    assert cursor is not None
    second = await _agenda(
        container, owner, max_minutes=15, include_undated=True, limit=1, cursor=cursor
    )
    assert len(second.structured_content["items"]) == 1
    assert second.structured_content["items"][0]["id"] != first.structured_content["items"][0]["id"]

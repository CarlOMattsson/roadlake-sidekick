"""A waiting Task's follow-up day stands in the agenda, whatever its due date says.

The agenda date of a Task is the earlier of its due time and its follow-up time, and a follow-up
only counts while the Task is waiting and open. The Task keeps its own `due_at` and `follow_up_at`.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from sidekick.work.application.work_lists import owner_day_bounds
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _in(days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


async def _create(client: Client, title: str, key: str, **extra: Any) -> dict[str, Any]:
    created = await client.call_tool(
        "create_task", {"title": title, "idempotency_key": key, **extra}
    )
    assert not created.is_error, created.structured_content
    return created.structured_content["task"]


async def _change(
    client: Client, task: dict[str, Any], key: str, changes: dict[str, Any]
) -> dict[str, Any]:
    updated = await client.call_tool(
        "update_task",
        {
            "task_id": task["id"],
            "version": task["version"],
            "idempotency_key": key,
            "changes": changes,
        },
    )
    assert not updated.is_error, updated.structured_content
    return updated.structured_content["task"]


async def _wait(
    client: Client, task: dict[str, Any], key: str, follow_up_at: str
) -> dict[str, Any]:
    return await _change(
        client, task, key, {"waiting_since": _in(-1), "follow_up_at": follow_up_at}
    )


async def _agenda(client: Client) -> dict[str, dict[str, Any]]:
    agenda = await client.call_tool("get_work_agenda", {"limit": 100})
    assert not agenda.is_error, agenda.structured_content
    return {item["id"]: item for item in agenda.structured_content["items"]}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_waiting_task_without_a_due_date_is_overdue_after_its_follow_up_day() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("follow-overdue", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        task = await _create(client, "Anders svarar", "follow-overdue-task")
        task = await _wait(client, task, "follow-overdue-wait", _in(-1))

        items = await _agenda(client)

    assert items[task["id"]]["agenda_group"] == "overdue"
    assert items[task["id"]]["due_at"] is None
    assert items[task["id"]]["follow_up_at"] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_follow_up_later_today_puts_the_task_in_today() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("follow-today", "Owner")
    _, day_end = owner_day_bounds(datetime.now(UTC), make_settings().owner_zone)
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        task = await _create(client, "Ring tillbaka", "follow-today-task")
        task = await _wait(
            client, task, "follow-today-wait", (day_end - timedelta(minutes=1)).isoformat()
        )

        items = await _agenda(client)

    assert items[task["id"]]["agenda_group"] == "today"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_earlier_follow_up_wins_over_a_later_due_date() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("follow-earlier", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        week = await _create(client, "due in a week", "follow-earlier-a", due_at=_in(7))
        week = await _wait(client, week, "follow-earlier-a-wait", _in(2))
        plain = await _create(client, "due in four days", "follow-earlier-b", due_at=_in(4))

        items = await _agenda(client)
        ordered = list(items)

    assert items[week["id"]]["agenda_group"] == "upcoming"
    assert items[week["id"]]["due_at"] is not None
    # Sorted by the agenda date: the follow-up in two days comes before the due date in four.
    assert ordered.index(week["id"]) < ordered.index(plain["id"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_follow_up_stays_out_once_the_task_is_done() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("follow-out", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        # A follow-up cannot exist without waiting, so "done" is the only way to stop counting.
        done = await _create(client, "done waiting", "follow-out-done")
        done = await _wait(client, done, "follow-out-done-wait", _in(-1))
        completed = await client.call_tool(
            "complete_task",
            {
                "task_id": done["id"],
                "version": done["version"],
                "idempotency_key": "follow-out-done-complete",
            },
        )
        assert not completed.is_error, completed.structured_content
        items = await _agenda(client)

    assert done["id"] not in items


@pytest.mark.asyncio
@pytest.mark.integration
async def test_today_and_its_totals_follow_the_follow_up() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("follow-total", "Owner")
    actor = Actor(owner, SCOPES)
    async with Client(_server_for(container, actor)) as client:
        late = await _create(client, "late follow-up", "follow-total-late")
        await _wait(client, late, "follow-total-late-wait", _in(-1))
        far = await _create(client, "far follow-up", "follow-total-far", due_at=_in(9))
        await _wait(client, far, "follow-total-far-wait", _in(5))

    today = container.work_lists.work_today_page(actor, limit=10)

    assert [item.title for item in today.items] == ["late follow-up"]
    assert today.overdue_total == 1
    assert today.total == 1

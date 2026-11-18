"""reschedule_tasks keeps a Task's due time of day on its new day.

A Task with a clock time (anything but 23:59) gets its push reminder from that time, so moving it
to another day must not turn it into a bare date. A Task without one, or without a due date, lands
on 23:59 in the owner's zone. The clock is fixed through the Task service.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.instrument import instrument_mcp
from sidekick.mcp.reschedule import register_reschedule_tools
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.types import Actor
from sidekick.tasks.domain import Task
from tests.db import database_factory
from tests.support.settings import make_settings

ZONE = make_settings().owner_zone
THURSDAY_NOON = datetime(2026, 10, 29, 12, 0, tzinfo=ZONE)
SCOPES = frozenset({"tasks:read", "tasks:write"})


class FixedClock:
    def now(self) -> datetime:
        return THURSDAY_NOON


def _setup() -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("reschedule-clock-owner", "Owner")
    container.tasks.clock = FixedClock()
    return container, Actor(owner, SCOPES)


def _server(container: Container, actor: Actor) -> FastMCP:
    mcp = FastMCP("reschedule-clock-test")
    register_reschedule_tools(
        mcp, ToolContext(container, lambda: actor, lambda name: instrument_mcp(container, name))
    )
    return mcp


def _task(container: Container, actor: Actor, title: str, due_at: datetime | None) -> Task:
    return container.tasks.create(
        actor, title=title, idempotency_key=f"clock-{uuid4().hex}", due_at=due_at
    )


async def _move(client: Client[Any], task: Task, when: str, key: str) -> dict[str, Any]:
    moved = await client.call_tool(
        "reschedule_tasks",
        {
            "items": [{"task_id": str(task.id), "expected_version": task.version, "when": when}],
            "idempotency_key": key,
        },
        raise_on_error=False,
    )
    assert not moved.is_error, moved.structured_content
    assert moved.structured_content is not None
    return moved.structured_content["tasks"][0]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_due_time_of_day_is_kept_on_the_new_day() -> None:
    container, actor = _setup()
    task = _task(container, actor, "Möte", datetime(2026, 10, 28, 17, 30, tzinfo=ZONE))

    async with Client(_server(container, actor)) as client:
        tomorrow = await _move(client, task, "tomorrow", "clock-tomorrow")

    assert datetime.fromisoformat(tomorrow["due_at"]) == datetime(2026, 10, 30, 17, 30, tzinfo=ZONE)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_task_with_a_given_date_keeps_its_time_too() -> None:
    container, actor = _setup()
    task = _task(container, actor, "Läkare", datetime(2026, 10, 28, 8, 15, tzinfo=ZONE))

    async with Client(_server(container, actor)) as client:
        moved = await _move(client, task, "2026-11-12", "clock-date")

    assert datetime.fromisoformat(moved["due_at"]) == datetime(2026, 11, 12, 8, 15, tzinfo=ZONE)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_task_without_a_time_of_day_lands_on_2359() -> None:
    container, actor = _setup()
    task = _task(container, actor, "Betala", datetime(2026, 10, 28, 23, 59, tzinfo=ZONE))

    async with Client(_server(container, actor)) as client:
        moved = await _move(client, task, "tomorrow", "clock-bare")

    assert datetime.fromisoformat(moved["due_at"]) == datetime(2026, 10, 30, 23, 59, tzinfo=ZONE)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_task_without_a_due_date_lands_on_2359() -> None:
    container, actor = _setup()
    task = _task(container, actor, "Ringa", None)

    async with Client(_server(container, actor)) as client:
        moved = await _move(client, task, "tomorrow", "clock-none")

    assert datetime.fromisoformat(moved["due_at"]) == datetime(2026, 10, 30, 23, 59, tzinfo=ZONE)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_clear_still_clears_the_due_date_of_a_task_with_a_time() -> None:
    container, actor = _setup()
    task = _task(container, actor, "Möte", datetime(2026, 10, 28, 17, 30, tzinfo=ZONE))

    async with Client(_server(container, actor)) as client:
        moved = await _move(client, task, "clear", "clock-clear")

    assert moved["due_at"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_retry_with_the_same_key_answers_the_same_and_moves_nothing_twice() -> None:
    container, actor = _setup()
    task = _task(container, actor, "Möte", datetime(2026, 10, 28, 17, 30, tzinfo=ZONE))

    async with Client(_server(container, actor)) as client:
        first = await _move(client, task, "tomorrow", "clock-retry")
        second = await _move(client, task, "tomorrow", "clock-retry")

    assert second == first
    assert datetime.fromisoformat(second["due_at"]) == datetime(2026, 10, 30, 17, 30, tzinfo=ZONE)

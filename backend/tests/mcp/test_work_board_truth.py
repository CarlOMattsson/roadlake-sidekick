"""The board tells the truth about the whole list: tasks only, the most overdue first, real totals.

A page is cut from the whole selection on the server, so what stands first is what matters most,
and the counts never depend on how much of the board the page happens to hold.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
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


async def _complete(client: Client, task: dict[str, Any], key: str) -> None:
    completed = await client.call_tool(
        "complete_task",
        {"task_id": task["id"], "version": task["version"], "idempotency_key": key},
    )
    assert not completed.is_error, completed.structured_content


async def _board(client: Client, **arguments: Any) -> dict[str, Any]:
    board = await client.call_tool("get_work_board", arguments)
    assert not board.is_error, board.structured_content
    return board.structured_content


def _titles(board: dict[str, Any], status: str) -> list[str]:
    return [item["title"] for item in board["columns"].get(status, [])]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_first_page_holds_the_most_overdue_tasks_not_the_latest_changed() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("truth-overdue", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        # The overdue Tasks are written first, so the 25 most recently changed ones are later
        # Tasks: the old order would show those and leave every overdue Task off the page.
        for index in range(3):
            await _create(client, f"late {index}", f"truth-late-{index}", due_at=_in(-3 + index))
        for index in range(30):
            await _create(
                client, f"later {index:02d}", f"truth-later-{index}", due_at=_in(5 + index)
            )

        board = await _board(client, limit=25)

    todo = _titles(board, "todo")
    assert todo[:3] == ["late 0", "late 1", "late 2"]
    assert len(todo) == 25
    assert board["column_totals"]["todo"] == 33
    assert board["overdue_total"] == 3
    assert board["next_cursor"] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_steps_are_neither_listed_nor_counted_on_the_board() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("truth-steps", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        task = await _create(client, "with steps", "truth-steps-task")
        for index in range(3):
            added = await client.call_tool(
                "create_task_step",
                {
                    "task_id": task["id"],
                    "title": f"step {index}",
                    "idempotency_key": f"truth-step-{index}",
                },
            )
            assert not added.is_error, added.structured_content

        board = await _board(client, limit=50)

    kinds = {item["kind"] for items in board["columns"].values() for item in items}
    assert kinds == {"task"}
    assert board["column_totals"]["todo"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_completed_tasks_come_after_open_ones_whatever_their_dates() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("truth-done", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        done = await _create(client, "done long ago", "truth-done", due_at=_in(-30))
        await _complete(client, done, "truth-done-c")
        await _create(client, "open soon", "truth-open", due_at=_in(2))

        board = await _board(client, limit=1)

    # One slot on the page: it goes to the open Task, not the finished one with the older date.
    assert _titles(board, "todo") == ["open soon"]
    assert board["column_totals"]["completed"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_overdue_count_follows_the_board_filters_and_leaves_completed_out() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("truth-filter", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        await _create(client, "late tagged", "truth-f-1", due_at=_in(-2), tags=["client"])
        await _create(client, "late plain", "truth-f-2", due_at=_in(-1))
        await _create(client, "not due", "truth-f-3", due_at=_in(3))
        finished = await _create(client, "late finished", "truth-f-4", due_at=_in(-4))
        await _complete(client, finished, "truth-f-4c")

        whole = await _board(client)
        tagged = await _board(client, tags=["client"])

    assert whole["overdue_total"] == 2
    assert tagged["overdue_total"] == 1

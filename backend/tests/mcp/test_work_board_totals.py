"""The board's per-column totals count the whole filtered list, owner-scoped, never the page."""

from typing import Any

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

WRITE_SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
READ_SCOPES = frozenset({"tasks:read"})
EMPTY_COLUMNS = {"todo": 0, "in_progress": 0, "blocked": 0, "completed": 0}


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


async def _create(client: Client, title: str, key: str, **extra: Any) -> dict[str, Any]:
    created = await client.call_tool(
        "create_task", {"title": title, "idempotency_key": key, **extra}
    )
    return created.structured_content["task"]


async def _set_status(client: Client, task: dict[str, Any], status: str) -> None:
    changed = await client.call_tool(
        "update_task",
        {
            "task_id": task["id"],
            "version": task["version"],
            "idempotency_key": f"{task['id']}-{status}",
            "changes": {"status": status},
        },
    )
    assert not changed.is_error, changed.structured_content


async def _totals(client: Client, **arguments: Any) -> dict[str, int]:
    board = await client.call_tool("get_work_board", {"limit": 50, **arguments})
    return board.structured_content["column_totals"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_totals_count_more_tasks_than_the_page_shows_and_zero_for_empty_columns() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("totals-owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        for index in range(4):
            await _create(client, f"todo {index}", f"totals-todo-{index}")
        started = await _create(client, "started", "totals-started")
        await _set_status(client, started, "in_progress")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        board = await client.call_tool("get_work_board", {"limit": 2})
        first_page = board.structured_content
        next_page = await client.call_tool(
            "get_work_board", {"limit": 2, "cursor": first_page["next_cursor"]}
        )

    assert sum(len(items) for items in first_page["columns"].values()) == 2
    expected = {**EMPTY_COLUMNS, "todo": 4, "in_progress": 1}
    # The same totals on every page: they never depend on the limit or the cursor.
    assert first_page["column_totals"] == expected
    assert next_page.structured_content["column_totals"] == expected


@pytest.mark.asyncio
@pytest.mark.integration
async def test_totals_follow_the_status_project_and_tag_filters() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("totals-filter-owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Hem", "idempotency_key": "totals-domain"}
        )
        project = await client.call_tool(
            "create_project",
            {
                "title": "Renovering",
                "domain_id": domain.structured_content["domain"]["id"],
                "idempotency_key": "totals-project",
            },
        )
        project_id = project.structured_content["project"]["id"]
        in_project = [
            await _create(client, f"p{i}", f"totals-p-{i}", project_id=project_id, tags=["rot"])
            for i in range(3)
        ]
        await _set_status(client, in_project[0], "blocked")
        await _create(client, "elsewhere", "totals-elsewhere", tags=["rot"])
        await _create(client, "untagged", "totals-untagged")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        by_project = await _totals(client, project_id=project_id)
        by_tag = await _totals(client, tags=["rot"])
        by_status = await _totals(client, status="blocked")
        whole = await _totals(client)

    assert by_project == {**EMPTY_COLUMNS, "todo": 2, "blocked": 1}
    assert by_tag == {**EMPTY_COLUMNS, "todo": 3, "blocked": 1}
    assert by_status == {**EMPTY_COLUMNS, "blocked": 1}
    assert whole["todo"] == 4
    assert whole["blocked"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_totals_never_count_another_owners_tasks_and_an_empty_board_reads_zero() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("totals-mine", "Owner")
    other = container.auth.provision_user("totals-theirs", "Other")
    async with Client(_server_for(container, Actor(other, WRITE_SCOPES))) as client:
        for index in range(3):
            await _create(client, f"theirs {index}", f"totals-theirs-{index}")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        assert await _totals(client) == EMPTY_COLUMNS
    async with Client(_server_for(container, Actor(other, READ_SCOPES))) as client:
        assert await _totals(client) == {**EMPTY_COLUMNS, "todo": 3}

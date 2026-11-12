"""App-only board column reorder over MCP: complete columns, owner-scoped, versioned, replayable."""

from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.board import BOARD_TOOL_NAMES
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from sidekick.tasks.application import MAX_BOARD_COLUMN_REORDER
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


async def _create_tasks(client: Client, prefix: str, count: int) -> list[dict[str, Any]]:
    tasks = []
    for index in range(count):
        created = await client.call_tool(
            "create_task",
            {"title": f"{prefix} {index}", "idempotency_key": f"{prefix}-task-{index}"},
        )
        tasks.append(created.structured_content["task"])
    return tasks


async def _reorder(client: Client, status: str, pairs: list[tuple[str, int]], key: str) -> Any:
    return await client.call_tool(
        "reorder_work_board_column",
        {
            "status": status,
            "items": [{"task_id": task_id, "version": version} for task_id, version in pairs],
            "idempotency_key": key,
        },
        raise_on_error=False,
    )


async def _column_ids(client: Client, status: str) -> list[str]:
    board = await client.call_tool("get_work_board", {"limit": 100})
    return [item["id"] for item in board.structured_content["columns"][status]]


@pytest.mark.asyncio
async def test_reorder_is_app_only_and_not_listed_for_the_model() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}

    assert BOARD_TOOL_NAMES == ("reorder_work_board_column",)
    tool = tools["reorder_work_board_column"]
    assert tool.meta is not None
    assert tool.meta["ui"]["visibility"] == ["app"]
    assert "resourceUri" not in tool.meta["ui"]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.output_schema is not None
    assert set(tool.parameters["properties"]) == {"status", "items", "idempotency_key"}
    assert tool.parameters["properties"]["idempotency_key"]["minLength"] == 8
    assert tool.parameters["properties"]["items"]["minItems"] == 1
    assert tool.parameters["properties"]["items"]["maxItems"] == MAX_BOARD_COLUMN_REORDER


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reorder_writes_the_complete_column_in_the_requested_order() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("board-owner", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        first, second, third = await _create_tasks(client, "order", 3)
        # A task in another status column is not part of the todo column and must not block it.
        started = await client.call_tool(
            "update_task",
            {
                "task_id": third["id"],
                "version": third["version"],
                "idempotency_key": "order-third-started",
                "changes": {"status": "in_progress"},
            },
        )
        assert not started.is_error, started.structured_content

        reordered = await _reorder(
            client,
            "todo",
            [(second["id"], second["version"]), (first["id"], first["version"])],
            "order-todo-0001",
        )

        assert not reordered.is_error, reordered.structured_content
        placements = reordered.structured_content["items"]
        assert [item["task_id"] for item in placements] == [second["id"], first["id"]]
        assert set(placements[0]) == {"task_id", "version"}
        assert all(item["version"] > 1 for item in placements)
        text_block = reordered.content[0].text  # pyright: ignore[reportAttributeAccessIssue]
        assert second["id"] in text_block and first["id"] in text_block
        assert await _column_ids(client, "todo") == [second["id"], first["id"]]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stale_partial_and_unknown_columns_are_refused_and_change_nothing() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("stale-owner", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        first, second, third = await _create_tasks(client, "stale", 3)
        settled = await _reorder(
            client,
            "todo",
            [
                (first["id"], first["version"]),
                (second["id"], second["version"]),
                (third["id"], third["version"]),
            ],
            "stale-first-0001",
        )
        assert not settled.is_error, settled.structured_content
        current = {item["task_id"]: item["version"] for item in settled.structured_content["items"]}
        order_before = await _column_ids(client, "todo")

        stale = await _reorder(
            client,
            "todo",
            [
                (third["id"], third["version"]),
                (first["id"], first["version"]),
                (second["id"], second["version"]),
            ],
            "stale-old-0002",
        )
        assert stale.is_error
        assert stale.structured_content["code"] == "conflict"

        partial = await _reorder(
            client,
            "todo",
            [(third["id"], current[third["id"]]), (first["id"], current[first["id"]])],
            "stale-partial-003",
        )
        assert partial.is_error
        assert partial.structured_content["code"] == "validation_error"

        unknown = await _reorder(
            client,
            "todo",
            [
                (third["id"], current[third["id"]]),
                (first["id"], current[first["id"]]),
                (str(uuid4()), 1),
            ],
            "stale-unknown-04",
        )
        assert unknown.is_error
        assert unknown.structured_content["code"] == "validation_error"

        assert await _column_ids(client, "todo") == order_before


@pytest.mark.asyncio
@pytest.mark.integration
async def test_other_owners_tasks_are_not_reachable_through_the_reorder() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("reorder-owner", "Owner")
    other = container.auth.provision_user("reorder-other", "Other")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as owner_client:
        mine = await _create_tasks(owner_client, "mine", 2)
    async with Client(_server_for(container, Actor(other, SCOPES))) as other_client:
        (foreign,) = await _create_tasks(other_client, "foreign", 1)

    async with Client(_server_for(container, Actor(owner, SCOPES))) as owner_client:
        mixed = await _reorder(
            owner_client,
            "todo",
            [
                (mine[0]["id"], mine[0]["version"]),
                (mine[1]["id"], mine[1]["version"]),
                (foreign["id"], foreign["version"]),
            ],
            "foreign-mixed-0001",
        )
        assert mixed.is_error
        assert mixed.structured_content["code"] == "validation_error"
        assert foreign["id"] not in mixed.content[0].text  # pyright: ignore[reportAttributeAccessIssue]
        assert foreign["id"] not in str(mixed.structured_content)

        only_foreign = await _reorder(
            owner_client,
            "todo",
            [(foreign["id"], foreign["version"])],
            "foreign-only-0002",
        )
        assert only_foreign.is_error
        assert only_foreign.structured_content["code"] == "validation_error"
        assert set(await _column_ids(owner_client, "todo")) == {mine[0]["id"], mine[1]["id"]}

    async with Client(_server_for(container, Actor(other, SCOPES))) as other_client:
        untouched = await other_client.call_tool("get_task", {"task_id": foreign["id"]})
        assert untouched.structured_content["task"]["version"] == foreign["version"]
        assert await _column_ids(other_client, "todo") == [foreign["id"]]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_replay_returns_the_stored_result_and_a_new_payload_conflicts() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("replay-owner", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        first, second = await _create_tasks(client, "replay", 2)
        pairs = [(second["id"], second["version"]), (first["id"], first["version"])]
        original = await _reorder(client, "todo", pairs, "replay-key-0001")
        assert not original.is_error, original.structured_content

        replayed = await _reorder(client, "todo", pairs, "replay-key-0001")
        assert not replayed.is_error, replayed.structured_content
        assert replayed.structured_content == original.structured_content

        changed = await _reorder(
            client,
            "todo",
            [(first["id"], first["version"]), (second["id"], second["version"])],
            "replay-key-0001",
        )
        assert changed.is_error
        assert changed.structured_content["code"] == "conflict"
        assert await _column_ids(client, "todo") == [second["id"], first["id"]]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_manually_ordered_names_only_columns_moved_by_hand_in_column_order() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("manual-owner", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        first, second, third = await _create_tasks(client, "manual", 3)
        started = await client.call_tool(
            "update_task",
            {
                "task_id": third["id"],
                "version": third["version"],
                "idempotency_key": "manual-third-started",
                "changes": {"status": "in_progress"},
            },
        )
        assert not started.is_error, started.structured_content
        # An unranked Task in its column does not make that column manually ordered.
        board = await client.call_tool("get_work_board", {"limit": 100})
        assert board.structured_content["manually_ordered"] == []

        in_progress = await _reorder(
            client,
            "in_progress",
            [(third["id"], started.structured_content["task"]["version"])],
            "manual-progress-0001",
        )
        assert not in_progress.is_error, in_progress.structured_content
        todo = await _reorder(
            client,
            "todo",
            [(second["id"], second["version"]), (first["id"], first["version"])],
            "manual-todo-0002",
        )
        assert not todo.is_error, todo.structured_content

        board = await client.call_tool("get_work_board", {"limit": 100})
        # Column order, not the order in which the columns were moved by hand.
        assert board.structured_content["manually_ordered"] == ["todo", "in_progress"]
        assert "board_rank" not in str(board.structured_content)

        scoped = await client.call_tool("get_work_board", {"limit": 100, "status": "in_progress"})
        assert scoped.structured_content["manually_ordered"] == ["in_progress"]
        scoped = await client.call_tool("get_work_board", {"limit": 100, "status": "completed"})
        assert scoped.structured_content["manually_ordered"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_other_owners_manual_order_is_not_visible_on_the_board() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("manual-private-owner", "Owner")
    other = container.auth.provision_user("manual-other-owner", "Other")
    async with Client(_server_for(container, Actor(other, SCOPES))) as other_client:
        ranked = await _create_tasks(other_client, "theirs", 2)
        moved = await _reorder(
            other_client,
            "todo",
            [(ranked[1]["id"], ranked[1]["version"]), (ranked[0]["id"], ranked[0]["version"])],
            "theirs-todo-0001",
        )
        assert not moved.is_error, moved.structured_content

    async with Client(_server_for(container, Actor(owner, SCOPES))) as owner_client:
        await _create_tasks(owner_client, "mine", 1)
        board = await owner_client.call_tool("get_work_board", {"limit": 100})
        assert board.structured_content["manually_ordered"] == []

    async with Client(_server_for(container, Actor(other, SCOPES))) as other_client:
        board = await other_client.call_tool("get_work_board", {"limit": 100})
        assert board.structured_content["manually_ordered"] == ["todo"]

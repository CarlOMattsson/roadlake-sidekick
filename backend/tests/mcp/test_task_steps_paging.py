"""A Task with more Steps than one page holds can be read to the end with `next_cursor`.

`list_task_steps` returns at most 100 Steps per call. Past that, `next_cursor` continues after the
last Step returned (keyset on position and id), so every Step is seen once, in order.
"""

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

STEP_COUNT = 125


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("limit", [None, 100, 37, 1])
async def test_list_task_steps_walks_every_page_of_a_task_with_more_than_100_steps(
    limit: int | None,
) -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("steps-owner", "Owner")
    stranger = container.auth.provision_user("steps-other", "Other")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    task = container.tasks.create(actor, title="Many steps", idempotency_key="many-steps-task")
    created = [
        container.steps.create_step(
            actor, task.id, title=f"Step {n:03d}", idempotency_key=f"many-steps-{n:03d}"
        ).id
        for n in range(STEP_COUNT)
    ]
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    seen: list[str] = []
    page_sizes: list[int] = []
    async with Client(server) as client:
        cursor: str | None = None
        for _ in range(STEP_COUNT + 1):
            arguments: dict[str, object] = {"task_id": str(task.id)}
            if limit is not None:
                arguments["limit"] = limit
            if cursor is not None:
                arguments["cursor"] = cursor
            page = await client.call_tool("list_task_steps", arguments)
            assert page.structured_content is not None
            items = page.structured_content["items"]
            page_sizes.append(len(items))
            seen.extend(item["id"] for item in items)
            cursor = page.structured_content["next_cursor"]
            if cursor is None:
                break
        else:
            pytest.fail("the cursor never ended")

        # Another owner cannot continue this walk or read these Steps.
        first = await client.call_tool("list_task_steps", {"task_id": str(task.id), "limit": 1})
        assert first.structured_content is not None
        stolen = first.structured_content["next_cursor"]

    assert seen == [str(step_id) for step_id in created]
    assert max(page_sizes) == (limit or 100)
    assert page_sizes[0] == (limit or 100)
    assert len(page_sizes) == -(-STEP_COUNT // (limit or 100))

    other = Actor(stranger, frozenset(MCP_SCOPES))
    other_server = create_mcp_server(container, actor_provider=lambda: other, enable_auth=False)
    async with Client(other_server) as client:
        refused = await client.call_tool(
            "list_task_steps", {"task_id": str(task.id), "cursor": stolen}, raise_on_error=False
        )
        assert refused.is_error
        empty = await client.call_tool(
            "list_task_steps", {"task_id": str(task.id)}, raise_on_error=False
        )
        assert empty.structured_content is not None
        assert empty.structured_content.get("items", []) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reorder_task_steps_accepts_every_step_of_a_task_with_more_than_100_steps() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("reorder-owner", "Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    task = container.tasks.create(actor, title="Many steps", idempotency_key="reorder-many-task")
    created = [
        container.steps.create_step(
            actor, task.id, title=f"Step {n:03d}", idempotency_key=f"reorder-many-{n:03d}"
        )
        for n in range(120)
    ]
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    items = [{"id": str(step.id), "version": step.version} for step in reversed(created)]

    async with Client(server) as client:
        reordered = await client.call_tool(
            "reorder_task_steps",
            {"task_id": str(task.id), "items": items, "idempotency_key": "reorder-many-key"},
        )
        # Leaving one Step out is still refused: the order must cover every active Step.
        refused = await client.call_tool(
            "reorder_task_steps",
            {"task_id": str(task.id), "items": items[1:], "idempotency_key": "reorder-many-key-2"},
            raise_on_error=False,
        )

    assert reordered.structured_content is not None
    assert [item["id"] for item in reordered.structured_content["items"]] == [
        item["id"] for item in items
    ]
    assert refused.is_error

"""MCP writes accept only low, normal or high priority; a stored urgent Task still reads back.

`urgent` stays in the domain and in every read. Only the inputs of create_task and TaskChanges
(used by update_task) leave it out, so the owner's own urgent Tasks are never hidden.
"""

from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from sidekick.tasks.domain import Priority
from tests.db import database_factory
from tests.support.settings import make_settings

# projects:read is needed too: create_task, update_task and get_task read the Task's tags
# through work_tags.for_record, which requires it (the owner's real tokens carry it).
SCOPES = frozenset({"projects:read", "tasks:read", "tasks:write"})
WRITE_PRIORITIES = {"low", "normal", "high"}


def _enum_values(node: Any) -> set[str]:
    """Every enum value found anywhere under one JSON schema node."""

    values: set[str] = set()
    if isinstance(node, dict):
        enum = node.get("enum")
        if isinstance(enum, list):
            values |= {str(value) for value in enum}
        for child in node.values():
            values |= _enum_values(child)
    elif isinstance(node, list):
        for child in node:
            values |= _enum_values(child)
    return values


def _priority_values(schema: Any) -> set[str]:
    """Enum values of each `priority` property in a tool's input schema, nested models included."""

    values: set[str] = set()
    if isinstance(schema, dict):
        for key, child in schema.items():
            if key == "priority" and isinstance(child, dict):
                values |= _enum_values(child)
            else:
                values |= _priority_values(child)
    elif isinstance(schema, list):
        for child in schema:
            values |= _priority_values(child)
    return values


@pytest.mark.asyncio
async def test_write_tools_offer_only_low_normal_and_high() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}

    assert _priority_values(tools["create_task"].parameters) == WRITE_PRIORITIES
    assert _priority_values(tools["update_task"].parameters) == WRITE_PRIORITIES


@pytest.mark.asyncio
@pytest.mark.integration
async def test_write_tools_reject_urgent_and_accept_the_three_offered_values() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, SCOPES)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_task",
                {
                    "title": "urgent input",
                    "idempotency_key": "priority-urgent-0001",
                    "priority": "urgent",
                },
            )

        created = await client.call_tool(
            "create_task",
            {"title": "high input", "idempotency_key": "priority-high-0001", "priority": "high"},
        )
        task = created.structured_content["task"]
        assert task["priority"] == "high"

        with pytest.raises(ToolError):
            await client.call_tool(
                "update_task",
                {
                    "task_id": task["id"],
                    "version": task["version"],
                    "idempotency_key": "priority-urgent-update-0001",
                    "changes": {"priority": "urgent"},
                },
            )

        updated = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "priority-low-update-0001",
                "changes": {"priority": "low"},
            },
        )
    assert updated.structured_content["task"]["priority"] == "low"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stored_urgent_task_still_reads_back_as_urgent() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, SCOPES)
    stored = container.tasks.create(
        actor,
        title="stored urgent",
        idempotency_key="priority-stored-urgent-0001",
        priority=Priority.URGENT,
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        read = await client.call_tool("get_task", {"task_id": str(stored.id)})

    assert read.structured_content["task"]["priority"] == "urgent"

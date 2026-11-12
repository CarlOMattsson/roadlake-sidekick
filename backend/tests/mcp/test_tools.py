"""Curated MCP tool execution against authoritative PostgreSQL state."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_project_and_task_have_structured_and_text_results() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(
        user_id,
        frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"}),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Operations", "idempotency_key": "mcp-domain-001"}
        )
        project = await client.call_tool(
            "create_project",
            {
                "title": "Sidekick",
                "domain_id": domain.structured_content["domain"]["id"],
                "idempotency_key": "mcp-project-001",
            },
        )
        project_data = project.structured_content["project"]
        assert project_data["title"] == "Sidekick"
        assert "owner_id" not in project_data
        assert project.content[0].type == "text"
        task = await client.call_tool(
            "create_task",
            {
                "title": "Test MCP",
                "project_id": project_data["id"],
                "description": "Temporary description",
                "due_at": "2026-08-01T10:00:00Z",
                "idempotency_key": "mcp-task-001",
            },
        )
        assert task.structured_content["task"]["project_id"] == project_data["id"]
        cleared = await client.call_tool(
            "update_task",
            {
                "task_id": task.structured_content["task"]["id"],
                "version": 1,
                "idempotency_key": "mcp-task-clear",
                "changes": {"project_id": None, "description": None, "due_at": None},
            },
        )
        assert cleared.structured_content["task"]["project_id"] is None
        assert cleared.structured_content["task"]["description"] is None
        assert cleared.structured_content["task"]["due_at"] is None
        listed = await client.call_tool("list_tasks", {"limit": 10})
        assert len(listed.structured_content["tasks"]) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_idempotency_replay_and_conflict() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"projects:read", "projects:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Operations", "idempotency_key": "mcp-domain-retry"}
        )
        first = await client.call_tool(
            "create_project",
            {
                "title": "One",
                "domain_id": domain.structured_content["domain"]["id"],
                "idempotency_key": "mcp-retry-key",
            },
        )
        replay = await client.call_tool(
            "create_project",
            {
                "title": "One",
                "domain_id": domain.structured_content["domain"]["id"],
                "idempotency_key": "mcp-retry-key",
            },
        )
        assert first.structured_content == replay.structured_content
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_project",
                {
                    "title": "Two",
                    "domain_id": domain.structured_content["domain"]["id"],
                    "idempotency_key": "mcp-retry-key",
                },
            )

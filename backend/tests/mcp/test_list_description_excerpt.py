"""list_tasks and list_projects return a description excerpt; get_* return the whole text."""

from typing import Any

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})


def _structured(tool_result: Any) -> dict[str, Any]:
    assert tool_result.structured_content is not None
    structured: dict[str, Any] = tool_result.structured_content
    return structured


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_rows_carry_an_excerpt_and_get_returns_the_whole_description() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("mcp_excerpt_owner", "Owner")
    long_text = " ".join(["detail"] * 100)

    async with Client(
        create_mcp_server(container, actor_provider=lambda: Actor(owner, SCOPES), enable_auth=False)
    ) as client:
        domain = _structured(
            await client.call_tool(
                "create_domain", {"name": "Home", "idempotency_key": "excerpt-d"}
            )
        )["domain"]
        project = _structured(
            await client.call_tool(
                "create_project",
                {
                    "domain_id": domain["id"],
                    "title": "Garden",
                    "description": long_text,
                    "idempotency_key": "excerpt-p",
                },
            )
        )["project"]
        long_task = _structured(
            await client.call_tool(
                "create_task",
                {
                    "project_id": project["id"],
                    "title": "Long",
                    "description": long_text,
                    "idempotency_key": "excerpt-t1",
                },
            )
        )["task"]
        for title, description, key in (
            ("Short", "Just a note", "excerpt-t2"),
            ("Bare", None, "excerpt-t3"),
        ):
            arguments: dict[str, Any] = {
                "project_id": project["id"],
                "title": title,
                "idempotency_key": key,
            }
            if description is not None:
                arguments["description"] = description
            await client.call_tool("create_task", arguments)

        tasks = {
            row["title"]: row
            for row in _structured(await client.call_tool("list_tasks", {"limit": 10}))["tasks"]
        }
        projects = _structured(await client.call_tool("list_projects", {"limit": 10}))["projects"]
        task = _structured(await client.call_tool("get_task", {"task_id": long_task["id"]}))["task"]
        full_project = _structured(
            await client.call_tool("get_project", {"project_id": project["id"]})
        )["project"]

    assert all("description" not in row for row in [*tasks.values(), *projects])
    assert tasks["Long"]["description_truncated"] is True
    assert len(tasks["Long"]["description_excerpt"]) <= 160
    assert long_text.startswith(tasks["Long"]["description_excerpt"].removesuffix("…"))
    assert tasks["Short"]["description_excerpt"] == "Just a note"
    assert tasks["Short"]["description_truncated"] is False
    assert tasks["Bare"]["description_excerpt"] is None
    assert tasks["Bare"]["description_truncated"] is False
    assert projects[0]["description_truncated"] is True
    assert len(projects[0]["description_excerpt"]) <= 160
    assert task["description"] == long_text
    assert full_project["description"] == long_text

"""list_tasks `unsorted`: Tasks without a Domain, Project or Process context, owner-scoped.

A Task linked to a Process is sorted, because its Domain comes from the Process; the test keeps
that rule visible.
"""

import json
from typing import Any

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.results import _without_empty  # pyright: ignore[reportPrivateUsage]
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

WRITE_SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
READ_SCOPES = frozenset({"projects:read", "tasks:read"})


def _structured(tool_result: Any) -> dict[str, Any]:
    assert tool_result.structured_content is not None
    structured: dict[str, Any] = tool_result.structured_content
    return structured


def _summary_and_json(tool_result: Any) -> tuple[str, dict[str, Any]]:
    assert len(tool_result.content) == 2, "expected a summary block and a JSON block"
    decoded: dict[str, Any] = json.loads(tool_result.content[1].text)
    summary: str = tool_result.content[0].text
    return summary, decoded


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_unsorted_returns_count_line_and_only_loose_tasks() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("mcp_unsorted_owner", "Owner")
    other = container.auth.provision_user("mcp_unsorted_other", "Other")

    async with Client(
        create_mcp_server(
            container, actor_provider=lambda: Actor(owner, WRITE_SCOPES), enable_auth=False
        )
    ) as client:
        domain = _structured(
            await client.call_tool(
                "create_domain", {"name": "Home", "idempotency_key": "mu-domain"}
            )
        )["domain"]
        project = _structured(
            await client.call_tool(
                "create_project",
                {"domain_id": domain["id"], "title": "Garden", "idempotency_key": "mu-project"},
            )
        )["project"]
        process = _structured(
            await client.call_tool(
                "create_process",
                {
                    "domain_id": domain["id"],
                    "name": "Weekly review",
                    "idempotency_key": "mu-process",
                },
            )
        )["process"]
        contexts: dict[str, dict[str, Any]] = {
            "with-domain": {"domain_id": domain["id"]},
            "with-project": {"project_id": project["id"]},
            "with-process": {"process_id": process["id"]},
            "loose-one": {},
            "loose-two": {},
        }
        ids: dict[str, str] = {}
        for name, context in contexts.items():
            task = _structured(
                await client.call_tool(
                    "create_task",
                    {"title": name, "idempotency_key": f"mu-task-{name}", **context},
                )
            )["task"]
            ids[name] = task["id"]

    async with Client(
        create_mcp_server(
            container, actor_provider=lambda: Actor(owner, READ_SCOPES), enable_auth=False
        )
    ) as client:
        unsorted = await client.call_tool("list_tasks", {"unsorted": True})
        default = await client.call_tool("list_tasks", {})

    assert {task["id"] for task in _structured(unsorted)["tasks"]} == {
        ids["loose-one"],
        ids["loose-two"],
    }
    summary, decoded = _summary_and_json(unsorted)
    assert summary.splitlines()[0] in (
        "You have 2 unsorted tasks: loose-one and loose-two.",
        "You have 2 unsorted tasks: loose-two and loose-one.",
    )
    assert decoded == _without_empty(_structured(unsorted))

    default_summary, default_json = _summary_and_json(default)
    assert default_summary.splitlines()[0].startswith("Found 5 tasks: ")
    assert len(default_json["tasks"]) == 5

    async with Client(
        create_mcp_server(
            container, actor_provider=lambda: Actor(other, READ_SCOPES), enable_auth=False
        )
    ) as client:
        foreign = await client.call_tool("list_tasks", {"unsorted": True})
    assert _structured(foreign)["tasks"] == []
    assert _summary_and_json(foreign)[0].splitlines()[0] == "You have no unsorted tasks."

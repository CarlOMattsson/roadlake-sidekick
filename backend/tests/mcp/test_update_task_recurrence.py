"""update_task sets, changes and removes a Task's own recurrence, for any Task.

Recurrence belongs to the Task, not to a Process: the Task here is in no Process at all. The same
use case answers the call, an unknown field or a rule the domain refuses is a tool error that
echoes nothing, and a read-only caller cannot change it.
"""

from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"projects:read", "tasks:read", "tasks:write"})


def _task(result: Any) -> dict[str, Any]:
    assert result.structured_content is not None
    task: dict[str, Any] = result.structured_content["task"]
    return task


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_task_sets_changes_and_removes_recurrence() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = create_mcp_server(
        container, actor_provider=lambda: Actor(owner, SCOPES), enable_auth=False
    )

    async with Client(server) as client:
        task = _task(
            await client.call_tool(
                "create_task", {"title": "Water", "idempotency_key": "rec-mcp-create-1"}
            )
        )
        assert task["recurrence"] is None

        weekly = _task(
            await client.call_tool(
                "update_task",
                {
                    "task_id": task["id"],
                    "version": task["version"],
                    "idempotency_key": "rec-mcp-set-0001",
                    "changes": {"recurrence": {"frequency": "weekly", "weekdays": [0, 3]}},
                },
            )
        )
        assert weekly["recurrence"] == {
            "frequency": "weekly",
            "interval": 1,
            "weekdays": [0, 3],
            "day_of_month": None,
            "until": None,
        }

        monthly = _task(
            await client.call_tool(
                "update_task",
                {
                    "task_id": task["id"],
                    "version": weekly["version"],
                    "idempotency_key": "rec-mcp-change-1",
                    "changes": {"recurrence": {"frequency": "monthly", "until": "2027-06-30"}},
                },
            )
        )
        assert monthly["recurrence"]["frequency"] == "monthly"
        assert monthly["recurrence"]["until"] == "2027-06-30"
        # The rule reads back through get_task as well.
        read = await client.call_tool("get_task", {"task_id": task["id"]})
        assert read.structured_content["task"]["recurrence"] == monthly["recurrence"]

        cleared = _task(
            await client.call_tool(
                "update_task",
                {
                    "task_id": task["id"],
                    "version": monthly["version"],
                    "idempotency_key": "rec-mcp-clear-01",
                    "changes": {"recurrence": None},
                },
            )
        )
        assert cleared["recurrence"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_task_refuses_a_bad_rule_and_a_reader() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    reader_scopes = frozenset({"projects:read", "tasks:read"})
    actor = {"scopes": SCOPES}
    server = create_mcp_server(
        container, actor_provider=lambda: Actor(owner, actor["scopes"]), enable_auth=False
    )

    async with Client(server) as client:
        task = _task(
            await client.call_tool(
                "create_task", {"title": "Rule", "idempotency_key": "rec-mcp-bad-create"}
            )
        )
        for index, rule in enumerate(
            (
                {"frequency": "daily", "weekdays": [1]},
                {"frequency": "weekly", "interval": 99},
                {"frequency": "fortnightly"},
            )
        ):
            with pytest.raises(ToolError):
                await client.call_tool(
                    "update_task",
                    {
                        "task_id": task["id"],
                        "version": task["version"],
                        "idempotency_key": f"rec-mcp-bad-0{index}-xx",
                        "changes": {"recurrence": rule},
                    },
                )
        actor["scopes"] = reader_scopes
        denied = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "rec-mcp-reader-01",
                "changes": {"recurrence": {"frequency": "daily"}},
            },
            raise_on_error=False,
        )
        assert denied.is_error
        read = await client.call_tool("get_task", {"task_id": task["id"]})
    assert read.structured_content["task"]["recurrence"] is None
    assert read.structured_content["task"]["version"] == task["version"]

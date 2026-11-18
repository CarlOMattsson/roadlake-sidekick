"""Who an activity entry belongs to: Claude for a model tool call, the owner for the app.

The ledger reads the transport's change source, so the use cases that write an owner-actor
entry need no knowledge of it. AI plan and run entries also carry the task title.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

APP = {"com.roadlake.sidekick/origin": "app"}
TITLE = "Boka tid hos tandläkaren"


def _setup() -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    owner_id = container.auth.provision_user("activity-owner", "Activity Owner")
    return container, Actor(owner_id, frozenset(MCP_SCOPES))


def _client(container: Container, actor: Actor) -> Client[Any]:
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    return Client(server)


async def _call(
    client: Client[Any], tool: str, args: dict[str, Any], meta: dict[str, str] | None = None
) -> dict[str, Any]:
    result = await client.call_tool(tool, {**args, "idempotency_key": f"act-{uuid4()}"}, meta=meta)
    assert result.structured_content is not None
    return dict(result.structured_content)


async def _activity(client: Client[Any]) -> list[dict[str, Any]]:
    result = await client.call_tool("list_assistant_activity", {"limit": 100})
    assert result.structured_content is not None
    return list(result.structured_content["items"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_model_call_is_assistant_and_an_app_call_is_user() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        by_claude = await _call(client, "create_task", {"title": "Från Claude"})
        by_app = await _call(client, "create_task", {"title": "Från appen"}, meta=APP)
        sources = {
            entry["after_values"]["title"]: entry["source"] for entry in await _activity(client)
        }
    assert by_claude["task"]["id"] != by_app["task"]["id"]
    assert sources == {"Från Claude": "assistant", "Från appen": "user"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_plan_and_run_entries_name_the_task_and_follow_the_caller() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        task = (await _call(client, "create_task", {"title": TITLE}, meta=APP))["task"]
        step = {"title": "Ring", "performer": "ai", "ai_spec": {"goal": "Find the number"}}
        view = (
            await _call(
                client,
                "set_ai_plan",
                {"task_id": task["id"], "task_version": task["version"], "steps": [step]},
            )
        )["plan"]
        await _call(
            client, "approve_ai_plan", {"task_id": task["id"], "digest": view["digest"]}, meta=APP
        )
        started = (
            await _call(client, "start_ai_step", {"step_id": view["steps"][0]["step"]["id"]})
        )["run"]
        entries = [
            entry
            for entry in await _activity(client)
            if entry["operation"].startswith(("plan_", "run_"))
        ]
    by_operation = {entry["operation"]: entry for entry in entries}
    assert {"plan_set", "plan_approved", "run_started"} <= set(by_operation)
    for entry in by_operation.values():
        assert entry["after_values"]["title"] == TITLE
        assert TITLE in entry["summary"]
    assert by_operation["plan_set"]["source"] == "assistant"
    assert by_operation["plan_approved"]["source"] == "user"
    assert by_operation["run_started"]["source"] == "assistant"
    assert by_operation["plan_approved"]["summary"] == f"AI plan approved: {TITLE}"
    assert by_operation["run_started"]["summary"] == f"AI step run running: {TITLE}"
    assert by_operation["run_started"]["after_values"]["state"] == "running"
    assert by_operation["run_started"]["after_values"]["attempt"] == started["attempt"]

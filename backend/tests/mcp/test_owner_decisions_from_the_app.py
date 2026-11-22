"""An owner's decision is made in the app: the server refuses a model's call to it by name.

Hiding a tool from the model is only a listing. The server also refuses the call unless the request
carries the app's origin mark, which the model cannot set, and the refusal changes nothing and
audits nothing as the owner's.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.mcp.change_source import is_owner_decision
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.app_origin import APP_ORIGIN, OWNER_DECISIONS
from tests.support.settings import make_settings

STEP = {"title": "Ring", "performer": "ai", "ai_spec": {"goal": "Find the number"}}
AUTOMATION = {
    "title": "Morning mail",
    "purpose": "Collect what the morning mail asks of me",
    "instruction": "Read yesterday's mail and propose tasks for requests.",
    "sources": ["mail"],
    "allowed_effects": ["create_task"],
}


def _setup() -> tuple[Container, Any, Client[Any]]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("decision-owner", "Decision Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    return container, server, Client(server)


def _audit(container: Container) -> list[tuple[str, str]]:
    store: Any = container.session_factory
    with store.begin() as session:
        rows = session.execute(text("SELECT event, source FROM sidekick.audit_events")).all()
    return sorted((event, source) for event, source in rows)


async def _ok(
    client: Client[Any], tool: str, arguments: dict[str, Any], meta: dict[str, str] | None = None
) -> dict[str, Any]:
    result = await client.call_tool(
        tool, {**arguments, "idempotency_key": f"dec-{uuid4().hex}"}, meta=meta
    )
    assert result.structured_content is not None
    return dict(result.structured_content)


async def _refused(client: Client[Any], tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await client.call_tool(
        tool, {**arguments, "idempotency_key": f"dec-{uuid4().hex}"}, raise_on_error=False
    )
    assert result.is_error, tool
    assert result.structured_content is not None
    return dict(result.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_guard_covers_every_tool_the_server_marks_as_the_owners_decision() -> None:
    _, server, _ = _setup()
    marked = {tool.name for tool in await server.list_tools() if is_owner_decision(tool.meta)}
    assert marked == OWNER_DECISIONS


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_model_call_to_the_ai_plan_decisions_is_refused_and_an_app_call_works() -> None:
    container, _, client = _setup()
    async with client:
        task = (await _ok(client, "create_task", {"title": "Boka tid"}, APP_ORIGIN))["task"]
        plan = (
            await _ok(
                client,
                "set_ai_plan",
                {"task_id": task["id"], "task_version": task["version"], "steps": [STEP]},
            )
        )["plan"]
        arguments = {"task_id": task["id"], "digest": plan["digest"]}
        before = _audit(container)

        for tool in ("approve_ai_plan", "run_ai_plan"):
            refusal = await _refused(client, tool, arguments)
            assert refusal["code"] == "forbidden", tool
            assert refusal["reason"] == "app_only", tool
        assert _audit(container) == before

        approved = await _ok(client, "approve_ai_plan", arguments, APP_ORIGIN)
        assert approved["plan"]["digest"] == plan["digest"]
        # The test server runs no AI steps, so the app's run is declined by the use case and not
        # by the guard: the answer is not the `app_only` refusal.
        declined = await client.call_tool(
            "run_ai_plan",
            {**arguments, "idempotency_key": f"dec-{uuid4().hex}"},
            meta=APP_ORIGIN,
            raise_on_error=False,
        )
        assert (declined.structured_content or {}).get("reason") != "app_only"

    added = [source for event, source in _audit(container) if "approved" in event]
    assert added == ["you"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_model_call_to_approve_an_automation_is_refused_and_an_app_call_works() -> None:
    container, _, client = _setup()
    async with client:
        draft = (await _ok(client, "save_automation", {"changes": AUTOMATION}))["automation"]
        arguments = {"automation_id": draft["id"], "spec_digest": draft["spec_digest"]}
        before = _audit(container)

        refusal = await _refused(client, "approve_automation", arguments)
        assert refusal["code"] == "forbidden"
        assert refusal["reason"] == "app_only"
        assert _audit(container) == before

        await _ok(client, "approve_automation", arguments, APP_ORIGIN)

    approvals = [source for event, source in _audit(container) if event == "automation.approved"]
    assert approvals == ["you"]

"""Planning metadata is authorized server-side and never reaches telemetry.

Definitions of done, Step instructions, Action notes, and tag labels are personal
content on the same level as Journal text: they may cross HTTP and MCP, but never a
log, metric, span, audit payload, or error message. Tag slugs are also content, so
they are never used as metric label values.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from sidekick.api.app import create_app, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.persistence.models import AuditEventRow
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings
from tests.support.telemetry import CaptureTelemetry

SENTINEL = "PLANNING_PRIVATE_SENTINEL"
TAG_SENTINEL = "SentinelTag"
NOW = datetime.now(UTC)


WORK_SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})


def _server(container, actor: Actor):
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_planning_content_never_reaches_telemetry_or_audit() -> None:
    telemetry = CaptureTelemetry()
    factory = database_factory()
    container = create_container(make_settings(), factory, telemetry)
    owner_id = container.auth.provision_user("plan_redaction", "Plan")
    actor = Actor(owner_id, WORK_SCOPES)
    async with Client(_server(container, actor)) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Ops", "idempotency_key": "redact-domain"}
        )
        project = await client.call_tool(
            "create_project",
            {
                "domain_id": domain.structured_content["domain"]["id"],
                "title": "Release",
                "idempotency_key": "redact-project",
            },
        )
        project_record = project.structured_content["project"]
        await client.call_tool(
            "update_project",
            {
                "project_id": project_record["id"],
                "version": project_record["version"],
                "idempotency_key": "redact-project-patch",
                "changes": {"definition_of_done": SENTINEL, "tags": [TAG_SENTINEL]},
            },
        )
        created = await client.call_tool(
            "create_task",
            {
                "title": "Ship",
                "estimated_minutes": 30,
                "tags": [TAG_SENTINEL],
                "idempotency_key": "redact-task",
            },
        )
        task = created.structured_content["task"]
        step = await client.call_tool(
            "create_task_step",
            {"task_id": task["id"], "title": "Review", "idempotency_key": "redact-step"},
        )
        step_record = step.structured_content["step"]
        # The MCP tools do not expose instruction or note, so the application service is the
        # only write path for them; the redaction contract covers it all the same.
        container.steps.update_step(
            actor,
            UUID(step_record["id"]),
            version=step_record["version"],
            idempotency_key="redact-step-patch",
            instruction=SENTINEL,
        )
        action = await client.call_tool(
            "create_step_action",
            {"step_id": step_record["id"], "title": "Call", "idempotency_key": "redact-action"},
        )
        action_record = action.structured_content["action"]
        container.steps.update_action(
            actor,
            UUID(action_record["id"]),
            version=action_record["version"],
            idempotency_key="redact-action-patch",
            note=SENTINEL,
        )
        await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "redact-waiting",
                "changes": {"waiting_since": NOW.isoformat()},
            },
        )
        await client.call_tool("list_tags", {"limit": 50})
        await client.call_tool("get_work_agenda", {"limit": 10})

    with factory() as session:
        audit = session.scalars(select(AuditEventRow)).all()

    serialized = str(telemetry.records) + str(audit)
    assert SENTINEL not in serialized
    assert TAG_SENTINEL not in serialized
    assert TAG_SENTINEL.lower() not in serialized
    for _name, attributes in telemetry.records:
        assert not any(
            isinstance(value, str) and value.lower() == TAG_SENTINEL.lower()
            for value in attributes.values()
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_planning_writes_require_the_write_scope_and_stay_owner_scoped() -> None:
    container = create_container(make_settings(), database_factory())
    owner_id = container.auth.provision_user("scope_owner", "Scope Owner")
    other_id = container.auth.provision_user("other_owner", "Other Owner")

    async with Client(_server(container, Actor(other_id, WORK_SCOPES))) as client:
        foreign = await client.call_tool(
            "create_task",
            {"title": "Not yours", "tags": ["ekonomi"], "idempotency_key": "scope-foreign-task"},
        )
        foreign_task = foreign.structured_content["task"]

    owner = Actor(owner_id, WORK_SCOPES)
    async with Client(_server(container, owner)) as client:
        # A cross-owner record is a safe not-found, not a permission hint.
        with pytest.raises(ToolError) as cross:
            await client.call_tool(
                "update_task",
                {
                    "task_id": foreign_task["id"],
                    "version": foreign_task["version"],
                    "idempotency_key": "scope-cross-task",
                    "changes": {"estimated_minutes": 15},
                },
            )
        assert "Not yours" not in str(cross.value)

        # The other owner's tag vocabulary and tasks reveal nothing to this owner.
        vocabulary = await client.call_tool("list_tags", {"limit": 50})
        assert vocabulary.structured_content["tags"] == []
        listed = await client.call_tool("list_tasks", {"limit": 100})
        assert foreign_task["id"] not in {item["id"] for item in listed.structured_content["tasks"]}

        own = await client.call_tool(
            "create_task", {"title": "Mine", "idempotency_key": "scope-own-task"}
        )
        own_task = own.structured_content["task"]

    # Without the write scope the owner's own planning write is refused.
    read_only = Actor(owner_id, frozenset({"projects:read", "tasks:read"}))
    async with Client(_server(container, read_only)) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "update_task",
                {
                    "task_id": own_task["id"],
                    "version": own_task["version"],
                    "idempotency_key": "scope-read-only",
                    "changes": {"estimated_minutes": 15},
                },
            )


@pytest.mark.asyncio
async def test_curated_tag_read_tool_requires_the_read_scope() -> None:
    factory = database_factory()
    app = create_app(make_settings(), factory)
    reader = Actor(
        app.state.container.auth.provision_user("mcp_tag_reader", "Reader"),
        frozenset({"projects:read", "tasks:read"}),
    )
    unscoped = Actor(reader.user_id, frozenset({"journal:read"}))

    allowed = create_mcp_server(
        app.state.container, actor_provider=lambda: reader, enable_auth=False
    )
    denied = create_mcp_server(
        app.state.container, actor_provider=lambda: unscoped, enable_auth=False
    )

    async with Client(allowed) as client:
        result = await client.call_tool("list_tags", {"limit": 10})
        assert result.structured_content is not None
        assert result.structured_content["tags"] == []

    async with Client(denied) as client:
        with pytest.raises(ToolError):
            await client.call_tool("list_tags", {"limit": 10})


@pytest.mark.asyncio
async def test_curated_task_tools_carry_planning_metadata_and_tags() -> None:
    factory = database_factory()
    app = create_app(make_settings(), factory)
    owner_id = app.state.container.auth.provision_user("mcp_planner", "Planner")
    actor = Actor(
        owner_id, frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
    )
    server = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        created = await client.call_tool(
            "create_task",
            {
                "title": "Monthly bookkeeping",
                "idempotency_key": "mcp-planning-create",
                "estimated_minutes": 120,
                "not_before": (NOW + timedelta(days=2)).isoformat(),
                "tags": ["Ekonomi"],
            },
        )
        task = created.structured_content["task"]
        assert task["estimated_minutes"] == 120
        assert task["not_before"] is not None
        assert task["tags"] == ["ekonomi"]

        updated = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "mcp-planning-update",
                "changes": {"estimated_minutes": 30, "tags": ["Telefon"]},
            },
        )
        assert updated.structured_content["task"]["estimated_minutes"] == 30
        assert updated.structured_content["task"]["tags"] == ["telefon"]

        vocabulary = await client.call_tool("list_tags", {"limit": 50})
        assert {tag["slug"] for tag in vocabulary.structured_content["tags"]} == {
            "ekonomi",
            "telefon",
        }

        with pytest.raises(ToolError):
            await client.call_tool(
                "update_task",
                {
                    "task_id": task["id"],
                    "version": task["version"] + 1,
                    "idempotency_key": "mcp-planning-invalid",
                    "changes": {"estimated_minutes": 0},
                },
            )

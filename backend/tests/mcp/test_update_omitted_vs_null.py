"""An omitted field stays; an explicit null clears it where the record allows, else is refused.

Covers the partial updates over MCP: update_project, update_domain, update_process,
update_task_step and update_step_action.
"""

from datetime import UTC, date, datetime

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

DUE = datetime(2030, 1, 2, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_project_update_keeps_omitted_fields_and_clears_explicit_nulls() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("patch-owner", "Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    domain = container.contexts.create_domain(
        actor, name="Ops", description=None, idempotency_key="patch-domain"
    )
    project = container.projects.create(
        actor,
        title="Keep",
        description="Described",
        start_date=date(2030, 1, 1),
        target_date=date(2030, 2, 1),
        domain_id=domain.id,
        idempotency_key="patch-project",
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        renamed = await client.call_tool(
            "update_project",
            {
                "project_id": str(project.id),
                "version": 1,
                "idempotency_key": "patch-rename",
                "changes": {"title": "Renamed"},
            },
        )
        cleared = await client.call_tool(
            "update_project",
            {
                "project_id": str(project.id),
                "version": 2,
                "idempotency_key": "patch-clear",
                "changes": {"description": None, "target_date": None},
            },
        )
        with pytest.raises(ToolError):
            await client.call_tool(
                "update_project",
                {
                    "project_id": str(project.id),
                    "version": 3,
                    "idempotency_key": "patch-null-status",
                    "changes": {"status": None},
                },
            )

    assert renamed.structured_content is not None
    first = renamed.structured_content["project"]
    assert (first["title"], first["description"]) == ("Renamed", "Described")
    assert (first["start_date"], first["target_date"]) == ("2030-01-01", "2030-02-01")
    assert cleared.structured_content is not None
    second = cleared.structured_content["project"]
    assert second["version"] == 3
    assert (second["title"], second["start_date"]) == ("Renamed", "2030-01-01")
    assert (second["description"], second["target_date"]) == (None, None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_domain_and_process_updates_keep_omitted_fields_and_refuse_null_status() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("patch-owner", "Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    domain = container.contexts.create_domain(
        actor, name="Ops", description="Described", idempotency_key="patch-domain"
    )
    process = container.contexts.create_process(
        actor,
        domain_id=domain.id,
        name="Review",
        description="Described",
        idempotency_key="patch-process",
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        domain_cleared = await client.call_tool(
            "update_domain",
            {
                "domain_id": str(domain.id),
                "version": 1,
                "idempotency_key": "patch-domain-clear",
                "changes": {"description": None},
            },
        )
        process_renamed = await client.call_tool(
            "update_process",
            {
                "process_id": str(process.id),
                "version": 1,
                "idempotency_key": "patch-process-rename",
                "changes": {"name": "Reviewed"},
            },
        )
        for tool, id_arg, record_id in (
            ("update_domain", "domain_id", domain.id),
            ("update_process", "process_id", process.id),
        ):
            with pytest.raises(ToolError):
                await client.call_tool(
                    tool,
                    {
                        id_arg: str(record_id),
                        "version": 2,
                        "idempotency_key": f"patch-null-status-{tool}",
                        "changes": {"status": None},
                    },
                )

    assert domain_cleared.structured_content is not None
    cleared = domain_cleared.structured_content["domain"]
    assert (cleared["name"], cleared["description"]) == ("Ops", None)
    assert process_renamed.structured_content is not None
    renamed = process_renamed.structured_content["process"]
    assert (renamed["name"], renamed["description"]) == ("Reviewed", "Described")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_step_and_action_updates_keep_omitted_fields_and_clear_a_null_due_date() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("patch-owner", "Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    task = container.tasks.create(actor, title="Parent", idempotency_key="patch-task")
    step = container.steps.create_step(
        actor, task.id, title="Step", due_at=DUE, idempotency_key="patch-step"
    )
    action = container.steps.create_action(
        actor, step.id, title="Action", due_at=DUE, idempotency_key="patch-action"
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        step_renamed = await client.call_tool(
            "update_task_step",
            {
                "step_id": str(step.id),
                "version": 1,
                "idempotency_key": "patch-step-rename",
                "changes": {"title": "Renamed"},
            },
        )
        step_cleared = await client.call_tool(
            "update_task_step",
            {
                "step_id": str(step.id),
                "version": 2,
                "idempotency_key": "patch-step-clear",
                "changes": {"due_at": None},
            },
        )
        action_renamed = await client.call_tool(
            "update_step_action",
            {
                "action_id": str(action.id),
                "version": 1,
                "idempotency_key": "patch-action-rename",
                "changes": {"title": "Renamed"},
            },
        )
        action_cleared = await client.call_tool(
            "update_step_action",
            {
                "action_id": str(action.id),
                "version": 2,
                "idempotency_key": "patch-action-clear",
                "changes": {"due_at": None},
            },
        )

    assert step_renamed.structured_content is not None
    assert step_renamed.structured_content["step"]["due_at"] is not None
    assert step_cleared.structured_content is not None
    cleared_step = step_cleared.structured_content["step"]
    assert (cleared_step["title"], cleared_step["due_at"]) == ("Renamed", None)
    assert action_renamed.structured_content is not None
    assert action_renamed.structured_content["action"]["due_at"] is not None
    assert action_cleared.structured_content is not None
    cleared_action = action_cleared.structured_content["action"]
    assert (cleared_action["title"], cleared_action["due_at"]) == ("Renamed", None)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("tool", "id_arg", "field"),
    [
        ("update_task_step", "step_id", "title"),
        ("update_task_step", "step_id", "status"),
        ("update_task_step", "step_id", "attention_requested"),
        ("update_step_action", "action_id", "title"),
        ("update_step_action", "action_id", "attention_requested"),
    ],
)
async def test_step_and_action_refuse_a_null_for_a_required_field(
    tool: str, id_arg: str, field: str
) -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("patch-owner", "Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    task = container.tasks.create(actor, title="Parent", idempotency_key="patch-task")
    step = container.steps.create_step(actor, task.id, title="Step", idempotency_key="patch-step")
    action = container.steps.create_action(
        actor, step.id, title="Action", idempotency_key="patch-action"
    )
    record_id = step.id if id_arg == "step_id" else action.id
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                tool,
                {
                    id_arg: str(record_id),
                    "version": 1,
                    "idempotency_key": "patch-null-required",
                    "changes": {field: None},
                },
            )

    still = container.steps.list_actions(actor, step.id)
    assert [item.version for item in still.items] == [1]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_step_instruction_and_action_note_are_set_kept_and_cleared() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("patch-owner", "Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    task = container.tasks.create(actor, title="Parent", idempotency_key="patch-task")
    step = container.steps.create_step(actor, task.id, title="Step", idempotency_key="patch-step")
    action = container.steps.create_action(
        actor, step.id, title="Action", idempotency_key="patch-action"
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async def update(
        tool: str, id_arg: str, record_id: object, version: int, changes: dict[str, object]
    ) -> dict[str, dict[str, object]]:
        reply = await client.call_tool(
            tool,
            {
                id_arg: str(record_id),
                "version": version,
                "idempotency_key": f"patch-{tool}-{version}",
                "changes": changes,
            },
        )
        assert reply.structured_content is not None
        return reply.structured_content

    async with Client(server) as client:
        step_set = await update("update_task_step", "step_id", step.id, 1, {"instruction": "Do"})
        step_kept = await update("update_task_step", "step_id", step.id, 2, {"title": "Renamed"})
        step_cleared = await update(
            "update_task_step", "step_id", step.id, 3, {"instruction": None}
        )
        action_set = await update("update_step_action", "action_id", action.id, 1, {"note": "Hi"})
        action_kept = await update(
            "update_step_action", "action_id", action.id, 2, {"title": "Renamed"}
        )
        action_cleared = await update(
            "update_step_action", "action_id", action.id, 3, {"note": None}
        )

    assert step_set["step"]["instruction"] == "Do"
    assert (step_kept["step"]["title"], step_kept["step"]["instruction"]) == ("Renamed", "Do")
    assert step_cleared["step"].get("instruction") is None
    assert action_set["action"]["note"] == "Hi"
    assert (action_kept["action"]["title"], action_kept["action"]["note"]) == ("Renamed", "Hi")
    assert action_cleared["action"].get("note") is None

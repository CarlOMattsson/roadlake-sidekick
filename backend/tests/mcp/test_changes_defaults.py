"""A write tool with a `changes` object accepts it when a client fills in the schema defaults.

The published input schema once gave each field of a `changes` object `"default": null`. A client
that fills in the defaults before sending then sent every field as an explicit null, and an
explicit null on a field with no empty value (a title, a status) was refused, so no update went
through. The schema now advertises no defaults, and an explicit null on such a field reads as "not
sent". A null on a field that can be cleared still clears it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

NO_CHANGE_ROW = "changes: at least one change is required"


def _changes_properties(parameters: Mapping[str, Any]) -> dict[str, Any]:
    return parameters["properties"]["changes"]["properties"]


def _filled_in(properties: Mapping[str, Any]) -> dict[str, Any]:
    """What a client sends for the fields it did not set, if it fills in the schema's defaults."""

    return {name: schema["default"] for name, schema in properties.items() if "default" in schema}


@dataclass(frozen=True)
class Case:
    tool: str
    id_arg: str
    version_arg: str
    record_key: str
    fixed: tuple[str, ...]
    """Fields with no empty value: an explicit null on them means "not sent"."""
    change: dict[str, Any]
    """One real change, sent next to the nulls."""
    changed_field: str


CASES = [
    Case(
        "update_task",
        "task_id",
        "version",
        "task",
        ("title", "status", "priority", "ambition", "ai_possible"),
        {"priority": "high"},
        "priority",
    ),
    Case(
        "update_task_step",
        "step_id",
        "version",
        "step",
        ("title", "status", "attention_requested"),
        {"title": "Renamed step"},
        "title",
    ),
    Case(
        "update_step_action",
        "action_id",
        "version",
        "action",
        ("title", "status", "attention_requested"),
        {"title": "Renamed action"},
        "title",
    ),
    Case(
        "update_project",
        "project_id",
        "version",
        "project",
        ("title", "status", "domain_id"),
        {"description": "Now described"},
        "description",
    ),
    Case(
        "update_domain",
        "domain_id",
        "version",
        "domain",
        ("name", "status"),
        {"description": "Now described"},
        "description",
    ),
    Case(
        "update_process",
        "process_id",
        "version",
        "process",
        ("name", "status", "domain_id"),
        {"description": "Now described"},
        "description",
    ),
    Case(
        "update_contact",
        "contact_id",
        "expected_version",
        "contact",
        ("display_name",),
        {"role": "Neighbour"},
        "role",
    ),
]
BY_TOOL = {case.tool: case for case in CASES}


async def _seed(client: Client) -> dict[str, dict[str, Any]]:
    """One record of each kind, as the tool replies describe it."""

    async def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        reply = await client.call_tool(tool, {**arguments, "idempotency_key": f"seed-{tool}-0001"})
        return next(iter(reply.structured_content.values()))

    domain = await call("create_domain", {"name": "Home"})
    project = await call("create_project", {"title": "House", "domain_id": domain["id"]})
    process = await call("create_process", {"domain_id": domain["id"], "name": "Chores"})
    task = await call("create_task", {"title": "Paint", "project_id": project["id"]})
    step = await call("create_task_step", {"task_id": task["id"], "title": "Buy paint"})
    action = await call("create_step_action", {"step_id": step["id"], "title": "Pick a colour"})
    contact = await call("create_contact", {"display_name": "Anna"})
    return {
        "task": task,
        "step": step,
        "action": action,
        "project": project,
        "domain": domain,
        "process": process,
        "contact": contact,
    }


def _server() -> Any:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


@pytest.mark.asyncio
async def test_no_write_tool_publishes_a_default_for_a_changes_field() -> None:
    server = _server()
    tools = {tool.name: tool for tool in await server.list_tools()}

    with_changes = {
        name for name, tool in tools.items() if "changes" in tool.parameters.get("properties", {})
    }
    assert with_changes == set(BY_TOOL)
    for name in with_changes:
        assert _filled_in(_changes_properties(tools[name].parameters)) == {}, name


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.tool)
async def test_a_client_that_fills_in_schema_defaults_still_updates(case: Case) -> None:
    server = _server()
    properties = _changes_properties(
        next(tool for tool in await server.list_tools() if tool.name == case.tool).parameters
    )
    async with Client(server) as client:
        record = (await _seed(client))[case.record_key]
        updated = await client.call_tool(
            case.tool,
            {
                case.id_arg: record["id"],
                case.version_arg: record["version"],
                "idempotency_key": "defaults-0001",
                "changes": {**_filled_in(properties), **case.change},
            },
        )

    stored = updated.structured_content[case.record_key]
    assert stored[case.changed_field] == next(iter(case.change.values()))
    assert stored["version"] == record["version"] + 1


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.tool)
async def test_an_explicit_null_on_a_field_without_an_empty_value_means_not_sent(
    case: Case,
) -> None:
    server = _server()
    async with Client(server) as client:
        record = (await _seed(client))[case.record_key]
        updated = await client.call_tool(
            case.tool,
            {
                case.id_arg: record["id"],
                case.version_arg: record["version"],
                "idempotency_key": "nulls-0001",
                "changes": {**dict.fromkeys(case.fixed), **case.change},
            },
        )

    stored = updated.structured_content[case.record_key]
    assert stored[case.changed_field] == next(iter(case.change.values()))
    for field in case.fixed:
        if field not in case.change and field in record:
            assert stored[field] == record[field], field


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("case", [BY_TOOL["update_task"], BY_TOOL["update_project"]])
async def test_nulls_on_fields_without_an_empty_value_alone_change_nothing(case: Case) -> None:
    server = _server()
    async with Client(server) as client:
        record = (await _seed(client))[case.record_key]
        refused = await client.call_tool(
            case.tool,
            {
                case.id_arg: record["id"],
                case.version_arg: record["version"],
                "idempotency_key": "only-nulls-0001",
                "changes": dict.fromkeys(case.fixed),
            },
            raise_on_error=False,
        )
        empty = await client.call_tool(
            case.tool,
            {
                case.id_arg: record["id"],
                case.version_arg: record["version"],
                "idempotency_key": "empty-0001",
                "changes": {},
            },
            raise_on_error=False,
        )

    assert refused.is_error
    assert empty.is_error
    assert refused.content[0].text == empty.content[0].text
    assert NO_CHANGE_ROW in refused.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_explicit_null_still_clears_a_field_that_can_be_cleared() -> None:
    server = _server()
    async with Client(server) as client:
        seeded = await _seed(client)
        task = seeded["task"]
        described = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "describe-0001",
                "changes": {"description": "Two coats", "tags": ["home"]},
            },
        )
        cleared = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": described.structured_content["task"]["version"],
                "idempotency_key": "clear-0001",
                "changes": {"title": None, "description": None, "project_id": None, "tags": None},
            },
        )
        step = seeded["step"]
        step_cleared = await client.call_tool(
            "update_task_step",
            {
                "step_id": step["id"],
                "version": step["version"],
                "idempotency_key": "clear-0002",
                "changes": {"instruction": None, "status": None, "due_at": None},
            },
        )

    after = cleared.structured_content["task"]
    assert after["title"] == "Paint"
    assert after["description"] is None
    assert after["project_id"] is None
    assert after["tags"] == []
    assert step_cleared.structured_content["step"]["status"] == step["status"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "arguments", "row"),
    [
        ("update_task", {"changes": {"title": ""}}, "changes.title: too short"),
        ("update_task", {"changes": {"priority": "urgent"}}, "changes.priority: not an allowed"),
        ("update_task", {"changes": {"title": 5}}, "changes.title: expected string or null"),
        ("update_task", {"changes": {"surprise": "SECRET"}}, "changes: unexpected field"),
        ("update_task", {"changes": {}}, NO_CHANGE_ROW),
        ("update_task", {"changes": {"title": None}}, NO_CHANGE_ROW),
        ("update_project", {"changes": {"status": None}}, NO_CHANGE_ROW),
        ("list_tasks", {"cursor": 5}, "cursor: expected string or null"),
    ],
)
async def test_a_rejected_call_names_the_path_and_the_reason_but_no_value(
    tool: str, arguments: dict[str, Any], row: str
) -> None:
    server = _server()
    identity = {
        "update_task": {"task_id": str(uuid4()), "version": 1, "idempotency_key": "reject-0001"},
        "update_project": {
            "project_id": str(uuid4()),
            "version": 1,
            "idempotency_key": "reject-0002",
        },
        "list_tasks": {},
    }[tool]
    async with Client(server) as client:
        reply = await client.call_tool(tool, {**identity, **arguments}, raise_on_error=False)

    assert reply.is_error
    text = reply.content[0].text
    assert row in text
    assert "SECRET" not in text

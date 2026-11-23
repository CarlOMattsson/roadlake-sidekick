"""A write tool with a `changes` object accepts it when a client fills in the schema defaults.

Some clients send every optional field as an explicit null. A null in `changes` therefore means
"not sent" (the reply lists it in `ignored_nulls`), and a field is emptied only by naming it in the
tool's `clear` list. A field that is both given a value and named in `clear` is refused.
"""

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.automation_tools import AutomationChanges
from sidekick.mcp.contact_records import ContactChanges
from sidekick.mcp.ready_tools import ReadyChanges
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from sidekick.structured.base import PartialChanges
from sidekick.structured.journal_photos import PhotoChangesInput
from sidekick.structured.work_records import (
    ActionChanges,
    DomainChanges,
    ProcessChanges,
    ProjectChanges,
    StepChanges,
    TaskChanges,
)
from tests.db import database_factory
from tests.support import photo_files
from tests.support.app_origin import origin_for
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
    changes_model: type[PartialChanges]
    clear_field: str
    """A clearable field that `clear_value` sets before the test empties it."""
    clear_value: Any
    derived: tuple[str, ...] = ()
    """Fields computed from the cleared one, which change with it."""


CASES = [
    Case(
        "update_task",
        "task_id",
        "version",
        "task",
        ("title", "status", "priority", "ambition", "ai_possible"),
        {"priority": "high"},
        "priority",
        TaskChanges,
        "description",
        "Two coats",
    ),
    Case(
        "update_task_step",
        "step_id",
        "version",
        "step",
        ("title", "status", "attention_requested"),
        {"title": "Renamed step"},
        "title",
        StepChanges,
        "instruction",
        "Use the roller",
    ),
    Case(
        "update_step_action",
        "action_id",
        "version",
        "action",
        ("title", "status", "attention_requested"),
        {"title": "Renamed action"},
        "title",
        ActionChanges,
        "note",
        "Matt finish",
    ),
    Case(
        "update_project",
        "project_id",
        "version",
        "project",
        ("title", "status", "domain_id"),
        {"description": "Now described"},
        "description",
        ProjectChanges,
        "definition_of_done",
        "All walls painted",
    ),
    Case(
        "update_domain",
        "domain_id",
        "version",
        "domain",
        ("name", "status"),
        {"description": "Now described"},
        "description",
        DomainChanges,
        "accent",
        "teal",
    ),
    Case(
        "update_process",
        "process_id",
        "version",
        "process",
        ("name", "status", "domain_id"),
        {"description": "Now described"},
        "description",
        ProcessChanges,
        "cadence",
        "weekly",
    ),
    Case(
        "update_contact",
        "contact_id",
        "expected_version",
        "contact",
        ("display_name",),
        {"role": "Neighbour"},
        "role",
        ContactChanges,
        "organization",
        "Next door",
    ),
    Case(
        "update_journal_photo",
        "photo_id",
        "expected_version",
        "photo",
        ("position",),
        {"orientation": 6},
        "orientation",
        PhotoChangesInput,
        "camera",
        "Pixel 9",
    ),
    Case(
        "save_automation",
        "automation_id",
        "expected_version",
        "automation",
        tuple(name for name in AutomationChanges.model_fields if name != "cadence"),
        {"title": "Renamed"},
        "title",
        AutomationChanges,
        "cadence",
        {"frequency": "daily", "local_time": "07:30"},
        ("spec_digest",),
    ),
    Case(
        "save_ready_conversation",
        "conversation_id",
        "expected_version",
        "conversation",
        tuple(name for name in ReadyChanges.model_fields if name != "instruction"),
        {"title": "Renamed"},
        "title",
        ReadyChanges,
        "instruction",
        "Ask one question at a time.",
        ("instruction_written_by",),
    ),
]
BY_TOOL = {case.tool: case for case in CASES}


async def _seed(client: Client) -> dict[str, dict[str, Any]]:
    """One record of each kind, as the tool replies describe it."""

    async def call(tool: str, arguments: dict[str, Any], key: str | None = None) -> dict[str, Any]:
        reply = await client.call_tool(
            tool,
            {**arguments, "idempotency_key": f"seed-{tool}-0001"},
            meta=origin_for(tool),
        )
        return reply.structured_content[key or next(iter(reply.structured_content))]

    domain = await call("create_domain", {"name": "Home"})
    project = await call("create_project", {"title": "House", "domain_id": domain["id"]})
    process = await call("create_process", {"domain_id": domain["id"], "name": "Chores"})
    task = await call("create_task", {"title": "Paint", "project_id": project["id"]})
    step = await call("create_task_step", {"task_id": task["id"], "title": "Buy paint"})
    action = await call("create_step_action", {"step_id": step["id"], "title": "Pick a colour"})
    contact = await call("create_contact", {"display_name": "Anna"})
    entry = await call(
        "write_journal_entry",
        {"journal_date": "2026-11-22", "title": "Walk", "source_text": "A short walk."},
    )
    photo = await call(
        "add_journal_photo",
        {
            "entry_id": entry["id"],
            "photo": base64.b64encode(photo_files.jpeg()).decode(),
            "thumbnail": base64.b64encode(photo_files.jpeg(320, 240)).decode(),
        },
    )
    automation = await call(
        "save_automation",
        {
            "changes": {
                "title": "Morning mail",
                "purpose": "Collect what the morning mail asks of me",
                "instruction": "Read yesterday's mail and propose tasks for requests.",
            }
        },
        "automation",
    )
    conversation = await call(
        "save_ready_conversation",
        {
            "changes": {
                "title": "Evening review",
                "cadence": {"frequency": "daily", "local_time": "18:00"},
            }
        },
        "conversation",
    )
    return {
        "photo": photo,
        "automation": automation,
        "conversation": conversation,
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
            meta=origin_for(case.tool),
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
            meta=origin_for(case.tool),
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
            meta=origin_for(case.tool),
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
            meta=origin_for(case.tool),
        )

    assert refused.is_error
    assert empty.is_error
    assert refused.content[0].text == empty.content[0].text
    assert NO_CHANGE_ROW in refused.content[0].text


async def _with_a_value(client: Client, case: Case) -> dict[str, Any]:
    """Seed the records and give `case.clear_field` of its record a value; return that record."""

    record = (await _seed(client))[case.record_key]
    reply = await client.call_tool(
        case.tool,
        {
            case.id_arg: record["id"],
            case.version_arg: record["version"],
            "idempotency_key": "set-0001",
            "changes": {case.clear_field: case.clear_value},
        },
        meta=origin_for(case.tool),
    )
    stored = reply.structured_content[case.record_key]
    assert stored[case.clear_field] is not None
    return stored


async def _call(client: Client, case: Case, stored: dict[str, Any], **arguments: Any) -> Any:
    return await client.call_tool(
        case.tool,
        {
            case.id_arg: stored["id"],
            case.version_arg: stored["version"],
            "idempotency_key": "after-0001",
            **arguments,
        },
        raise_on_error=False,
        meta=origin_for(case.tool),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.tool)
async def test_nulls_change_nothing_and_clear_empties_only_the_named_field(case: Case) -> None:
    server = _server()
    tool = next(tool for tool in await server.list_tools() if tool.name == case.tool)
    # What a client that fills in every nullable property sends.
    nullable = [
        name
        for name, schema in _changes_properties(tool.parameters).items()
        if any(branch.get("type") == "null" for branch in schema.get("anyOf", []))
    ]
    every_field_null = dict.fromkeys(nullable)
    async with Client(server) as client:
        before = await _with_a_value(client, case)
        ignored = await _call(client, case, before, changes=every_field_null)
        cleared = await _call(
            client,
            case,
            before,
            changes=every_field_null,
            clear=[case.clear_field],
            idempotency_key="after-0002",
        )

    # Nothing was sent, so nothing changes.
    assert ignored.is_error
    assert not cleared.is_error
    after = cleared.structured_content[case.record_key]
    assert after[case.clear_field] is None
    for name, value in before.items():
        if name not in (case.clear_field, "version", "updated_at", *case.derived):
            assert after[name] == value, name
    assert cleared.structured_content["ignored_nulls"] == [
        name
        for name in case.changes_model.model_fields
        if name in nullable and name != case.clear_field
    ]
    assert "Ignored null for" in cleared.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.tool)
async def test_a_field_given_a_value_and_named_in_clear_is_refused(case: Case) -> None:
    async with Client(_server()) as client:
        stored = await _with_a_value(client, case)
        reply = await _call(
            client,
            case,
            stored,
            changes={case.clear_field: case.clear_value, **case.change},
            clear=[case.clear_field],
        )

    assert reply.is_error
    assert f"changes.{case.clear_field}: also named in clear" in reply.content[0].text
    assert str(case.clear_value) not in reply.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_tags_only_change_with_client_filled_nulls_keeps_the_other_fields() -> None:
    """The reported case: `changes: {"tags": []}` with every other field sent as null."""

    async with Client(_server()) as client:
        task = (await _seed(client))["task"]
        assert task["project_id"] is not None
        described = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "issue-0001",
                "changes": {"description": "Two coats", "tags": ["home"]},
            },
        )
        reply = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": described.structured_content["task"]["version"],
                "idempotency_key": "issue-0002",
                "changes": {**dict.fromkeys(TaskChanges.model_fields), "tags": []},
            },
        )

    after = reply.structured_content["task"]
    assert after["tags"] == []
    assert after["project_id"] == task["project_id"]
    assert after["description"] == "Two coats"
    assert reply.structured_content["ignored_nulls"] == [
        name for name in TaskChanges.model_fields if name != "tags"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.tool)
async def test_the_clear_parameter_lists_exactly_the_clearable_fields(case: Case) -> None:
    tool = next(tool for tool in await _server().list_tools() if tool.name == case.tool)
    clear = tool.parameters["properties"]["clear"]
    listed = next(branch for branch in clear["anyOf"] if branch.get("type") == "array")
    # A list of one possible value is described as a constant, not as an enum of one.
    names = listed["items"].get("enum") or [listed["items"]["const"]]
    assert set(names) == set(case.changes_model.clearable_fields())
    assert "clear" not in tool.parameters.get("required", [])


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

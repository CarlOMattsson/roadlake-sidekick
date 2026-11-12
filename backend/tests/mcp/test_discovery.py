"""MCP discovery is a reviewed public contract."""

from typing import Any

import pytest
from mcp.types import ToolAnnotations

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from tests.contract_counts import app_only_tool_names
from tests.support.settings import make_settings

# Read-only tools that are not named list_/get_: one closing confirmation card for Work changes,
# search by words, and recall over the memory provider.
READ_TOOLS_WITHOUT_READ_PREFIX = {"show_work_changes", "search", "recall_memory"}

EXPECTED_TOOLS = {
    "search",
    "recall_memory",
    "get_memory_status",
    "set_memory_settings",
    "exclude_from_memory",
    "set_license_key",
    "list_shopping_lists",
    "get_shopping_list",
    "create_shopping_list",
    "update_shopping_list",
    "add_shopping_items",
    "update_shopping_item",
    "set_shopping_item_purchased",
    "set_shopping_items_purchased",
    "list_contacts",
    "get_contact_context",
    "create_contact",
    "update_contact",
    "archive_contact",
    "restore_contact",
    "add_contact_alias",
    "remove_contact_alias",
    "link_contact_to_project",
    "unlink_contact_from_project",
    "link_contact_to_task",
    "unlink_contact_from_task",
    "list_task_contacts",
    "link_external_reference_to_task",
    "unlink_external_reference_from_task",
    "list_task_external_references",
    "list_journal_entries",
    "get_journal_entry",
    "get_journal_day",
    "get_daily_journal_summary",
    "get_journal_source",
    "list_pending_journal",
    "create_journal_source",
    "create_manual_journal_entry",
    "write_journal_entry",
    "update_journal_entry",
    "set_daily_journal_summary",
    "get_journal_draft",
    "update_journal_draft",
    "reject_journal_draft",
    "finalize_journal_draft",
    "list_projects",
    "get_project",
    "create_project",
    "update_project",
    "list_domains",
    "get_domain",
    "create_domain",
    "update_domain",
    "create_process",
    "update_process",
    "list_processes",
    "get_process",
    "list_task_steps",
    "list_step_actions",
    "create_task_step",
    "create_step_action",
    "update_task_step",
    "complete_task_step",
    "archive_task_step",
    "restore_task_step",
    "reorder_task_steps",
    "update_step_action",
    "complete_step_action",
    "archive_step_action",
    "restore_step_action",
    "reorder_step_actions",
    "list_tags",
    "list_trash",
    "move_to_trash",
    "restore_from_trash",
    "list_tasks",
    "get_work_board",
    "reorder_work_board_column",
    "get_work_agenda",
    "get_work_hierarchy",
    "list_saved_work_views",
    "create_saved_work_view",
    "update_saved_work_view",
    "archive_saved_work_view",
    "restore_saved_work_view",
    "get_task",
    "create_task",
    "update_task",
    "complete_task",
    "list_assistant_activity",
    "show_work_changes",
    "list_recent_changes",
    "reschedule_tasks",
    "create_tasks",
    "get_today_brief",
}

# D-057: owner commands and app-side writes that an open app calls through tools/call. They carry
# `_meta.ui.visibility == ["app"]` so a host can hide them from the model. Every other tool stays
# model-visible; reads, creates and small updates are deliberately not in this set. The five
# below are hidden to keep the model-visible tool budget small.
APP_ONLY_TOOLS = {
    "finalize_journal_draft",
    "reject_journal_draft",
    "update_journal_draft",
    "create_journal_source",
    "create_manual_journal_entry",
    "get_daily_journal_summary",
    "get_domain",
    "get_process",
    "unlink_contact_from_task",
    "unlink_contact_from_project",
    "unlink_external_reference_from_task",
    "remove_contact_alias",
    "reorder_task_steps",
    "reorder_step_actions",
    "archive_task_step",
    "restore_task_step",
    "archive_step_action",
    "restore_step_action",
    "list_saved_work_views",
    "create_saved_work_view",
    "update_saved_work_view",
    "archive_saved_work_view",
    "restore_saved_work_view",
    "reorder_work_board_column",
    # D-081: the app's license field enters the key; the model never sees a key.
    "set_license_key",
}


@pytest.mark.asyncio
async def test_discovery_has_exact_names_schemas_and_annotations() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.title
        assert tool.description and len(tool.description) >= 40
        assert tool.parameters["additionalProperties"] is False
        assert tool.output_schema is not None
        assert tool.output_schema["additionalProperties"] is False
        assert isinstance(tool.annotations, ToolAnnotations)
        assert tool.annotations.openWorldHint is False
        assert tool.annotations.destructiveHint is (
            tool.name
            in {
                "remove_contact_alias",
                "unlink_contact_from_project",
                "unlink_contact_from_task",
                "unlink_external_reference_from_task",
                "reject_journal_draft",
                "finalize_journal_draft",
                "move_to_trash",
                "set_memory_settings",
            }
        )
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.readOnlyHint is (
            tool.name.startswith(("list_", "get_")) or tool.name in READ_TOOLS_WITHOUT_READ_PREFIX
        )


@pytest.mark.asyncio
async def test_server_instructions_name_the_work_card_and_stay_short() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    instructions = server.instructions or ""
    assert "show_work_changes" in instructions
    assert len(instructions.split("\n")) <= 30
    assert len(instructions) <= 2400


@pytest.mark.asyncio
async def test_server_instructions_state_the_work_data_model_rules() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    instructions = server.instructions or ""
    for phrase in ("Domain", "Project requires a Domain", "23:59", "no card", "contact_ids"):
        assert phrase in instructions


def _resolve_property(prop: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Follow a nullable `anyOf` branch and a `$ref` into `$defs` (pydantic nested models)."""
    schema = prop
    if "anyOf" in schema:
        schema = next(branch for branch in schema["anyOf"] if branch.get("type") != "null")
    if "$ref" in schema:
        schema = defs[schema["$ref"].rsplit("/", 1)[-1]]
    return schema


@pytest.mark.asyncio
async def test_nested_output_records_are_closed_and_do_not_expose_owner() -> None:
    tools = await create_mcp_server(
        create_container(make_settings()), enable_auth=False
    ).list_tools()
    for tool in tools:
        schema_text = str(tool.output_schema)
        assert "owner_id" not in schema_text
        props = tool.output_schema.get("properties", {})
        defs = (tool.output_schema or {}).get("$defs", {})
        possible = ["projects", "tasks", "project", "task", "contact", "contacts"]
        property_name = next((p for p in possible if p in props), None)
        if property_name is None:
            continue
        record_schema = _resolve_property(props[property_name], defs)
        if record_schema.get("type") == "array":
            record_schema = _resolve_property(record_schema["items"], defs)
        assert record_schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_work_app_tools_open_the_sidekick_app() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}
    for name in (
        "get_task",
        "get_project",
        "get_contact_context",
        "get_work_board",
        "get_work_agenda",
        "get_work_hierarchy",
    ):
        assert tools[name].meta["ui"]["resourceUri"] == SIDEKICK_APP_URI, name
    # A page of Contacts names no Task or Contact to open, so it is called from inside the
    # app rather than opening it.
    for name in (
        "list_tasks",
        "list_task_contacts",
    ):
        assert "ui" not in (tools[name].meta or {}), name
    # The saved-view tools are app-only (D-057: hidden from the model until further notice) and
    # still open no view.
    for name in (
        "list_saved_work_views",
        "create_saved_work_view",
        "update_saved_work_view",
        "archive_saved_work_view",
        "restore_saved_work_view",
    ):
        assert "resourceUri" not in (tools[name].meta or {}).get("ui", {}), name


@pytest.mark.asyncio
async def test_journal_app_tools_open_the_sidekick_app() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}
    for name in (
        "get_journal_day",
        "get_journal_entry",
        "list_pending_journal",
        "get_journal_draft",  # the in-app review view is built later
    ):
        assert tools[name].meta["ui"]["resourceUri"] == SIDEKICK_APP_URI, name
    # Lists, summaries and sources are read in the app or by the model; they open no view. The
    # draft commands run from inside the open app after the owner decides, so they open none.
    for name in (
        "list_journal_entries",
        "get_journal_source",
    ):
        assert "ui" not in (tools[name].meta or {}), name
    # The daily summary and the draft commands are app-only (D-057) and still open no view.
    for name in (
        "get_daily_journal_summary",
        "update_journal_draft",
        "reject_journal_draft",
        "finalize_journal_draft",
    ):
        assert "resourceUri" not in (tools[name].meta or {}).get("ui", {}), name


@pytest.mark.asyncio
async def test_app_only_tools_are_pinned_and_no_other_tool_is_app_only() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert len(APP_ONLY_TOOLS) == 25
    assert set(EXPECTED_TOOLS) >= APP_ONLY_TOOLS
    assert app_only_tool_names() == APP_ONLY_TOOLS
    for name in APP_ONLY_TOOLS:
        assert tools[name].meta["ui"]["visibility"] == ["app"], name
    for name, tool in tools.items():
        if name not in APP_ONLY_TOOLS:
            visibility = (tool.meta or {}).get("ui", {}).get("visibility", [])
            assert "app" not in visibility, name

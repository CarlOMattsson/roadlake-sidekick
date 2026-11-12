"""Discovery contract for the fifteen curated Journal MCP tools."""

import pytest
from mcp.types import ToolAnnotations

from sidekick.api.app import create_container
from sidekick.mcp.journal import JOURNAL_TOOL_NAMES, JOURNAL_TOOL_SCOPES
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import MAX_CURSOR_LENGTH
from tests.support.settings import make_settings

EXPECTED_SCOPES = {
    "list_journal_entries": {"journal:read"},
    "get_journal_entry": {"journal:read"},
    "get_journal_day": {"journal:read"},
    "get_daily_journal_summary": {"journal:read"},
    "get_journal_source": {"journal:read"},
    "list_pending_journal": {"journal:read"},
    "create_journal_source": {"journal:write"},
    "create_manual_journal_entry": {
        "journal:write",
        "projects:read",
        "tasks:read",
        "contacts:read",
    },
    "write_journal_entry": {
        "journal:write",
        "projects:read",
        "tasks:read",
        "contacts:read",
    },
    "update_journal_entry": {"journal:read", "journal:write"},
    "set_daily_journal_summary": {"journal:write"},
    "get_journal_draft": {"journal:read", "projects:read", "tasks:read", "contacts:read"},
    "update_journal_draft": {"journal:read", "journal:write"},
    "reject_journal_draft": {"journal:read", "journal:write"},
    "finalize_journal_draft": {
        "journal:read",
        "journal:write",
        "projects:read",
        "tasks:read",
        "contacts:read",
        "tasks:write",
    },
}
# Review is terminal for the draft, so the host may confirm these before running them.
TERMINAL_REVIEW_TOOLS = {"reject_journal_draft", "finalize_journal_draft"}
# D-057 app-only Journal tools, plus the three hidden to keep the tool budget.
# update_journal_entry is model-visible (it is not in this set).
JOURNAL_APP_ONLY_TOOLS = {
    "update_journal_draft",
    "reject_journal_draft",
    "finalize_journal_draft",
    "create_journal_source",
    "create_manual_journal_entry",
    "get_daily_journal_summary",
}
# Only these tools' output may carry source text, by default unless include_content is false.
RAW_TEXT_TOOLS = {"get_journal_source", "get_journal_draft"}


def assert_closed(schema: object) -> None:
    if isinstance(schema, list):
        for item in schema:
            assert_closed(item)
    elif isinstance(schema, dict):
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False
        for key in ("properties", "$defs"):
            for value in schema.get(key, {}).values():
                assert_closed(value)
        for key in ("items", "anyOf", "oneOf"):
            if key in schema:
                assert_closed(schema[key])


@pytest.mark.asyncio
async def test_journal_discovery_exposes_exact_fifteen_closed_tools() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = await server.list_tools()
    journal_tools = [tool for tool in tools if tool.name in JOURNAL_TOOL_NAMES]

    assert {tool.name for tool in journal_tools} == set(JOURNAL_TOOL_NAMES)
    assert len(journal_tools) == 15
    assert JOURNAL_TOOL_SCOPES == EXPECTED_SCOPES
    app_only = {
        tool.name
        for tool in journal_tools
        if (tool.meta or {}).get("ui", {}).get("visibility") == ["app"]
    }
    assert app_only == JOURNAL_APP_ONLY_TOOLS
    assert "update_journal_entry" in {tool.name for tool in journal_tools} - app_only
    assert not {
        tool.name
        for tool in tools
        if "journal" in tool.name and tool.name not in JOURNAL_TOOL_NAMES
    }

    for tool in journal_tools:
        assert tool.title
        assert tool.description and len(tool.description) >= 40
        assert tool.parameters["type"] == "object"
        assert tool.parameters["additionalProperties"] is False
        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        assert tool.output_schema["additionalProperties"] is False
        assert_closed(tool.parameters)
        assert_closed(tool.output_schema)
        assert isinstance(tool.annotations, ToolAnnotations)
        assert tool.annotations.openWorldHint is False
        assert tool.annotations.destructiveHint is (tool.name in TERMINAL_REVIEW_TOOLS)
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.readOnlyHint is tool.name.startswith(("list_", "get_"))


@pytest.mark.asyncio
async def test_journal_discovery_has_contract_bounds_and_no_sensitive_output_fields() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}

    list_schema = tools["list_journal_entries"].parameters
    assert list_schema["properties"]["limit"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "default": 10,
    }
    cursor_schema = list_schema["properties"]["cursor"]
    assert cursor_schema["anyOf"][0]["maxLength"] == MAX_CURSOR_LENGTH
    assert list_schema["properties"]["include_content"]["default"] is True

    day_schema = tools["get_journal_day"].parameters
    assert day_schema["properties"]["limit"]["maximum"] == 50
    assert day_schema["properties"]["include_archived"]["default"] is False
    assert day_schema["properties"]["include_content"]["default"] is True

    source_schema = tools["create_journal_source"].parameters
    assert source_schema["properties"]["raw_text"]["maxLength"] == 100_000
    assert source_schema["properties"]["idempotency_key"]["minLength"] == 8

    manual_schema = tools["create_manual_journal_entry"].parameters
    assert manual_schema["properties"]["project_ids"]["uniqueItems"] is True
    assert manual_schema["properties"]["task_ids"]["uniqueItems"] is True
    assert manual_schema["properties"]["contact_ids"]["uniqueItems"] is True

    source_read_schema = tools["get_journal_source"].parameters
    assert source_read_schema["properties"]["include_content"]["default"] is True
    assert "source_id" in source_read_schema["properties"]
    assert "raw_text" in str(tools["get_journal_source"].output_schema)

    draft_read_schema = tools["get_journal_draft"].parameters
    assert draft_read_schema["properties"]["include_content"]["default"] is True
    assert draft_read_schema["required"] == ["draft_id"]
    assert "raw_text" in str(tools["get_journal_draft"].output_schema)
    for name in ("update_journal_draft", "reject_journal_draft", "finalize_journal_draft"):
        assert {"draft_id", "expected_version", "idempotency_key"} <= set(
            tools[name].parameters["required"]
        ), name
        assert tools[name].parameters["properties"]["expected_version"]["minimum"] == 1
        assert tools[name].parameters["properties"]["idempotency_key"]["minLength"] == 8
        assert "include_content" not in tools[name].parameters["properties"]
    for name in ("update_journal_draft", "finalize_journal_draft"):
        assert tools[name].parameters["properties"]["task_proposals"]["maxItems"] == 20

    for tool in tools.values():
        if tool.name in JOURNAL_TOOL_NAMES:
            schema_text = str(tool.output_schema)
            assert "owner_id" not in schema_text
            # Source text is the one field allowed on the wire, and only through a read of one
            # owned source or its draft (include_content defaults to true, D-060); every other
            # schema omits it.
            if tool.name not in RAW_TEXT_TOOLS:
                assert "raw_text" not in schema_text

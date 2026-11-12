"""Every reviewed MCP contract is still honoured by the running code.

This replaces the frozen whole-document snapshot gates of the early features. Those
compared today's runtime with a byte-for-byte copy of a past moment, so every
additive field or route had to be filtered back out by hand, and the filter list
grew with each feature until the gates only tested the filters.

What is worth holding is compatibility with what was reviewed: each reviewed
operation and tool still exists, keeps its identity, annotations, and shape, still
accepts what it accepted, and still returns what it promised. Later features may add
routes, fields, and optional inputs; they may not remove or reshape a reviewed one,
and they may not make a new input mandatory.

The live snapshot gate lives in `test_generated_contracts.py`, which compares the
checked-in `contracts/*.generated.json` with runtime exactly.
"""

from typing import Any

import pytest

from sidekick.mcp.export_contract import export as export_mcp
from tests.contract.reviewed_contracts import (
    assert_reviewed_tool_still_offered,
    reviewed,
)

MCP_FEATURES = (
    "project-task-mcp",
    "contacts-relationships",
    "journal-review",
)
# Inputs that a later reviewed decision made mandatory on an existing tool or route.
# Every Project must belong to one owner-consistent Domain; see the projects-tasks capability.
NEWLY_REQUIRED_TOOL_INPUTS: dict[str, frozenset[str]] = {
    "create_project": frozenset({"domain_id"}),
}
JOURNAL_TOOL_NAMES = frozenset(
    {
        "list_journal_entries",
        "get_journal_entry",
        "get_journal_day",
        "get_daily_journal_summary",
        "create_journal_source",
        "create_manual_journal_entry",
    }
)


@pytest.mark.asyncio
@pytest.mark.parametrize("feature", MCP_FEATURES)
async def test_reviewed_mcp_tools_are_still_curated(feature: str) -> None:
    document = reviewed(feature, "mcp-tools.yaml")
    runtime_tools = await export_mcp()
    runtime = {tool["name"]: tool for tool in runtime_tools}

    for reviewed_tool in document["tools"]:
        name = reviewed_tool["name"]
        assert name in runtime, name
        assert_reviewed_tool_still_offered(
            reviewed_tool,
            runtime[name],
            reviewed_root=document,
            runtime_root=runtime_tools,
            allowed_new_required=NEWLY_REQUIRED_TOOL_INPUTS.get(name, frozenset()),
        )


def test_update_task_contract_can_explicitly_clear_nullable_fields() -> None:
    document = reviewed("project-task-mcp", "mcp-tools.yaml")
    nullable = document["$defs"]["updateTaskInput"]["properties"]["changes"]["properties"]

    assert {"null"} <= set(nullable["description"]["type"])
    assert {"null"} <= set(nullable["project_id"]["type"])
    assert {"null"} <= set(nullable["due_at"]["type"])


@pytest.mark.asyncio
async def test_journal_mcp_surface_is_exactly_the_six_reviewed_tools() -> None:
    document = reviewed("journal-review", "mcp-tools.yaml")
    runtime = {tool["name"] for tool in await export_mcp()}

    assert {tool["name"] for tool in document["tools"]} == set(JOURNAL_TOOL_NAMES)
    assert runtime >= JOURNAL_TOOL_NAMES
    # AI processing and the daily-summary writes stay out of the public surface by decision.
    # The four draft-review tools were admitted by review as explicit owner commands;
    # `test_journal_review_tools_are_not_automatic.py` pins that the assistant cannot reach them.
    assert runtime >= {
        "get_journal_draft",
        "update_journal_draft",
        "reject_journal_draft",
        "finalize_journal_draft",
    }
    assert not runtime & {
        "process_journal_source",
        "put_manual_daily_journal_summary",
        "generate_daily_journal_summary_proposal",
        "accept_daily_journal_summary_proposal",
    }


@pytest.mark.asyncio
async def test_journal_tool_payloads_match_the_reviewed_schemas() -> None:
    document = reviewed("journal-review", "mcp-tools.yaml")
    runtime_tools = await export_mcp()
    runtime = {tool["name"]: tool for tool in runtime_tools}

    for reviewed_tool in document["tools"]:
        assert_reviewed_tool_still_offered(
            reviewed_tool,
            runtime[reviewed_tool["name"]],
            reviewed_root=document,
            runtime_root=runtime_tools,
            compare_output=True,
        )


def assert_closed_objects(schema: Any, path: str = "$") -> None:
    """Assert every inline object schema is explicitly closed."""

    if isinstance(schema, list):
        for index, item in enumerate(schema):
            assert_closed_objects(item, f"{path}[{index}]")
        return
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False, f"open object schema at {path}"
    for key in ("properties", "$defs"):
        for name, child in schema.get(key, {}).items():
            assert_closed_objects(child, f"{path}.{key}.{name}")
    for key in ("items", "oneOf", "anyOf"):
        if key in schema:
            assert_closed_objects(schema[key], f"{path}.{key}")


def test_reviewed_journal_contracts_are_closed() -> None:
    mcp = reviewed("journal-review", "mcp-tools.yaml")
    analysis = reviewed("journal-review", "journal-analysis.schema.json")

    for schema in mcp["$defs"].values():
        assert_closed_objects(schema)
    assert_closed_objects(analysis)

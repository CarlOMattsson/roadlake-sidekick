"""The reviewed Work context MCP contract stays stable apart from additive fields.

The restored-Work generated fixture is a historical artifact. Later changes may add
*optional* planning metadata to these reviewed tools; they may not rename a tool,
change an annotation, or change a scope. This test therefore compares the fixture
against runtime with the reviewed additive planning properties removed, exactly as
the legacy OpenAPI snapshot gates strip additive paths. The current curated surface
size is asserted separately in `test_ui_surface_stability`.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sidekick.mcp.export_contract import export as export_mcp
from tests.contract.reviewed_contracts import (
    expected_tool_annotations,
    expected_tool_description,
    expected_tool_title,
    with_reviewed_cursor_bound,
)

WORK_TOOLS = {
    "list_domains",
    "get_domain",
    "create_domain",
    "list_processes",
    "get_process",
    "create_process",
}

ADDITIVE_PLANNING_FIELDS = frozenset(
    {
        "review_cadence",
        "last_reviewed_at",
        "cadence",
        "tags",
        "definition_of_done",
        "not_before",
        "estimated_minutes",
        "waiting_since",
        "follow_up_at",
        "waiting_on_contact_id",
        "instruction",
        "note",
        # D-061: optional domain colour, added after the reviewed fixture.
        "accent",
        "domain_accent",
    }
)


# Tools hidden from the model to keep the tool budget. Hiding only adds
# `_meta.ui.visibility`, so the reviewed schema itself is unchanged.
HIDDEN_AFTER_REVIEW = frozenset({"get_domain", "get_process"})


def _without_hidden_meta(tool: dict[str, Any]) -> dict[str, Any]:
    if tool["name"] in HIDDEN_AFTER_REVIEW and tool.get("_meta") == {"ui": {"visibility": ["app"]}}:
        return {key: value for key, value in tool.items() if key != "_meta"}
    return tool


def _strip_planning_fields(value: Any) -> Any:
    """Remove the additive optional planning properties from a JSON schema tree."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "properties" and isinstance(item, dict):
                result[key] = {
                    name: _strip_planning_fields(field)
                    for name, field in item.items()
                    if name not in ADDITIVE_PLANNING_FIELDS
                }
                continue
            if key == "required" and isinstance(item, list):
                result[key] = [name for name in item if name not in ADDITIVE_PLANNING_FIELDS]
                continue
            result[key] = _strip_planning_fields(item)
        return result
    if isinstance(value, list):
        return [_strip_planning_fields(item) for item in value]
    return value


@pytest.mark.asyncio
async def test_work_mcp_contract_fixture_matches_discovery() -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[3] / "contracts/reviewed/work-restore/mcp-tools.generated.json"
        ).read_text()
    )
    runtime = await export_mcp()

    reviewed_runtime = [
        _strip_planning_fields(_without_hidden_meta(with_reviewed_cursor_bound(deepcopy(tool))))
        for tool in runtime
        if tool["name"] in WORK_TOOLS
    ]
    reviewed_fixture = [
        {
            **tool,
            "title": expected_tool_title(tool["title"]),
            "description": expected_tool_description(tool),
            "annotations": expected_tool_annotations(tool),
        }
        for tool in fixture
        if tool["name"] in WORK_TOOLS
    ]

    assert reviewed_runtime == reviewed_fixture
    assert {tool["name"] for tool in fixture if tool["name"] in WORK_TOOLS} == WORK_TOOLS

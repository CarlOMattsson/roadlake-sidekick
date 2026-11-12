"""The checked-in contract snapshots are the current runtime contract.

`contracts/openapi.generated.json` is what the frontend generates its types from, and
`contracts/mcp-tools.generated.json` is the reviewed curated MCP surface. Both are
regenerated deliberately, so a drifting snapshot is a failing test rather than a
silent difference between the API and the client.

Regenerate with:
    uv run --project backend python -m sidekick.api.export_openapi \
        --output contracts/openapi.generated.json
    uv run --project backend python -m sidekick.mcp.export_contract \
        --output contracts/mcp-tools.generated.json
"""

import json
from pathlib import Path

import pytest

from sidekick.api.app import create_app
from sidekick.mcp.export_contract import export as export_mcp

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def test_openapi_snapshot_matches_the_running_api() -> None:
    snapshot = json.loads((CONTRACTS / "openapi.generated.json").read_text(encoding="utf-8"))

    assert snapshot == json.loads(json.dumps(create_app().openapi()))


@pytest.mark.asyncio
async def test_mcp_snapshot_matches_the_curated_surface() -> None:
    snapshot = json.loads((CONTRACTS / "mcp-tools.generated.json").read_text(encoding="utf-8"))
    runtime = json.loads(json.dumps(await export_mcp()))

    # This equality is what pins the curated tool count: the snapshot's size is the count.
    assert snapshot == runtime
    assert "list_tags" in {tool["name"] for tool in snapshot}


# The shopping card opens for the list read and for the two writes that answer with its batch and
# item view. set_shopping_item_purchased and the list writes open no card, so they stay out.
# Every app tool names the one shared Sidekick app resource, so the card tools point there too.
SIDEKICK_APP_URI = "ui://sidekick/app-v1.html"
SHOPPING_CARD_TOOLS = ("get_shopping_list", "add_shopping_items", "update_shopping_item")


def test_shopping_card_tools_open_the_sidekick_app_in_the_snapshot() -> None:
    snapshot = json.loads((CONTRACTS / "mcp-tools.generated.json").read_text(encoding="utf-8"))
    tools = {tool["name"]: tool for tool in snapshot}

    for name in SHOPPING_CARD_TOOLS:
        assert tools[name]["_meta"]["ui"]["resourceUri"] == SIDEKICK_APP_URI, name
    for name in ("set_shopping_item_purchased", "create_shopping_list", "update_shopping_list"):
        assert "ui" not in tools[name].get("_meta", {}), name


# The added-items and updated-item cards name their list, so both answers carry list_name as a
# required string next to the existing fields, which must stay.
SHOPPING_LIST_NAME_TOOLS = ("add_shopping_items", "update_shopping_item")


def test_shopping_batch_and_item_results_name_their_list_in_the_snapshot() -> None:
    snapshot = json.loads((CONTRACTS / "mcp-tools.generated.json").read_text(encoding="utf-8"))
    tools = {tool["name"]: tool for tool in snapshot}

    for name in SHOPPING_LIST_NAME_TOOLS:
        output = tools[name]["outputSchema"]
        assert output["properties"]["list_name"] == {"title": "List Name", "type": "string"}, name
        assert "list_name" in output["required"], name
        assert {"items" if name == "add_shopping_items" else "item", "evaluated_on"} <= set(
            output["required"]
        ), name

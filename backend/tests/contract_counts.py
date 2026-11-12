"""Single source for the curated MCP tool count: the checked-in contract snapshot.

The count is never hardcoded in a test. `contracts/mcp-tools.generated.json` is the reviewed
surface, and `test_generated_contracts.py` pins that snapshot to the runtime export, so a test
that compares a runtime tool list against this count is pinned by the same snapshot.
"""

import json
from pathlib import Path

MCP_TOOLS_SNAPSHOT = Path(__file__).resolve().parents[2] / "contracts" / "mcp-tools.generated.json"


def curated_tool_count() -> int:
    """Return the number of tools in the reviewed curated MCP snapshot."""
    return len(json.loads(MCP_TOOLS_SNAPSHOT.read_text(encoding="utf-8")))


def app_only_tool_names() -> frozenset[str]:
    """Return the names the reviewed snapshot marks app-only (`_meta.ui.visibility == ["app"]`)."""
    tools = json.loads(MCP_TOOLS_SNAPSHOT.read_text(encoding="utf-8"))
    return frozenset(
        tool["name"]
        for tool in tools
        if (tool.get("_meta") or {}).get("ui", {}).get("visibility") == ["app"]
    )

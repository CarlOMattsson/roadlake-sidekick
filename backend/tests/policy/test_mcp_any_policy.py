"""The MCP layer does not gain `Any` annotations (typing ratchet).

A tool returns a `ToolResult`, a text helper reads a record it can name. `MAX_ANY` is the number
of `Any` names under `mcp/` today (annotations, casts and type arguments; imports do not count).
It only shrinks: when you replace another `Any` with a precise type, lower the number to the new
count; never raise it to get a build green.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

MCP_ROOT = Path(__file__).resolve().parents[2] / "src" / "sidekick" / "mcp"
MAX_ANY = 1


def _any_names() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(MCP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "Any")
        if count:
            counts[path.relative_to(MCP_ROOT).as_posix()] = count
    return counts


def test_mcp_does_not_gain_any() -> None:
    counts = _any_names()
    total = sum(counts.values())
    assert total <= MAX_ANY, (
        f"mcp/ has {total} `Any` (cap {MAX_ANY}); use a precise type instead:\n"
        + "\n".join(f"{path}: {count}" for path, count in counts.items())
    )


def test_cap_is_not_stale() -> None:
    total = sum(_any_names().values())
    assert total == MAX_ANY, f"lower MAX_ANY to {total}"

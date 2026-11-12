"""No function in backend/src/sidekick is longer than the limit (maintainability policy).

Long functions hide several steps behind one name. Split them into well-named private helpers
instead of raising the limit. The allowlist holds the functions that could not reasonably be
split yet; remove an entry when the function is shortened, never add one for new code.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "sidekick"
MAX_FUNCTION_LINES = 120
# (path relative to the sidekick package, function name) -> reason
ALLOWLIST: dict[tuple[str, str], str] = {}


def _function_lengths() -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                assert node.end_lineno is not None
                found.append((relative, node.name, node.end_lineno - node.lineno + 1))
    return found


def test_no_function_exceeds_the_line_limit() -> None:
    too_long = [
        f"{path}:{name} has {length} lines (limit {MAX_FUNCTION_LINES})"
        for path, name, length in _function_lengths()
        if length > MAX_FUNCTION_LINES and (path, name) not in ALLOWLIST
    ]
    assert not too_long, "split these into private helpers:\n" + "\n".join(too_long)


def test_allowlist_has_no_stale_entries() -> None:
    lengths = {(path, name): length for path, name, length in _function_lengths()}
    stale = [
        f"{path}:{name}"
        for (path, name) in ALLOWLIST
        if lengths.get((path, name), 0) <= MAX_FUNCTION_LINES
    ]
    assert not stale, "remove from ALLOWLIST (now short enough or gone):\n" + "\n".join(stale)

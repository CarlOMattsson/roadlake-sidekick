"""Page sizes are checked with `validate_limit` and pages are cut with `paginate`.

Both live in `sidekick.shared.types`. A hand-written `1 <= limit <= N` check or a `rows[:limit]`
slicing gives that one list its own wording, error class or off-by-one; a list read goes through
the shared helpers instead. `ALLOWED_SLICES` names the places that cut a list for another reason
than paging a read, and every entry says why.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "sidekick"
ALLOWED_SLICES = {
    "shared/types/core.py": "the implementation of paginate",
    "lifecycle/persistence.py": "merges per-kind lists in memory, then trims the merged result",
    "mcp/text.py": "a card shows its first rows and counts the rest, it is not a page read",
}


def _limit_name(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id.endswith("limit")
    return isinstance(node, ast.Attribute) and node.attr.endswith("limit")


def _handwritten_paging(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Slice)
            and node.slice.lower is None
            and node.slice.upper is not None
            and _limit_name(node.slice.upper)
        ):
            lines.append(node.lineno)
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 2
            and all(isinstance(op, ast.LtE) for op in node.ops)
            and _limit_name(node.comparators[0])
        ):
            lines.append(node.lineno)
    return sorted(lines)


def _offenders() -> list[str]:
    found: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT).as_posix()
        if relative in ALLOWED_SLICES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(f"{relative}:{line}" for line in _handwritten_paging(tree))
    return found


def test_page_bounds_and_slices_use_the_shared_helpers() -> None:
    offenders = _offenders()
    assert not offenders, (
        "use validate_limit / paginate from sidekick.shared.types instead of a hand-written "
        "limit check or `[:limit]` slicing:\n" + "\n".join(offenders)
    )


def test_the_detector_sees_both_hand_written_forms() -> None:
    tree = ast.parse("if not 1 <= limit <= 100:\n    raise ValueError\npage = rows[:limit]\n")
    assert _handwritten_paging(tree) == [1, 3]


def test_every_allowed_slice_still_exists_and_needs_the_exception() -> None:
    for relative in ALLOWED_SLICES:
        path = SRC_ROOT / relative
        assert path.is_file(), f"{relative} no longer exists; drop it from ALLOWED_SLICES"
        if relative == "shared/types/core.py":
            continue
        assert _handwritten_paging(ast.parse(path.read_text(encoding="utf-8"))), (
            f"{relative} no longer cuts by limit; drop it from ALLOWED_SLICES"
        )

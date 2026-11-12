"""Every exception class in the package belongs to the `SidekickError` tree.

The API and MCP boundaries translate errors by class and `code`. An exception that sits outside
the tree (a bare `ValueError`, `LookupError`, `PermissionError`, `Exception`) is translated ad hoc
or becomes an unexplained 500. Define new errors under `SidekickError` (see
`sidekick.shared.errors.core`). The allowlist is closed: each entry needs a reason.
"""

import ast
import builtins
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "sidekick"

# (module path relative to src/sidekick, class name) -> why it stays outside the tree.
ALLOWLIST = {
    ("shared/errors/core.py", "InvalidInputError"): "stays a ValueError so callers that "
    "translate ValueError keep working; the boundaries name it in CLIENT_INPUT_ERRORS",
    ("api/companion.py", "CompanionProblem"): "the companion envelope itself, raised and "
    "rendered only inside the companion route",
}

BUILTIN_EXCEPTIONS = {
    name
    for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException)
}


def _classes() -> dict[str, list[tuple[str, list[str]]]]:
    found: dict[str, list[tuple[str, list[str]]]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(SRC).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [
                    base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                    for base in node.bases
                ]
                found.setdefault(node.name, []).append((relative, bases))
    return found


def _reaches(name: str, goal: str, classes: dict[str, list[tuple[str, list[str]]]]) -> bool:
    seen: set[str] = set()
    stack = [name]
    while stack:
        current = stack.pop()
        if current == goal:
            return True
        if current in seen:
            continue
        seen.add(current)
        for _path, bases in classes.get(current, []):
            stack.extend(bases)
    return False


def test_every_exception_class_derives_from_sidekick_error() -> None:
    classes = _classes()
    offenders = []
    for name, definitions in classes.items():
        for path, _bases in definitions:
            if _reaches(name, "SidekickError", classes) or (path, name) in ALLOWLIST:
                continue
            if any(_reaches(name, builtin, classes) for builtin in BUILTIN_EXCEPTIONS):
                offenders.append(f"{path}: {name}")
    assert not offenders, (
        "exception classes outside the SidekickError tree (derive from SidekickError): "
        + ", ".join(offenders)
    )


def test_allowlist_entries_still_exist() -> None:
    classes = _classes()
    for path, name in ALLOWLIST:
        assert any(p == path for p, _ in classes.get(name, [])), f"stale allowlist entry {name}"


def test_the_builtin_permission_error_is_neither_raised_nor_caught() -> None:
    """`PermissionError` is an `OSError`; a refused right is `PermissionDeniedError` (ADR-010).

    The class-definition check above cannot see what is raised, so this one reads the code.
    """

    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Name) and node.id == "PermissionError":
                offenders.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    assert not offenders, "built-in PermissionError used (use PermissionDeniedError): " + ", ".join(
        offenders
    )

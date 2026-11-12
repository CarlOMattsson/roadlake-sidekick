"""Private parts of third-party libraries are only reached through `sidekick/shared/compat.py`.

An underscore attribute, a private class or a private module of a library has no stability
promise, so a library upgrade must re-check each use by hand. `sidekick/shared/compat.py` is the one
place that lists them. This test reads every source file with `ast` and fails when another file
accesses an underscore name of a library (`obj._name`, `getattr(obj, "_name")`, or an import of a
private name or module). Access to `self`/`cls` and to this project's own modules is fine.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SOURCE = Path(__file__).resolve().parents[2] / "src" / "sidekick"
COMPAT = SOURCE / "shared" / "compat.py"
# Files that keep private access of their own, each with the reason and the probe that guards it.
ALLOWED: dict[str, str] = {
    "shared/observability/span_allowlist.py": (
        "rewrites private ReadableSpan fields; probed by sdk_internals.span_rewrite_problem"
    ),
    "shared/observability/setup.py": (
        "rewrites private ReadableSpan fields; probed by sdk_internals.span_rewrite_problem"
    ),
    "mcp/oauth.py": (
        "overrides FileTreeStore._setup_collection; startup is refused by _require_file_tree_hooks"
    ),
    "lifecycle/persistence.py": "private helpers of its own LifecycleStore class, not a library",
    "references/domain.py": "NamedTuple._replace is public API despite the underscore",
}
_OWN_OBJECTS = frozenset({"self", "cls", "mcs"})


def _is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def violations(source: str, label: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and _is_private(node.attr):
            owner = node.value
            if not (isinstance(owner, ast.Name) and owner.id in _OWN_OBJECTS):
                found.append(f"{label}:{node.lineno}: .{node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = node.args
            if (
                node.func.id in {"getattr", "setattr", "hasattr", "delattr"}
                and len(args) > 1
                and isinstance(args[1], ast.Constant)
                and isinstance(args[1].value, str)
                and _is_private(args[1].value)
            ):
                found.append(f"{label}:{node.lineno}: {node.func.id}(..., {args[1].value!r})")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[0] in {"sidekick", "__future__"}:
                continue
            private = [a.name for a in node.names if _is_private(a.name)]
            private += [part for part in node.module.split(".") if _is_private(part)]
            found.extend(f"{label}:{node.lineno}: import {name}" for name in private)
        elif isinstance(node, ast.Import):
            found.extend(
                f"{label}:{node.lineno}: import {alias.name}"
                for alias in node.names
                if any(_is_private(part) for part in alias.name.split("."))
            )
    return found


def test_private_library_access_lives_only_in_compat() -> None:
    found: list[str] = []
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        if path == COMPAT or relative in ALLOWED:
            continue
        found.extend(violations(path.read_text(encoding="utf-8"), relative))
    assert found == [], "move private library access into sidekick/shared/compat.py:\n" + "\n".join(
        found
    )


def test_every_allowed_file_still_needs_its_exception() -> None:
    stale = [
        relative
        for relative in ALLOWED
        if not violations((SOURCE / relative).read_text(encoding="utf-8"), relative)
    ]
    assert stale == [], f"remove from ALLOWED, no private access left: {stale}"


@pytest.mark.parametrize(
    "source",
    [
        "server._mcp_server.x = 1",
        "getattr(provider, '_active_span_processor', None)",
        "from argparse import _SubParsersAction",
        "import mcp.server._modern",
        "isinstance(a, argparse._HelpAction)",
    ],
)
def test_the_check_flags_private_library_access(source: str) -> None:
    assert violations(source, "x.py") != []


@pytest.mark.parametrize(
    "source",
    [
        "self._value = 1",
        "from sidekick.shared._private import thing",
        "from __future__ import annotations",
        "x = obj.__class__",
    ],
)
def test_the_check_accepts_own_and_dunder_names(source: str) -> None:
    assert violations(source, "x.py") == []

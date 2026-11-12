"""The shared store members are declared once, in `sidekick.shared.types.ports`.

`transaction`, `idempotent` and `append_audit` are identical in every context's store Protocol.
A context Protocol inherits `TransactionalStore`, `IdempotentStore` and `AuditingStore` instead of
re-declaring them, so a signature change is made in one place.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "sidekick"
PORTS_MODULE = "shared/types/ports.py"
SHARED_MEMBERS = frozenset({"transaction", "idempotent", "append_audit"})


def _is_protocol(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name == "Protocol":
            return True
    return False


def _redeclarations() -> list[str]:
    found: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        if relative == PORTS_MODULE:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.ClassDef) and _is_protocol(node)):
                continue
            found.extend(
                f"{relative}: {node.name}.{member.name}"
                for member in node.body
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
                and member.name in SHARED_MEMBERS
            )
    return found


def test_context_protocols_do_not_redeclare_the_shared_store_members() -> None:
    redeclared = _redeclarations()
    assert not redeclared, (
        "inherit TransactionalStore / IdempotentStore / AuditingStore from "
        "sidekick.shared.types instead of re-declaring:\n" + "\n".join(redeclared)
    )


def test_ports_module_declares_each_shared_member() -> None:
    tree = ast.parse((SOURCE_ROOT / PORTS_MODULE).read_text(encoding="utf-8"))
    declared = {
        member.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _is_protocol(node)
        for member in node.body
        if isinstance(member, ast.FunctionDef)
    }
    assert declared == SHARED_MEMBERS

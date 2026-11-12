"""Test files never import from other test files.

Helpers shared between tests live in `tests/support/` (or in a conftest or another non-test
module). Importing from a `test_*` module couples one test file to another: renaming or
splitting the exporting file breaks unrelated tests, and pytest may collect the helper's
tests twice. The check parses every file under `tests/` and rejects any import whose module,
or any imported submodule, is named `test_*`.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

TESTS = Path(__file__).resolve().parents[1]
# Explicit, reasoned exceptions as "relative/path.py": reason. Empty: nothing needs one.
ALLOWED: dict[str, str] = {}


def _is_test_module(dotted: str) -> bool:
    return any(part.startswith("test_") for part in dotted.split("."))


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                f"{path}:{node.lineno}: import {alias.name}"
                for alias in node.names
                if _is_test_module(alias.name)
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module and _is_test_module(node.module):
                found.append(f"{path}:{node.lineno}: from {node.module} import ...")
            else:
                found.extend(
                    f"{path}:{node.lineno}: from {node.module or '.'} import {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("test_")
                )
    return found


def test_no_test_file_imports_from_another_test_file() -> None:
    violations = [
        violation
        for path in sorted(TESTS.rglob("*.py"))
        if str(path.relative_to(TESTS)) not in ALLOWED
        for violation in _violations(path)
    ]
    assert violations == [], "move the shared helper to tests/support/:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    "source",
    [
        "from tests.api.test_companion import owner\n",
        "from tests.api import test_companion\n",
        "import tests.api.test_companion\n",
        "from .test_companion import owner\n",
    ],
)
def test_the_policy_detects_a_violation(tmp_path: Path, source: str) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(source, encoding="utf-8")
    assert len(_violations(sample)) == 1


def test_the_policy_accepts_support_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("from tests.support.companion import owner\n", encoding="utf-8")
    assert _violations(sample) == []

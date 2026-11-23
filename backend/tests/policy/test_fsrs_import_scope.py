"""Only the scheduling module imports the FSRS library.

The rest of the code deals in the module's own card state and grades, so a library upgrade is
checked in one place (against the golden values in the scheduling tests), and the optimizer
extra (torch) cannot creep in through another import.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SRC = Path(__file__).resolve().parents[2] / "src"
SCHEDULING = SRC / "sidekick" / "review" / "domain" / "scheduling.py"


def _imports_fsrs(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        else:
            continue
        if any(name == "fsrs" or name.startswith("fsrs.") for name in names):
            return True
    return False


def test_only_the_scheduling_module_imports_fsrs() -> None:
    importers = sorted(
        path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py") if _imports_fsrs(path)
    )

    assert importers == [SCHEDULING.relative_to(SRC).as_posix()]

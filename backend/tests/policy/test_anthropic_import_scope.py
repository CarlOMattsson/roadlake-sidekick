"""Only the model adapter imports the Anthropic SDK.

The SDK reads ANTHROPIC_* variables, traces calls and can quote a request in its errors. Keeping
it behind one module keeps those settings and the error mapping in one place.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SRC = Path(__file__).resolve().parents[2] / "src"
ADAPTER = SRC / "sidekick" / "work" / "infrastructure" / "anthropic_model.py"


def _imports_anthropic(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        else:
            continue
        if any(name == "anthropic" or name.startswith("anthropic.") for name in names):
            return True
    return False


def test_only_the_model_adapter_imports_the_anthropic_sdk() -> None:
    importers = sorted(
        path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py") if _imports_anthropic(path)
    )

    assert importers == [ADAPTER.relative_to(SRC).as_posix()]

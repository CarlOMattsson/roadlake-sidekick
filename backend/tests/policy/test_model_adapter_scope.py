"""The OpenAI-compatible adapter speaks plain HTTP and imports no vendor SDK.

An SDK reads its own environment variables, traces calls and can quote a request in its errors.
The adapter keeps the destination, the redirect rule and the error mapping in one module instead.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SRC = Path(__file__).resolve().parents[2] / "src"
VENDOR_SDKS = ("openai", "litellm", "langchain", "langchain_openai", "ollama")


def _imported_names(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.append(node.module or "")
    return names


def test_no_module_imports_an_openai_compatible_vendor_sdk() -> None:
    importers = sorted(
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if any(
            name == sdk or name.startswith(f"{sdk}.")
            for name in _imported_names(path)
            for sdk in VENDOR_SDKS
        )
    )

    assert importers == []

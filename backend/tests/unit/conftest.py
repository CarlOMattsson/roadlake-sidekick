"""Shared fixtures for the unit suite."""

import ast
from pathlib import Path

import pytest


class _ParsedSources(dict[Path, tuple[str, ast.Module]]):
    """Source text and AST per file, read and parsed once per pytest session.

    A missing key is loaded on first access, so only the files a test actually walks are parsed,
    and every later test in the session reuses the same entry.
    """

    def __missing__(self, path: Path) -> tuple[str, ast.Module]:
        text = path.read_text(encoding="utf-8")
        entry = (text, ast.parse(text, filename=str(path)))
        self[path] = entry
        return entry


@pytest.fixture(scope="session")
def parsed_sources() -> dict[Path, tuple[str, ast.Module]]:
    """Maps a source path to `(source_text, ast.Module)`; shared by the static boundary gates."""

    return _ParsedSources()

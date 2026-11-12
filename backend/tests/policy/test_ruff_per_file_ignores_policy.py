"""Every literal per-file-ignore in pyproject.toml must name a file that exists.

Glob patterns are skipped here because they may legitimately match nothing in a checkout.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
GLOB_CHARS = set("*?[")


def test_every_literal_per_file_ignore_points_to_an_existing_file() -> None:
    config = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    missing = [
        pattern
        for pattern in ignores
        if not GLOB_CHARS & set(pattern) and not (BACKEND / pattern).is_file()
    ]
    assert missing == [], f"per-file-ignores point to files that do not exist: {missing}"

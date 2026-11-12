"""Every decision id (`D-0xx`) that docs/ or backend/src mention exists in the decision log.

The log is `docs/decisions/log.md`, plus `archive.md` where replaced decisions
live (a decision that is replaced moves to the archive).
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

ROOT = Path(__file__).resolve().parents[3]
DECISIONS = ROOT / "docs" / "decisions"
DECISION_ID = re.compile(r"\bD-\d{3}\b")
SUFFIXES = {".md", ".py", ".yaml", ".yml", ".html", ".sql", ".toml"}


def _logged_ids() -> set[str]:
    ids: set[str] = set()
    for name in ("log.md", "archive.md"):
        path = DECISIONS / name
        if path.is_file():
            ids |= set(DECISION_ID.findall(path.read_text(encoding="utf-8")))
    return ids


def test_the_decision_log_is_not_empty() -> None:
    assert len(_logged_ids()) > 10


def test_every_referenced_decision_id_is_in_the_log() -> None:
    logged = _logged_ids()
    missing: dict[str, list[str]] = {}
    for base in (ROOT / "docs", ROOT / "backend" / "src"):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            for found in set(
                DECISION_ID.findall(path.read_text(encoding="utf-8", errors="ignore"))
            ):
                if found not in logged:
                    missing.setdefault(found, []).append(path.relative_to(ROOT).as_posix())
    assert not missing, f"decision ids referenced but missing from the log: {missing}"

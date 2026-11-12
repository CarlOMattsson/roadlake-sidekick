"""Every ADR file under docs/decisions/adr is listed in the ADR index, docs/decisions/README.md."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

ROOT = Path(__file__).resolve().parents[3]
DECISIONS_DIR = ROOT / "docs" / "decisions"
ADR_DIR = DECISIONS_DIR / "adr"


def _adr_files() -> list[Path]:
    return sorted(ADR_DIR.rglob("ADR-*.md"))


def test_adr_files_exist() -> None:
    assert _adr_files()


def test_every_adr_is_in_the_index() -> None:
    text = (DECISIONS_DIR / "README.md").read_text(encoding="utf-8")
    missing = [
        p.relative_to(DECISIONS_DIR).as_posix()
        for p in _adr_files()
        if f"]({p.relative_to(DECISIONS_DIR).as_posix()})" not in text
    ]
    assert not missing, f"ADRs missing from docs/decisions/README.md: {missing}"

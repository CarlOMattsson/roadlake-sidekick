"""Every OSV-Scanner exception has a reason and an expiry date that is near and has not passed.

OSV-Scanner and the OpenSSF Scorecard Vulnerabilities check read osv-scanner.toml next to the
lockfile and nowhere else. An exception is a decision to live with a finding for a while, so it
must say why and lapse on its own, like the pip-audit exceptions.
"""

import datetime
import os
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

ROOT = Path(__file__).resolve().parents[3]
MAX_EXCEPTION_DAYS = 90
LOCKFILES = ("package-lock.json", "uv.lock")
SKIPPED_DIRECTORIES = {".git", ".venv", "node_modules"}


def _config_files() -> list[Path]:
    found = []
    for directory, subdirectories, files in os.walk(ROOT):
        subdirectories[:] = [name for name in subdirectories if name not in SKIPPED_DIRECTORIES]
        found.extend(Path(directory) / name for name in files if name.endswith("osv-scanner.toml"))
    return sorted(found)


CONFIGS = _config_files()


def label(path: Path) -> str:
    return str(path.relative_to(ROOT))


def test_the_exception_files_are_found() -> None:
    assert CONFIGS


@pytest.mark.parametrize("path", CONFIGS, ids=label)
def test_the_scanner_reads_the_file_next_to_a_lockfile(path: Path) -> None:
    assert path.name == "osv-scanner.toml", f"{label(path)}: the scanner reads only that name"
    assert any((path.parent / lock).exists() for lock in LOCKFILES), (
        f"{label(path)}: not next to a lockfile, so the scanner never reads it"
    )


@pytest.mark.parametrize("path", CONFIGS, ids=label)
def test_every_exception_has_a_reason_and_an_expiry_date_that_has_not_passed(path: Path) -> None:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    assert set(config) <= {"IgnoredVulns"}, f"{label(path)}: only IgnoredVulns entries are used"
    today = datetime.date.today()
    limit = today + datetime.timedelta(days=MAX_EXCEPTION_DAYS)
    for entry in config.get("IgnoredVulns", []):
        advisory = entry.get("id")
        assert advisory, f"{label(path)}: an entry has no id"
        assert len(str(entry.get("reason", "")).strip()) >= 40, f"{advisory} has no real reason"
        expiry = entry.get("ignoreUntil")
        assert isinstance(expiry, datetime.date), f"{advisory} needs ignoreUntil = YYYY-MM-DD"
        assert expiry >= today, f"the exception for {advisory} expired on {expiry}; decide again"
        assert expiry <= limit, f"the exception for {advisory} runs past {MAX_EXCEPTION_DAYS} days"

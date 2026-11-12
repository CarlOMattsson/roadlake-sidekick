"""No Python file in backend/src/sidekick grows past 1000 lines (maintainability ratchet).

Long modules hide several responsibilities behind one name. Split them per use case group (see
`tasks/application/` for the pattern) instead of raising a cap. `LEGACY_CAPS` holds the files that
are still over the limit, each with the length it has today as its ceiling: a listed file may not
grow, and no new file may pass the limit. The list only shrinks. When you split a file, delete
its entry (the stale-entry test fails until you do); never add an entry or raise a number to
get a build green.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "sidekick"
MAX_FILE_LINES = 1000
# path relative to the sidekick package -> its line count when the ratchet was set. Shrink only.
LEGACY_CAPS: dict[str, int] = {}


def _line_counts() -> dict[str, int]:
    return {
        path.relative_to(SOURCE_ROOT).as_posix(): len(path.read_text(encoding="utf-8").splitlines())
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
    }


def test_no_unlisted_file_exceeds_the_line_limit() -> None:
    too_long = [
        f"{path} has {count} lines (limit {MAX_FILE_LINES})"
        for path, count in _line_counts().items()
        if count > MAX_FILE_LINES and path not in LEGACY_CAPS
    ]
    assert not too_long, "split these per use case group:\n" + "\n".join(too_long)


def test_listed_files_do_not_grow() -> None:
    counts = _line_counts()
    grown = [
        f"{path} has {counts[path]} lines (cap {cap})"
        for path, cap in LEGACY_CAPS.items()
        if counts.get(path, 0) > cap
    ]
    assert not grown, "a listed file may only shrink:\n" + "\n".join(grown)


def test_legacy_caps_have_no_stale_entries() -> None:
    counts = _line_counts()
    stale = [path for path in LEGACY_CAPS if counts.get(path, 0) <= MAX_FILE_LINES]
    assert not stale, "remove from LEGACY_CAPS (now short enough or gone):\n" + "\n".join(stale)

"""The Work context does not gain untyped `dict[str, Any]` shapes (typing ratchet).

Work rows have their own types (`WorkRow` and the commands in `work/application/models.py`);
a plain `dict[str, Any]` hides which fields exist. `MAX_UNTYPED_DICTS` is the number of
occurrences under `work/` today. It only shrinks: when you type another shape, lower the number
to the new count; never raise it to get a build green.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

WORK_ROOT = Path(__file__).resolve().parents[2] / "src" / "sidekick" / "work"
MAX_UNTYPED_DICTS = 4
NEEDLE = "dict[str, Any]"


def _untyped_dicts() -> dict[str, int]:
    counts = {
        path.relative_to(WORK_ROOT).as_posix(): path.read_text(encoding="utf-8").count(NEEDLE)
        for path in sorted(WORK_ROOT.rglob("*.py"))
    }
    return {path: count for path, count in counts.items() if count}


def test_work_does_not_gain_untyped_dicts() -> None:
    counts = _untyped_dicts()
    total = sum(counts.values())
    assert total <= MAX_UNTYPED_DICTS, (
        f"work/ has {total} `{NEEDLE}` (cap {MAX_UNTYPED_DICTS}); type the shape instead:\n"
        + "\n".join(f"{path}: {count}" for path, count in counts.items())
    )


def test_cap_is_not_stale() -> None:
    total = sum(_untyped_dicts().values())
    assert total == MAX_UNTYPED_DICTS, f"lower MAX_UNTYPED_DICTS to {total}"

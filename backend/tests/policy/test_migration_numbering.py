"""Migration numbers 101 to 105 belong to the folded first chain and are never reused.

Older databases still carry those ids in their migration log, so a new migration with one of them
would be treated as already applied there. New migrations are numbered 106 and up.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIRST_FREE_NUMBER = 106
FOLDED_NUMBERS = range(101, FIRST_FREE_NUMBER)


def test_no_migration_reuses_a_number_of_the_folded_chain() -> None:
    numbers = {
        path.name: int(match.group(1))
        for path in (REPO_ROOT / "migrations").glob("[0-9]*.py")
        if (match := re.match(r"(\d+)_", path.name))
    }
    assert numbers, "no migrations found"
    reused = sorted(name for name, number in numbers.items() if number in FOLDED_NUMBERS)
    assert reused == [], (
        "numbers 101 to 105 are taken by the folded chain, number new migrations from "
        f"{FIRST_FREE_NUMBER}: {reused}"
    )

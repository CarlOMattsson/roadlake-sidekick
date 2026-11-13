"""Every type-checker suppression in backend source names the rule it silences.

A bare `# pyright: ignore` hides every error on its line, including the ones added later. The
rule code (`# pyright: ignore[reportX]`) keeps the suppression as narrow as the problem it was
written for. The checker is pyright, so `# type: ignore` (which pyright reads loosely) is not used.

`MAX_SUPPRESSIONS` is the number of suppressions today. It only shrinks: when you remove one,
lower the number to the new count; never raise it to get a build green.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SRC = Path(__file__).resolve().parents[2] / "src"
SUPPRESSION = re.compile(r"#\s*(?:pyright|type):\s*ignore\b(?P<rest>.*)")
RULE_LIST = re.compile(r"^\[report\w+(?:,\s*report\w+)*\]")
MAX_SUPPRESSIONS = 8


def _violations(path: Path) -> list[str]:
    found: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = SUPPRESSION.search(line)
        if match is None:
            continue
        if "type: ignore" in match.group(0):
            found.append(f"{path}:{number}: `type: ignore` (use `pyright: ignore[reportX]`)")
        elif not RULE_LIST.match(match.group("rest")):
            found.append(f"{path}:{number}: `pyright: ignore` without a rule code")
    return found


def test_every_suppression_in_backend_source_names_its_rule() -> None:
    violations = [v for path in sorted(SRC.rglob("*.py")) for v in _violations(path)]
    assert not violations, "\n".join(violations)


def _suppression_count() -> int:
    return sum(
        1
        for path in SRC.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if SUPPRESSION.search(line)
    )


def test_backend_source_does_not_gain_suppressions() -> None:
    count = _suppression_count()
    assert count <= MAX_SUPPRESSIONS, (
        f"backend source has {count} type-checker suppressions (cap {MAX_SUPPRESSIONS}); "
        "fix the type instead of silencing it"
    )


def test_suppression_cap_is_not_stale() -> None:
    count = _suppression_count()
    assert count == MAX_SUPPRESSIONS, f"lower MAX_SUPPRESSIONS to {count}"


def test_the_policy_rejects_bare_and_foreign_suppressions(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "a = 1  # pyright: ignore\n"
        "b = 2  # type: ignore[call-arg]\n"
        "c = 3  # pyright: ignore[reportPrivateUsage]\n",
        encoding="utf-8",
    )
    assert len(_violations(sample)) == 2

"""Every type-checker suppression in backend source names the rule it silences.

A bare `# pyright: ignore` hides every error on its line, including the ones added later. The
rule code (`# pyright: ignore[reportX]`) keeps the suppression as narrow as the problem it was
written for. The checker is pyright, so `# type: ignore` (which pyright reads loosely) is not used.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SRC = Path(__file__).resolve().parents[2] / "src"
SUPPRESSION = re.compile(r"#\s*(?:pyright|type):\s*ignore\b(?P<rest>.*)")
RULE_LIST = re.compile(r"^\[report\w+(?:,\s*report\w+)*\]")


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


def test_the_policy_rejects_bare_and_foreign_suppressions(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "a = 1  # pyright: ignore\n"
        "b = 2  # type: ignore[call-arg]\n"
        "c = 3  # pyright: ignore[reportPrivateUsage]\n",
        encoding="utf-8",
    )
    assert len(_violations(sample)) == 2

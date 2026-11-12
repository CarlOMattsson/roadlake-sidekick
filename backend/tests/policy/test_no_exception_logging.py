"""Backend code never logs an attached exception (privacy policy: logs carry no user data).

`logger.exception(...)` and `exc_info=` put the exception message, the traceback and its frames
into a log record, where SQL parameters and row values can appear. The code logs the failure
through `sidekick.shared.observability.log_failure`, which writes the event name and the
exception class only. The formatters strip the traceback as a second line of defence, but the
record itself must not carry it.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

SRC = Path(__file__).resolve().parents[2] / "src"
FORBIDDEN_KEYWORDS = frozenset({"exc_info", "stack_info"})
# Explicit, reasoned exceptions as "relative/path.py": reason. Empty: nothing needs one.
ALLOWED: dict[str, str] = {}


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "exception":
            found.append(f"{path}:{node.lineno}: .exception(...)")
        found.extend(
            f"{path}:{node.lineno}: {keyword.arg}="
            for keyword in node.keywords
            if keyword.arg in FORBIDDEN_KEYWORDS
        )
    return found


def test_backend_source_never_attaches_an_exception_to_a_log_record() -> None:
    violations = [
        violation
        for path in sorted(SRC.rglob("*.py"))
        if str(path.relative_to(SRC)) not in ALLOWED
        for violation in _violations(path)
    ]
    assert violations == [], "use log_failure(logger, event, error) instead:\n" + "\n".join(
        violations
    )


def test_the_policy_detects_a_violation(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "try:\n    pass\nexcept Exception:\n"
        "    LOGGER.exception('x')\n    LOGGER.error('y', exc_info=True)\n",
        encoding="utf-8",
    )
    assert len(_violations(sample)) == 2

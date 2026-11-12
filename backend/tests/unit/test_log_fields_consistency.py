"""Every field a call site logs is in the allow-list, so no counter is silently filtered away."""

import ast
import dataclasses
from collections.abc import Iterator
from pathlib import Path

import sidekick
from sidekick.memory.application.lifecycle import BankCheckResult, SweepResult
from sidekick.shared.observability import SAFE_LOG_FIELDS

_SOURCE_ROOT = Path(sidekick.__file__).parent
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _literal_keys(node: ast.expr) -> Iterator[str]:
    """Top-level string keys of a dict literal, including literals joined to it with `|`."""

    if isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                yield key.value
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        yield from _literal_keys(node.left)
        yield from _literal_keys(node.right)


def _logged_keys(path: Path) -> Iterator[tuple[int, str]]:
    for call in ast.walk(ast.parse(path.read_text())):
        if not isinstance(call, ast.Call):
            continue
        name = getattr(call.func, "attr", getattr(call.func, "id", None))
        if name == "safe_log_fields":
            for argument in call.args:
                yield from ((call.lineno, key) for key in _literal_keys(argument))
        elif name in _LOG_METHODS:
            for keyword in call.keywords:
                if keyword.arg == "extra":
                    yield from ((call.lineno, key) for key in _literal_keys(keyword.value))


def test_every_literal_log_field_is_in_the_allowlist() -> None:
    unlisted = sorted(
        f"{path.relative_to(_SOURCE_ROOT)}:{line} {key}"
        for path in _SOURCE_ROOT.rglob("*.py")
        for line, key in _logged_keys(path)
        if key not in SAFE_LOG_FIELDS
    )
    assert unlisted == [], "logged but not in SAFE_LOG_FIELDS, so dropped at runtime"


def test_the_memory_worker_logs_its_result_counters_unfiltered() -> None:
    # The worker logs `asdict(result)` for these two, so each field must be an allowed name.
    for result_type in (BankCheckResult, SweepResult):
        names = {field.name for field in dataclasses.fields(result_type)}
        assert names <= SAFE_LOG_FIELDS, names - SAFE_LOG_FIELDS


def test_no_identifier_is_allowed() -> None:
    assert not {"owner_id", "user_id", "bank_id", "device_id", "token"} & SAFE_LOG_FIELDS

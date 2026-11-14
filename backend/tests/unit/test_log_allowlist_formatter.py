"""The configured log formatter emits only reviewed fields, whatever a call site attaches."""

import io
import json
import logging
from pathlib import Path

import pytest

import sidekick
from sidekick.shared.observability import (
    SAFE_LOG_FIELDS,
    AllowlistJsonFormatter,
    configure_worker_logging,
)

FORMAT = "%(levelname)s %(name)s %(message)s"


def render(**extra: object) -> dict[str, object]:
    record = logging.LogRecord("sidekick.test", logging.INFO, __file__, 1, "event_name", None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(AllowlistJsonFormatter(FORMAT).format(record))


def test_allowed_fields_are_written() -> None:
    output = render(correlation_id="abc", http_status=200, duration_ms=1.5)
    assert output["message"] == "event_name"
    assert output["correlation_id"] == "abc"
    assert output["http_status"] == 200
    assert output["duration_ms"] == 1.5
    assert "dropped_field_count" not in output


def test_unknown_fields_with_personal_data_are_removed_and_counted() -> None:
    output = render(
        correlation_id="abc",
        owner_email="anna@example.com",
        task_title="Ring tandläkaren om Johans rot",
        outcome="success",
    )
    serialized = json.dumps(output)
    assert "anna@example.com" not in serialized
    assert "tandläkaren" not in serialized
    assert "owner_email" not in output
    assert output["dropped_field_count"] == 2
    assert output["correlation_id"] == "abc"
    assert output["outcome"] == "success"


def test_configured_sidekick_logger_applies_the_allowlist() -> None:
    """The handler `configure_observability` installs on the `sidekick` logger uses it."""

    formatters = [h.formatter for h in logging.getLogger("sidekick").handlers if h.formatter]
    assert formatters
    assert all(isinstance(formatter, AllowlistJsonFormatter) for formatter in formatters)


def test_allowlist_holds_no_content_field_names() -> None:
    assert not {"password", "token", "title", "email"} & SAFE_LOG_FIELDS


PERSONAL = "anna.svensson@example.com ringde om Johans tandrot"
WORKER_MODULES = (
    "work/worker.py",
    "backup/worker.py",
    "companion/push_worker.py",
    "memory/worker.py",
)


def _raise_and_log(logger: logging.Logger) -> None:
    try:
        raise ValueError(PERSONAL)
    except ValueError:
        logger.exception("iteration failed", stack_info=True)


def _assert_only_exception_type(output: str) -> None:
    for fragment in ("anna", "example.com", "Johan", "tandrot", "Traceback", "raise ValueError"):
        assert fragment not in output
    assert "ValueError" in output


def test_exception_in_the_configured_sidekick_logger_is_reduced_to_its_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (handler,) = logging.getLogger("sidekick").handlers
    assert isinstance(handler, logging.StreamHandler)
    stream = io.StringIO()
    monkeypatch.setattr(handler, "stream", stream)
    _raise_and_log(logging.getLogger("sidekick.work.worker"))
    output = stream.getvalue()
    _assert_only_exception_type(output)
    record = json.loads(output)
    assert record["error_type"] == "ValueError"
    assert "exc_info" not in record
    assert "stack_info" not in record


def test_exception_in_a_worker_logger_is_reduced_to_its_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logging.root, "handlers", [])
    monkeypatch.setattr(logging.root, "level", logging.root.level)
    # A worker process never runs `configure_observability`, so `sidekick` has no handler.
    monkeypatch.setattr(logging.getLogger("sidekick"), "handlers", [])
    monkeypatch.setattr(logging.getLogger("sidekick"), "propagate", True)
    configure_worker_logging()
    (handler,) = logging.root.handlers
    assert isinstance(handler, logging.StreamHandler)
    stream = io.StringIO()
    monkeypatch.setattr(handler, "stream", stream)
    _raise_and_log(logging.getLogger("sidekick.worker.test"))
    output = stream.getvalue()
    _assert_only_exception_type(output)
    assert "error_type=ValueError" in output
    assert "iteration failed" in output


@pytest.mark.policy
@pytest.mark.parametrize("module", WORKER_MODULES)
def test_worker_entry_points_use_the_safe_logging_setup(module: str) -> None:
    source = (Path(sidekick.__file__).parent / module).read_text(encoding="utf-8")
    assert "basicConfig" not in source
    assert "configure_worker_logging()" in source

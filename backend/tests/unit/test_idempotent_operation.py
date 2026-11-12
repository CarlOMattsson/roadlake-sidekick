"""The shared feature-write wrapper: key check, span, counters and one content-free log line."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest

from sidekick.shared.errors import ValidationError
from sidekick.shared.idempotent_operation import run_idempotent_operation

KEY = "idempotency-key-0001"
SECRET = "anna.svensson@example.com"


class _Telemetry:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, Any]]] = []
        self.counts: list[tuple[str, dict[str, Any]]] = []

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any]) -> Iterator[None]:
        self.spans.append((name, attributes))
        yield

    def count(self, name: str, attributes: dict[str, Any]) -> None:
        self.counts.append((name, attributes))


class _Store:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def transaction(self, operation: Callable[[object], Any]) -> Any:
        return operation(object())

    def idempotent(
        self, session: object, *, operation: str, execute: Callable[[], Any], **_: Any
    ) -> Any:
        self.operations.append(operation)
        return execute()


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _run(
    telemetry: _Telemetry,
    store: _Store,
    logger: logging.Logger,
    execute: Callable[[Any], dict[str, Any]],
    key: str = KEY,
) -> dict[str, Any]:
    return run_idempotent_operation(
        store=store,  # type: ignore[arg-type]
        telemetry=telemetry,  # type: ignore[arg-type]
        logger=logger,
        feature="thing",
        actor_id=uuid4(),
        operation="create",
        key=key,
        payload={"title": SECRET},
        execute=execute,
        correlation_id="corr-1",
    )


def _logger() -> tuple[logging.Logger, _Collector]:
    logger = logging.getLogger("sidekick.tests.idempotent_operation")
    logger.setLevel(logging.INFO)
    collector = _Collector()
    logger.handlers = [collector]
    return logger, collector


def test_a_successful_write_is_traced_counted_and_logged_without_content() -> None:
    telemetry, store = _Telemetry(), _Store()
    logger, collector = _logger()

    result = _run(telemetry, store, logger, lambda _session: {"id": "x"})

    assert result == {"id": "x"}
    assert store.operations == ["thing.create"]
    assert telemetry.spans == [("thing.operation", {"thing.operation": "create"})]
    assert telemetry.counts == [
        ("sidekick.thing.operations", {"thing.operation": "create", "outcome": "success"})
    ]
    (record,) = collector.records
    assert record.getMessage() == "thing_operation_completed"
    assert vars(record)["correlation_id"] == "corr-1"
    assert SECRET not in repr(vars(record))


def test_a_failing_write_counts_a_failure_logs_nothing_and_reraises() -> None:
    telemetry, store = _Telemetry(), _Store()
    logger, collector = _logger()

    def failing(_session: object) -> dict[str, Any]:
        raise RuntimeError(SECRET)

    with pytest.raises(RuntimeError):
        _run(telemetry, store, logger, failing)

    assert telemetry.counts == [
        ("sidekick.thing.operations", {"thing.operation": "create", "outcome": "failure"})
    ]
    assert collector.records == []


@pytest.mark.parametrize("key", ["short", "k" * 129])
def test_a_key_outside_the_allowed_length_is_rejected_before_anything_runs(key: str) -> None:
    telemetry, store = _Telemetry(), _Store()
    logger, _ = _logger()

    with pytest.raises(ValidationError):
        _run(telemetry, store, logger, lambda _session: {}, key=key)

    assert store.operations == [] and telemetry.spans == [] and telemetry.counts == []

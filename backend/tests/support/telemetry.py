"""Shared test helpers moved out of `tests/contract/test_telemetry_redaction.py`."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry.trace import SpanKind

from sidekick.shared.observability import safe_telemetry_attributes


class CaptureTelemetry:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    @contextmanager
    def span(
        self, name: str, attributes: dict[str, Any], *, kind: SpanKind = SpanKind.INTERNAL
    ) -> Iterator[None]:
        del kind
        self.records.append((name, safe_telemetry_attributes(attributes)))
        yield

    def count(self, name: str, attributes: dict[str, Any]) -> None:
        self.records.append((name, safe_telemetry_attributes(attributes)))

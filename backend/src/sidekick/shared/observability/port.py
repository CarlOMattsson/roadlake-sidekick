"""Application-facing telemetry port and privacy-safe OpenTelemetry adapter."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol

from opentelemetry import metrics, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

# Every attribute Sidekick code emits, and nothing more. A name with no emitter is removed, not kept
# for later: it would only widen what the exporter lets through.
SAFE_ATTRIBUTE_NAMES = frozenset(
    {
        "correlation.id",
        "db.system.name",
        "deployment.environment",
        "http.request.method",
        "http.response.status_code",
        "shopping.operation",
        "mcp.tool.name",
        "mcp.auth.mode",
        "mcp.auth.outcome",
        "mcp.auth.reason",
        "outcome",
        "service.name",
        "service.version",
    }
)


def safe_telemetry_attributes(values: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """Drop content and credentials at the port boundary."""

    return {
        key: value
        for key, value in values.items()
        if key in SAFE_ATTRIBUTE_NAMES and isinstance(value, (str, int, float, bool))
    }


class TelemetryPort(Protocol):
    """Small substitution boundary for application-owned telemetry."""

    def span(
        self, name: str, attributes: dict[str, Any], *, kind: SpanKind = SpanKind.INTERNAL
    ) -> AbstractContextManager[None]: ...

    def count(self, name: str, attributes: dict[str, Any]) -> None: ...


class NoopTelemetryAdapter:
    """Test/default adapter that preserves the port without global providers."""

    @contextmanager
    def span(
        self, name: str, attributes: dict[str, Any], *, kind: SpanKind = SpanKind.INTERNAL
    ) -> Iterator[None]:
        del name, attributes, kind
        yield

    def count(self, name: str, attributes: dict[str, Any]) -> None:
        del name, attributes


class OpenTelemetryAdapter:
    def __init__(self) -> None:
        self._tracer = trace.get_tracer("sidekick")
        self._meter = metrics.get_meter("sidekick")
        self._counters: dict[str, Any] = {}

    @contextmanager
    def span(
        self, name: str, attributes: dict[str, Any], *, kind: SpanKind = SpanKind.INTERNAL
    ) -> Iterator[None]:
        # The SDK would record the exception message as a span event and as the status
        # description; both can echo personal data, so only the exception class is kept.
        with self._tracer.start_as_current_span(
            name, kind=kind, record_exception=False, set_status_on_exception=False
        ) as span:
            for key, value in safe_telemetry_attributes(attributes).items():
                span.set_attribute(key, value)
            try:
                yield
            except Exception as error:
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("exception.type", type(error).__name__)
                raise

    def count(self, name: str, attributes: dict[str, Any]) -> None:
        counter = self._counters.get(name)
        if counter is None:
            counter = self._meter.create_counter(name)
            self._counters[name] = counter
        counter.add(1, safe_telemetry_attributes(attributes))

"""Client-controlled HTTP values never reach a log field or an exported span (allowlists only)."""

import logging
from collections.abc import Iterator
from uuid import UUID

import pytest
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.types import Message, Receive, Scope, Send

from sidekick.shared.observability import (
    TRACEPARENT_ONLY,
    CorrelationMiddleware,
    OpenTelemetryAdapter,
    configure_observability,
    safe_http_method,
)
from sidekick.shared.observability.middleware import accepted_correlation_id

PERSONAL = "anna.svensson@example.com"
TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
TRACE_ID = int("0af7651916cd43dd8448eb211c80319c", 16)
SPAN_ID = int("b7ad6b7169203331", 16)


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def rendered(self) -> str:
        return "\n".join(repr(vars(record)) for record in self.records)


@pytest.fixture(name="exporter")
def _exporter(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", lambda *_a, **_k: provider.get_tracer("test"))
    return exporter


@pytest.fixture(name="logs")
def _logs() -> Iterator[_Collector]:
    collector = _Collector()
    logger = logging.getLogger("sidekick.http")
    previous = logger.level
    logger.addHandler(collector)
    logger.setLevel(logging.INFO)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous)


async def _app(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _call(headers: dict[str, str], method: str = "GET") -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "method": method,
        "path": "/x",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    await CorrelationMiddleware(_app, OpenTelemetryAdapter())(scope, receive, send)
    return sent


def _response_correlation(sent: list[Message]) -> str:
    return next(v.decode() for k, v in sent[0]["headers"] if k == b"x-correlation-id")


def _remote_span_context(carrier: dict[str, str]) -> trace.SpanContext:
    return trace.get_current_span(TRACEPARENT_ONLY.extract(carrier)).get_span_context()


@pytest.mark.asyncio
async def test_inbound_tracestate_is_not_in_the_exported_span_or_its_parent(
    exporter: InMemorySpanExporter,
) -> None:
    await _call(
        {"traceparent": TRACEPARENT, "tracestate": f"vendor={PERSONAL}", "baggage": PERSONAL}
    )

    (span,) = exporter.get_finished_spans()
    assert span.context is not None and span.parent is not None
    # The parent was taken from `traceparent`...
    assert span.context.trace_id == TRACE_ID
    assert span.parent.span_id == SPAN_ID
    # ...and no tracestate came with it.
    assert len(span.context.trace_state) == 0
    assert len(span.parent.trace_state) == 0
    assert PERSONAL not in span.to_json()


def test_the_propagator_drops_tracestate_and_baggage_on_extract() -> None:
    carrier = {"traceparent": TRACEPARENT, "tracestate": f"v={PERSONAL}", "baggage": PERSONAL}
    span_context = _remote_span_context(carrier)
    assert span_context.trace_id == TRACE_ID
    assert len(span_context.trace_state) == 0
    assert PERSONAL not in repr(TRACEPARENT_ONLY.extract(carrier))


def test_the_propagator_sends_only_traceparent() -> None:
    carrier: dict[str, str] = {}
    outgoing = trace.SpanContext(
        TRACE_ID,
        SPAN_ID,
        is_remote=False,
        trace_flags=trace.TraceFlags(1),
        trace_state=trace.TraceState([("vendor", PERSONAL)]),
    )
    TRACEPARENT_ONLY.inject(carrier, trace.set_span_in_context(trace.NonRecordingSpan(outgoing)))
    assert set(carrier) == {"traceparent"}
    assert set(TRACEPARENT_ONLY.fields) == {"traceparent"}


def test_configure_observability_makes_it_the_global_propagator() -> None:
    # The MCP SDK and FastMCP extract `_meta.traceparent`/`tracestate` through the global one.
    previous = propagate.get_global_textmap()
    try:
        configure_observability("test")
        assert propagate.get_global_textmap() is TRACEPARENT_ONLY
        context = propagate.extract({"traceparent": TRACEPARENT, "tracestate": f"v={PERSONAL}"})
        token = otel_context.attach(context)
        try:
            span_context = trace.get_current_span().get_span_context()
        finally:
            otel_context.detach(token)
        assert span_context.trace_id == TRACE_ID
        assert len(span_context.trace_state) == 0
    finally:
        propagate.set_global_textmap(previous)


@pytest.mark.parametrize(
    "supplied",
    [
        "anna.svensson",
        PERSONAL,
        "corr-404-check",
        # A UUID in a form other than the canonical one is not echoed back.
        "A3F5C7B1-8D2E-4F6A-9B0C-1D2E3F4A5B6C",
        "a3f5c7b18d2e4f6a9b0c1d2e3f4a5b6c",
        "{a3f5c7b1-8d2e-4f6a-9b0c-1d2e3f4a5b6c}",
        "urn:uuid:a3f5c7b1-8d2e-4f6a-9b0c-1d2e3f4a5b6c",
    ],
)
@pytest.mark.asyncio
async def test_a_correlation_id_that_is_not_a_canonical_uuid_is_replaced(
    supplied: str, exporter: InMemorySpanExporter, logs: _Collector
) -> None:
    sent = await _call({"x-correlation-id": supplied})

    issued = _response_correlation(sent)
    assert str(UUID(issued)) == issued
    assert issued != supplied
    (span,) = exporter.get_finished_spans()
    assert (span.attributes or {})["correlation.id"] == issued
    assert vars(logs.records[0])["correlation_id"] == issued
    assert supplied not in span.to_json()
    assert supplied not in logs.rendered()
    assert accepted_correlation_id(supplied) is None


@pytest.mark.asyncio
async def test_a_missing_correlation_id_is_issued_by_the_server() -> None:
    issued = _response_correlation(await _call({}))
    assert str(UUID(issued)) == issued


@pytest.mark.asyncio
async def test_a_canonical_uuid_correlation_id_is_kept(
    exporter: InMemorySpanExporter, logs: _Collector
) -> None:
    supplied = "a3f5c7b1-8d2e-4f6a-9b0c-1d2e3f4a5b6c"
    sent = await _call({"x-correlation-id": supplied})

    assert _response_correlation(sent) == supplied
    (span,) = exporter.get_finished_spans()
    assert (span.attributes or {})["correlation.id"] == supplied
    assert vars(logs.records[0])["correlation_id"] == supplied


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("GET", "GET"),
        ("HEAD", "HEAD"),
        ("POST", "POST"),
        ("PUT", "PUT"),
        ("PATCH", "PATCH"),
        ("DELETE", "DELETE"),
        ("OPTIONS", "OPTIONS"),
        ("ANNA_SVENSSON", "OTHER"),
        ("get", "OTHER"),
        ("PROPFIND", "OTHER"),
    ],
)
@pytest.mark.asyncio
async def test_the_http_method_is_a_fixed_value_in_the_log_and_the_span(
    method: str, expected: str, exporter: InMemorySpanExporter, logs: _Collector
) -> None:
    await _call({}, method=method)

    (span,) = exporter.get_finished_spans()
    assert (span.attributes or {})["http.request.method"] == expected
    assert vars(logs.records[0])["http_method"] == expected
    assert safe_http_method({"method": method}) == expected
    if expected == "OTHER":
        assert method not in span.to_json()
        assert method not in logs.rendered()


def test_a_missing_or_non_text_method_is_other() -> None:
    assert safe_http_method({}) == "OTHER"
    assert safe_http_method({"method": None}) == "OTHER"

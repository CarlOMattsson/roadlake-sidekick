"""No exception text reaches an exported span, however the exception was recorded."""

import logging

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode, Tracer

from sidekick.shared.observability import (
    ExceptionScrubbingSpanProcessor,
    OpenTelemetryAdapter,
    configure_observability,
    harden_tracer_provider,
    setup,
)

PERSONAL = "anna.svensson@example.com ringde om Johans tandrot"


def make_tracer() -> tuple[Tracer, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(ExceptionScrubbingSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def exported_text(exporter: InMemorySpanExporter) -> str:
    parts: list[str] = []
    for span in exporter.get_finished_spans():
        parts.append(str(dict(span.attributes or {})))
        parts.append(str(span.status.description))
        for event in span.events:
            parts.append(event.name)
            parts.append(str(dict(event.attributes or {})))
    return "\n".join(parts)


def assert_no_personal_text(exporter: InMemorySpanExporter) -> None:
    text = exported_text(exporter)
    for fragment in ("anna", "example.com", "Johan", "tandrot"):
        assert fragment not in text


def test_default_sdk_recording_is_scrubbed_but_keeps_the_exception_type() -> None:
    tracer, exporter = make_tracer()
    with pytest.raises(ValueError), tracer.start_as_current_span("instrumented"):
        raise ValueError(PERSONAL)
    (span,) = exporter.get_finished_spans()
    assert_no_personal_text(exporter)
    (event,) = span.events
    assert event.name == "exception"
    assert dict(event.attributes or {}) == {"exception.type": "ValueError"}
    assert span.status.description is None
    assert span.status.status_code is StatusCode.ERROR


def test_recorded_exception_and_explicit_status_text_are_scrubbed() -> None:
    tracer, exporter = make_tracer()
    with tracer.start_as_current_span("manual") as span:
        span.record_exception(RuntimeError(PERSONAL), attributes={"exception.message": PERSONAL})
        span.set_status(Status(StatusCode.ERROR, PERSONAL))
    assert_no_personal_text(exporter)


def test_adapter_span_exports_only_the_exception_class() -> None:
    tracer, exporter = make_tracer()
    adapter = OpenTelemetryAdapter()
    adapter._tracer = tracer  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ValueError), adapter.span("sidekick.op", {"outcome": "failure"}):
        raise ValueError(PERSONAL)
    (span,) = exporter.get_finished_spans()
    assert_no_personal_text(exporter)
    assert not span.events
    assert (span.attributes or {})["exception.type"] == "ValueError"


def test_preregistered_exporting_processor_never_sees_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reused provider whose exporting processor predates `configure_observability`."""

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    early_tracer = provider.get_tracer("obtained-before-configuration")
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(trace, "set_tracer_provider", lambda _provider: None)
    monkeypatch.setattr(metrics, "set_meter_provider", lambda _provider: None)
    monkeypatch.setattr(setup, "_configured", False)
    monkeypatch.setattr(setup, "_adapter", None)
    sidekick_logger = logging.getLogger("sidekick")
    monkeypatch.setattr(sidekick_logger, "handlers", list(sidekick_logger.handlers))
    monkeypatch.setattr(sidekick_logger, "level", sidekick_logger.level)
    monkeypatch.setattr(sidekick_logger, "propagate", sidekick_logger.propagate)

    configure_observability("test")

    late_exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(late_exporter))
    for tracer in (early_tracer, provider.get_tracer("obtained-after-configuration")):
        with pytest.raises(ValueError), tracer.start_as_current_span("instrumented"):
            raise ValueError(PERSONAL)
        with tracer.start_as_current_span("manual") as span:
            span.record_exception(
                RuntimeError(PERSONAL), attributes={"exception.message": PERSONAL}
            )
            span.set_status(Status(StatusCode.ERROR, PERSONAL))
    for each in (exporter, late_exporter):
        assert len(each.get_finished_spans()) == 4
        assert_no_personal_text(each)
        first = each.get_finished_spans()[0]
        assert dict(first.events[0].attributes or {}) == {"exception.type": "ValueError"}


def test_hardening_twice_does_not_stack_scrubbers() -> None:
    provider = TracerProvider()
    harden_tracer_provider(provider)
    first = provider._active_span_processor.on_end  # pyright: ignore[reportPrivateUsage]
    harden_tracer_provider(provider)
    assert provider._active_span_processor.on_end is first  # pyright: ignore[reportPrivateUsage]

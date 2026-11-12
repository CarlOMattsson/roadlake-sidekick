"""Telemetry export fails closed: no redaction processor, no exporter can run."""

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import sidekick
from sidekick.shared.observability import (
    NoopTelemetryAdapter,
    OpenTelemetryAdapter,
    configure_observability,
    harden_tracer_provider,
    setup,
)

SECRET = "anna.svensson@example.com ringde om Johans tandrot"


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def rendered(self) -> str:
        return "\n".join(repr(vars(record)) for record in self.records)


@pytest.fixture(name="logs")
def _logs() -> Iterator[_Collector]:
    collector = _Collector()
    logger = logging.getLogger("sidekick.observability")
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)


@pytest.fixture(name="published")
def _fresh_configuration(monkeypatch: pytest.MonkeyPatch) -> list[TracerProvider]:
    """Run `configure_observability` again without touching the process-wide providers."""

    published: list[TracerProvider] = []
    monkeypatch.setattr(trace, "set_tracer_provider", published.append)
    monkeypatch.setattr(metrics, "set_meter_provider", lambda _provider: None)
    monkeypatch.setattr(setup, "_configured", False)
    monkeypatch.setattr(setup, "_adapter", None)
    sidekick_logger = logging.getLogger("sidekick")
    monkeypatch.setattr(sidekick_logger, "handlers", list(sidekick_logger.handlers))
    monkeypatch.setattr(sidekick_logger, "level", sidekick_logger.level)
    monkeypatch.setattr(sidekick_logger, "propagate", sidekick_logger.propagate)
    return published


class _RecordingProvider(TracerProvider):
    created: list["_RecordingProvider"] = []  # noqa: RUF012

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.created.append(self)


class _RedactionBroken:
    def __init__(self) -> None:
        raise ImportError(SECRET)


def test_a_failed_redaction_install_publishes_no_provider_and_falls_back_to_noop(
    monkeypatch: pytest.MonkeyPatch,
    published: list[TracerProvider],
    logs: _Collector,
) -> None:
    monkeypatch.setattr(trace, "get_tracer_provider", trace.ProxyTracerProvider)
    monkeypatch.setattr(_RecordingProvider, "created", [])
    monkeypatch.setattr(setup, "TracerProvider", _RecordingProvider)
    monkeypatch.setattr(setup, "SpanAllowlistProcessor", _RedactionBroken)

    adapter = configure_observability("test")

    assert isinstance(adapter, NoopTelemetryAdapter)
    assert published == []
    messages = [record.getMessage() for record in logs.records]
    assert "telemetry_redaction_install_failed" in messages
    assert "telemetry_export_stopped" in messages
    # Only the exception class is logged, never its text.
    assert vars(logs.records[0])["error_type"] == "ImportError"
    assert SECRET not in logs.rendered()
    # An exporter added later to the provider that was built is never fed.
    (fresh,) = _RecordingProvider.created
    exporter = InMemorySpanExporter()
    fresh.add_span_processor(SimpleSpanProcessor(exporter))
    with fresh.get_tracer("t").start_as_current_span("after"):
        pass
    assert exporter.get_finished_spans() == ()


def test_a_failed_redaction_install_stops_a_provider_that_already_has_an_exporter(
    monkeypatch: pytest.MonkeyPatch,
    published: list[TracerProvider],
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    early_tracer = provider.get_tracer("obtained-before-configuration")
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(setup, "SpanAllowlistProcessor", _RedactionBroken)

    adapter = configure_observability("test")

    assert isinstance(adapter, NoopTelemetryAdapter)
    assert published == []
    late_exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(late_exporter))
    for tracer in (early_tracer, provider.get_tracer("obtained-after-configuration")):
        with tracer.start_as_current_span("instrumented") as span:
            span.set_attribute("person", SECRET)
    assert exporter.get_finished_spans() == ()
    assert late_exporter.get_finished_spans() == ()


def test_a_scrubber_that_cannot_be_built_leaves_the_chain_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = TracerProvider()
    chain = provider._active_span_processor  # pyright: ignore[reportPrivateUsage]
    original = chain.on_end
    monkeypatch.setattr(setup, "ExceptionScrubbingSpanProcessor", _RedactionBroken)

    with pytest.raises(ImportError):
        harden_tracer_provider(provider)

    assert chain.on_end == original


def test_a_provider_without_a_processor_chain_reports_that_redaction_is_missing(
    logs: _Collector,
) -> None:
    provider = TracerProvider()
    chain = provider._active_span_processor  # pyright: ignore[reportPrivateUsage]
    provider._active_span_processor = object()  # type: ignore[assignment]  # pyright: ignore[reportPrivateUsage]
    try:
        assert harden_tracer_provider(provider) is False
    finally:
        provider._active_span_processor = chain  # pyright: ignore[reportPrivateUsage]
    assert "span_scrubbing_unavailable" in [record.getMessage() for record in logs.records]


def test_a_working_install_keeps_the_open_telemetry_adapter_and_publishes_the_provider(
    monkeypatch: pytest.MonkeyPatch,
    published: list[TracerProvider],
) -> None:
    monkeypatch.setattr(trace, "get_tracer_provider", trace.ProxyTracerProvider)

    adapter = configure_observability("test")

    assert isinstance(adapter, OpenTelemetryAdapter)
    (provider,) = published
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("t").start_as_current_span("ok") as span:
        span.set_attribute("person", SECRET)
    (exported,) = exporter.get_finished_spans()
    assert SECRET not in exported.to_json()


def test_the_telemetry_resource_reports_the_package_version() -> None:
    resource = setup.build_resource("test")

    assert resource.attributes["service.version"] == sidekick.__version__
    assert resource.attributes["deployment.environment"] == "test"

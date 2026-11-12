"""Minimal local OpenTelemetry providers and JSON logging with explicit allowlists."""

import logging
import os
import sys
import warnings
from types import TracebackType
from typing import Any, TextIO

from opentelemetry import metrics, propagate, trace
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import (
    Event,
    ReadableSpan,
    SpanProcessor,
    SynchronousMultiSpanProcessor,
    TracerProvider,
)
from opentelemetry.trace import Status
from pythonjsonlogger.json import JsonFormatter

from sidekick import __version__
from sidekick.shared.compat import active_span_processor, replace_active_span_processor

from .http_client_logs import HTTP_CLIENT_LOGGERS, silence_http_client_loggers
from .port import NoopTelemetryAdapter, OpenTelemetryAdapter, TelemetryPort
from .propagation import TRACEPARENT_ONLY
from .sdk_internals import span_rewrite_problem
from .span_allowlist import SpanAllowlistProcessor
from .third_party_logs import exception_class, install_safe_record_factory

SAFE_LOG_FIELDS = frozenset(
    {
        "correlation_id",
        "duration_ms",
        "http_method",
        # The matched route template (`/companion/v1/tasks/{task_id}`), never the request path.
        "http_route",
        "http_status",
        "mcp_tool_name",
        # MCP request accounting (sidekick.mcp.request): the protocol method, the error class and
        # a closed error code. Never arguments, results, titles, or Journal text (D-058).
        "mcp_method",
        "mcp_error_class",
        "mcp_error_code",
        # The `mcp-protocol-version` a client sent with a transport 400 that was refused as
        # unsupported. Logged only when it is a date (YYYY-MM-DD), otherwise as "invalid".
        "mcp_protocol_version",
        # Public MCP authentication: the configured mode, whether a credential was accepted
        # and, for a refusal, one reason from a closed vocabulary. Never a token, an
        # authorization code, an upstream login, an e-mail address, or an upstream id.
        "mcp_auth_mode",
        "mcp_auth_outcome",
        "mcp_auth_reason",
        # Companion app adapter (ADR-005): the fixed operation name and a closed error code.
        # Never a token, pairing secret, device label, task id, title or query value.
        "companion_operation",
        "companion_error",
        # Push delivery (ADR-005, D-078): the fixed kind (`w` or `r`), the endpoint's host alone, a
        # closed outcome and the endpoint's HTTP status. Never the endpoint URL, topic or payload.
        "push_kind",
        "push_host",
        "push_outcome",
        "push_status",
        "outcome",
        # License key (D-081, sidekick.license): a closed state and a closed reject reason. Never
        # the key, its signature, the licensee or the key id.
        "license_state",
        "license_reason",
        # A database time budget that ran out (db_timeouts) and the fixed worker step it hit: a
        # closed vocabulary, never the statement or its parameters.
        "db_timeout",
        "worker_step",
        "service_name",
        "service_version",
        "deployment_environment",
        # Where this process took its configuration from. The fields carry variable
        # *names* and never a value, including when a name identifies a credential: that
        # the key in use is not the one in `.env` is the fact the owner needs, and the key
        # itself is never read into the record. `config_environment_only` is set in the
        # environment but not in the file (normal in containers); `config_dotenv_file` says
        # whether the file was found at all.
        "config_environment_disagreements",
        "config_environment_only",
        "config_dotenv_file",
        # Closed vocabularies from the memory worker and recall: an exception class name, a fixed
        # provider error category and counts. Never an exception message or a fact.
        "error_type",
        "error_category",
        "category",
        "process_run_count",
        # Retention job for idempotency replay records: a count, never a key or a result.
        "idempotency_pruned_count",
        # Encrypted local backup worker: counts and a random per-run id (uuid4 hex), never a path,
        # a key or an owner.
        "backup_run_id",
        "backup_owner_count",
        "backup_pruned_count",
        # Push reminder scheduling: how many reminders one run queued.
        "push_reminders",
        # Search and external-reference operations: a fixed operation name, the searched kinds,
        # hit counts per kind and the length and term count of the query. Never the query text.
        "operation",
        "kinds",
        "hit_counts",
        "query_length",
        "term_count",
        # Memory worker, sync, recall and lifecycle: counts, flags and closed vocabularies
        # (`outcome`, `error_category`, `error_categories`, a fixed refusal name). Never a
        # fact, a query, an owner or a bank identifier.
        "full",
        "owner_count",
        "row_count",
        "rows_reset",
        "rows_removed",
        "documents_deleted",
        "markers_kept",
        "second_delete_pending",
        "deferred",
        "queued",
        "sent",
        "retained",
        "failed",
        "parked",
        "deleted",
        "delete_deferred",
        "delete_failed",
        "deferred_by_budget",
        "discarded_by_policy",
        "sending_blocked",
        "error_categories",
        "provider_facts",
        "returned",
        "truncated",
        "dropped_unverified",
        "dropped_not_readable",
        "dropped_source_not_live",
        "dropped_stale_version",
        "dropped_fact_type",
        "owners_checked",
        "owners_reset",
        "owners_locked",
        "complete",
        "banks_listed",
        "banks_ours",
        "orphans_found",
        "banks_deleted",
        "refused",
        # Set by `AllowlistJsonFormatter` itself: how many unreviewed fields it removed.
        "dropped_field_count",
    }
)
# Fields the formatter itself writes from its format string and from an attached exception.
# `exc_info` and `stack_info` are deliberately absent: an exception's message and its traceback
# can echo personal data, so only the exception class is logged, as `error_type`.
_FORMAT_FIELDS = frozenset({"levelname", "name", "message"})
_EXC_INFO = tuple[type[BaseException], BaseException, TracebackType | None]
_LOG = logging.getLogger("sidekick.observability")
_SCRUBS_FIRST = "_sidekick_scrubs_first"


_configured = False
_adapter: TelemetryPort | None = None


def safe_log_fields(values: dict[str, Any]) -> dict[str, Any]:
    """Keep only reviewed low-cardinality metadata; content is dropped, not masked."""

    return {key: value for key, value in values.items() if key in SAFE_LOG_FIELDS}


class AllowlistJsonFormatter(JsonFormatter):
    """JSON log formatter that only emits `extra` fields named in `SAFE_LOG_FIELDS`.

    The message is an event name by convention. Any other field a call site attaches is
    removed, so a new `extra={...}` can never put content in the output by accident; only the
    number removed is recorded. An exception attached to the record (`LOGGER.exception`) is
    reduced to its class name in `error_type`: neither its message, its traceback nor
    `stack_info` is ever written, because they can echo personal data.
    """

    def add_fields(
        self,
        log_data: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_data, record, message_dict)
        log_data.pop("exc_info", None)
        log_data.pop("stack_info", None)
        error_type = exception_class(record.exc_info)
        if error_type and "error_type" not in log_data:
            log_data["error_type"] = error_type

    def process_log_record(self, log_data: dict[str, Any]) -> dict[str, Any]:
        allowed = SAFE_LOG_FIELDS | _FORMAT_FIELDS
        kept = {key: value for key, value in log_data.items() if key in allowed}
        dropped = len(log_data) - len(kept)
        if dropped:
            kept["dropped_field_count"] = dropped
        return super().process_log_record(kept)


class ExceptionTypeOnlyFormatter(logging.Formatter):
    """Plain-text formatter that never writes a traceback or exception text.

    Used by `configure_worker_logging` and for the library loggers (see
    `harden_third_party_logging`). `LOGGER.exception(...)` appends only
    `error_type=<ExceptionClass>`; the message, the frames and `stack_info` are withheld.
    `record.exc_text` is a cache that an earlier handler (a pytest capture handler, a stock
    formatter) may already have filled with the full traceback, so it is never read or written
    here: it is cleared for this call and restored after, leaving other handlers untouched.
    """

    def format(self, record: logging.LogRecord) -> str:
        cached = record.exc_text
        record.exc_text = None
        try:
            return super().format(record)
        finally:
            record.exc_text = cached

    def formatException(self, ei: _EXC_INFO | tuple[None, None, None]) -> str:
        return f"error_type={exception_class(ei) or 'unknown'}"

    def formatStack(self, stack_info: str) -> str:
        return ""


def _log_warning(
    message: Warning | str,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: TextIO | None = None,
    line: str | None = None,
) -> None:
    """`warnings.showwarning` replacement: the category and the source module, never the text."""

    module = os.path.splitext(os.path.basename(filename))[0]
    logging.getLogger("sidekick.warnings").warning(
        "python_warning category=%s module=%s", category.__name__, module
    )


def capture_warnings_safely() -> None:
    """Route `warnings.warn` through logging, reduced to category and source module.

    `warnings.warn` otherwise writes the full message straight to stderr, past every formatter
    here, and a message can echo a value. Idempotent.
    """

    warnings.showwarning = _log_warning


# Third-party loggers that get Sidekick's own handler. The content guarantee does not depend on this
# list: `install_safe_record_factory` rewrites every non-Sidekick record when it is created.
_THIRD_PARTY_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.asgi",
    "fastapi",
    "starlette",
    "sqlalchemy",
    *HTTP_CLIENT_LOGGERS,
    "mcp",
    "fastmcp",
    "asyncio",
    "py.warnings",
)
_ACCESS_LOGGER = "uvicorn.access"


class _RejectEverything(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


def disable_access_log() -> None:
    """Turn uvicorn's access log off for good: no handler, no propagation, disabled, filtered.

    uvicorn enables the access log per connection when `uvicorn.access` `hasHandlers()`, which
    also looks at the ancestors, and its record carries the client address and the full request
    path (an e-mail address in a URL, an OAuth `code`). So nothing is attached here: a handler
    would switch a log back on that `--no-access-log` had turned off. Idempotent.
    """

    access = logging.getLogger(_ACCESS_LOGGER)
    access.handlers = []
    access.propagate = False
    access.disabled = True
    if not any(isinstance(item, _RejectEverything) for item in access.filters):
        access.addFilter(_RejectEverything())


def harden_third_party_logging(stream: TextIO | None = None) -> None:
    """Make the loggers of uvicorn and the other libraries unable to write request content.

    The guarantee comes from `install_safe_record_factory`: a record from any logger outside
    `sidekick` carries a fixed label (a short uvicorn allowlist) or `third_party_log` plus the
    exception class, never the library's message, arguments or traceback. On top of that the named
    library loggers get one plain handler and stop propagating, so their output has one format,
    and the root logger gets the same handler when it has none. `uvicorn.access` is disabled
    entirely (`disable_access_log`). We deliberately keep uvicorn's own `log_config` and start
    flags (the reloader and server need no configuration from us). A failure while uvicorn is still
    importing the app is the one window this does not cover. Idempotent: handlers are replaced.
    """

    install_safe_record_factory()
    silence_http_client_loggers()
    safe = logging.StreamHandler(stream or sys.stderr)
    safe.setFormatter(ExceptionTypeOnlyFormatter("%(levelname)s %(name)s %(message)s"))
    for name in _THIRD_PARTY_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = [safe]
        logger.propagate = False
    disable_access_log()
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(safe)
    capture_warnings_safely()


def configure_worker_logging() -> None:
    """Root logging for the worker entry points, replacing `logging.basicConfig`.

    Same line format as before, but exceptions are reduced to their class name, Python warnings
    are logged as category and module only, and records from outside `sidekick` carry a fixed label
    only (`install_safe_record_factory`).
    """

    install_safe_record_factory()
    silence_http_client_loggers()
    handler = logging.StreamHandler()
    handler.setFormatter(ExceptionTypeOnlyFormatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    capture_warnings_safely()


class ExceptionScrubbingSpanProcessor(SpanProcessor):
    """Strip exception text from every ended span, whoever recorded it.

    `record_exception` (also the default of the FastAPI, SQLAlchemy and httpx instrumentations
    and of `start_as_current_span`) stores `exception.message` and `exception.stacktrace` as a
    span event, and a failed span's status description is the message. Either can echo
    personal data. This keeps the event and `exception.type`, and drops every other event
    attribute and the status description. Register it before any exporting processor.
    """

    def on_end(self, span: ReadableSpan) -> None:
        mutable: Any = span
        mutable._events = [
            Event(
                event.name,
                {k: v for k, v in (event.attributes or {}).items() if k == "exception.type"}
                if event.name == "exception"
                else event.attributes,
                event.timestamp,
            )
            for event in span.events
        ]
        if span.status.description:
            mutable._status = Status(span.status.status_code)


def harden_tracer_provider(provider: TracerProvider) -> bool:
    """Make only allowlisted span content leave the provider, whatever processors it already has.

    The chain first rewrites names and attributes through `SpanAllowlistProcessor` (client-chosen
    tool names and URIs, unreviewed attribute keys), then strips exception text.

    A reused `TracerProvider` may already carry exporting processors (a `SimpleSpanProcessor`,
    a `BatchSpanProcessor`, anything). Appending a scrubber after them would export the
    exception text before it is removed. So the scrubber is put in front of the provider's whole
    processor chain: the chain's `on_end` is wrapped on the instance, which scrubs the span and
    then hands it on. This covers processors registered before and after this call, tracers
    already obtained from the provider (they hold the chain object, not a copy), and both
    multi-processor classes, without any knowledge of exporter internals. Wrapping each exporter
    instead would miss processors added later and needs per-processor-class private access.
    If the SDK no longer exposes the chain, or no longer reads the private span fields the
    redaction rewrites (`span_rewrite_problem`), a warning is logged rather than claiming safety.

    Returns whether the redaction is installed (also when it already was). `False` means no
    exporter may be attached to this provider; `configure_observability` then stops span export.

    Known limit: a custom processor that overrides `_on_ending` (called before `on_end`, on a
    still-writable span) sees the raw exception text, and this wrapper cannot reach it. Sidekick
    registers no such processor (a test asserts that); do not add one without scrubbing there.
    """

    chain: Any = active_span_processor(provider)
    if not isinstance(chain, SpanProcessor):
        _LOG.warning("span_scrubbing_unavailable")
        return False
    problem = span_rewrite_problem()
    if problem is not None:
        # The field name is the SDK's, never span content.
        _LOG.error("span_rewrite_internals_changed: %s", problem)
        return False
    if getattr(chain, _SCRUBS_FIRST, False):
        return True
    # Both are constructed before the chain is touched: a failure leaves the chain as it was.
    allowlist = SpanAllowlistProcessor()
    scrubber = ExceptionScrubbingSpanProcessor()
    original_on_end = chain.on_end

    def on_end(span: ReadableSpan) -> None:
        allowlist.on_end(span)
        scrubber.on_end(span)
        original_on_end(span)

    chain.on_end = on_end
    setattr(chain, _SCRUBS_FIRST, True)
    return True


def _drop_span(span: ReadableSpan) -> None:
    del span


def _drop_started(span: Any, parent_context: Any = None) -> None:
    del span, parent_context


def _install_redaction(provider: TracerProvider) -> bool:
    """Install the span redaction; `False` (and a content-free log) when that is impossible."""

    try:
        return harden_tracer_provider(provider)
    except Exception as error:
        _LOG.error(
            "telemetry_redaction_install_failed",
            extra=safe_log_fields({"error_type": type(error).__name__}),
        )
        return False


def stop_span_export(provider: TracerProvider) -> None:
    """Make a provider drop every span: no exporter on it, present or added later, sees one.

    Used when the redaction could not be installed (fail closed). The processor chain the
    provider already handed to its tracers has `on_start` and `on_end` replaced on the instance, so
    tracers obtained earlier stop reaching their exporters, and the provider gets a fresh empty
    chain for tracers obtained later and for processors added later. Spans that ended before this
    call are not recalled. Never raises.
    """

    chain: Any = active_span_processor(provider)
    if chain is not None:
        try:
            chain.on_start = _drop_started
            chain.on_end = _drop_span
        except Exception as error:
            _LOG.error(
                "telemetry_export_stop_incomplete",
                extra=safe_log_fields({"error_type": type(error).__name__}),
            )
    try:
        replace_active_span_processor(provider, SynchronousMultiSpanProcessor())
        provider.add_span_processor = lambda _processor: None  # type: ignore[method-assign]
    except Exception as error:
        _LOG.error(
            "telemetry_export_stop_incomplete",
            extra=safe_log_fields({"error_type": type(error).__name__}),
        )


def build_resource(environment: str) -> Resource:
    """The telemetry resource; the service version follows the package version."""

    return Resource.create(
        {
            "service.name": "sidekick",
            "service.version": __version__,
            "deployment.environment": environment,
        }
    )


def configure_observability(environment: str) -> TelemetryPort:
    """Configure local no-export providers; production exporters are environment composition."""

    global _adapter, _configured
    if _configured:
        if _adapter is None:
            raise RuntimeError("observability is marked configured without an adapter")
        return _adapter
    resource = build_resource(environment)
    # The redaction goes onto the provider before the provider is published or any exporter can be
    # added, and when it cannot be installed the provider drops every span instead (fail closed).
    existing = trace.get_tracer_provider()
    provider = (
        existing if isinstance(existing, TracerProvider) else TracerProvider(resource=resource)
    )
    redacted = _install_redaction(provider)
    if not redacted:
        _LOG.error("telemetry_export_stopped")
        stop_span_export(provider)
    elif provider is not existing:
        trace.set_tracer_provider(provider)
    # The MCP SDK and FastMCP extract client trace context through this global propagator.
    propagate.set_global_textmap(TRACEPARENT_ONLY)
    metrics.set_meter_provider(SdkMeterProvider(resource=resource))
    handler = logging.StreamHandler()
    handler.setFormatter(AllowlistJsonFormatter("%(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("sidekick")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    harden_third_party_logging()
    _adapter = OpenTelemetryAdapter() if redacted else NoopTelemetryAdapter()
    _configured = True
    return _adapter

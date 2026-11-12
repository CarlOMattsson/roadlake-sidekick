"""Privacy-preserving request correlation and structured logging."""

from .failure import log_failure
from .http_client_logs import HTTP_CLIENT_LOGGERS, silence_http_client_loggers
from .middleware import (
    CorrelationMiddleware,
    IngressLogRecord,
    route_template,
    safe_http_method,
)
from .port import (
    SAFE_ATTRIBUTE_NAMES,
    NoopTelemetryAdapter,
    OpenTelemetryAdapter,
    TelemetryPort,
    safe_telemetry_attributes,
)
from .propagation import TRACEPARENT_ONLY, TraceparentOnlyPropagator
from .setup import (
    SAFE_LOG_FIELDS,
    AllowlistJsonFormatter,
    ExceptionScrubbingSpanProcessor,
    ExceptionTypeOnlyFormatter,
    capture_warnings_safely,
    configure_observability,
    configure_worker_logging,
    disable_access_log,
    harden_third_party_logging,
    harden_tracer_provider,
    safe_log_fields,
    stop_span_export,
)
from .span_allowlist import (
    SAFE_SPAN_ATTRIBUTES,
    SAFE_SPAN_NAMES,
    SpanAllowlistProcessor,
    is_registered_tool,
    register_trusted_mcp_names,
    safe_mcp_method,
)
from .third_party_logs import install_safe_record_factory

__all__ = [
    "HTTP_CLIENT_LOGGERS",
    "SAFE_ATTRIBUTE_NAMES",
    "SAFE_LOG_FIELDS",
    "SAFE_SPAN_ATTRIBUTES",
    "SAFE_SPAN_NAMES",
    "TRACEPARENT_ONLY",
    "AllowlistJsonFormatter",
    "CorrelationMiddleware",
    "ExceptionScrubbingSpanProcessor",
    "ExceptionTypeOnlyFormatter",
    "IngressLogRecord",
    "NoopTelemetryAdapter",
    "OpenTelemetryAdapter",
    "SpanAllowlistProcessor",
    "TelemetryPort",
    "TraceparentOnlyPropagator",
    "capture_warnings_safely",
    "configure_observability",
    "configure_worker_logging",
    "disable_access_log",
    "harden_third_party_logging",
    "harden_tracer_provider",
    "install_safe_record_factory",
    "is_registered_tool",
    "log_failure",
    "register_trusted_mcp_names",
    "route_template",
    "safe_http_method",
    "safe_log_fields",
    "safe_mcp_method",
    "safe_telemetry_attributes",
    "silence_http_client_loggers",
    "stop_span_export",
]

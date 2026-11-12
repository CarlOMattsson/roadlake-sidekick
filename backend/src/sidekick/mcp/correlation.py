"""The correlation id of the HTTP request an MCP handler is running inside."""

from uuid import uuid4

from fastmcp.server.dependencies import get_http_request

#: Marker used by log lines when no id is available.
UNKNOWN_CORRELATION = "unknown"


def request_correlation_id() -> str | None:
    """The id the correlation middleware put on the request scope, or None outside a request."""

    try:
        value = get_http_request().scope.get("sidekick.correlation_id")
    except RuntimeError:
        return None
    return value if isinstance(value, str) else None


def request_correlation_id_or_new() -> str:
    """The request's correlation id, or a fresh one when no HTTP request is running (stdio).

    A write path hands this to its use case so the audit event carries an id either way.
    """

    return request_correlation_id() or uuid4().hex

"""One structured log line per MCP request, and a reason code for a transport-level 400.

The line names the protocol method, the tool for `tools/call`, the outcome and a closed error
code. It never carries arguments, results, titles or Journal text (D-058: logs and telemetry never
carry user content). The method must be on
the fixed protocol list and the tool a registered one, so a client cannot write free text into
a log field by choosing a method or tool name.
"""

import json
import logging
import re
import time
from typing import cast

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sidekick.mcp.correlation import UNKNOWN_CORRELATION, request_correlation_id
from sidekick.mcp.input_schemas import INTERNAL_LISTING
from sidekick.shared.observability import (
    is_registered_tool,
    safe_http_method,
    safe_log_fields,
    safe_mcp_method,
)

LOGGER = logging.getLogger("sidekick.mcp.request")

_CODE = re.compile(r"[a-z_]{1,40}")
_UNKNOWN_TOOL = "unknown"

# The MCP SDK's transport answers 400 with a JSON-RPC error whose message begins with one of
# these fixed texts. The body is only read for that message, which is mapped to a code here.
_TRANSPORT_REASONS: tuple[tuple[str, str], ...] = (
    ("Parse error", "parse_error"),
    ("Validation error", "invalid_params"),
    ("Bad Request: Missing session ID", "missing_session_id"),
    ("Bad Request: Unsupported protocol version", "unsupported_protocol_version"),
    # The modern-protocol (2026-07-28) path names the same reason without the prefix.
    ("Unsupported protocol version", "unsupported_protocol_version"),
    ("Invalid Content-Type header", "invalid_content_type"),
)
_UNCLASSIFIED_REASON = "unclassified"
_UNSUPPORTED_VERSION_REASON = "unsupported_protocol_version"
_PROTOCOL_VERSION_HEADER = b"mcp-protocol-version"
_PROTOCOL_VERSION = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INVALID_PROTOCOL_VERSION = "invalid"
_MAX_BODY_BYTES = 8192
_TOOL_ERROR_CLASS = "ToolError"
_SCHEMA_ERROR_CODE = "json_schema"


def _log(
    method: str | None,
    *,
    outcome: str,
    tool: str | None = None,
    error_class: str | None = None,
    error_code: str | None = None,
    duration_ms: float | None = None,
) -> None:
    fields: dict[str, object] = {
        "correlation_id": request_correlation_id() or UNKNOWN_CORRELATION,
        "mcp_method": safe_mcp_method(method),
        "outcome": outcome,
    }
    if duration_ms is not None:
        # Wall time of the request inside the MCP server, in milliseconds. A number only.
        fields["duration_ms"] = round(duration_ms, 1)
    if tool is not None:
        fields["mcp_tool_name"] = tool
    if error_class is not None:
        fields["mcp_error_class"] = error_class
    if error_code is not None:
        fields["mcp_error_code"] = error_code
    LOGGER.info("mcp_request_completed", extra=safe_log_fields(fields))


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _logged_tool_name(message: object) -> str:
    """The tool name when the server registered it (the registry the span allowlist uses)."""

    name = message.name if isinstance(message, CallToolRequestParams) else None
    return name if name is not None and is_registered_tool(name) else _UNKNOWN_TOOL


def _error_code(structured: dict[str, object] | None) -> str | None:
    """The closed code Sidekick's `error_result` puts in structured content, if well formed."""

    value = structured.get("code") if structured is not None else None
    if isinstance(value, str) and _CODE.fullmatch(value) is not None:
        return value
    return None


class SchemaRejection(ToolError):
    """A `tools/call` whose arguments failed the JSON Schema check of the tool's input schema.

    Raised by `sidekick.mcp.validation_errors.SchemaCheckedArguments` and logged here as a
    `ToolError` with the closed code `json_schema`.
    """


class McpRequestLogging(Middleware):
    """Log method, tool name, outcome and error class for each MCP request.

    Notifications are not logged. Added before the argument-redaction middleware, so the
    outcome seen here is the one the client receives.

    A tool name is logged only when the server registers a tool of that name; any other name a
    client sends is logged as `unknown`.
    """

    async def on_message(
        self,
        context: MiddlewareContext[object],
        call_next: CallNext[object, object],
    ) -> object:
        if context.type != "request" or INTERNAL_LISTING.get():
            return await call_next(context)
        method = context.method
        tool = _logged_tool_name(context.message) if method == "tools/call" else None
        started = time.perf_counter()
        try:
            result = await call_next(context)
        except SchemaRejection:
            _log(
                method,
                outcome="error",
                tool=tool,
                error_class=_TOOL_ERROR_CLASS,
                error_code=_SCHEMA_ERROR_CODE,
                duration_ms=_elapsed_ms(started),
            )
            raise
        except Exception as error:
            _log(
                method,
                outcome="error",
                tool=tool,
                error_class=type(error).__name__,
                duration_ms=_elapsed_ms(started),
            )
            raise
        duration_ms = _elapsed_ms(started)
        if isinstance(result, ToolResult) and result.is_error:
            _log(
                method,
                outcome="error",
                tool=tool,
                error_class=_TOOL_ERROR_CLASS,
                error_code=_error_code(result.structured_content),
                duration_ms=duration_ms,
            )
        else:
            _log(method, outcome="success", tool=tool, duration_ms=duration_ms)
        return result


def transport_reason(body: bytes) -> str:
    """Name the reason in a transport 400 body by its fixed message. The text is never logged."""

    message = _error_message(body[:_MAX_BODY_BYTES])
    for prefix, code in _TRANSPORT_REASONS:
        if message.startswith(prefix):
            return code
    return _UNCLASSIFIED_REASON


def _error_message(raw: bytes) -> str:
    text = raw.decode(errors="replace")
    try:
        parsed: object = json.loads(text)
    except ValueError:
        return text
    if not isinstance(parsed, dict):
        return ""
    error = cast("dict[str, object]", parsed).get("error")
    if not isinstance(error, dict):
        return ""
    message = cast("dict[str, object]", error).get("message")
    return message if isinstance(message, str) else ""


class McpTransportLogging:
    """Log why the public `/mcp` transport answered 400, as a code, never as the response body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        # Lookups of the mounted FastMCP app (its state names the server) see through the wrapper.
        self.state = getattr(app, "state", None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        observed: dict[str, int] = {}
        body = bytearray()

        async def observe(message: Message) -> None:
            if message["type"] == "http.response.start":
                observed["status"] = int(message["status"])
            elif observed.get("status") == 400 and len(body) < _MAX_BODY_BYTES:
                body.extend(bytes(message.get("body", b"")))
            await send(message)

        await self.app(scope, receive, observe)
        if observed.get("status") == 400:
            _log_transport_rejection(scope, bytes(body))


def _protocol_version(scope: Scope) -> str:
    """The `mcp-protocol-version` header the client sent, when it is a date; else "invalid"."""

    for name, value in scope.get("headers", []):
        if name.lower() == _PROTOCOL_VERSION_HEADER:
            text = value.decode("latin-1")
            if _PROTOCOL_VERSION.fullmatch(text) is not None:
                return text
            return _INVALID_PROTOCOL_VERSION
    return _INVALID_PROTOCOL_VERSION


def _log_transport_rejection(scope: Scope, body: bytes) -> None:
    correlation = scope.get("sidekick.correlation_id")
    reason = transport_reason(body)
    fields: dict[str, object] = {
        "correlation_id": correlation if isinstance(correlation, str) else UNKNOWN_CORRELATION,
        "http_method": safe_http_method(scope),
        "http_status": 400,
        "mcp_error_code": reason,
    }
    if reason == _UNSUPPORTED_VERSION_REASON:
        fields["mcp_protocol_version"] = _protocol_version(scope)
    LOGGER.info("mcp_transport_rejected", extra=safe_log_fields(fields))

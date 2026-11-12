"""HTTP correlation middleware with an explicit metadata allowlist."""

import logging
from dataclasses import dataclass
from time import monotonic
from uuid import UUID, uuid4

from opentelemetry import context as otel_context
from opentelemetry.trace import SpanKind
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .port import TelemetryPort
from .propagation import TRACEPARENT_ONLY

LOGGER = logging.getLogger("sidekick.http")

#: The only HTTP methods that reach a log field or span attribute; anything else is `OTHER`.
KNOWN_HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
OTHER_HTTP_METHOD = "OTHER"


def safe_http_method(scope: Scope) -> str:
    """The request method when it is one of the fixed set, else `OTHER`. A client picks the text."""

    method = scope.get("method")
    return method if isinstance(method, str) and method in KNOWN_HTTP_METHODS else OTHER_HTTP_METHOD


#: The route text logged when the request matched no route registered by the server.
UNMATCHED_ROUTE = "unmatched"
_MAX_ROUTE_TEMPLATE = 128


def route_template(scope: Scope) -> str:
    """The server's own route template (`/companion/v1/tasks/{task_id}`), never the request path.

    The template comes from the route the router matched, so it holds parameter names and not the
    ids, e-mail addresses or tokens a client put in the URL. No match logs `unmatched`.
    """

    template = getattr(scope.get("route"), "path", None)
    if (
        isinstance(template, str)
        and template.startswith("/")
        and len(template) <= _MAX_ROUTE_TEMPLATE
    ):
        return template
    return UNMATCHED_ROUTE


@dataclass(frozen=True, slots=True)
class IngressLogRecord:
    """The one closed shape of the HTTP ingress log line.

    The record is built from these fields and nothing else: it has no place for a path, a query
    string, a header, a body, a token or a client address, and no free-form `extra` to carry one.
    Adding a field means adding it here, to `SAFE_LOG_FIELDS` and to the test that pins the set.
    """

    correlation_id: str
    http_method: str
    http_route: str
    http_status: int
    duration_ms: float

    def fields(self) -> dict[str, str | int | float]:
        return {
            "correlation_id": self.correlation_id,
            "http_method": self.http_method,
            "http_route": self.http_route,
            "http_status": self.http_status,
            "duration_ms": self.duration_ms,
        }


def accepted_correlation_id(supplied: str) -> str | None:
    """The client's `x-correlation-id` only when it is a canonical UUID, else None."""

    try:
        parsed = UUID(supplied)
    except ValueError:
        return None
    return supplied if str(parsed) == supplied else None


class CorrelationMiddleware:
    def __init__(self, app: ASGIApp, telemetry: TelemetryPort) -> None:
        self.app = app
        self.telemetry = telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"x-correlation-id", b"").decode(errors="ignore")
        correlation_id = accepted_correlation_id(supplied) or str(uuid4())
        scope["sidekick.correlation_id"] = correlation_id
        method = safe_http_method(scope)
        status_code = 500
        started = monotonic()

        async def send_with_header(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                message.setdefault("headers", []).append(
                    (b"x-correlation-id", correlation_id.encode())
                )
            await send(message)

        # Only `traceparent` is read: `tracestate` and `baggage` are free client text.
        carrier = {
            "traceparent": headers.get(b"traceparent", b"").decode(errors="ignore"),
        }
        context = TRACEPARENT_ONLY.extract(carrier)
        token = otel_context.attach(context)
        try:
            with self.telemetry.span(
                "http.request",
                {"http.request.method": method, "correlation.id": correlation_id},
                kind=SpanKind.SERVER,
            ):
                await self.app(scope, receive, send_with_header)
        finally:
            otel_context.detach(token)
            attributes = {
                "http.request.method": method,
                "http.response.status_code": status_code,
                "outcome": "success" if status_code < 500 else "failure",
            }
            self.telemetry.count("sidekick.http.server.requests", attributes)
            record = IngressLogRecord(
                correlation_id=correlation_id,
                http_method=method,
                http_route=route_template(scope),
                http_status=status_code,
                duration_ms=round((monotonic() - started) * 1000, 3),
            )
            LOGGER.info("request_completed", extra=record.fields())

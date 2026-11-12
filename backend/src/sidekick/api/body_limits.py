"""Request-body ceilings and read-time budgets, enforced at ingress for every auth mode.

A size cap alone lets a client that drips bytes hold a worker, and a time budget alone lets a
client send an unbounded body, so both are applied before the app, FastMCP or any route parses a
byte. They guard the process whether the MCP endpoint runs with a personal access token or with
GitHub OAuth, and whether or not a public-surface allowlist is installed in front of it.

Only methods that carry a body are bounded. The MCP endpoint takes JSON-RPC (a journal entry is the
largest argument), the companion routes keep their own tighter per-route caps behind
authentication (`RequestBody`), and every other path (the OAuth token, consent and authorize forms,
or anything else a body is posted to) gets the small default.
"""

import asyncio
import logging
from collections.abc import Collection

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sidekick.api.failed_auth import VERIFIED_BEARER_SCOPE_KEY
from sidekick.api.ingress_problem import refuse_request
from sidekick.api.public_surface import is_companion_route
from sidekick.mcp import MCP_MOUNT_PATH
from sidekick.shared.observability import TelemetryPort, safe_http_method, safe_log_fields
from sidekick.shared.rooms import ROOMS

LOGGER = logging.getLogger("sidekick.http")

BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
MAX_MCP_BODY_BYTES = 1024 * 1024
MAX_COMPANION_BODY_BYTES = 256 * 1024
MAX_DEFAULT_BODY_BYTES = 16 * 1024

# Total time budgets for reading a body, from the moment ingress starts reading it. The OAuth forms
# are tiny and sent straight away, so they get the shorter budget; both are configurable
# (`SIDEKICK_BODY_READ_TIMEOUT_SECONDS`, `SIDEKICK_OAUTH_BODY_READ_TIMEOUT_SECONDS`).
DEFAULT_BODY_READ_TIMEOUT_SECONDS = 30.0
DEFAULT_OAUTH_BODY_READ_TIMEOUT_SECONDS = 10.0
# Most request bodies that may still be arriving at once, for the whole process. Each is at most
# `MAX_MCP_BODY_BYTES`, so the default bounds slow, incomplete bodies to 32 MiB of memory; a
# request that finds every slot taken is answered 503 at once (configurable, see
# `SIDEKICK_MAX_BUFFERED_REQUESTS`). The slot is released when the body is complete and handed to
# the app, not when the app returns: an MCP POST may answer with a stream that stays open for long
# time, and holding a slot for it would let a few legitimate streams starve every other request.
# A complete body therefore lives on while its request is handled, bounded by the app's own work.
# Ingress cannot verify a credential (that is a database query in the app), so the slots are
# shared by priority instead: a request whose bearer token the application has verified within
# the hour (see `sidekick.api.failed_auth`) may use every slot, anyone else (no credential, or a
# token not known yet) only all but a quarter, so anonymous clients that open many slow bodies
# cannot starve the owner's recent clients.
DEFAULT_MAX_BUFFERED_REQUESTS = 32
BUFFER_FULL_RETRY_AFTER_SECONDS = 1
VERIFIED_RESERVE_DIVISOR = 4


def _is_mcp_endpoint(path: str) -> bool:
    return path in {MCP_MOUNT_PATH, f"{MCP_MOUNT_PATH}/"}


def body_limit(path: str, companion: bool) -> int:
    """The largest body, in bytes, a body-carrying request to this path may send."""

    if companion:
        return MAX_COMPANION_BODY_BYTES
    if _is_mcp_endpoint(path):
        return MAX_MCP_BODY_BYTES
    return MAX_DEFAULT_BODY_BYTES


def is_oauth_body_path(path: str, companion: bool) -> bool:
    """True for the OAuth flow's own paths (not the MCP endpoint, not a companion route)."""

    return not companion and not _is_mcp_endpoint(path)


class RequestBodyLimitMiddleware:
    """Bound the size and arrival time of every request body, in front of the whole application."""

    def __init__(
        self,
        app: ASGIApp,
        telemetry: TelemetryPort,
        *,
        companion: bool = False,
        rooms: Collection[str] = ROOMS,
        oauth_surface: bool = False,
        body_read_timeout: float = DEFAULT_BODY_READ_TIMEOUT_SECONDS,
        oauth_body_read_timeout: float = DEFAULT_OAUTH_BODY_READ_TIMEOUT_SECONDS,
        max_buffered_requests: int = DEFAULT_MAX_BUFFERED_REQUESTS,
    ) -> None:
        self.app = app
        self.telemetry = telemetry
        self._companion = companion
        self._rooms = rooms
        # Only a deployment that serves the OAuth flow has OAuth forms to give the short budget.
        self._oauth_surface = oauth_surface
        self._body_timeout = body_read_timeout
        self._oauth_body_timeout = oauth_body_read_timeout
        # Counted without awaiting, so it is exact on the event loop without a lock.
        self._max_buffered = max_buffered_requests
        # Slots held back for verified bearers; a cap of 1..3 has none to spare.
        self._unverified_cap = (
            max_buffered_requests - max_buffered_requests // VERIFIED_RESERVE_DIVISOR
        )
        self._buffering = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        method = str(scope.get("method", ""))
        if scope["type"] != "http" or method not in BODY_METHODS:
            await self.app(scope, receive, send)
            return
        path = str(scope["path"])
        companion = self._companion and is_companion_route(method, path, self._rooms)
        limit = body_limit(path, companion)
        declared = _content_length(scope)
        if declared is None and _has_content_length(scope):
            await self._refuse(scope, receive, send, 411, "length_required", "Length required")
            return
        if declared is not None and declared > limit:
            await self._refuse(scope, receive, send, 413, "payload_too_large", "Payload too large")
            return
        # Hold the whole body, declared or chunked, until it is known to fit and has arrived within
        # the time budget, so the app only ever parses a complete body within the ceiling and a
        # client that drips bytes cannot hold a worker.
        timeout = (
            self._oauth_body_timeout
            if self._oauth_surface and is_oauth_body_path(path, companion)
            else self._body_timeout
        )
        cap = self._max_buffered if scope.get(VERIFIED_BEARER_SCOPE_KEY) else self._unverified_cap
        if self._buffering >= cap:
            await self._refuse(
                scope,
                receive,
                send,
                503,
                "service_busy",
                "Service busy",
                headers={"Retry-After": str(BUFFER_FULL_RETRY_AFTER_SECONDS)},
            )
            return
        self._buffering += 1
        timed_out = False
        buffered: bytes | None | object = None
        try:
            async with asyncio.timeout(timeout):
                buffered = await _buffer_within(receive, limit)
        except TimeoutError:
            timed_out = True
        finally:
            # Freed before any answer is sent: a slow reader of that answer must not hold a slot.
            self._buffering -= 1
        if timed_out:
            await self._refuse(scope, receive, send, 408, "request_timeout", "Request timeout")
            return
        if buffered is _DISCONNECTED:
            # The client is gone mid-body: nothing to answer and nothing to hand the app.
            return
        if not isinstance(buffered, bytes):
            await self._refuse(scope, receive, send, 413, "payload_too_large", "Payload too large")
            return
        await self.app(scope, _replay(buffered, receive), send)

    async def _refuse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        code: str,
        title: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.telemetry.count("sidekick.http.request_body", {"outcome": "denied"})
        LOGGER.info(
            "request_body_refused",
            extra=safe_log_fields(
                {
                    "correlation_id": scope.get("sidekick.correlation_id", "unknown"),
                    "http_method": safe_http_method(scope),
                    "http_status": status,
                    "outcome": "denied",
                }
            ),
        )
        await refuse_request(scope, receive, send, status, code, title, headers)


def _content_length(scope: Scope) -> int | None:
    """The declared body length, or `None` if absent or not a plain non-negative integer."""

    for name, value in scope.get("headers", []):
        if name == b"content-length":
            text = value.decode("latin-1").strip()
            return int(text) if text.isascii() and text.isdecimal() else None
    return None


def _has_content_length(scope: Scope) -> bool:
    return any(name == b"content-length" for name, _value in scope.get("headers", []))


_DISCONNECTED = object()


async def _buffer_within(receive: Receive, limit: int) -> bytes | None | object:
    """Read the whole request body.

    `None` as soon as it exceeds `limit` bytes; `_DISCONNECTED` if the client went away before the
    body was complete, so a partial body is never presented to the app as a finished one.
    """

    received = bytearray()
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return _DISCONNECTED
        received.extend(message.get("body", b""))
        if len(received) > limit:
            return None
        if not message.get("more_body", False):
            return bytes(received)


def _replay(body: bytes, receive: Receive) -> Receive:
    """A `receive` that yields an already-read body once, then defers to the real one."""

    sent = False

    async def replay() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay

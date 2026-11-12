"""The only paths a publicly tunnelled process answers in `github_oauth` mode.

A public tunnel points straight at this process, so the process itself must
refuse everything that is not the MCP endpoint or the OAuth flow in front of it. Anything
else, the whole `/api`, health, docs and OpenAPI included, answers an ordinary
404 that says nothing about what exists. The check is an exact allowlist on the decoded path;
it trusts no forwarded header and distinguishes no caller, because a tunnel's peer is loopback
for every visitor.
"""

import logging
import math
import re
from collections.abc import Callable, Collection
from time import monotonic

from starlette.types import ASGIApp, Receive, Scope, Send

from sidekick.api.ingress_problem import refuse_request
from sidekick.mcp import MCP_MOUNT_PATH
from sidekick.shared.observability import TelemetryPort, safe_http_method, safe_log_fields
from sidekick.shared.rooms import ROOMS

LOGGER = logging.getLogger("sidekick.http")

_EXACT_PATHS = frozenset(
    {
        f"{MCP_MOUNT_PATH}/",
        f"{MCP_MOUNT_PATH}/authorize",
        f"{MCP_MOUNT_PATH}/token",
        f"{MCP_MOUNT_PATH}/register",
        f"{MCP_MOUNT_PATH}/consent",
        f"{MCP_MOUNT_PATH}/auth/callback",
    }
)
# Discovery documents at the host root, including their path-aware forms (RFC 8414 / 9728).
_WELL_KNOWN_PREFIXES = (
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
)


# The companion app adapter (ADR-005), public only with `SIDEKICK_COMPANION_ENABLED=true`:
# exact method and path pairs, a lower-case canonical UUID where a Task id goes. Any other method
# on these paths, and any other path under `/companion/`, is the same plain 404 as the rest.
_UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
COMPANION_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"/companion/v1/pair")),
    ("GET", re.compile(r"/companion/v1/device")),
    ("DELETE", re.compile(r"/companion/v1/device")),
    ("POST", re.compile(r"/companion/v1/device/renew")),
    ("PUT", re.compile(r"/companion/v1/push/subscription")),
    ("DELETE", re.compile(r"/companion/v1/push/subscription")),
    ("POST", re.compile(r"/companion/v1/push/test")),
    ("GET", re.compile(r"/companion/v1/reminders/pending")),
    ("POST", re.compile(r"/companion/v1/reminders/ack")),
    ("GET", re.compile(r"/companion/v1/work/agenda")),
    ("GET", re.compile(r"/companion/v1/work/today")),
    ("GET", re.compile(rf"/companion/v1/tasks/{_UUID}")),
    ("GET", re.compile(rf"/companion/v1/tasks/{_UUID}/steps")),
    ("GET", re.compile(rf"/companion/v1/tasks/{_UUID}/contacts")),
    ("GET", re.compile(rf"/companion/v1/tasks/{_UUID}/external-references")),
    ("POST", re.compile(rf"/companion/v1/tasks/{_UUID}/complete")),
    ("POST", re.compile(rf"/companion/v1/tasks/{_UUID}/reopen")),
    # Arbete beyond the agenda: hierarchy, Project, Domain, Process, and the tick of a Step.
    ("GET", re.compile(r"/companion/v1/work/hierarchy")),
    ("GET", re.compile(rf"/companion/v1/projects/{_UUID}")),
    ("GET", re.compile(rf"/companion/v1/projects/{_UUID}/tasks")),
    ("GET", re.compile(rf"/companion/v1/domains/{_UUID}")),
    ("GET", re.compile(rf"/companion/v1/processes/{_UUID}")),
    ("POST", re.compile(rf"/companion/v1/steps/{_UUID}/complete")),
    ("POST", re.compile(rf"/companion/v1/steps/{_UUID}/reopen")),
    # Inköp and Dagbok (sidekick.api.companion_rooms); a journal day is an ISO date.
    ("GET", re.compile(r"/companion/v1/shopping/lists")),
    ("GET", re.compile(rf"/companion/v1/shopping/lists/{_UUID}")),
    ("POST", re.compile(r"/companion/v1/shopping/lists")),
    ("POST", re.compile(rf"/companion/v1/shopping/lists/{_UUID}/update")),
    ("POST", re.compile(rf"/companion/v1/shopping/lists/{_UUID}/items")),
    ("POST", re.compile(rf"/companion/v1/shopping/items/{_UUID}/update")),
    ("POST", re.compile(rf"/companion/v1/shopping/items/{_UUID}/purchased")),
    ("GET", re.compile(r"/companion/v1/journal/days/[0-9]{4}-[0-9]{2}-[0-9]{2}")),
    ("GET", re.compile(r"/companion/v1/journal/entries")),
    ("GET", re.compile(rf"/companion/v1/journal/entries/{_UUID}")),
    ("GET", re.compile(rf"/companion/v1/journal/sources/{_UUID}")),
    ("POST", re.compile(r"/companion/v1/journal/entries")),
    ("POST", re.compile(rf"/companion/v1/journal/entries/{_UUID}/update")),
    # The instance's license key (sidekick.api.companion_license).
    ("GET", re.compile(r"/companion/v1/license")),
    ("PUT", re.compile(r"/companion/v1/license")),
)


# The rooms whose companion routes a switched-off room (`SIDEKICK_ENABLED_ROOMS`) takes away, by
# the path prefix that holds them.
COMPANION_ROOM_PREFIXES: dict[str, str] = {
    "shopping": "/companion/v1/shopping/",
    "journal": "/companion/v1/journal/",
}


def is_companion_route(method: str, path: str, rooms: Collection[str] = ROOMS) -> bool:
    """True for an allowlisted method and path, unless the path belongs to a room that is off."""

    if any(
        path.startswith(prefix) and room not in rooms
        for room, prefix in COMPANION_ROOM_PREFIXES.items()
    ):
        return False
    return any(
        method == allowed and pattern.fullmatch(path) for allowed, pattern in COMPANION_ROUTES
    )


# Unauthenticated endpoints that create server-side state (a client record, a pending
# transaction) get a global budget. It is shared by all callers on purpose: behind a tunnel every
# visitor shares one peer address, so there is nothing safer to key on.
RATE_LIMITED = frozenset(
    {("POST", f"{MCP_MOUNT_PATH}/register"), ("GET", f"{MCP_MOUNT_PATH}/authorize")}
)
RATE_LIMIT_PER_MINUTE = 20
MAX_REGISTER_BODY_BYTES = 16 * 1024


class TokenBucket:
    """A refilling budget of `capacity` requests per minute, with an injectable clock."""

    def __init__(self, capacity: int, clock: Callable[[], float] = monotonic) -> None:
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._rate = capacity / 60.0
        self._clock = clock
        self._stamp = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._stamp) * self._rate)
        self._stamp = now

    def seconds_until_budget(self) -> int:
        """Whole seconds, at least 1, until one token has refilled (the `Retry-After` value)."""

        self._refill()
        return max(1, math.ceil((1.0 - self._tokens) / self._rate))

    def take(self) -> bool:
        self._refill()
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def refund(self) -> None:
        """Give one token back (never above capacity), e.g. for a reservation that was not used."""

        self._refill()
        self._tokens = min(self._capacity, self._tokens + 1.0)


def is_public_path(path: str) -> bool:
    if any(segment in {".", ".."} for segment in path.split("/")):
        return False
    if path in _EXACT_PATHS:
        return True
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in _WELL_KNOWN_PREFIXES)


class PublicSurfaceAllowlistMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        telemetry: TelemetryPort,
        clock: Callable[[], float] = monotonic,
        companion: bool = False,
        rooms: Collection[str] = ROOMS,
    ) -> None:
        self.app = app
        self.telemetry = telemetry
        # The companion method/path pairs (`SIDEKICK_COMPANION_ENABLED`).
        self._companion = companion
        # With `SIDEKICK_ENABLED_ROOMS`, the companion routes of a room that is off stay out.
        self._rooms = rooms
        self._buckets = {key: TokenBucket(RATE_LIMIT_PER_MINUTE, clock) for key in RATE_LIMITED}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        path = str(scope["path"])
        if path == MCP_MOUNT_PATH:
            # Serve the published, slash-less URL directly. A redirect would be built from the
            # tunnel's plain-HTTP hop and send the client to an address it never configured.
            path = f"{MCP_MOUNT_PATH}/"
            scope["path"] = path
            scope["raw_path"] = path.encode()
        method = str(scope.get("method", ""))
        companion = self._companion and is_companion_route(method, path, self._rooms)
        if not companion and not is_public_path(path):
            await self._refuse(scope, receive, send, 404, "not_found", "Not found")
            return
        bucket = self._buckets.get((str(scope.get("method", "")), path))
        if bucket is not None and not bucket.take():
            await self._refuse(
                scope,
                receive,
                send,
                429,
                "rate_limited",
                "Too many requests",
                headers={"Retry-After": "60"},
            )
            return
        await self.app(scope, receive, send)

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
        correlation_id = scope.get("sidekick.correlation_id", "unknown")
        self.telemetry.count("sidekick.http.public_surface", {"outcome": "denied"})
        LOGGER.info(
            "public_surface_denied",
            extra=safe_log_fields(
                {
                    "correlation_id": correlation_id,
                    "http_method": safe_http_method(scope),
                    "http_status": status,
                    "outcome": "denied",
                }
            ),
        )
        await refuse_request(scope, receive, send, status, code, title, headers)

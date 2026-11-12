"""A cheap, in-memory limit on failed bearer attempts, applied before any database work.

Verifying a bearer token costs a database round trip, so a client that guesses tokens in a loop
would otherwise make the database do the work for it. This middleware counts the requests that carry
a bearer token and are answered 401, per client address and for the whole process, in a sliding
window. Once a budget is spent, further requests that carry an unknown token are answered 429
before the application (and so the database) sees them.

The owner is not locked out by someone else's guesses:

- a token the application has really verified (the auth code calls
  `verification_signal.mark_verified()`; a status code proves nothing, a redirect or an open route
  answers 2xx or 3xx for any token) is remembered for an hour, renewed on every use, as a keyed hash
  (random per process, never the token). Its requests skip the check, so valid traffic is
  unaffected while an attack runs. The application still verifies it on every request; if it has
  been revoked it answers 401, the token is forgotten and the failure counts like any other;
- a small reserve of requests with unknown tokens (`reserve_per_minute`) is always let through to
  the application, whatever the budgets say. After a restart, or when a token has not been used for
  an hour, the owner's first valid call therefore reaches the application within seconds, even
  during a sustained attack, and its token becomes known. A guesser can use the reserve up too, so
  the owner may need a few retries; the reserve is deliberately too small to be worth attacking;
- only 401 answers count: an unauthenticated request without any bearer header is answered by the
  MCP layer without database work and is not counted, and neither are 403, 404 or 5xx answers;
- requests refused here are not counted, so a client that stops gets in again as its failures age
  out of the window.

A client can tell "429" from "401" and so learn that a token is not a recently used one while a
budget is spent: this is an oracle for guessed tokens, which is harmless for 256-bit random tokens.
Behind a tunnel every visitor shares one peer address and no forwarded header is trusted, so the
per-client budget then equals the global one in effect, and the global budget and the reserve are
what protect the owner there.
"""

import hashlib
import hmac
import logging
import math
import secrets
from collections import deque
from collections.abc import Callable
from time import monotonic

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sidekick.api.ingress_problem import refuse_request
from sidekick.api.public_surface import TokenBucket
from sidekick.shared.auth.verification_signal import watch
from sidekick.shared.observability import TelemetryPort, safe_http_method, safe_log_fields

LOGGER = logging.getLogger("sidekick.http")

DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE = 10
DEFAULT_FAILURES_GLOBAL_PER_MINUTE = 60
DEFAULT_RESERVE_PER_MINUTE = 5
WINDOW_SECONDS = 60.0
# Peer addresses tracked at once, and recently accepted tokens remembered (as hashes).
MAX_TRACKED_CLIENTS = 4096
MAX_KNOWN_TOKENS = 64
KNOWN_TOKEN_SECONDS = 3600.0
# Set on the ASGI scope for a request whose bearer token the application verified within the hour,
# so later ingress layers (the request-buffer cap) can tell the owner's traffic from the unknown.
VERIFIED_BEARER_SCOPE_KEY = "sidekick.verified_bearer"
# A refusal is logged at most once per this many seconds; every one is still counted as telemetry.
LOG_INTERVAL_SECONDS = 60.0


def bearer_token(scope: Scope) -> bytes | None:
    """The bearer credential of this request, or `None` when it carries none."""

    for name, value in scope.get("headers", []):
        if name == b"authorization":
            scheme, _, token = value.partition(b" ")
            token = token.strip()
            if scheme.lower() == b"bearer" and token:
                return bytes(token)
            return None
    return None


class FailedAuthGuard:
    """Sliding-window budgets of failed bearer attempts, with an injectable clock."""

    def __init__(
        self,
        per_client: int = DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE,
        global_limit: int = DEFAULT_FAILURES_GLOBAL_PER_MINUTE,
        *,
        reserve_per_minute: int = DEFAULT_RESERVE_PER_MINUTE,
        window: float = WINDOW_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._per_client = per_client
        self._global_limit = global_limit
        self._window = window
        self._clock = clock
        self._reserve = TokenBucket(reserve_per_minute, clock) if reserve_per_minute > 0 else None
        self._key = secrets.token_bytes(32)
        self._global: deque[float] = deque()
        self._clients: dict[str, deque[float]] = {}
        self._known: dict[bytes, float] = {}

    def fingerprint(self, token: bytes) -> bytes:
        """A keyed hash of the token that is only good for recognising it again in this process."""

        return hmac.new(self._key, token, hashlib.sha256).digest()

    def knows(self, fingerprint: bytes) -> bool:
        """True if the application verified this token recently (renews its hour, like a use)."""

        return self._is_known(fingerprint, self._clock())

    def retry_after(self, client: str, fingerprint: bytes | None) -> int | None:
        """Seconds to wait if this request must be refused now, else `None`."""

        now = self._clock()
        if fingerprint is not None and self._is_known(fingerprint, now):
            return None
        waits: list[float] = []
        self._prune(self._global, now)
        if len(self._global) >= self._global_limit:
            waits.append(self._global[0] + self._window - now)
        failures = self._clients.get(client)
        if failures is not None:
            self._prune(failures, now)
            if not failures:
                del self._clients[client]
            elif len(failures) >= self._per_client:
                waits.append(failures[0] + self._window - now)
        if not waits:
            return None
        if self._reserve is not None and self._reserve.take():
            return None
        return max(1, math.ceil(max(waits)))

    def record_failure(self, client: str, fingerprint: bytes | None) -> None:
        now = self._clock()
        if fingerprint is not None:
            self._known.pop(fingerprint, None)
        self._global.append(now)
        failures = self._clients.get(client)
        if failures is None:
            if len(self._clients) >= MAX_TRACKED_CLIENTS:
                self._make_room(now)
            failures = self._clients.setdefault(client, deque())
        failures.append(now)

    def record_success(self, fingerprint: bytes) -> None:
        now = self._clock()
        if fingerprint not in self._known and len(self._known) >= MAX_KNOWN_TOKENS:
            oldest = min(self._known, key=lambda key: self._known[key])
            del self._known[oldest]
        self._known[fingerprint] = now + KNOWN_TOKEN_SECONDS

    def _is_known(self, fingerprint: bytes, now: float) -> bool:
        expires = self._known.get(fingerprint)
        if expires is None:
            return False
        if expires <= now:
            del self._known[fingerprint]
            return False
        self._known[fingerprint] = now + KNOWN_TOKEN_SECONDS  # renewed on every use
        return True

    def _prune(self, failures: deque[float], now: float) -> None:
        while failures and failures[0] <= now - self._window:
            failures.popleft()

    def _make_room(self, now: float) -> None:
        for client in list(self._clients):
            failures = self._clients[client]
            self._prune(failures, now)
            if not failures:
                del self._clients[client]
        if len(self._clients) >= MAX_TRACKED_CLIENTS:
            # Still full of live clients: forget the one whose failures began first.
            del self._clients[min(self._clients, key=lambda key: self._clients[key][0])]


class FailedAuthLimitMiddleware:
    """Refuse bearer requests from a client or process that failed too often, pre-database."""

    def __init__(
        self,
        app: ASGIApp,
        telemetry: TelemetryPort,
        guard: FailedAuthGuard | None = None,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.app = app
        self.telemetry = telemetry
        self._guard = guard or FailedAuthGuard()
        self._clock = clock
        self._last_logged: float | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = bearer_token(scope) if scope["type"] == "http" else None
        if token is None:
            await self.app(scope, receive, send)
            return
        fingerprint = self._guard.fingerprint(token)
        if self._guard.knows(fingerprint):
            scope[VERIFIED_BEARER_SCOPE_KEY] = True
        client = client_address(scope)
        wait = self._guard.retry_after(client, fingerprint)
        if wait is not None:
            await self._refuse(scope, receive, send, wait)
            return

        with watch() as verification:

            async def observe(message: Message) -> None:
                if message["type"] == "http.response.start":
                    if verification.verified:
                        self._guard.record_success(fingerprint)
                    elif int(message["status"]) == 401:
                        self._guard.record_failure(client, fingerprint)
                await send(message)

            await self.app(scope, receive, observe)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send, wait: int) -> None:
        self.telemetry.count("sidekick.http.failed_auth", {"outcome": "limited"})
        now = self._clock()
        if self._last_logged is None or now - self._last_logged >= LOG_INTERVAL_SECONDS:
            self._last_logged = now
            LOGGER.warning(
                "failed_auth_limited",
                extra=safe_log_fields(
                    {
                        "correlation_id": scope.get("sidekick.correlation_id", "unknown"),
                        "http_method": safe_http_method(scope),
                        "http_status": 429,
                        "outcome": "limited",
                    }
                ),
            )
        await refuse_request(
            scope,
            receive,
            send,
            429,
            "rate_limited",
            "Too many requests",
            headers={"Retry-After": str(wait)},
        )


def client_address(scope: Scope) -> str:
    """The peer address of this request (the one the transport reports; no header is trusted)."""

    client = scope.get("client")
    return str(client[0]) if client else "unknown"

"""Push delivery rules (ADR-005; D-078, push through UnifiedPush): what to send, when to retry and
when to give up.

`PushDeliveryService` sends what `push_outbox` holds, after the commit that queued it. It knows the
rules and nothing about storage or HTTP: rows are read and written through `PushDeliveryStore`
(`push_delivery_store`) and a send is one call to `PushSender` (`push_sender`). The process loop
and CLI are in `push_worker`.

A send is one POST to the subscription's UnifiedPush endpoint with the fixed body `{"k":"w"}` or
`{"k":"r"}`: no redirects, a 10 second timeout, and the response is never read beyond its status.

- 2xx: delivered.
- 404 or 410: the endpoint is gone; the subscription is revoked and its pending rows are closed.
- 408, 425, 429, 5xx and network errors: retried with exponential backoff and jitter, at most
  `MAX_ATTEMPTS` times, then given up (the phone syncs when it next opens). A `Retry-After` on a
  429 or 503 (seconds or an HTTP date; a malformed value is ignored) postpones the retry to at
  least that long; one longer than `BACKOFF_CAP` gives the row up at once. A 429 never revokes
  the subscription.
  The quota is per sender IP, so a 429 or 503 also blocks the whole host in memory for the same
  time (the `Retry-After`, else the backoff): rows due meanwhile are not sent but moved to the end
  of the block (or given up if it lies beyond `BACKOFF_CAP`), and their attempts are not counted.
  After a restart one 429 teaches the worker the block again; nothing is stored.
- No send slot free (earlier sends still running past their deadline): the row is moved
  `BUSY_DEFER` ahead and its attempt is not counted, so a slow host cannot use up the attempts
  of other subscriptions.
- A send that hits the deadline is retried like any network error, but its request may already
  have reached the server: delivery is at-least-once, so a wake can in rare cases arrive twice.
  That is harmless: the body carries no content and the phone fetches what is pending
  idempotently. (ntfy's `X-Sequence-ID` replaces a notification in the ntfy app; it is no
  idempotency guarantee for a UnifiedPush forward, so it is not used.)
- 401 or 403 from the auth host (`SIDEKICK_PUSH_AUTH_HOST`, a token the server refuses): an
  operator problem, not a dead device. Retried with backoff like a 5xx (`last_error_kind`
  `unauthorized`) and the host is held back in memory; the subscription is never revoked.
- any other status: the row is closed, not retried.

With `SIDEKICK_PUSH_AUTH_HOST` and `SIDEKICK_PUSH_AUTH_TOKEN` set, a send carries
`Authorization: Bearer <token>` only when the endpoint's host equals the auth host exactly; every
other host (ntfy.sh as a fallback) gets no credentials. The token is a `SecretStr`, never logged.

Before every send the endpoint is validated again (`validate_endpoint`, so removing a host from
`SIDEKICK_PUSH_ALLOWED_HOSTS` takes effect at once) and the device's companion credential is
checked: a revoked or expired credential, or an inactive owner, revokes the subscription and
nothing is sent.

A claimed row is leased: its `next_attempt_at` is moved `LEASE` ahead, and the outcome is written
only if the row still carries that lease. A change that queued a wake meanwhile has made the row due
again, so the finished send never swallows it.

The claim takes a whole batch at once but the sends run one after another, each up to a few send
timeouts, so a later row's lease can run out before its turn and another worker then claims and
sends it. Therefore each row's lease is renewed, with the same compare-and-set, right before its
send starts (`_begin`): a row that another worker took, or that a change made due again, is skipped
here, and the renewed lease outlasts the one send (LEASE is longer than the worst-case send).

Nothing here logs an endpoint, a topic or a response: a subscription is identified by its host.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from sidekick.companion.push import EndpointRejected, validate_endpoint
from sidekick.shared.errors.core import SidekickError
from sidekick.shared.observability import log_failure, safe_log_fields
from sidekick.shared.types import utc_now

LOGGER = logging.getLogger("sidekick.companion.push_delivery")

MAX_ATTEMPTS = 6
BACKOFF_BASE = timedelta(seconds=30)
BACKOFF_CAP = timedelta(minutes=30)
LEASE = timedelta(seconds=60)
BUSY_DEFER = timedelta(seconds=15)
BATCH_SIZE = 50
PAYLOADS = {"w": b'{"k":"w"}', "r": b'{"k":"r"}'}
RETRYABLE_STATUSES = frozenset({408, 425, 429})
RETRY_AFTER_STATUSES = frozenset({429, 503})
UNAUTHORIZED_STATUSES = frozenset({401, 403})


def parse_retry_after(value: str | None, now: datetime) -> timedelta | None:
    """A `Retry-After` header as a non-negative wait: delay-seconds or an HTTP date. A missing,
    malformed or absurd value gives None, so the ordinary backoff applies."""

    if value is None:
        return None
    text = value.strip()
    if text.isascii() and text.isdigit():
        return timedelta(seconds=min(int(text), 10**9))
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(moment - now, timedelta(0))


@dataclass(frozen=True, slots=True)
class Claim:
    outbox_id: UUID
    subscription_id: UUID
    kind: str
    lease: datetime
    attempts: int


@dataclass(frozen=True, slots=True)
class Target:
    """What one send needs; `endpoint` stays inside the delivery code and is never logged."""

    endpoint: str
    host: str
    user_id: UUID
    device_id: UUID | None
    revoked: bool
    credential_valid: bool


class SendsBusy(SidekickError):
    """Every send slot is held by an earlier send that is still running past its deadline."""


class SendFailed(SidekickError):
    """A send that got no status: `kind` is `timeout` or `network`. Carries no URL or message."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class PushSender(Protocol):
    def send(
        self, endpoint: str, content: bytes, headers: dict[str, str]
    ) -> tuple[int, str | None]:
        """POST once; returns (status, Retry-After header). Raises `SendsBusy` when no send slot
        is free and `SendFailed` when there was no response."""
        ...


class PushDeliveryStore(Protocol):
    """The outbox, subscription and credential rows the delivery rules read and write."""

    def claim_due(
        self, now: datetime, lease: datetime, batch_size: int, max_attempts: int
    ) -> list[Claim]:
        """Lease the due rows (a row already at `max_attempts` is given up instead)."""
        ...

    def failed_rows_waiting(self) -> bool: ...

    def renew_lease(self, claim: Claim, lease: datetime) -> bool:
        """Move the lease while the row still carries the claim's; False if it no longer does."""
        ...

    def target(self, subscription_id: UUID, now: datetime) -> Target | None: ...

    def mark_delivered(self, claim: Claim, now: datetime) -> None: ...

    def close(self, claim: Claim, reason: str) -> None:
        """Stop retrying the row for good, with `reason` as its last error kind."""
        ...

    def schedule_retry(self, claim: Claim, at: datetime | None, error_kind: str) -> None:
        """Try the row again at `at`, or give it up when `at` is None."""
        ...

    def defer_unsent(self, claim: Claim, until: datetime | None, error_kind: str | None) -> None:
        """Hand the attempt back and move the never-sent row to `until` (None gives it up)."""
        ...

    def record_success(
        self, subscription_id: UUID, now: datetime, hold_wakes_until: datetime | None
    ) -> None:
        """Note the success; a wake still waiting for the subscription is held to the given time."""
        ...

    def record_failure(self, subscription_id: UUID) -> None: ...

    def revoke(self, claim: Claim, target: Target, reason: str, now: datetime) -> None:
        """Revoke the subscription (only if still on `target.endpoint`) and close its rows."""
        ...


class PushDeliveryService:
    def __init__(
        self,
        store: PushDeliveryStore,
        sender: PushSender,
        allowed_hosts: frozenset[str],
        *,
        clock: Callable[[], datetime] = utc_now,
        jitter: Callable[[], float] = random.random,
        wake_min_interval: timedelta = timedelta(0),
        auth_host: str | None = None,
        auth_token: SecretStr | None = None,
    ) -> None:
        self._auth_host = auth_host.lower() if auth_host and auth_token is not None else None
        self._auth_token = auth_token if self._auth_host else None
        self._store = store
        self._sender = sender
        self._allowed_hosts = allowed_hosts
        self._clock = clock
        self._jitter = jitter
        self._wake_min_interval = wake_min_interval
        self._blocked: dict[str, datetime] = {}
        #: True when the last `run_once` had rows and every one of them failed unexpectedly
        #: (an exception, not a refusal from a push server): the cycle is not a success. It stays
        #: true through empty polls while failed rows wait out their lease or backoff, and ends
        #: when a delivery cycle does not fail or no failed row is left waiting.
        self.last_run_failed = False

    def run_once(self) -> int:
        """Send every due row once; returns how many were attempted."""

        now = self._clock()
        claims = self._store.claim_due(now, now + LEASE, BATCH_SIZE, MAX_ATTEMPTS)
        failures = 0
        for claim in claims:
            try:
                started = self._begin(claim)
                if started is not None:
                    self._deliver(started)
            except Exception as error:
                # The lease expires and the row is tried again; the loop must not stop.
                failures += 1
                log_failure(LOGGER, "push delivery failed unexpectedly", error)
        if claims:
            self.last_run_failed = failures == len(claims)
        elif self.last_run_failed and not self._store.failed_rows_waiting():
            # An empty poll only counts as recovery when nothing that failed is still waiting.
            self.last_run_failed = False
        return len(claims)

    def _begin(self, claim: Claim) -> Claim | None:
        """Renew the claim's lease just before its send, or None if the row is no longer ours.

        The batch was leased at claim time, but the earlier sends in it may have been slow; by now
        another worker may have claimed the row (its lease ran out) and be sending it. The renewal
        succeeds only while the row still carries this claim's lease, atomically, so of two workers
        exactly one goes on to send."""

        lease = self._clock() + LEASE
        if not self._store.renew_lease(claim, lease):
            return None
        return replace(claim, lease=lease)

    def _deliver(self, claim: Claim) -> None:
        target = self._store.target(claim.subscription_id, self._clock())
        if target is None or target.revoked:
            self._store.close(claim, "revoked")
            return
        if not target.credential_valid:
            self._revoke(claim, target, "credential")
            self._log(claim, target, "credential_invalid")
            return
        try:
            validate_endpoint(target.endpoint, self._allowed_hosts)
        except EndpointRejected:
            self._revoke(claim, target, "endpoint")
            self._log(claim, target, "endpoint_rejected")
            return

        if self._defer_if_blocked(claim, target):
            self._log(claim, target, "blocked")
            return

        status: int | None = None
        failure: str | None = None
        retry_after: timedelta | None = None
        headers = {"Content-Type": "application/json"}
        authenticated = self._auth_token is not None and target.host == self._auth_host
        if authenticated and self._auth_token is not None:
            headers["Authorization"] = f"Bearer {self._auth_token.get_secret_value()}"
        try:
            status, retry_after_header = self._sender.send(
                target.endpoint, PAYLOADS[claim.kind], headers
            )
            if status in RETRY_AFTER_STATUSES:
                retry_after = parse_retry_after(retry_after_header, self._clock())
        except SendsBusy:
            self._defer_busy(claim)
            self._log(claim, target, "busy")
            return
        except SendFailed as error:
            failure = error.kind

        if status is not None and 200 <= status < 300:
            self._store.mark_delivered(claim, self._clock())
            self._record_success(claim.subscription_id)
            self._log(claim, target, "delivered", status)
        elif status in (404, 410):
            self._revoke(claim, target, "gone")
            self._log(claim, target, "gone", status)
        elif authenticated and status in UNAUTHORIZED_STATUSES:
            # The server refuses our token: fix the configuration; the device is not at fault.
            outcome = self._retry(claim, "unauthorized", None, target.host)
            self._log(claim, target, outcome, status)
        elif failure is not None or status in RETRYABLE_STATUSES or (status or 0) >= 500:
            kind = failure or ("rate_limited" if status == 429 else "server_error")
            block_host = target.host if status in RETRY_AFTER_STATUSES else None
            outcome = self._retry(claim, kind, retry_after, block_host)
            self._log(claim, target, outcome, status)
        else:
            self._store.close(claim, "rejected")
            self._store.record_failure(claim.subscription_id)
            self._log(claim, target, "rejected", status)

    def _retry(
        self,
        claim: Claim,
        error_kind: str,
        retry_after: timedelta | None = None,
        block_host: str | None = None,
    ) -> str:
        """Schedule the next attempt, or give the row up; returns the outcome to log. With
        `block_host` no row is sent to that host until the wait has passed."""

        delay = min(BACKOFF_BASE * 2 ** (claim.attempts - 1), BACKOFF_CAP)
        # Between half and the whole delay, so a burst of failures does not retry in step.
        wait = delay * (0.5 + 0.5 * self._jitter())
        if retry_after is not None:
            wait = max(wait, retry_after)
        now = self._clock()
        if block_host is not None:
            self._blocked[block_host] = now + wait
        if claim.attempts >= MAX_ATTEMPTS or (
            retry_after is not None and retry_after > BACKOFF_CAP
        ):
            # Out of attempts, or the server asks for more than we would ever wait: the phone
            # syncs when it next opens and fetches reminders itself.
            outcome = "gave_up"
            self._store.schedule_retry(claim, None, error_kind)
        else:
            outcome = "retry"
            self._store.schedule_retry(claim, now + wait, error_kind)
        self._store.record_failure(claim.subscription_id)
        return outcome

    def _defer_if_blocked(self, claim: Claim, target: Target) -> bool:
        """If the host is blocked, move the (never sent) row to the end of the block, or give it
        up when that lies beyond `BACKOFF_CAP`; the claim's attempt is handed back."""

        now = self._clock()
        until = self._blocked.get(target.host)
        if until is None:
            return False
        if until <= now:
            del self._blocked[target.host]
            return False
        if until - now > BACKOFF_CAP:
            self._store.defer_unsent(claim, None, "rate_limited")
        else:
            self._store.defer_unsent(claim, until, None)
        return True

    def _defer_busy(self, claim: Claim) -> None:
        """Move a never-sent row a little ahead and hand its attempt back (like a blocked host)."""

        self._store.defer_unsent(claim, self._clock() + BUSY_DEFER, None)

    def _record_success(self, subscription_id: UUID) -> None:
        """Note the success and keep the wake interval: a wake still waiting for this
        subscription (queued, or made due again by a change during this very send) is held until
        the interval after this success, which the enqueue could not know."""

        now = self._clock()
        hold = now + self._wake_min_interval if self._wake_min_interval > timedelta(0) else None
        self._store.record_success(subscription_id, now, hold)

    def _revoke(self, claim: Claim, target: Target, reason: str) -> None:
        self._store.revoke(claim, target, reason, self._clock())

    @staticmethod
    def _log(claim: Claim, target: Target, outcome: str, status: int | None = None) -> None:
        fields: dict[str, object] = {
            "push_kind": claim.kind,
            "push_host": target.host,
            "push_outcome": outcome,
        }
        if status is not None:
            fields["push_status"] = status
        LOGGER.info("push_delivery", extra=safe_log_fields(fields))

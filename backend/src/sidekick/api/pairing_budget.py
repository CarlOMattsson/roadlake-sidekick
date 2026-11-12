"""The budget of failed pairing attempts on `POST /companion/v1/pair`.

The pairing secret has 256 bits, so no limit here guards against guessing; the budget bounds the
unauthenticated database work a caller who knows the URL can make the server do. The budget is
reserved BEFORE the exchange runs (no await between check and take, so concurrent requests cannot
overshoot it) and given back when the pairing succeeds: only failures consume it.

One shared budget would let a stranger spend it and so refuse the owner's valid code, because
validity is only known after the exchange. Three layers keep that from happening:

- a budget per client address. A client that has spent its own is refused, whatever the others do;
- a global budget on top, which only gates clients that have failed recently. A client with no
  recent failures (its bucket is full) is let in even when the global budget is spent, so an
  attack spread over many addresses cannot lock out an owner on another address;
- a small reserve, taken only when the two above refuse. Behind a tunnel or proxy every visitor
  has the same peer address (no forwarded header is trusted), so there the owner shares the
  attacker's client budget and the reserve is what lets a few attempts through. A sustained
  attacker can use the reserve up too, so the owner may need a few retries; the reserve is
  deliberately too small to be worth attacking, given 256-bit secrets.

Clients are tracked in memory for the process only, bounded, and never logged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from sidekick.api.public_surface import TokenBucket

DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE = 10
DEFAULT_FAILURES_GLOBAL_PER_MINUTE = 30
DEFAULT_RESERVE_PER_MINUTE = 3
MAX_TRACKED_CLIENTS = 4096


@dataclass(frozen=True, slots=True)
class PairingReservation:
    """The tokens one admitted attempt holds; `refund` gives them back after a success."""

    buckets: tuple[TokenBucket, ...]

    def refund(self) -> None:
        for bucket in self.buckets:
            bucket.refund()


class PairingBudget:
    """Per-client, global and reserve budgets of failed pairings, with an injectable clock."""

    def __init__(
        self,
        per_client: int = DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE,
        global_limit: int = DEFAULT_FAILURES_GLOBAL_PER_MINUTE,
        reserve_per_minute: int = DEFAULT_RESERVE_PER_MINUTE,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._per_client = per_client
        self._clock = clock
        self._global = TokenBucket(global_limit, clock)
        self._reserve = TokenBucket(reserve_per_minute, clock) if reserve_per_minute > 0 else None
        self._clients: dict[str, TokenBucket] = {}

    def admit(self, client: str) -> PairingReservation | None:
        """Reserve one attempt for this client, or `None` when it must be refused now."""

        own = self._client_bucket(client)
        clean = own.available() >= self._per_client
        if own.take():
            if self._global.take():
                return PairingReservation((own, self._global))
            if clean:
                return PairingReservation((own,))
            own.refund()
        if self._reserve is not None and self._reserve.take():
            return PairingReservation((self._reserve,))
        return None

    def retry_after(self, client: str) -> int:
        """Seconds until a refused client could be admitted again (the `Retry-After` value)."""

        waits: list[int] = []
        own = self._clients.get(client)
        if own is not None and own.available() < 1.0:
            waits.append(own.seconds_until_budget())
        if self._global.available() < 1.0:
            waits.append(self._global.seconds_until_budget())
        wait = max(waits) if waits else 1
        if self._reserve is not None:
            wait = min(wait, self._reserve.seconds_until_budget())
        return wait

    def _client_bucket(self, client: str) -> TokenBucket:
        bucket = self._clients.get(client)
        if bucket is None:
            if len(self._clients) >= MAX_TRACKED_CLIENTS:
                self._make_room()
            bucket = self._clients.setdefault(client, TokenBucket(self._per_client, self._clock))
        return bucket

    def _make_room(self) -> None:
        for client in [c for c, b in self._clients.items() if b.available() >= self._per_client]:
            del self._clients[client]
        if len(self._clients) >= MAX_TRACKED_CLIENTS:
            # Still full of clients with recent failures: forget the one that failed least.
            del self._clients[max(self._clients, key=lambda key: self._clients[key].available())]

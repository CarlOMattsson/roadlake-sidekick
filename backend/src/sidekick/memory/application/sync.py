"""Derived-memory reconcile pass: Sidekick's records against the Hindsight bank.

One pass per owner compares the owner's records with `memory_sources` and brings the bank in line.
The pass is the only code that sends owner data to the memory provider and the only code that
deletes from it. It follows the memory design (backfill, verified recall, cost caps, deletion).

Order of a pass, under a per-owner advisory lock (a second worker skips the owner):

1. Poll submitted operations: `retained`, `failed` (bounded retries, then `parked`), or lost after a
   deadline.
2. Tombstones: rows whose record is permanently gone, replaced, excluded or whose domain is switched
   off lose their document, then their row. Never delayed, never subject to pause or kill switch.
3. Scan the live records of each enabled domain. A record that no longer qualifies loses its
   document. A qualifying record outside the quiet period gets its canonical document and
   fingerprint computed; a new or changed fingerprint makes the row `pending`.
4. Send at most one batch of due rows, newest first, inside the daily caps.

State of a `memory_sources` row:

    (none) -> pending -> submitted -> retained
                 ^           |  \\-> failed (backoff) -> pending-like retry -> ... -> parked
                 |           \\----- operation lost after OPERATION_DEADLINE -> failed
    any state + changed fingerprint / pipeline_version -> pending (attempts reset)
    parked: no automatic retry; only a changed fingerprint or pipeline version resets it

`failed` and `pending` rows are due when `next_attempt_at` is empty or passed. For a `submitted` row
`next_attempt_at` is the operation deadline.

Crash safety. Before a batch is sent, one transaction counts the batch against today's caps and
bumps `attempts` and `next_attempt_at` of its rows. A crash after the provider accepted the batch
but before `submitted` is committed leaves those rows `pending` with a future retry time. The retry
sends the same `doc_key` with replace semantics, so the bank never holds a duplicate; the cost is at
most one repeated extraction, and the day's cap has already been charged for it. A failed send that
certainly delivered nothing is refunded.

Deletion semantics. A record in the trash is hidden at recall time and keeps
its document, so a restore is free; `tombstone_page` does not list it. Permanent deletion,
replacement, exclusion and a switched-off domain delete the document. A document is never deleted
while its row is `submitted`, because a later completion of that operation could bring it back;
the delete waits for the operation to finish or to be declared lost.

No resurrection. A retain can be accepted by the provider without `submitted` ever being committed
(a crash after the request, a failed commit, a timeout, a lost operation, a rebuild that reset the
row). The provider then applies it later, asynchronously, and would recreate a document we deleted.
So a row that is not `retained` and may ever have reached the provider (`retained_at` is set when a
send is reserved and never cleared; `attempts`, `operation_id` and a `failed`/`parked` status are
further evidence) is not dropped when its document is deleted. It stays as a marker
(`parked`/`REMOVED_CATEGORY`) with `next_attempt_at = now + OPERATION_DEADLINE`. When that time has
passed the document is deleted a second time and only then is the row dropped. An excluded row stays
as a marker for good, so that the exclusion is not forgotten; its second delete clears the time.

Pause and kill switch. `MemorySettingsRow.paused`, `SyncPolicy.ingest_enabled` False and an open
circuit breaker stop every new send. Polling, deletes and tombstones still run: privacy moves in one
direction. `SyncPolicy.enabled` False turns the whole pass off.

Privacy of logs. Nothing here logs or raises document text, titles, names or provider bodies. Logs
carry ids, counts and fixed failure categories only; failures are logged by exception type.

Day caps reset at UTC midnight (`now.astimezone(UTC).date()`), not at the owner's local
midnight. The owner zone (`SIDEKICK_OWNER_TIMEZONE`) is passed only to the candidate queries.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sidekick.memory.application.store import LockLost, MemoryStore
from sidekick.memory.application.sync_pass import ReconcilePass
from sidekick.memory.application.sync_state import (
    Breaker,
    PassDeps,
    PassState,
    ReconcileResult,
    SyncPolicy,
)
from sidekick.memory.ports import MemoryProvider
from sidekick.shared.types import Clock, SystemClock, new_uuid7

LOGGER = logging.getLogger("sidekick.memory.sync")


class MemoryReconciler:
    """Runs reconcile passes. Holds only configuration, the provider and the failure breaker."""

    def __init__(
        self,
        store: MemoryStore,
        provider: MemoryProvider,
        policy: SyncPolicy,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._policy = policy
        self._clock: Clock = clock or SystemClock()
        self._breaker = Breaker()

    # -- public API --

    def reconcile_all(self, *, full: bool = False) -> list[ReconcileResult]:
        """One pass per owner that has memory settings or memory rows. One owner's failure never
        stops the others; it is logged by exception type only and returned as a result with
        status "failed", so a caller can tell a failed pass from an empty one."""

        results: list[ReconcileResult] = []
        for owner_id in self.owners():
            try:
                results.append(self.reconcile_owner(owner_id, full=full))
            except Exception as error:
                LOGGER.error(
                    "memory_sync_owner_failed",
                    extra={"error_type": type(error).__name__},
                )
                results.append(
                    ReconcileResult(owner_id=owner_id, correlation_id=_new_cid(), status="failed")
                )
        return results

    def owners(self) -> list[UUID]:
        with self._store.read() as session:
            return sorted(self._store.owner_ids(session))

    def reconcile_owner(
        self,
        owner_id: UUID,
        *,
        full: bool = False,
        correlation_id: str | None = None,
    ) -> ReconcileResult:
        """One pass for one owner. `full` recomputes every fingerprint (the nightly pass)."""

        result = ReconcileResult(owner_id=owner_id, correlation_id=correlation_id or _new_cid())
        if not self._policy.enabled:
            result.status = "disabled"
            self._log(result)
            return result
        lock = self._store.owner_lock(owner_id)
        if not lock.acquire():
            result.status = "locked"
            self._log(result)
            return result
        try:
            deps = PassDeps(self._store, self._provider, self._policy, self._breaker, self._clock)
            state = PassState(owner_id=owner_id, result=result, lock=lock)
            ReconcilePass(deps, state, full=full).run()
        except LockLost:
            result.status = "lock_lost"
        except Exception as error:
            LOGGER.error(
                "memory_sync_failed",
                extra={
                    "correlation_id": result.correlation_id,
                    "error_type": type(error).__name__,
                },
            )
            raise
        finally:
            lock.release()
        self._log(result)
        return result

    # -- internals shared with _Pass --

    def _log(self, result: ReconcileResult) -> None:
        LOGGER.info(
            "memory_sync_pass",
            extra={
                "correlation_id": result.correlation_id,
                "outcome": result.status,
                "queued": result.queued,
                "sent": result.sent,
                "retained": result.retained,
                "failed": result.failed,
                "parked": result.parked,
                "deleted": result.deleted,
                "delete_deferred": result.delete_deferred,
                "delete_failed": result.delete_failed,
                "deferred_by_budget": result.deferred_by_budget,
                "discarded_by_policy": result.discarded_by_policy,
                "sending_blocked": result.sending_blocked,
                "error_categories": dict(result.error_categories),
            },
        )


def _new_cid() -> str:
    return new_uuid7().hex

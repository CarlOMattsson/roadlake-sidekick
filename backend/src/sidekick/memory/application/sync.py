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

import hashlib
import hmac
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sidekick.memory.application.queries import MemoryCandidate
from sidekick.memory.application.records import MemorySourceRecord
from sidekick.memory.application.store import LockLost, MemoryStore, OwnerLockPort
from sidekick.memory.domain import (
    MEMORY_PIPELINE_VERSION,
    MemoryDocument,
    MemoryKind,
    canonical_document,
)
from sidekick.memory.ports import (
    MAX_RETAIN_BATCH,
    MemoryProvider,
    MemoryProviderError,
    RetainItem,
    validate_retain_items,
)
from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE, parse_owner_timezone
from sidekick.shared.errors.core import InternalFaultError
from sidekick.shared.types import Clock, SystemClock, TxSession, new_uuid7

if TYPE_CHECKING:
    from sidekick.shared.config import Settings

LOGGER = logging.getLogger("sidekick.memory.sync")
DEFAULT_OWNER_ZONE = parse_owner_timezone(DEFAULT_OWNER_TIMEZONE)

# Row statuses (CHECK constraint in the 0.1.0 baseline schema).
PENDING = "pending"
SUBMITTED = "submitted"
RETAINED = "retained"
FAILED = "failed"
PARKED = "parked"

#: Marks a `parked` row whose document was deleted because the owner excluded the record.
REMOVED_CATEGORY = "removed"

MAX_ATTEMPTS = 6
BACKOFF_BASE = timedelta(minutes=5)
BACKOFF_CAP = timedelta(hours=6)
#: A submitted operation that is still pending after this long is declared lost and retried.
OPERATION_DEADLINE = timedelta(hours=2)
#: A record last changed longer ago than this is counted against the backfill cap, not the live cap.
BACKFILL_AGE = timedelta(hours=24)
#: Settings default for the characters sent per owner per day (live and backfill together).
DEFAULT_DAILY_CHAR_CAP = 400_000
BREAKER_FAILURES = 3
BREAKER_PAUSE = timedelta(minutes=30)
MAX_POLLED_OPERATIONS = 50
MAX_DELETES_PER_PASS = 500
SCAN_PAGE_SIZE = 100
UNSET_TIMESTAMP = "unset"
DOC_KEY_PREFIX = "d1_"

_DOC_KEY_LABEL = "memory-doc"

#: Failures that say the provider as a whole is unreachable or refusing us, not one document.
_PROVIDER_WIDE: frozenset[str] = frozenset(
    {"unavailable", "timeout", "unauthorized", "rate_limited"}
)
#: Failures after which a retain request certainly delivered nothing, so its budget is refunded.
_NOTHING_SENT: frozenset[str] = frozenset(
    {"unavailable", "unauthorized", "rate_limited", "rejected"}
)

_SETTINGS_FLAG: dict[str, str] = {
    MemoryKind.JOURNAL_ENTRY.value: "journal",
    MemoryKind.CONTACT.value: "contacts",
    MemoryKind.PROJECT.value: "projects",
    MemoryKind.TASK.value: "tasks",
}

PassStatus = Literal["completed", "locked", "disabled", "lock_lost", "failed"]


# --- Pure rules (no database, clock or provider) --------------------------------------------


def derive_doc_key(key: bytes, owner_id: UUID, kind: MemoryKind, source_id: UUID) -> str:
    """Stable, opaque Hindsight document id: HMAC over owner, kind and source id.

    It reveals nothing about the record and matches the adapter's `[A-Za-z0-9_-]{1,200}` rule.
    Changing the key or this schema re-identifies every document and forces a full rebuild.
    """

    if not key:
        raise ValueError("memory id derivation key is required")
    material = "\x1f".join((_DOC_KEY_LABEL, str(owner_id), kind.value, str(source_id)))
    digest = hmac.new(key, material.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{DOC_KEY_PREFIX}{digest}"


def retry_backoff(attempts: int) -> timedelta:
    """Delay after the `attempts`-th failed attempt: 5 min, doubling, capped at 6 h."""

    exponent = max(attempts - 1, 0)
    # Cap the exponent first so a huge attempt count cannot build a huge timedelta.
    return min(BACKOFF_BASE * (2 ** min(exponent, 16)), BACKOFF_CAP)


def is_backfill(source_updated_at: datetime, now: datetime) -> bool:
    return now - source_updated_at >= BACKFILL_AGE


def retain_timestamp(event_date: date | None) -> str:
    if event_date is None:
        return UNSET_TIMESTAMP
    return datetime.combine(event_date, time.min, tzinfo=UTC).isoformat()


def to_retain_item(doc_key: str, document: MemoryDocument) -> RetainItem:
    return RetainItem(
        document_id=doc_key,
        content=document.text,
        timestamp=retain_timestamp(document.event_date),
        entities=document.entities,
        tags=document.tags,
    )


@dataclass(frozen=True, slots=True)
class SendCandidate:
    """A due document that may be sent, with the facts the budget needs."""

    row_id: UUID
    source_updated_at: datetime
    backfill: bool
    item: RetainItem
    fingerprint: str

    @property
    def characters(self) -> int:
        return len(self.item.content)


def select_batch(
    candidates: Sequence[SendCandidate],
    *,
    live_remaining: int,
    backfill_remaining: int,
    limit: int = MAX_RETAIN_BATCH,
    char_cap: int | None = None,
    chars_used: int = 0,
) -> list[SendCandidate]:
    """Newest first, at most `limit`, live and backfill documents each inside their own budget.

    `char_cap` (None means unlimited) bounds the characters sent per day. A document longer than
    what is left waits for the next day. A document longer than the whole cap would wait forever,
    so on a fresh day (`chars_used` 0) the newest such document is sent alone, ahead of the rest.
    A cap of 0 sends nothing.
    """

    ordered = sorted(candidates, key=lambda c: (c.source_updated_at, c.row_id), reverse=True)
    live_left = max(live_remaining, 0)
    backfill_left = max(backfill_remaining, 0)
    chars_left: int | None = None
    if char_cap is not None:
        if char_cap <= 0:
            return []
        chars_left = max(char_cap - chars_used, 0)
        if chars_used == 0:
            for candidate in ordered:
                if candidate.characters > char_cap and (
                    backfill_left > 0 if candidate.backfill else live_left > 0
                ):
                    return [candidate]
    selected: list[SendCandidate] = []
    for candidate in ordered:
        if len(selected) >= limit:
            break
        if chars_left is not None and candidate.characters > chars_left:
            continue
        if candidate.backfill:
            if backfill_left <= 0:
                continue
            backfill_left -= 1
        else:
            if live_left <= 0:
                continue
            live_left -= 1
        if chars_left is not None:
            chars_left -= candidate.characters
        selected.append(candidate)
    return selected


@dataclass(frozen=True, slots=True)
class SyncPolicy:
    """Everything the pass needs from configuration. `id_key` never leaves this process."""

    id_key: bytes
    enabled: bool = True
    ingest_enabled: bool = True
    quiet: timedelta = timedelta(seconds=600)
    daily_retain_cap: int = 40
    backfill_daily_cap: int = 150
    daily_char_cap: int = DEFAULT_DAILY_CHAR_CAP
    owner_timezone: tzinfo = DEFAULT_OWNER_ZONE

    def __post_init__(self) -> None:
        if not self.id_key:
            raise ValueError("memory id derivation key is required")
        if self.quiet < timedelta(0):
            raise ValueError("memory quiet period cannot be negative")
        if self.daily_retain_cap < 0 or self.backfill_daily_cap < 0 or self.daily_char_cap < 0:
            raise ValueError("memory daily caps cannot be negative")

    @classmethod
    def from_settings(cls, settings: Settings) -> SyncPolicy:
        secret = settings.memory_id_derivation_key
        value = secret.get_secret_value() if secret is not None else ""
        if not value.strip():
            raise ValueError("memory id derivation key is required")
        return cls(
            id_key=value.encode("utf-8"),
            enabled=settings.memory_enabled,
            ingest_enabled=settings.memory_ingest_enabled,
            quiet=timedelta(seconds=settings.memory_quiet_seconds),
            daily_retain_cap=settings.memory_daily_retain_cap,
            backfill_daily_cap=settings.memory_backfill_daily_cap,
            daily_char_cap=settings.memory_daily_char_cap,
            owner_timezone=settings.owner_zone,
        )


@dataclass(slots=True)
class ReconcileResult:
    """Counts and fixed categories only. Safe to log and to return."""

    owner_id: UUID
    correlation_id: str
    status: PassStatus = "completed"
    queued: int = 0
    sent: int = 0
    retained: int = 0
    failed: int = 0
    parked: int = 0
    deleted: int = 0
    delete_deferred: int = 0
    delete_failed: int = 0
    deferred_by_budget: int = 0
    #: Rows whose retain returned after the owner paused memory, switched the kind off, excluded
    #: the record or deleted it: not marked submitted (see `_mark_submitted`).
    discarded_by_policy: int = 0
    sending_blocked: bool = False
    error_categories: dict[str, int] = field(default_factory=dict[str, int])

    def note_error(self, category: str) -> None:
        self.error_categories[category] = self.error_categories.get(category, 0) + 1

    @property
    def healthy(self) -> bool:
        """False when the owner's pass failed outright, lost its lock, or met a provider-wide
        failure (unreachable, refusing us). A locked or disabled owner had nothing to do."""

        if self.status in ("failed", "lock_lost"):
            return False
        return not any(category in _PROVIDER_WIDE for category in self.error_categories)


# --- Internal helpers -------------------------------------------------------------------------


class _BudgetRefused(InternalFaultError):
    """The conditional usage upsert refused the reservation (cap would be exceeded)."""


@dataclass(frozen=True, slots=True)
class _Deletion:
    row_id: UUID
    doc_key: str
    status: str
    excluded: bool
    removed: bool
    attempts: int
    operation_id: str | None
    retained_at: datetime | None
    next_attempt_at: datetime | None


def _deletion_of(row: MemorySourceRecord) -> _Deletion:
    return _Deletion(
        row_id=row.id,
        doc_key=row.doc_key,
        status=row.status,
        excluded=row.excluded,
        removed=_is_removed_marker(row),
        attempts=row.attempts,
        operation_id=row.operation_id,
        retained_at=row.retained_at,
        next_attempt_at=row.next_attempt_at,
    )


class _Breaker:
    """Counts consecutive provider-side failures per owner and pauses sending after three."""

    def __init__(self) -> None:
        self._failures: dict[UUID, int] = {}
        self._paused_until: dict[UUID, datetime] = {}

    def is_open(self, owner_id: UUID, now: datetime) -> bool:
        until = self._paused_until.get(owner_id)
        if until is None:
            return False
        if now >= until:
            del self._paused_until[owner_id]
            return False
        return True

    def failure(self, owner_id: UUID, now: datetime) -> None:
        count = self._failures.get(owner_id, 0) + 1
        if count >= BREAKER_FAILURES:
            self._paused_until[owner_id] = now + BREAKER_PAUSE
            count = 0
        self._failures[owner_id] = count

    def success(self, owner_id: UUID) -> None:
        self._failures[owner_id] = 0


class _SendCollector:
    """Keeps the newest due documents of each class so memory stays bounded during a backfill."""

    def __init__(self) -> None:
        self._live: list[SendCandidate] = []
        self._backfill: list[SendCandidate] = []

    def add(self, candidate: SendCandidate) -> None:
        bucket = self._backfill if candidate.backfill else self._live
        bucket.append(candidate)
        bucket.sort(key=lambda c: (c.source_updated_at, c.row_id), reverse=True)
        del bucket[MAX_RETAIN_BATCH:]

    def items(self) -> list[SendCandidate]:
        return [*self._live, *self._backfill]


def _record_failure(row: MemorySourceRecord, category: str, now: datetime) -> str:
    """Move a row to `failed` (with backoff) or `parked`. Returns the new status."""

    row.failure_category = category
    row.operation_id = None
    if category in _PROVIDER_WIDE:
        # The provider as a whole is down or refusing us; that says nothing about this document,
        # so the attempt is given back and the row can never be parked by an outage.
        row.attempts = max(row.attempts - 1, 0)
        row.status = FAILED
        row.next_attempt_at = now + retry_backoff(row.attempts)
        return row.status
    if row.attempts >= MAX_ATTEMPTS:
        row.status = PARKED
        row.next_attempt_at = None
    else:
        row.status = FAILED
        row.next_attempt_at = now + retry_backoff(row.attempts)
    return row.status


def _reset_to_pending(
    row: MemorySourceRecord, document: MemoryDocument, updated_at: datetime
) -> None:
    row.fingerprint = document.fingerprint
    row.pipeline_version = MEMORY_PIPELINE_VERSION
    row.source_updated_at = updated_at
    row.status = PENDING
    row.attempts = 0
    row.next_attempt_at = None
    row.operation_id = None
    row.failure_category = None


def removal_hold_until(
    *,
    status: str,
    attempts: int,
    operation_id: str | None,
    retained_at: datetime | None,
    now: datetime,
) -> datetime | None:
    """When a deleted row must be deleted from the bank a second time, or None for no second pass.

    A `retained` row has no operation in flight. Any other row that may ever have reached the
    provider could still have a retain applied late, so it keeps a marker until the operation
    deadline has passed. See the module docstring, "No resurrection".
    """

    if status == RETAINED:
        return None
    may_have_been_sent = (
        retained_at is not None
        or attempts > 0
        or operation_id is not None
        or status in (FAILED, PARKED, SUBMITTED)
    )
    return now + OPERATION_DEADLINE if may_have_been_sent else None


def _is_due(row: MemorySourceRecord, now: datetime) -> bool:
    return row.status in (PENDING, FAILED) and (
        row.next_attempt_at is None or row.next_attempt_at <= now
    )


# --- The reconciler -------------------------------------------------------------------------


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
        self._breaker = _Breaker()

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
            deps = _Deps(self._store, self._provider, self._policy, self._breaker, self._clock)
            _Pass(deps, owner_id, result, lock, full=full).run()
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


@dataclass(frozen=True, slots=True)
class _Deps:
    store: MemoryStore
    provider: MemoryProvider
    policy: SyncPolicy
    breaker: _Breaker
    clock: Clock


class _Pass:
    """State of one pass for one owner."""

    def __init__(
        self,
        deps: _Deps,
        owner_id: UUID,
        result: ReconcileResult,
        lock: OwnerLockPort,
        *,
        full: bool,
    ) -> None:
        self._clock = deps.clock
        self._store = deps.store
        self._provider = deps.provider
        self._policy = deps.policy
        self._breaker = deps.breaker
        self._owner = owner_id
        self._result = result
        self._lock = lock
        self._full = full
        self._provider_down = False
        self._deletes_left = MAX_DELETES_PER_PASS
        self._collector = _SendCollector()
        self._may_send = False

    def _now(self) -> datetime:
        return self._clock.now()

    # -- driver --

    def run(self) -> None:
        now = self._now()
        paused = self._load_paused()
        self._may_send = (
            self._policy.ingest_enabled
            and not paused
            and not self._breaker.is_open(self._owner, now)
        )
        self._result.sending_blocked = not self._may_send
        self._poll_operations()
        self._delete_tombstones()
        self._scan()
        if self._may_send and not self._provider_down:
            self._send_batch()

    def _load_paused(self) -> bool:
        with self._store.read() as session:
            settings = self._store.settings(session, self._owner)
            return settings is None or settings.paused

    # -- 1. polling --

    def _poll_operations(self) -> None:
        with self._store.read() as session:
            rows = self._store.submitted_operations(session, self._owner)
        deadlines: dict[str, datetime | None] = {}
        for operation_id, deadline in rows:
            if operation_id is not None and deadlines.get(operation_id) is None:
                deadlines[operation_id] = deadline
        for operation_id in list(deadlines)[:MAX_POLLED_OPERATIONS]:
            if self._provider_down:
                break
            self._poll_one(operation_id, deadlines[operation_id])

    def _poll_one(self, operation_id: str, deadline: datetime | None) -> None:
        self._lock.assert_alive()
        try:
            outcome = self._provider.operation_status(
                owner_id=self._owner, operation_id=operation_id
            )
        except ValueError:
            # A stored operation id the provider port refuses can never be polled.
            self._finish_operation(operation_id, failed="operation_lost")
            return
        except MemoryProviderError as error:
            category = error.category
            self._result.note_error(category)
            if category in _PROVIDER_WIDE:
                self._provider_down = True
            if deadline is not None and self._now() >= deadline:
                self._finish_operation(operation_id, failed="operation_lost")
            return
        if outcome.state == "retained":
            self._finish_operation(operation_id, failed=None)
        elif outcome.state == "failed":
            self._finish_operation(
                operation_id, failed=outcome.failure_category or "operation_failed"
            )
        elif deadline is not None and self._now() >= deadline:
            self._finish_operation(operation_id, failed="operation_lost")

    def _finish_operation(self, operation_id: str, *, failed: str | None) -> None:
        now = self._now()
        with self._store.begin() as session:
            rows = self._store.submitted_rows_for_update(session, self._owner, operation_id)
            for row in rows:
                if failed is None:
                    row.status = RETAINED
                    row.retained_at = now
                    row.operation_id = None
                    row.attempts = 0
                    row.next_attempt_at = None
                    row.failure_category = None
                    self._result.retained += 1
                else:
                    if _record_failure(row, failed, now) == PARKED:
                        self._result.parked += 1
                    else:
                        self._result.failed += 1
        if not rows:
            return
        if failed is None:
            self._breaker.success(self._owner)
        else:
            self._result.note_error(failed)
            self._breaker.failure(self._owner, now)
            if self._breaker.is_open(self._owner, now):
                self._may_send = False
                self._result.sending_blocked = True

    # -- 2. tombstones --

    def _delete_tombstones(self) -> None:
        for kind in MemoryKind:
            after: UUID | None = None
            while self._deletes_left > 0 and not self._provider_down:
                with self._store.read() as session:
                    page = self._store.tombstone_page(
                        session,
                        self._owner,
                        kind,
                        after=after,
                        limit=SCAN_PAGE_SIZE,
                    )
                    rows = (
                        self._store.source_rows_by_id(
                            session, self._owner, [t.memory_source_id for t in page]
                        )
                        if page
                        else {}
                    )
                if not page:
                    break
                after = page[-1].memory_source_id
                deletions = [
                    _deletion_of(rows[t.memory_source_id])
                    for t in page
                    if t.memory_source_id in rows
                ]
                self._run_deletions(deletions)
                if len(page) < SCAN_PAGE_SIZE:
                    break

    def _run_deletions(self, deletions: Sequence[_Deletion]) -> None:
        for deletion in deletions:
            now = self._now()
            hold_until: datetime | None = None
            if deletion.removed:
                if deletion.next_attempt_at is None and deletion.excluded:
                    continue  # Document gone for good; the row is only the exclusion marker.
                if deletion.next_attempt_at is not None and deletion.next_attempt_at > now:
                    self._result.delete_deferred += 1  # Second delete not yet due.
                    continue
                # Due: this delete is the second one, and the last.
            elif deletion.status == SUBMITTED:
                self._result.delete_deferred += 1
                continue
            else:
                hold_until = removal_hold_until(
                    status=deletion.status,
                    attempts=deletion.attempts,
                    operation_id=deletion.operation_id,
                    retained_at=deletion.retained_at,
                    now=now,
                )
            if self._deletes_left <= 0 or self._provider_down:
                return
            self._deletes_left -= 1
            self._lock.assert_alive()
            try:
                self._provider.delete_document(owner_id=self._owner, document_id=deletion.doc_key)
            except MemoryProviderError as error:
                category = error.category
                self._result.delete_failed += 1
                self._result.note_error(category)
                if category in _PROVIDER_WIDE:
                    self._provider_down = True
                continue
            self._finish_deletion(deletion, hold_until)

    def _finish_deletion(self, deletion: _Deletion, hold_until: datetime | None) -> None:
        with self._store.begin() as session:
            self._store.settle_removed_row(
                session,
                row_id=deletion.row_id,
                doc_key=deletion.doc_key,
                excluded=deletion.excluded,
                hold_until=hold_until,
            )
        self._result.deleted += 1

    # -- 3. scan --

    def _scan(self) -> None:
        for kind in MemoryKind:
            after: UUID | None = None
            while True:
                deletions: list[_Deletion] = []
                with self._store.begin() as session:
                    page = self._store.candidate_page(
                        session,
                        self._owner,
                        kind,
                        owner_timezone=self._policy.owner_timezone,
                        after=after,
                        limit=SCAN_PAGE_SIZE,
                    )
                    if not page:
                        break
                    existing = self._store.source_rows_by_record(
                        session, self._owner, kind, [c.source_id for c in page]
                    )
                    now = self._now()
                    for candidate in page:
                        row = existing.get(candidate.source_id)
                        if row is not None and _second_delete_pending(row):
                            # The record may be live again, but the marker must finish its second
                            # delete first, or a late retain of the old document would linger.
                            deletions.append(_deletion_of(row))
                            continue
                        if not candidate.is_candidate:
                            if row is not None:
                                deletions.append(_deletion_of(row))
                            continue
                        self._reconcile_record(session, kind, candidate, row, now)
                after = page[-1].source_id
                self._run_deletions(deletions)
                if len(page) < SCAN_PAGE_SIZE:
                    break

    def _reconcile_record(
        self,
        session: TxSession,
        kind: MemoryKind,
        candidate: MemoryCandidate,
        row: MemorySourceRecord | None,
        now: datetime,
    ) -> None:
        # A record changed inside the quiet period waits, so one exchange is sent once.
        if candidate.source_updated_at > now - self._policy.quiet:
            return
        if row is not None and row.status == SUBMITTED:
            return  # Wait for the operation; a change is picked up after it completes.
        if row is None:
            document = canonical_document(candidate.record)
            if document is None:
                return
            row = self._store.add_source(
                session,
                owner_id=self._owner,
                kind=kind,
                source_id=candidate.source_id,
                doc_key=derive_doc_key(self._policy.id_key, self._owner, kind, candidate.source_id),
                fingerprint=document.fingerprint,
                pipeline_version=MEMORY_PIPELINE_VERSION,
                status=PENDING,
                source_updated_at=candidate.source_updated_at,
            )
            self._result.queued += 1
        else:
            removed = _is_removed_marker(row)
            stale = row.pipeline_version != MEMORY_PIPELINE_VERSION
            changed = candidate.source_updated_at > row.source_updated_at
            if not (self._full or changed or stale or removed or _is_due(row, now)):
                return
            document = canonical_document(candidate.record)
            if document is None:
                return
            if document.fingerprint != row.fingerprint or stale or removed:
                _reset_to_pending(row, document, candidate.source_updated_at)
                self._result.queued += 1
            elif changed:
                row.source_updated_at = candidate.source_updated_at
        if self._may_send and _is_due(row, now):
            self._collector.add(
                SendCandidate(
                    row_id=row.id,
                    source_updated_at=candidate.source_updated_at,
                    backfill=is_backfill(candidate.source_updated_at, now),
                    item=to_retain_item(row.doc_key, document),
                    fingerprint=row.fingerprint,
                )
            )

    # -- 4. send --

    def _send_batch(self) -> None:
        collected = self._collector.items()
        if not collected:
            return
        now = self._now()
        day = now.astimezone(UTC).date()
        with self._store.read() as session:
            usage = self._store.daily_usage(session, self._owner, day)
        selected = select_batch(
            collected,
            live_remaining=self._policy.daily_retain_cap - usage.live,
            backfill_remaining=self._policy.backfill_daily_cap - usage.backfill,
            char_cap=self._policy.daily_char_cap,
            chars_used=usage.characters,
        )
        self._result.deferred_by_budget = len(collected) - len(selected)
        if not selected:
            return
        reserved = self._reserve(selected, day)
        if reserved is None:
            return
        self._lock.assert_alive()
        self._send_group(reserved, day)

    def _reserve(self, selected: list[SendCandidate], day: date) -> list[SendCandidate] | None:
        """One transaction: re-check settings, count the batch against the caps, bump attempts."""

        now = self._now()
        accepted: list[SendCandidate] = []
        try:
            with self._store.begin() as session:
                settings = self._store.settings(session, self._owner)
                if settings is None or settings.paused:
                    return None
                rows = self._store.source_rows_for_update(
                    session, self._owner, [c.row_id for c in selected]
                )
                for candidate in selected:
                    row = rows.get(candidate.row_id)
                    if (
                        row is None
                        or row.excluded
                        or row.fingerprint != candidate.fingerprint
                        or not _is_due(row, now)
                        or not getattr(settings, _SETTINGS_FLAG[row.source_kind])
                    ):
                        continue
                    row.attempts += 1
                    # Until `submitted` is committed, a crash leaves the row due again later.
                    row.next_attempt_at = now + retry_backoff(row.attempts)
                    try:
                        validate_retain_items([candidate.item])
                    except ValueError:
                        if _record_failure(row, "rejected", now) == PARKED:
                            self._result.parked += 1
                        else:
                            self._result.failed += 1
                        self._result.note_error("rejected")
                        continue
                    if row.retained_at is None:
                        # Evidence that a retain may reach the bank late, even if this attempt
                        # is never committed as `submitted`. Deletion relies on it.
                        row.retained_at = now
                    accepted.append(candidate)
                if not accepted:
                    return None
                self._charge(session, accepted, day)
        except _BudgetRefused:
            self._result.deferred_by_budget += len(selected)
            return None
        return accepted

    def _charge(self, session: TxSession, items: Sequence[SendCandidate], day: date) -> None:
        """Count documents against today's caps. The upsert refuses atomically past a cap."""

        live = sum(1 for c in items if not c.backfill)
        backfill = sum(1 for c in items if c.backfill)
        characters = sum(c.characters for c in items)
        char_cap = self._policy.daily_char_cap
        if live > self._policy.daily_retain_cap or backfill > self._policy.backfill_daily_cap:
            raise _BudgetRefused
        if char_cap <= 0 or (characters > char_cap and len(items) > 1):
            raise _BudgetRefused
        # A single document longer than the whole cap is only allowed on a day with nothing sent.
        charged = self._store.charge_usage(
            session,
            self._owner,
            day,
            live=live,
            backfill=backfill,
            characters=characters,
            live_cap=self._policy.daily_retain_cap,
            backfill_cap=self._policy.backfill_daily_cap,
            char_cap=char_cap,
            single_document=len(items) == 1,
        )
        if not charged:
            raise _BudgetRefused

    def _refund(self, session: TxSession, items: Sequence[SendCandidate], day: date) -> None:
        self._store.refund_usage(
            session,
            self._owner,
            day,
            live=sum(1 for c in items if not c.backfill),
            backfill=sum(1 for c in items if c.backfill),
            characters=sum(c.characters for c in items),
        )

    def _send_group(self, items: list[SendCandidate], day: date) -> None:
        """Send one request. A rejected multi-document batch is retried one document at a time,
        inside the same attempt, so a single bad document cannot park its neighbours."""

        if self._provider_down:
            self._release_unsent(items, day)
            return
        self._lock.assert_alive()
        try:
            operation_id = self._provider.retain_batch(
                owner_id=self._owner, items=[c.item for c in items]
            )
        except MemoryProviderError as error:
            if error.category == "rejected" and len(items) > 1:
                for item in items:
                    self._send_group([item], day)
                return
            self._fail_send(items, error.category, day)
            return
        self._mark_submitted(items, operation_id)

    def _release_unsent(self, items: Sequence[SendCandidate], day: date) -> None:
        """Give back the attempt and the budget of documents that were never offered."""

        with self._store.begin() as session:
            for row in self._store.source_rows_for_update(
                session, self._owner, [c.row_id for c in items]
            ).values():
                if row.status in (PENDING, FAILED):
                    row.attempts = max(row.attempts - 1, 0)
                    row.next_attempt_at = None
            self._refund(session, items, day)

    def _still_allowed(self, items: Sequence[SendCandidate]) -> frozenset[UUID]:
        """Row ids whose retain the owner's policy still permits, read after the provider call.

        The retain may have been slow. If the owner paused memory, switched the kind off, excluded
        the record or deleted it meanwhile, the row must not be recorded as synced.
        """

        with self._store.read() as session:
            settings = self._store.settings(session, self._owner)
            if settings is None or settings.paused:
                return frozenset()
            flags = self._store.source_flags(session, self._owner, [c.row_id for c in items])
        return frozenset(
            flag.row_id
            for flag in flags
            if not flag.excluded and getattr(settings, _SETTINGS_FLAG[flag.source_kind])
        )

    def _mark_submitted(self, items: Sequence[SendCandidate], operation_id: str) -> None:
        """Record the accepted retain as submitted, unless the policy changed during the call.

        A discarded row keeps `retained_at` (set when the send was reserved), so the no-resurrection
        rule still deletes its document twice if the record has been removed or excluded; if the
        owner only paused or switched the kind off, the row stays due and is sent again later.
        """

        allowed = self._still_allowed(items)
        kept = [c for c in items if c.row_id in allowed]
        self._result.discarded_by_policy += len(items) - len(kept)
        if not kept:
            return
        items = kept
        now = self._now()
        with self._store.begin() as session:
            self._store.mark_submitted(
                session,
                [c.row_id for c in items],
                operation_id=operation_id,
                deadline=now + OPERATION_DEADLINE,
            )
        self._result.sent += len(items)

    def _fail_send(self, items: Sequence[SendCandidate], category: str, day: date) -> None:
        now = self._now()
        self._result.note_error(category)
        with self._store.begin() as session:
            for row in self._store.source_rows_for_update(
                session, self._owner, [c.row_id for c in items]
            ).values():
                if row.status in (PENDING, FAILED):
                    if _record_failure(row, category, now) == PARKED:
                        self._result.parked += 1
                    else:
                        self._result.failed += 1
            if category in _NOTHING_SENT:
                self._refund(session, items, day)
        if category in _PROVIDER_WIDE:
            self._provider_down = True
        if category != "rejected":
            self._breaker.failure(self._owner, now)
            if self._breaker.is_open(self._owner, now):
                self._result.sending_blocked = True


# --- Small shared bits ----------------------------------------------------------------------


def _is_removed_marker(row: MemorySourceRecord) -> bool:
    return row.status == PARKED and row.failure_category == REMOVED_CATEGORY


def _second_delete_pending(row: MemorySourceRecord) -> bool:
    """A marker that still owes the provider a second delete (it holds the due time)."""

    return _is_removed_marker(row) and row.next_attempt_at is not None

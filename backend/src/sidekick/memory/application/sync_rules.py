"""Pure rules of the memory reconcile pass: row states, caps, backoff, batch selection.

No database, clock or provider is touched here. The pass itself is described in
`sidekick.memory.application.sync`.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sidekick.memory.application.records import MemorySourceRecord
from sidekick.memory.domain import MEMORY_PIPELINE_VERSION, MemoryDocument, MemoryKind
from sidekick.memory.ports import MAX_RETAIN_BATCH, RetainItem

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
PROVIDER_WIDE: frozenset[str] = frozenset(
    {"unavailable", "timeout", "unauthorized", "rate_limited"}
)
#: Failures after which a retain request certainly delivered nothing, so its budget is refunded.
NOTHING_SENT: frozenset[str] = frozenset(
    {"unavailable", "unauthorized", "rate_limited", "rejected"}
)

SETTINGS_FLAG: dict[str, str] = {
    MemoryKind.JOURNAL_ENTRY.value: "journal",
    MemoryKind.CONTACT.value: "contacts",
    MemoryKind.PROJECT.value: "projects",
    MemoryKind.TASK.value: "tasks",
}


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


def record_failure(row: MemorySourceRecord, category: str, now: datetime) -> str:
    """Move a row to `failed` (with backoff) or `parked`. Returns the new status."""

    row.failure_category = category
    row.operation_id = None
    if category in PROVIDER_WIDE:
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


def reset_to_pending(
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


def is_due(row: MemorySourceRecord, now: datetime) -> bool:
    return row.status in (PENDING, FAILED) and (
        row.next_attempt_at is None or row.next_attempt_at <= now
    )


def is_removed_marker(row: MemorySourceRecord) -> bool:
    return row.status == PARKED and row.failure_category == REMOVED_CATEGORY


def second_delete_pending(row: MemorySourceRecord) -> bool:
    """A marker that still owes the provider a second delete (it holds the due time)."""

    return is_removed_marker(row) and row.next_attempt_at is not None

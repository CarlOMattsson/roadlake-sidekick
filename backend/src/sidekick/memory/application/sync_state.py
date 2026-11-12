"""Configuration, results and shared state of one reconcile pass."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sidekick.memory.application.records import MemorySourceRecord
from sidekick.memory.application.store import MemoryStore, OwnerLockPort
from sidekick.memory.application.sync_rules import (
    BREAKER_FAILURES,
    BREAKER_PAUSE,
    DEFAULT_DAILY_CHAR_CAP,
    PROVIDER_WIDE,
    SendCandidate,
    is_removed_marker,
)
from sidekick.memory.ports import MAX_RETAIN_BATCH, MemoryProvider
from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE, parse_owner_timezone
from sidekick.shared.errors.core import InternalFaultError
from sidekick.shared.types import Clock

if TYPE_CHECKING:
    from sidekick.shared.config import Settings

DEFAULT_OWNER_ZONE = parse_owner_timezone(DEFAULT_OWNER_TIMEZONE)

PassStatus = Literal["completed", "locked", "disabled", "lock_lost", "failed"]


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
        return not any(category in PROVIDER_WIDE for category in self.error_categories)


class BudgetRefused(InternalFaultError):
    """The conditional usage upsert refused the reservation (cap would be exceeded)."""


@dataclass(frozen=True, slots=True)
class Deletion:
    row_id: UUID
    doc_key: str
    status: str
    excluded: bool
    removed: bool
    attempts: int
    operation_id: str | None
    retained_at: datetime | None
    next_attempt_at: datetime | None


def deletion_of(row: MemorySourceRecord) -> Deletion:
    return Deletion(
        row_id=row.id,
        doc_key=row.doc_key,
        status=row.status,
        excluded=row.excluded,
        removed=is_removed_marker(row),
        attempts=row.attempts,
        operation_id=row.operation_id,
        retained_at=row.retained_at,
        next_attempt_at=row.next_attempt_at,
    )


class Breaker:
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


class SendCollector:
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


@dataclass(frozen=True, slots=True)
class PassDeps:
    store: MemoryStore
    provider: MemoryProvider
    policy: SyncPolicy
    breaker: Breaker
    clock: Clock


@dataclass(slots=True)
class PassState:
    """What the phases of one pass share and change: the result, the lock and the send gates."""

    owner_id: UUID
    result: ReconcileResult
    lock: OwnerLockPort
    provider_down: bool = False
    may_send: bool = False

"""Visible push reminders (ADR-005; D-078, push through UnifiedPush, with quiet hours).

`ReminderScheduler` runs inside the push worker. For each owner with an active subscription it
creates, in the owner's zone (D-063: owner timezone setting) and by the rules in `push_schedule`:

- the morning **summary**: "N idag · M försenade" counted by `WorkListService.work_today_page`, the
  agenda's own selection, once per day;
- a **due** reminder for each open Task whose `due_at` carries a clock time, shortly before it;
  a moved `due_at` is a new reminder, a completed, trashed or archived Task gets none.

A reminder is a `push_reminders` row (its content: counts, a title snapshot, times) plus one `r`
row per active subscription in `push_outbox`, written in one transaction, so the push worker sends
`{"k":"r"}` after the commit. The outbox and the push never carry the content; the phone fetches it
with `ReminderService.pending` and acknowledges what it showed with `ack`.

`ReminderService` also queues the device's own test notification, at most five an hour per device.
Nothing here logs a title: logs carry counts and closed kinds only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sidekick.companion.push_reminder_models import (
    DueTask,
    NewReminder,
    PendingReminders,
)
from sidekick.companion.push_schedule import ReminderPolicy
from sidekick.shared.config import Settings
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale, LocalizedText, localized
from sidekick.shared.observability import log_failure, safe_log_fields
from sidekick.shared.types import Actor, CursorCodec, utc_now
from sidekick.work.application.store import ContextStore
from sidekick.work.application.work_lists import WorkListService

LOGGER = logging.getLogger("sidekick.companion.push_reminders")

TEST_TITLES: LocalizedText = {
    "sv": "Testnotis från Sidekick",
    "en": "Test notification from Sidekick",
}
TESTS_PER_HOUR = 5
# A reminder nobody fetched within a day is stale; a phone that was offline does not wake up to it.
PENDING_MAX_AGE = timedelta(hours=24)
MAX_PENDING_ITEMS = 20
MAX_ACK_IDS = 50
# Candidates for a due reminder are looked up this far back: the quiet hours move a reminder by at
# most a day, plus the window in which it stays eligible.
DUE_LOOKBACK = timedelta(days=2)
# The scheduler only needs the agenda's counts and open Tasks: it holds exactly these scopes.
_SCHEDULER_SCOPES = frozenset({"tasks:read", "projects:read"})


class ReminderStore(Protocol):
    def subscribed_owners(self) -> list[UUID]: ...

    def reminder_exists(self, user_id: UUID, dedup_key: str) -> bool: ...

    def due_tasks(
        self, user_id: UUID, now: datetime, *, lookback: timedelta, lead: timedelta
    ) -> Sequence[DueTask]: ...

    def create_reminder(self, user_id: UUID, reminder: NewReminder, now: datetime) -> bool: ...

    def pending(
        self, user_id: UUID, now: datetime, *, max_age: timedelta, limit: int
    ) -> PendingReminders: ...

    def acknowledge(self, user_id: UUID, ids: Sequence[UUID], now: datetime) -> int: ...

    def queue_test(
        self,
        user_id: UUID,
        device_id: UUID,
        *,
        title: str,
        now: datetime,
        per_hour: int,
        correlation_id: str | None,
    ) -> None: ...


class _ClockAdapter:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    def now(self) -> datetime:
        return self._clock()


def reminder_policy(settings: Settings) -> ReminderPolicy:
    return ReminderPolicy(
        zone=settings.owner_zone,
        summary_time=settings.push_summary_time,
        due_lead=timedelta(minutes=settings.push_due_lead_minutes),
        quiet_start=settings.push_quiet_start,
        quiet_end=settings.push_quiet_end,
    )


class ReminderScheduler:
    def __init__(
        self,
        store: ReminderStore,
        policy: ReminderPolicy,
        work_lists: WorkListService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._policy = policy
        self._work_lists = work_lists
        self._clock = clock

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        store: ReminderStore,
        work_store: ContextStore,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> ReminderScheduler:
        work_lists = WorkListService(
            work_store,
            _ClockAdapter(clock),
            CursorCodec(settings.cursor_signing_key),
            owner_timezone=settings.owner_zone,
        )
        return cls(store, reminder_policy(settings), work_lists, clock=clock)

    def run_once(self) -> int:
        """Queue every reminder that is due now; returns how many were created."""

        now = self._clock()
        created = 0
        for user_id in self._store.subscribed_owners():
            try:
                created += self._queue_summary(user_id, now) + self._queue_due(user_id, now)
            except Exception as error:
                # One owner's failure must not stop the others; the next run tries again.
                log_failure(LOGGER, "push reminder scheduling failed", error)
        if created:
            LOGGER.info("push_reminders_queued", extra=safe_log_fields({"push_reminders": created}))
        return created

    def _queue_summary(self, user_id: UUID, now: datetime) -> int:
        day = self._policy.summary_day(now)
        if day is None:
            return 0
        key = f"s:{day.isoformat()}"
        if self._store.reminder_exists(user_id, key):
            return 0
        today = self._work_lists.work_today_page(Actor(user_id, _SCHEDULER_SCOPES), limit=1)
        if today.total == 0:
            return 0
        return self._insert(
            user_id,
            NewReminder(
                kind="summary",
                dedup_key=key,
                summary_today=today.today_total,
                summary_overdue=today.overdue_total,
                scheduled_for=now,
            ),
            now,
        )

    def _queue_due(self, user_id: UUID, now: datetime) -> int:
        candidates = self._store.due_tasks(
            user_id, now, lookback=DUE_LOOKBACK, lead=self._policy.due_lead
        )
        created = 0
        for task in candidates:
            moment = self._policy.due_reminder_time(task.due_at)
            if moment is None or not self._policy.due_reminder_is_due(
                task.due_at, now, task.created_at
            ):
                continue
            created += self._insert(
                user_id,
                NewReminder(
                    kind="due",
                    task_id=task.id,
                    dedup_key=f"d:{task.id}:{int(task.due_at.timestamp())}",
                    payload_title=task.title[:200],
                    due_at=task.due_at,
                    scheduled_for=moment,
                ),
                now,
            )
        return created

    def _insert(self, user_id: UUID, reminder: NewReminder, now: datetime) -> int:
        """Create the reminder unless its dedup key exists, and queue its `r` pushes."""

        return int(self._store.create_reminder(user_id, reminder, now))


class ReminderService:
    """What the phone does with reminders: fetch what is pending, acknowledge, test."""

    def __init__(
        self,
        store: ReminderStore,
        clock: Callable[[], datetime] = utc_now,
        locale: AppLocale = DEFAULT_LOCALE,
    ) -> None:
        self._store = store
        self._clock = clock
        self._locale: AppLocale = locale

    def pending(self, user_id: UUID) -> PendingReminders:
        """The owner's reminders not yet acknowledged, newest day's summary and at most
        `MAX_PENDING_ITEMS` others, none older than `PENDING_MAX_AGE`. A due reminder drops out
        when its Task was completed, trashed, archived, lost a live parent (its Project, Process or
        Domain was trashed) or was given another `due_at` meanwhile."""

        return self._store.pending(
            user_id, self._clock(), max_age=PENDING_MAX_AGE, limit=MAX_PENDING_ITEMS
        )

    def ack(self, user_id: UUID, ids: Iterable[UUID]) -> int:
        """Mark the owner's own reminders shown. Idempotent: unknown, foreign and already
        acknowledged ids change nothing. Returns how many were newly acknowledged."""

        wanted = list(dict.fromkeys(ids))[:MAX_ACK_IDS]
        if not wanted:
            return 0
        return self._store.acknowledge(user_id, wanted, self._clock())

    def queue_test(
        self, user_id: UUID, device_id: UUID, *, correlation_id: str | None = None
    ) -> None:
        """Queue the visible test notification and an `r` push to this device's subscription.
        Raises `PushTestRateLimited` after five in an hour, `NoActiveSubscription` without one."""

        self._store.queue_test(
            user_id,
            device_id,
            title=localized(TEST_TITLES, self._locale),
            now=self._clock(),
            per_hour=TESTS_PER_HOUR,
            correlation_id=correlation_id,
        )

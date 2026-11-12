"""Visible push reminders (ADR-005; D-078, push through UnifiedPush, with quiet hours).

`ReminderScheduler` runs inside the push worker. For each owner with an active subscription it
creates, in the owner's zone (D-063) and by the rules in `push_schedule`:

- the morning **summary**: "N idag · M försenade" counted by `ContextService.work_today_page`, the
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
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from sidekick.companion.push import record_device_event
from sidekick.companion.push_outbox import enqueue_reminder_push
from sidekick.companion.push_schedule import ReminderPolicy
from sidekick.shared.config import Settings
from sidekick.shared.errors.core import NotFoundError, RateLimitedError
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale, LocalizedText, localized
from sidekick.shared.observability import log_failure, safe_log_fields
from sidekick.shared.persistence.models import PushReminderRow, PushSubscriptionRow, TaskRow
from sidekick.shared.persistence.stores.task_parents import task_parents_live
from sidekick.shared.types import Actor, CursorCodec, new_uuid7, utc_now
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.domain import TaskStatus
from sidekick.work.application.service import ContextService

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


class PushTestRateLimited(RateLimitedError):
    """The device already queued `TESTS_PER_HOUR` test notifications in the last hour."""


class NoActiveSubscription(NotFoundError):
    """The device has no active push subscription to send a test to."""


@dataclass(frozen=True, slots=True)
class NewReminder:
    kind: str
    dedup_key: str
    scheduled_for: datetime
    task_id: UUID | None = None
    payload_title: str | None = None
    summary_today: int | None = None
    summary_overdue: int | None = None
    due_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PendingItem:
    id: UUID
    kind: str
    title: str
    task_id: UUID | None
    due_at: datetime | None


@dataclass(frozen=True, slots=True)
class PendingSummary:
    id: UUID
    today: int
    overdue: int


@dataclass(frozen=True, slots=True)
class PendingReminders:
    items: tuple[PendingItem, ...]
    summary: PendingSummary | None


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
        session_factory: sessionmaker[Session],
        policy: ReminderPolicy,
        contexts: ContextService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy
        self._contexts = contexts
        self._clock = clock

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> ReminderScheduler:
        contexts = ContextService(
            SqlAlchemyStore(session_factory),
            _ClockAdapter(clock),
            CursorCodec(settings.cursor_signing_key),
            owner_timezone=settings.owner_zone,
        )
        return cls(session_factory, reminder_policy(settings), contexts, clock=clock)

    def run_once(self) -> int:
        """Queue every reminder that is due now; returns how many were created."""

        now = self._clock()
        created = 0
        for user_id in self._owners():
            try:
                created += self._queue_summary(user_id, now) + self._queue_due(user_id, now)
            except Exception as error:
                # One owner's failure must not stop the others; the next run tries again.
                log_failure(LOGGER, "push reminder scheduling failed", error)
        if created:
            LOGGER.info("push_reminders_queued", extra=safe_log_fields({"push_reminders": created}))
        return created

    def _owners(self) -> list[UUID]:
        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(PushSubscriptionRow.user_id)
                    .where(PushSubscriptionRow.revoked_at.is_(None))
                    .distinct()
                )
            )

    def _queue_summary(self, user_id: UUID, now: datetime) -> int:
        day = self._policy.summary_day(now)
        if day is None:
            return 0
        key = f"s:{day.isoformat()}"
        with self._session_factory() as session:
            if _exists(session, user_id, key):
                return 0
        today = self._contexts.work_today_page(Actor(user_id, _SCHEDULER_SCOPES), limit=1)
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
        with self._session_factory() as session:
            candidates = session.execute(
                select(TaskRow.id, TaskRow.title, TaskRow.due_at, TaskRow.created_at).where(
                    TaskRow.owner_id == user_id,
                    TaskRow.status != TaskStatus.COMPLETED.value,
                    TaskRow.trashed_at.is_(None),
                    TaskRow.archived_at.is_(None),
                    task_parents_live(),
                    or_(TaskRow.not_before.is_(None), TaskRow.not_before <= now),
                    TaskRow.due_at.is_not(None),
                    TaskRow.due_at >= now - DUE_LOOKBACK,
                    TaskRow.due_at <= now + self._policy.due_lead,
                )
            ).all()
        created = 0
        for task_id, title, due_at, created_at in candidates:
            moment = self._policy.due_reminder_time(due_at)
            if moment is None or not self._policy.due_reminder_is_due(due_at, now, created_at):
                continue
            created += self._insert(
                user_id,
                NewReminder(
                    kind="due",
                    task_id=task_id,
                    dedup_key=f"d:{task_id}:{int(due_at.timestamp())}",
                    payload_title=title[:200],
                    due_at=due_at,
                    scheduled_for=moment,
                ),
                now,
            )
        return created

    def _insert(self, user_id: UUID, reminder: NewReminder, now: datetime) -> int:
        """Create the reminder unless its dedup key exists, and queue its `r` pushes."""

        reminder_id = new_uuid7()
        with self._session_factory.begin() as session:
            created = session.scalar(
                insert(PushReminderRow)
                .values(
                    id=reminder_id,
                    user_id=user_id,
                    kind=reminder.kind,
                    task_id=reminder.task_id,
                    dedup_key=reminder.dedup_key,
                    payload_title=reminder.payload_title,
                    summary_today=reminder.summary_today,
                    summary_overdue=reminder.summary_overdue,
                    due_at=reminder.due_at,
                    scheduled_for=reminder.scheduled_for,
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=["user_id", "dedup_key"])
                .returning(PushReminderRow.id)
            )
            if created is None:
                return 0
            enqueue_reminder_push(session, user_id, created, now=now)
        return 1


def _exists(session: Session, user_id: UUID, dedup_key: str) -> bool:
    return (
        session.scalar(
            select(PushReminderRow.id).where(
                PushReminderRow.user_id == user_id, PushReminderRow.dedup_key == dedup_key
            )
        )
        is not None
    )


class ReminderService:
    """What the phone does with reminders: fetch what is pending, acknowledge, test."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: Callable[[], datetime] = utc_now,
        locale: AppLocale = DEFAULT_LOCALE,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._locale: AppLocale = locale

    def pending(self, user_id: UUID) -> PendingReminders:
        """The owner's reminders not yet acknowledged, newest day's summary and at most
        `MAX_PENDING_ITEMS` others, none older than `PENDING_MAX_AGE`. A due reminder drops out
        when its Task was completed, trashed, archived, lost a live parent (its Project, Process or
        Domain was trashed) or was given another `due_at` meanwhile."""

        now = self._clock()
        fresh = and_(
            PushReminderRow.user_id == user_id,
            PushReminderRow.acked_at.is_(None),
            PushReminderRow.scheduled_for >= now - PENDING_MAX_AGE,
        )
        task_is_current = and_(
            TaskRow.status != TaskStatus.COMPLETED.value,
            TaskRow.trashed_at.is_(None),
            TaskRow.archived_at.is_(None),
            task_parents_live(),
            TaskRow.due_at == PushReminderRow.due_at,
        )
        with self._session_factory() as session:
            rows = list(
                session.scalars(
                    select(PushReminderRow)
                    .outerjoin(TaskRow, TaskRow.id == PushReminderRow.task_id)
                    .where(
                        fresh,
                        PushReminderRow.kind != "summary",
                        or_(PushReminderRow.kind != "due", task_is_current),
                    )
                    .order_by(PushReminderRow.scheduled_for.desc(), PushReminderRow.id.desc())
                    .limit(MAX_PENDING_ITEMS)
                )
            )
            summary = session.scalar(
                select(PushReminderRow)
                .where(fresh, PushReminderRow.kind == "summary")
                .order_by(PushReminderRow.scheduled_for.desc(), PushReminderRow.id.desc())
                .limit(1)
            )
        rows.reverse()
        return PendingReminders(
            items=tuple(
                PendingItem(
                    row.id,
                    row.kind,
                    row.payload_title or "",
                    row.task_id,
                    row.due_at,
                )
                for row in rows
            ),
            summary=(
                PendingSummary(summary.id, summary.summary_today or 0, summary.summary_overdue or 0)
                if summary is not None
                else None
            ),
        )

    def ack(self, user_id: UUID, ids: Iterable[UUID]) -> int:
        """Mark the owner's own reminders shown. Idempotent: unknown, foreign and already
        acknowledged ids change nothing. Returns how many were newly acknowledged."""

        wanted = list(dict.fromkeys(ids))[:MAX_ACK_IDS]
        if not wanted:
            return 0
        with self._session_factory.begin() as session:
            result = session.execute(
                update(PushReminderRow)
                .where(
                    PushReminderRow.user_id == user_id,
                    PushReminderRow.id.in_(wanted),
                    PushReminderRow.acked_at.is_(None),
                )
                .values(acked_at=self._clock())
                .execution_options(synchronize_session=False)
            )
        return int(result.rowcount)  # type: ignore[attr-defined]

    def queue_test(
        self, user_id: UUID, device_id: UUID, *, correlation_id: str | None = None
    ) -> None:
        """Queue the visible test notification and an `r` push to this device's subscription.
        Raises `PushTestRateLimited` after five in an hour, `NoActiveSubscription` without one."""

        now = self._clock()
        prefix = f"t:{device_id}:"
        with self._session_factory.begin() as session:
            # Two simultaneous requests of one device must not both pass the count.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"push-test:{device_id}"},
            )
            recent = session.scalar(
                select(func.count())
                .select_from(PushReminderRow)
                .where(
                    PushReminderRow.user_id == user_id,
                    PushReminderRow.kind == "test",
                    PushReminderRow.dedup_key.startswith(prefix),
                    PushReminderRow.created_at > now - timedelta(hours=1),
                )
            )
            if (recent or 0) >= TESTS_PER_HOUR:
                raise PushTestRateLimited
            reminder_id = new_uuid7()
            session.add(
                PushReminderRow(
                    id=reminder_id,
                    user_id=user_id,
                    kind="test",
                    dedup_key=f"{prefix}{reminder_id}",
                    payload_title=localized(TEST_TITLES, self._locale),
                    scheduled_for=now,
                    created_at=now,
                )
            )
            session.flush()
            queued = enqueue_reminder_push(
                session, user_id, reminder_id, only_device_id=device_id, now=now
            )
            if not queued:
                raise NoActiveSubscription
            record_device_event(
                session, user_id, "companion.push_test_queued", device_id, correlation_id
            )

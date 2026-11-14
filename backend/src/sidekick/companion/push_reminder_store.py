"""Storage of visible push reminders: the `push_reminders` rows and their outbox pushes.

`SqlReminderStore` implements the port `ReminderScheduler` and `ReminderService` work against. The
rules (which reminders are due, how many tests an hour) are decided there and passed in; this
module reads and writes, and queues the matching `r` pushes in the same transaction. Titles are
stored and returned, never logged.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, CursorResult, and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from sidekick.companion.push_outbox_store import enqueue_reminder_push
from sidekick.companion.push_reminder_models import (
    DueTask,
    NewReminder,
    NoActiveSubscription,
    PendingItem,
    PendingReminders,
    PendingSummary,
    PushTestRateLimited,
)
from sidekick.companion.push_subscription_store import record_device_event
from sidekick.shared.persistence.models import PushReminderRow, PushSubscriptionRow, TaskRow
from sidekick.shared.persistence.stores.task_parents import task_parents_live
from sidekick.shared.types import new_uuid7
from sidekick.tasks.domain import TaskStatus


def _open_live_task() -> list[ColumnElement[bool]]:
    """A task that is neither completed, trashed, archived nor under a trashed parent."""

    return [
        TaskRow.status != TaskStatus.COMPLETED.value,
        TaskRow.trashed_at.is_(None),
        TaskRow.archived_at.is_(None),
        task_parents_live(),
    ]


class SqlReminderStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def subscribed_owners(self) -> list[UUID]:
        """Owners with at least one active push subscription."""

        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(PushSubscriptionRow.user_id)
                    .where(PushSubscriptionRow.revoked_at.is_(None))
                    .distinct()
                )
            )

    def reminder_exists(self, user_id: UUID, dedup_key: str) -> bool:
        with self._session_factory() as session:
            return (
                session.scalar(
                    select(PushReminderRow.id).where(
                        PushReminderRow.user_id == user_id, PushReminderRow.dedup_key == dedup_key
                    )
                )
                is not None
            )

    def due_tasks(
        self, user_id: UUID, now: datetime, *, lookback: timedelta, lead: timedelta
    ) -> Sequence[DueTask]:
        """Open, live tasks of the owner due between `now - lookback` and `now + lead`."""

        with self._session_factory() as session:
            rows = session.execute(
                select(TaskRow.id, TaskRow.title, TaskRow.due_at, TaskRow.created_at).where(
                    TaskRow.owner_id == user_id,
                    *_open_live_task(),
                    or_(TaskRow.not_before.is_(None), TaskRow.not_before <= now),
                    TaskRow.due_at.is_not(None),
                    TaskRow.due_at >= now - lookback,
                    TaskRow.due_at <= now + lead,
                )
            ).all()
        return [
            # The query keeps only tasks with a due time, which the column type cannot express.
            DueTask(task_id, title, cast(datetime, due_at), created_at)
            for task_id, title, due_at, created_at in rows
        ]

    def create_reminder(self, user_id: UUID, reminder: NewReminder, now: datetime) -> bool:
        """Create the reminder unless its dedup key exists, and queue its `r` pushes in the same
        transaction. False when it already existed."""

        with self._session_factory.begin() as session:
            created = session.scalar(
                insert(PushReminderRow)
                .values(
                    id=new_uuid7(),
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
                return False
            enqueue_reminder_push(session, user_id, created, now=now)
        return True

    def pending(
        self, user_id: UUID, now: datetime, *, max_age: timedelta, limit: int
    ) -> PendingReminders:
        """The owner's unacknowledged reminders scheduled within `max_age`, oldest first, and the
        newest summary. A due reminder is left out when its task was completed, trashed, archived,
        lost a live parent or was given another `due_at`."""

        fresh = and_(
            PushReminderRow.user_id == user_id,
            PushReminderRow.acked_at.is_(None),
            PushReminderRow.scheduled_for >= now - max_age,
        )
        task_is_current = and_(*_open_live_task(), TaskRow.due_at == PushReminderRow.due_at)
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
                    .limit(limit)
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
                PendingItem(row.id, row.kind, row.payload_title or "", row.task_id, row.due_at)
                for row in rows
            ),
            summary=(
                PendingSummary(summary.id, summary.summary_today or 0, summary.summary_overdue or 0)
                if summary is not None
                else None
            ),
        )

    def acknowledge(self, user_id: UUID, ids: Sequence[UUID], now: datetime) -> int:
        """Mark the owner's own unacknowledged reminders among `ids` shown; returns how many."""

        with self._session_factory.begin() as session:
            result = session.execute(
                update(PushReminderRow)
                .where(
                    PushReminderRow.user_id == user_id,
                    PushReminderRow.id.in_(ids),
                    PushReminderRow.acked_at.is_(None),
                )
                .values(acked_at=now)
                .execution_options(synchronize_session=False)
            )
        return int(cast(CursorResult[Any], result).rowcount)

    def queue_test(
        self,
        user_id: UUID,
        device_id: UUID,
        *,
        title: str,
        now: datetime,
        per_hour: int,
        correlation_id: str | None,
    ) -> None:
        """Queue the device's test reminder and its `r` push, and audit it, in one transaction.

        Raises `PushTestRateLimited` when the device already queued `per_hour` tests in the last
        hour and `NoActiveSubscription` when it has no subscription to send to; nothing is
        written then."""

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
            if (recent or 0) >= per_hour:
                raise PushTestRateLimited
            reminder_id = new_uuid7()
            session.add(
                PushReminderRow(
                    id=reminder_id,
                    user_id=user_id,
                    kind="test",
                    dedup_key=f"{prefix}{reminder_id}",
                    payload_title=title,
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

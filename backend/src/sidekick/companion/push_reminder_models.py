"""The values and errors that `push_reminders` and its store exchange."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sidekick.shared.errors.core import NotFoundError, RateLimitedError


class PushTestRateLimited(RateLimitedError):
    """The device already queued its allowed number of test notifications in the last hour."""


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
class DueTask:
    """An open task whose `due_at` falls in the window a due reminder is looked up for."""

    id: UUID
    title: str
    due_at: datetime
    created_at: datetime


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

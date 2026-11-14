"""What creating one Task takes, as the idempotency key hashes it."""

from datetime import datetime
from typing import NotRequired, TypedDict

from .recurrence import RecurrenceData


class NewTaskPayload(TypedDict):
    """What creating one Task needs, as the idempotency key hashes it: ids as text, no UUIDs."""

    title: str
    project_id: str | None
    domain_id: str | None
    process_id: str | None
    description: str | None
    priority: str
    due_at: datetime | None
    not_before: datetime | None
    estimated_minutes: int | None
    blocked_reminder_cadence: str | None
    blocked_reminder_snoozed_until: datetime | None
    recurrence: RecurrenceData | None
    tags: list[str]
    contact_ids: NotRequired[list[str]]
    """Only present when used, so retries of existing create keys keep their payload hash."""

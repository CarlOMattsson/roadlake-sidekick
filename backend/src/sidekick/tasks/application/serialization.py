"""Plain-data serialisation of a Task, shared by the transports."""

from __future__ import annotations

from typing import TypedDict

from sidekick.tasks.domain import Task
from sidekick.tasks.domain.recurrence import RecurrenceData


class TaskPublicData(TypedDict):
    """A Task as the public contract carries it: JSON values, no ownership fields."""

    id: str
    project_id: str | None
    domain_id: str | None
    process_id: str | None
    derived_domain_id: str | None
    attention_requested: bool
    title: str
    description: str | None
    status: str
    priority: str
    due_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str
    version: int
    archived_at: str | None
    not_before: str | None
    estimated_minutes: int | None
    waiting_since: str | None
    follow_up_at: str | None
    waiting_on_contact_id: str | None
    blocked_reminder_cadence: str | None
    blocked_reminder_snoozed_until: str | None
    blocked_last_reminded_at: str | None
    recurrence: RecurrenceData | None
    last_completed_at: str | None


def task_public_data(task: Task) -> TaskPublicData:
    return {
        "id": str(task.id),
        "project_id": str(task.project_id) if task.project_id else None,
        "domain_id": str(task.domain_id) if task.domain_id else None,
        "process_id": str(task.process_id) if task.process_id else None,
        "derived_domain_id": str(task.derived_domain_id) if task.derived_domain_id else None,
        "attention_requested": task.attention_requested,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "version": task.version,
        "archived_at": task.archived_at.isoformat() if task.archived_at else None,
        "not_before": task.not_before.isoformat() if task.not_before else None,
        "estimated_minutes": task.estimated_minutes,
        "waiting_since": task.waiting_since.isoformat() if task.waiting_since else None,
        "follow_up_at": task.follow_up_at.isoformat() if task.follow_up_at else None,
        "waiting_on_contact_id": (
            str(task.waiting_on_contact_id) if task.waiting_on_contact_id else None
        ),
        "blocked_reminder_cadence": (
            task.blocked_reminder_cadence.value if task.blocked_reminder_cadence else None
        ),
        "blocked_reminder_snoozed_until": (
            task.blocked_reminder_snoozed_until.isoformat()
            if task.blocked_reminder_snoozed_until
            else None
        ),
        "blocked_last_reminded_at": (
            task.blocked_last_reminded_at.isoformat() if task.blocked_last_reminded_at else None
        ),
        "recurrence": task.recurrence.to_data() if task.recurrence else None,
        "last_completed_at": (
            task.last_completed_at.isoformat() if task.last_completed_at else None
        ),
    }

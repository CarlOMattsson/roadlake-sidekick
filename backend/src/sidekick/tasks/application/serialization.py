"""Plain-data serialisation of a Task, shared by the use cases and the transports."""

from __future__ import annotations

from typing import Any

from sidekick.tasks.domain import Task


def task_to_data(task: Task) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "owner_id": str(task.owner_id),
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


def task_public_data(task: Task) -> dict[str, Any]:
    """Serialize the public contract without internal ownership fields."""

    data = task_to_data(task)
    data.pop("owner_id")
    return data

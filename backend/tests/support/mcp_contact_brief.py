"""Shared test helpers moved out of `tests/mcp/test_contact_meeting_brief.py`."""

from typing import Any

from sidekick.mcp.contact_records import ContactContextResult

CONTACT_ID = "7b0c2f1e-3a4d-4e5f-8a9b-0c1d2e3f4a5b"


def _task(title: str, due_at: str | None, **overrides: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": "11111111-1111-4111-8111-111111111111",
        "project_id": None,
        "title": title,
        "status": "todo",
        "priority": "normal",
        "due_at": due_at,
        "updated_at": "2026-10-28T10:00:00+02:00",
        "version": 1,
        "waiting_on_contact": False,
        "waiting_since": None,
        "follow_up_at": None,
        "follow_up_due": False,
    }
    task.update(overrides)
    return task


def _structured(
    *,
    role: str | None = None,
    organization: str | None = None,
    relationship: str | None = None,
    tasks: list[dict[str, Any]] | None = None,
    tasks_more: bool = False,
    journal_items: list[dict[str, Any]] | None = None,
    journal_readable: bool = True,
) -> ContactContextResult:
    items = tasks or []
    return ContactContextResult.model_validate(
        {
            "contact": {
                "id": CONTACT_ID,
                "display_name": "Sara Lind",
                "context_note": None,
                "email": None,
                "phone": None,
                "relationship": relationship,
                "organization": organization,
                "role": role,
                "address": None,
                "aliases": [],
                "archived": False,
                "created_at": "2026-10-01T10:00:00+02:00",
                "updated_at": "2026-10-01T10:00:00+02:00",
                "archived_at": None,
                "version": 3,
            },
            "projects": {"items": [], "next_cursor": None},
            "tasks": {
                "items": items,
                "next_cursor": "cursor-2" if tasks_more else None,
            },
            "journal_entries": {
                "items": journal_items or [],
                "has_more": False,
                "readable": journal_readable,
            },
        }
    )

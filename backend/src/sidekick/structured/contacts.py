"""Contact records and structured results, shared by the MCP tools and the companion API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sidekick.shared.types import Actor
from sidekick.structured.base import Output

if TYPE_CHECKING:
    from sidekick.composition import Container


class ContactSummaryRecord(Output):
    id: UUID
    display_name: str
    archived: bool
    updated_at: datetime
    version: int
    # Short profile fields only; the address stays on the full Contact record.
    relationship: str | None = None
    organization: str | None = None
    role: str | None = None


class TaskContactPageRecord(Output):
    """Linked Contacts for one Task, shaped like the REST `ContactPageView`."""

    items: list[ContactSummaryRecord]
    next_cursor: str | None = None


def task_contacts_structured(
    container: Container,
    actor: Actor,
    task_id: UUID,
    *,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """The structured content of `list_task_contacts` (shared with the companion route)."""

    page = container.contact_relations.list_task_contacts(
        actor, task_id, limit=limit, cursor=cursor
    )
    return TaskContactPageRecord(
        items=[
            ContactSummaryRecord(
                id=item.id,
                display_name=item.display_name,
                archived=item.archived,
                updated_at=item.updated_at,
                version=item.version,
                relationship=item.relationship,
                organization=item.organization,
                role=item.role,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    ).model_dump(mode="json")

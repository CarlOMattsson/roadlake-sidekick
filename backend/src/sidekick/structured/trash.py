"""The structured content of the reversible trash, shared by the MCP tools and the companion API.

Each function calls the same lifecycle use case for both interfaces and returns the closed record
payload; the MCP tools add their card text on top. Permanent removal is not here: it is an
operator command, and the companion API reaches it only for a trashed Task through its own route.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from sidekick.lifecycle import RecordKind, TrashItem
from sidekick.shared.types import Actor
from sidekick.structured.base import Output

if TYPE_CHECKING:
    from sidekick.composition import Container

KindValue = Literal[
    "domain",
    "process",
    "project",
    "task",
    "step",
    "action",
    "contact",
    "journal_entry",
    "shopping_item",
]

# A Journal source is immutable and the application role holds no UPDATE grant on its table, so
# it cannot be trashed at all today, and its label is an excerpt of raw journal text. It is
# therefore not part of this surface; a Journal source needs a trash path first.
TRASHABLE_KINDS = frozenset(RecordKind) - {RecordKind.JOURNAL_SOURCE}

# Same mapping as the use case's read scopes (service.py `_READ_SCOPE`); a test pins them equal.
# A label names the record, so it is returned only to an actor who can read that kind.
READ_SCOPE_BY_KIND: dict[RecordKind, str] = {
    RecordKind.DOMAIN: "projects:read",
    RecordKind.PROCESS: "projects:read",
    RecordKind.PROJECT: "projects:read",
    RecordKind.TASK: "tasks:read",
    RecordKind.STEP: "tasks:read",
    RecordKind.ACTION: "tasks:read",
    RecordKind.CONTACT: "contacts:read",
    RecordKind.JOURNAL_SOURCE: "journal:read",
    RecordKind.JOURNAL_ENTRY: "journal:read",
    RecordKind.SHOPPING_ITEM: "shopping:read",
}


class TrashItemRecord(Output):
    kind: KindValue
    id: UUID
    label: str | None
    trashed_at: datetime | None
    version: int


class TrashListResult(Output):
    items: list[TrashItemRecord]
    has_more: bool = False
    next_cursor: str | None = None


def trash_item_record(item: TrashItem, scopes: frozenset[str]) -> TrashItemRecord:
    readable = READ_SCOPE_BY_KIND[item.kind] in scopes
    return TrashItemRecord(
        # RecordKind also has journal_source, which this surface never lists as trashable.
        kind=cast("KindValue", item.kind.value),
        id=item.id,
        label=item.label if readable else None,
        trashed_at=item.trashed_at,
        version=item.version,
    )


def list_trash_structured(
    container: Container,
    actor: Actor,
    *,
    kind: RecordKind | None = None,
    limit: int = 100,
    cursor: str | None = None,
    within: frozenset[RecordKind] = TRASHABLE_KINDS,
) -> TrashListResult:
    """One page of the owner's trash; `within` narrows the kinds the caller's surface exposes."""

    # `within` filters in the query, so excluded kinds never take up slots in the page.
    page = container.lifecycle.list_trash(
        actor, kind=kind, limit=limit, within=within & TRASHABLE_KINDS, cursor=cursor
    )
    return TrashListResult(
        items=[trash_item_record(item, actor.scopes) for item in page.items],
        has_more=page.next_cursor is not None,
        next_cursor=page.next_cursor,
    )


def move_to_trash_structured(
    container: Container,
    actor: Actor,
    kind: RecordKind,
    record_id: UUID,
    *,
    version: int,
    idempotency_key: str,
    correlation_id: str | None = None,
) -> TrashItemRecord:
    """Move one record to the trash; the structured content of `move_to_trash`."""

    item = container.lifecycle.trash(
        actor,
        kind,
        record_id,
        version=version,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return trash_item_record(item, actor.scopes)


def restore_from_trash_structured(
    container: Container,
    actor: Actor,
    kind: RecordKind,
    record_id: UUID,
    *,
    version: int,
    idempotency_key: str,
    correlation_id: str | None = None,
) -> TrashItemRecord:
    """Take one record out of the trash; the structured content of `restore_from_trash`."""

    item = container.lifecycle.restore(
        actor,
        kind,
        record_id,
        version=version,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return trash_item_record(item, actor.scopes)

"""Reversible record lifecycle tools: list the trash, move a record there, restore it.

Permanent removal is deliberately not here (D-031: permanent removal is not an MCP tool): nothing in
this module can reach `RecordLifecycleService.permanently_remove`, and since D-082 (old web shell
removed) removed the REST
routes no public surface exposes that method. The tools call the lifecycle use case with the record
kinds and scopes listed here. The "ask first" wording of `move_to_trash` is an instruction to the
host model; the server enforces owner, scope, observed version and idempotency, and the move is
reversible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import Field

from sidekick.lifecycle import RecordKind, TrashItem
from sidekick.mcp.annotations import DESTRUCTIVE, READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result, spoken_names
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import flat
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.base import Output

LIFECYCLE_TOOL_NAMES = ("list_trash", "move_to_trash", "restore_from_trash")
"""Closed on purpose: no tool in this surface removes a record permanently."""

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
Version = Annotated[int, Field(ge=1)]


# A Journal source is immutable and the application role holds no UPDATE grant on its table, so
# it cannot be trashed at all today, and its label is an excerpt of raw journal text. It is
# therefore not part of this surface; a Journal source needs a trash path first.
_KINDS = frozenset(RecordKind) - {RecordKind.JOURNAL_SOURCE}

# Same mapping as the use case's read scopes (service.py `_READ_SCOPE`); a test pins them equal.
# A label names the record, so it is returned only to an actor who can read that kind.
_READ_SCOPE_BY_KIND: dict[RecordKind, str] = {
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


def _kind_phrase(kind: str) -> str:
    """The kind in words with its article, e.g. "a task", "an action", "a journal entry"."""

    words = kind.replace("_", " ")
    return f"{'an' if words[0] in 'aeiou' else 'a'} {words}"


def _trash_summary(items: list[TrashItemRecord], *, has_more: bool) -> str:
    """A count, the newest kind, and up to three labels.

    E.g. "7 trashed items, latest a task: A, B and 5 more." The page is newest first, so the first
    label is the latest item's when it is readable; a hidden label is said to be hidden.
    """

    if not items and not has_more:
        return "The trash is empty."
    count = len(items)
    noun = "trashed item" if count == 1 else "trashed items"
    head = f"at least {count} {noun}" if has_more else f"{count} {noun}"
    if items:
        latest = items[0]
        head += f", latest {_kind_phrase(latest.kind)}"
        if latest.label is None:
            head += " (name hidden)"
    names = spoken_names([item.label for item in items if item.label], total=count)
    return f"{head}: {names}." if names else f"{head}."


def _subject(kind: str, label: str | None) -> str:
    """`task "Skicka offert"`, or "the record" when the label is hidden without read access."""

    if label is None:
        return "the record"
    return f'{kind.replace("_", " ")} "{flat(label, limit=60)}"'


def _record(item: TrashItem, scopes: frozenset[str]) -> TrashItemRecord:
    readable = _READ_SCOPE_BY_KIND[item.kind] in scopes
    return TrashItemRecord(
        # RecordKind also has journal_source, which this surface never lists as trashable.
        kind=item.kind.value,  # pyright: ignore[reportArgumentType]
        id=item.id,
        label=item.label if readable else None,
        trashed_at=item.trashed_at,
        version=item.version,
    )


def _register_list_trash(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_trash",
        description=(
            "Use this to see the authenticated user's recoverable trash, newest first, "
            "optionally narrowed to one record kind. To get a record back, find it here, "
            "then call restore_from_trash with its kind, id and the version shown. Trash is "
            "different from archive: a trashed record is hidden everywhere. "
            "has_more means the list was cut at the limit: pass next_cursor as cursor, with the "
            "same kind, to read the next page. Journal sources are not part of this "
            "surface. This never removes anything."
        ),
        output_schema=output_schema(TrashListResult),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("list_trash")
    def list_trash(
        kind: KindValue | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 100,
        cursor: Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> Any:
        actor = ctx.actor_provider()
        # `within` filters in the query, so excluded kinds never take up slots in the page.
        page = ctx.container.lifecycle.list_trash(
            actor,
            kind=RecordKind(kind) if kind else None,
            limit=limit,
            within=_KINDS,
            cursor=cursor,
        )
        visible = [_record(item, actor.scopes) for item in page.items]
        structured = TrashListResult(
            items=visible,
            has_more=page.next_cursor is not None,
            next_cursor=page.next_cursor,
        ).model_dump(mode="json")
        return result(structured, _trash_summary(visible, has_more=structured["has_more"]))


def _register_move_to_trash(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="move_to_trash",
        description=(
            "Use this only after asking the user and getting an explicit yes in this turn to "
            "move this record to the trash. Supply the kind, record_id and observed version. "
            "It is reversible: the record is hidden, not erased, and restore_from_trash "
            "returns it. This tool can never remove anything permanently. Safe to retry with "
            "the same key and payload."
        ),
        output_schema=output_schema(TrashItemRecord),
        annotations=DESTRUCTIVE,
    )
    @ctx.instrument("move_to_trash")
    def move_to_trash(
        kind: KindValue, record_id: UUID, version: Version, idempotency_key: IdempotencyKey
    ) -> Any:
        actor = ctx.actor_provider()
        item = ctx.container.lifecycle.trash(
            actor,
            RecordKind(kind),
            record_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = _record(item, actor.scopes).model_dump(mode="json")
        subject = _subject(record["kind"], record["label"])
        return result(record, f"Moved {subject} to the trash.")


def _register_restore_from_trash(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="restore_from_trash",
        description=(
            "Use this when the user wants something back from the trash. Supply the kind, "
            "record_id and the version shown by list_trash. It only reverses move_to_trash; "
            "it does not undo an archive (use the archive-specific restore tools for that) "
            "and does not touch related records. Safe to retry with the same key and payload."
        ),
        output_schema=output_schema(TrashItemRecord),
        annotations=WRITE,
    )
    @ctx.instrument("restore_from_trash")
    def restore_from_trash(
        kind: KindValue, record_id: UUID, version: Version, idempotency_key: IdempotencyKey
    ) -> Any:
        actor = ctx.actor_provider()
        item = ctx.container.lifecycle.restore(
            actor,
            RecordKind(kind),
            record_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = _record(item, actor.scopes).model_dump(mode="json")
        subject = _subject(record["kind"], record["label"])
        return result(record, f"Restored {subject} from the trash.")


_REGISTRARS = (_register_list_trash, _register_move_to_trash, _register_restore_from_trash)


def register_lifecycle_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the three reversible trash tools."""
    for register in _REGISTRARS:
        register(mcp, ctx)

"""Reversible record lifecycle tools: list the trash, move a record there, restore it.

Permanent removal is deliberately not here (D-031: permanent removal is not an MCP tool): nothing in
this module can reach `RecordLifecycleService.permanently_remove`. The tools call the lifecycle use
case through `sidekick.structured.trash`, which the companion API shares. The "ask first" wording of
`move_to_trash` is an instruction to the host model; the server enforces owner, scope, observed
version and idempotency, and the move is reversible.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.lifecycle import RecordKind
from sidekick.mcp.annotations import DESTRUCTIVE, READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result, spoken_names
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import flat
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.trash import (
    KindValue,
    TrashItemRecord,
    TrashListResult,
    list_trash_structured,
    move_to_trash_structured,
    restore_from_trash_structured,
)

LIFECYCLE_TOOL_NAMES = ("list_trash", "move_to_trash", "restore_from_trash")
"""Closed on purpose: no tool in this surface removes a record permanently."""

Version = Annotated[int, Field(ge=1)]


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
    ) -> ToolResult:
        actor = ctx.actor_provider()
        listed = list_trash_structured(
            ctx.container,
            actor,
            kind=RecordKind(kind) if kind else None,
            limit=limit,
            cursor=cursor,
        )
        return result(
            listed.model_dump(mode="json"),
            _trash_summary(listed.items, has_more=listed.has_more),
        )


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
    ) -> ToolResult:
        actor = ctx.actor_provider()
        record = move_to_trash_structured(
            ctx.container,
            actor,
            RecordKind(kind),
            record_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        ).model_dump(mode="json")
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
    ) -> ToolResult:
        actor = ctx.actor_provider()
        record = restore_from_trash_structured(
            ctx.container,
            actor,
            RecordKind(kind),
            record_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        ).model_dump(mode="json")
        subject = _subject(record["kind"], record["label"])
        return result(record, f"Restored {subject} from the trash.")


_REGISTRARS = (_register_list_trash, _register_move_to_trash, _register_restore_from_trash)


def register_lifecycle_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the three reversible trash tools."""
    for register in _REGISTRARS:
        register(mcp, ctx)

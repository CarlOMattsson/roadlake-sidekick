"""Read-only "Senaste ändringar": the owner's newest changes, so a spoken undo has a target.

`list_recent_changes` adds no selection rules of its own. It calls `RecordLifecycleService.
list_recent_changes`, which reads owner events from the audit trail and takes each title and
version from the record itself. A kind whose read scope is missing is left out without an error.
Undo uses the existing write tools; this module never changes anything.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.mcp.annotations import READ
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import flat, spoken_date
from sidekick.mcp.tool_context import ToolContext
from sidekick.structured.base import Output

if TYPE_CHECKING:
    from sidekick.lifecycle.domain import RecentChange


class ChangeRecord(Output):
    """One change: what happened to which record, with the record's current version."""

    kind: Annotated[str, Field(max_length=40)]
    id: UUID
    title: Annotated[str, Field(max_length=200)]
    version: int
    action: Literal[
        "created",
        "updated",
        "completed",
        "archived",
        "restored",
        "trashed",
        "purchased",
        "reopened",
    ]
    state: Literal["active", "trashed"]
    # Who made the change: the owner in the app, Claude through a tool, or unknown (not recorded).
    actor: Literal["you", "claude", "unknown"]
    occurred_at: datetime
    related_id: UUID | None = None
    undo_tool: Annotated[str | None, Field(max_length=60)] = None


class ChangesOutput(Output):
    changes: Annotated[list[ChangeRecord], Field(max_length=20)]


# Storage kinds that read badly aloud get a spoken name; the others are their name with spaces.
_KIND_WORDS: dict[str, str] = {
    "contact_alias": "contact alias",
    "contact_alias_removed": "contact alias",
    "contact_link": "contact link",
    "contact_task_link": "link between contact and task",
    "contact_project_link": "link between contact and project",
    "external_reference": "external reference",
    "external_reference_link": "link between reference and task",
}


# Spoken verbs for actions that do not read well as the stored action name.
_ACTION_WORDS: dict[str, str] = {"purchased": "bought", "reopened": "put back"}
# Links can only be removed in the app; the unlink tools are app-only, so no row names them.
_LINK_KINDS = frozenset({"contact_task_link", "contact_project_link", "external_reference_link"})
# The first line names at most this many changes, then "and N more".
_SPOKEN_PHRASES = 3


def _words(kind: str) -> str:
    return _KIND_WORDS.get(kind, kind.replace("_", " "))


def _undo_hint(change: RecentChange) -> str | None:
    """How the model can undo this change, or None when it has no undo of its own."""

    if change.undo_tool is not None:
        # Only a purchase or put-back has a tool; the opposite value undoes it.
        value = "false" if change.action == "purchased" else "true"
        return f"undo with {change.undo_tool} purchased={value}"
    if change.kind in _LINK_KINDS and change.action == "created":
        return "undo in the app"
    return None


def _when(occurred_at: datetime, *, now: datetime, zone: tzinfo) -> str:
    """Say "today" or "yesterday" for the owner's calendar day, else the day in words."""

    day = occurred_at.astimezone(zone).date()
    today = now.astimezone(zone).date()
    if day == today:
        return "today"
    if day == today - timedelta(days=1):
        return "yesterday"
    return spoken_date(day, today)


def _text(changes: list[RecentChange], *, now: datetime, zone: tzinfo) -> str:
    """The first line is readable aloud and has no ids; ids and versions follow on later lines."""

    if not changes:
        return "You have no recent changes."
    phrases: list[str] = []
    for change in changes:
        now_trashed = change.state == "trashed" and change.action != "trashed"
        suffix = " (now trashed)" if now_trashed else ""
        title = flat(change.title, limit=60)
        verb = _ACTION_WORDS.get(change.action, change.action)
        when = _when(change.occurred_at, now=now, zone=zone)
        phrases.append(f'{verb} {_words(change.kind)} "{title}" {when}{suffix}')
    count = len(changes)
    head = "Your last change: " if count == 1 else f"Your last {count} changes: "
    spoken = ", ".join(phrases[:_SPOKEN_PHRASES])
    if count > _SPOKEN_PHRASES:
        spoken += f" and {count - _SPOKEN_PHRASES} more"
    lines = [head + spoken + "."]
    for number, change in enumerate(changes, start=1):
        line = (
            f"{number}. {change.kind} id {change.id}, version {change.version}, "
            f"{change.occurred_at.isoformat()}"
        )
        if change.related_id is not None:
            line += f", related id {change.related_id}"
        hint = _undo_hint(change)
        if hint is not None:
            line += f", {hint}"
        lines.append(line)
    return "\n".join(lines)


def register_change_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the read-only recent-changes tool; it opens the Control app card."""

    @mcp.tool(
        name="list_recent_changes",
        description=(
            "Use this when the user asks what they changed last, or to undo it. Returns the "
            "owner's newest changes (tasks, projects, contacts, journal, shopping), newest first: "
            "kind, id, version, title, action, state, actor (you, claude or unknown), related_id "
            "and time. Read-only. To undo, make the opposite change at that version (update_task, "
            "update_shopping_item); a "
            "purchase or put-back with set_shopping_item_purchased and undo_tool; move_to_trash "
            "after a yes for a new record, never for a purchase. A link is undone in the app."
        ),
        output_schema=output_schema(ChangesOutput),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("list_recent_changes")
    def list_recent_changes(
        limit: Annotated[int, Field(ge=1, le=20)] = 20,
    ) -> ToolResult:
        changes = ctx.container.lifecycle.list_recent_changes(ctx.actor_provider(), limit=limit)
        zone = ctx.container.settings.owner_zone
        structured = ChangesOutput(
            changes=[
                ChangeRecord(
                    kind=change.kind,
                    id=change.id,
                    title=change.title,
                    version=change.version,
                    action=change.action,
                    state=change.state,
                    actor=change.actor,
                    occurred_at=change.occurred_at,
                    related_id=change.related_id,
                    undo_tool=change.undo_tool,
                )
                for change in changes
            ]
        ).model_dump(mode="json")
        return result(structured, _text(changes, now=datetime.now(UTC), zone=zone))

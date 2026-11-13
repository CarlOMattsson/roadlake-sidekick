"""Read-only confirmation card for Work changes: one closing `show_work_changes` call.

A series of Work writes in one turn should end with one call to this tool rather than one card
per write. The tool takes only refs (kind and id), never free text, reads each ref back through
the same owner-scoped use cases as the `get_*` tools, and leaves out anything it cannot resolve
without saying why.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.mcp.annotations import READ
from sidekick.mcp.results import output_schema, result, spoken_names
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import flat, rows_text
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.errors import NotFoundError
from sidekick.shared.types import Actor, utc_now
from sidekick.structured.base import Output

if TYPE_CHECKING:
    from sidekick.composition import Container

MAX_REFS = 25


WorkKind = Literal["domain", "project", "task", "step"]


class WorkRef(Output):
    kind: WorkKind
    id: UUID


class WorkCardItem(Output):
    kind: WorkKind
    id: UUID
    title: str
    status: str
    version: int
    due_at: datetime | None


class WorkCard(Output):
    kind: Literal["work_changes"]
    total: int
    truncated: bool
    # Server clock in UTC when the card was built; serialized as ISO 8601 with a UTC offset.
    issued_at: datetime
    items: list[WorkCardItem]


class WorkChangesOutput(Output):
    card: WorkCard


def _load(
    container: Container, actor: Actor, kind: WorkKind, record_id: UUID
) -> WorkCardItem | None:
    """Return the current state of one ref, or None when it is unknown, foreign or trashed.

    The use cases raise NotFoundError for all three, so the caller cannot tell them apart.
    """

    try:
        if kind == "domain":
            domain = container.contexts.get_domain(actor, record_id)
            return WorkCardItem(
                kind=kind,
                id=record_id,
                title=domain.name,
                status=domain.status.value,
                version=domain.version,
                due_at=None,
            )
        if kind == "project":
            project = container.projects.get(actor, record_id)
            return WorkCardItem(
                kind=kind,
                id=record_id,
                title=project.title,
                status=project.status.value,
                version=project.version,
                due_at=None,
            )
        if kind == "task":
            task = container.tasks.get(actor, record_id)
            return WorkCardItem(
                kind=kind,
                id=record_id,
                title=task.title,
                status=task.status.value,
                version=task.version,
                due_at=task.due_at,
            )
        step = container.steps.get_step(actor, record_id)
        return WorkCardItem(
            kind=kind,
            id=record_id,
            title=step.title,
            status=step.status.value,
            version=step.version,
            due_at=step.due_at,
        )
    except NotFoundError:
        return None


def _row(item: WorkCardItem) -> str:
    return f"- {item.kind} {item.id} | {flat(item.title)} | v{item.version}"


def _sentence(items: list[WorkCardItem]) -> str:
    """Line 1 for voice: what changed, by title, with no ids."""

    if not items:
        return "I could not find any of those records."
    return f"Here is what changed: {spoken_names([item.title for item in items], len(items))}."


def register_work_card_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the Work confirmation-card tool."""

    @mcp.tool(
        name="show_work_changes",
        description=(
            "Call this at most once, as the last tool call, after a series of Work writes "
            "(domain, project, task or step creates and updates) in the same turn. Do not "
            "call it after a single small status change or after shopping-list changes. Pass "
            "the kind and id of each changed record, up to 25; unknown or inaccessible ids are "
            "left out silently. It only reads current state and changes nothing."
        ),
        output_schema=output_schema(WorkChangesOutput),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("show_work_changes")
    def show_work_changes(
        refs: Annotated[list[WorkRef], Field(min_length=1, max_length=MAX_REFS)],
    ) -> ToolResult:
        actor = ctx.actor_provider()
        # Duplicates collapse to one row, in the order the model asked for them.
        unique: dict[tuple[WorkKind, UUID], None] = {}
        for ref in refs:
            unique[(ref.kind, ref.id)] = None
        items: list[WorkCardItem] = []
        for kind, record_id in unique:
            item = _load(ctx.container, actor, kind, record_id)
            if item is not None:
                items.append(item)
        structured = WorkChangesOutput(
            card=WorkCard(
                kind="work_changes",
                total=len(items),
                # At most MAX_REFS refs are read and every resolved one is returned.
                truncated=False,
                issued_at=utc_now(),
                items=items,
            )
        ).model_dump(mode="json")
        return result(
            structured,
            rows_text(_sentence(items), [_row(item) for item in items]),
        )

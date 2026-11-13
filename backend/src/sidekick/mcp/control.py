"""Owner-control reads for the Sidekick app, served through MCP only.

`list_assistant_activity` opens the Sidekick app (`ui://sidekick/app-v1.html`), as its fourth view.
It returns the owner's own durable Activity Center entries, newest first, and needs `tasks:read`.
There is no REST route for it: the MCP tool calls the automation application service directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.automation.domain import AutomationPolicyMode
from sidekick.mcp.annotations import READ
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.base import Output

if TYPE_CHECKING:
    from sidekick.automation.application.service import ActivityEntry

CONTROL_TOOL_NAMES = ("list_assistant_activity",)
CONTROL_TOOL_SCOPES = {"list_assistant_activity": {"tasks:read"}}


class ActivityRecord(Output):
    """One Activity Center entry. Summary, before, after and evidence follow `include_content`."""

    id: UUID
    domain_event_id: UUID
    category: Annotated[str, Field(max_length=48)]
    source: Literal["user", "assistant", "worker", "system"]
    operation: Annotated[str, Field(max_length=120)]
    state: Literal["applied", "review", "failed", "reverted"]
    aggregate_type: Annotated[str, Field(max_length=64)]
    aggregate_id: UUID
    summary: Annotated[str, Field(max_length=2_000)]
    before_values: dict[str, Any]
    after_values: dict[str, Any]
    evidence: dict[str, Any]
    policy_mode: AutomationPolicyMode | None
    correlation_id: Annotated[str, Field(max_length=128)] | None
    occurred_at: datetime


class ActivityPageResult(Output):
    items: Annotated[list[ActivityRecord], Field(max_length=100)]
    next_cursor: Annotated[str, Field(max_length=MAX_CURSOR_LENGTH)] | None


def _summary(entry: ActivityEntry, *, include_content: bool) -> str:
    """The stored summary carries titles and process names, and is returned by default.

    With `include_content=false` the text is built from fixed codes alone: category, operation
    and aggregate type, for example `task_create: task.create_task`.
    """
    if include_content:
        return entry.summary
    return f"{entry.category}: {entry.aggregate_type}.{entry.operation}"


def _record(entry: ActivityEntry, *, include_content: bool) -> ActivityRecord:
    return ActivityRecord.model_validate(
        {
            "id": entry.id,
            "domain_event_id": entry.domain_event_id,
            "category": entry.category,
            "source": entry.source,
            "operation": entry.operation,
            "state": entry.state,
            "aggregate_type": entry.aggregate_type,
            "aggregate_id": entry.aggregate_id,
            "summary": _summary(entry, include_content=include_content),
            "before_values": dict(entry.before_values) if include_content else {},
            "after_values": dict(entry.after_values) if include_content else {},
            "evidence": dict(entry.evidence) if include_content else {},
            "policy_mode": entry.policy_mode,
            "correlation_id": entry.correlation_id,
            "occurred_at": entry.occurred_at,
        }
    )


def register_control_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the read-only owner-control tools; none of them changes any setting."""

    @mcp.tool(
        name="list_assistant_activity",
        description=(
            "Use this for a bounded, newest-first page of the authenticated user's own "
            "Activity Center entries: what changed, by whom, and in which state. Summary, "
            "values before and after a change and evidence are included by default; "
            "include_content=false omits them. Read-only; do not use it for another user or "
            "to change any setting."
        ),
        output_schema=output_schema(ActivityPageResult),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("list_assistant_activity")
    def list_assistant_activity(
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
        cursor: Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)] = None,
        category: Annotated[str | None, Field(max_length=48)] = None,
        state: Literal["applied", "review", "failed", "reverted"] | None = None,
        include_content: bool = True,
    ) -> ToolResult:
        page = ctx.container.automation.list_activity(
            ctx.actor_provider(), limit=limit, cursor=cursor, category=category, state=state
        )
        structured = ActivityPageResult(
            items=[_record(item, include_content=include_content) for item in page.items],
            next_cursor=page.next_cursor,
        ).model_dump(mode="json")
        return result(structured, f"Found {len(page.items)} activity entries.")

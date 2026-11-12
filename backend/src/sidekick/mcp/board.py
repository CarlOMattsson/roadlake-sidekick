"""App-only manual ordering of one Work board status column.

`reorder_work_board_column` calls `TaskService.reorder_board_column`; the board has no HTTP route,
so this MCP tool is the only way in. It is hidden from the model (`visibility=["app"]`; the owner's
own reordering is a small change that applies directly, D-057): the open board app sends the
complete column with each task's observed version. The use case owns the write scope, the owner
filter, the completeness and version checks, the idempotency record and the content-free audit
event, so this adapter only shapes input and output and hands over the request's correlation id.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import Field

from sidekick.mcp.annotations import WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.tool_context import ToolContext
from sidekick.structured.base import Output
from sidekick.tasks.application import MAX_BOARD_COLUMN_REORDER
from sidekick.tasks.domain import TaskStatus

BOARD_TOOL_NAMES = ("reorder_work_board_column",)


class BoardItemInput(Output):
    task_id: UUID
    version: Annotated[int, Field(ge=1)]


# Task id and its new version only. The rank stays internal to the use case, never in a schema.
class BoardPlacementRecord(Output):
    task_id: UUID
    version: int


class BoardReorderResult(Output):
    items: list[BoardPlacementRecord]


def register_board_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the app-only board column reorder."""

    @mcp.tool(
        name="reorder_work_board_column",
        description=(
            "App-only. Sets the manual order of one complete Work board status column. Pass "
            "every active task in that column exactly once, in the new order, with the version "
            "each task showed. A partial column, an unknown task or a stale version is refused "
            "and nothing changes. Safe to retry with the same key and payload."
        ),
        output_schema=output_schema(BoardReorderResult),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("reorder_work_board_column")
    def reorder_work_board_column(
        status: TaskStatus,
        items: Annotated[
            list[BoardItemInput], Field(min_length=1, max_length=MAX_BOARD_COLUMN_REORDER)
        ],
        idempotency_key: IdempotencyKey,
    ) -> Any:
        placements = ctx.container.tasks.reorder_board_column(
            ctx.actor_provider(),
            status,
            items=[(item.task_id, item.version) for item in items],
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        # The input order is the new column order; the use case turns it into ranks internally.
        structured = BoardReorderResult(
            items=[
                BoardPlacementRecord(task_id=placement.task_id, version=placement.version)
                for placement in placements
            ]
        ).model_dump(mode="json")
        ids = ", ".join(item["task_id"] for item in structured["items"])
        return result(
            structured,
            f"Reordered {len(structured['items'])} tasks in the {status.value} column: {ids}.",
        )

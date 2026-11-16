"""The Task tools: get, create, update, complete and restore."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.mcp.annotations import READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import card_result, output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.tool_context import ToolContext
from sidekick.mcp.work_text import (
    cell,
    record_card_text,
    record_ref,
    spoken_line,
    task_detail_lines,
    task_parent,
    work_item_sentence,
)
from sidekick.shared.text_guard import NoImageData
from sidekick.structured.base import Output
from sidekick.structured.work import (
    complete_task_structured,
    task_detail_structured,
    update_task_structured,
)
from sidekick.structured.work_records import (
    DueAtInput,
    TaskChanges,
    TaskDetailOutput,
    TaskOutput,
    WritePriority,
)
from sidekick.structured.work_writes import create_task_structured
from sidekick.tasks.domain.planning import MAX_ESTIMATED_MINUTES
from sidekick.work.domain.planning import MAX_TAGS_PER_RECORD

# Parameter types shared by several tools; the JSON schema each produces is pinned by the contract.
_Version = Annotated[int, Field(ge=1)]


def _task_reply(structured: TaskOutput, verb: str) -> ToolResult:
    """`<verb> task <title>.` and the task's reference line, as the tool result."""
    record = structured.task
    return result(
        structured.model_dump(mode="json"),
        spoken_line(
            f"{verb} task {cell(record.title)}.",
            record_ref(record.id, record.version, record.title, parent=task_parent(record)),
        ),
    )


def _register_get_task(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="get_task",
        description=(
            "Get one owned task by its Sidekick UUID. Returns no cross-user existence detail."
        ),
        output_schema=output_schema(TaskDetailOutput),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_task")
    def get_task(task_id: UUID) -> ToolResult:
        structured, detail = task_detail_structured(ctx.container, ctx.actor_provider(), task_id)
        task = detail.task
        record = structured.task
        zone = ctx.container.settings.owner_zone
        due = task.due_at.astimezone(zone).date() if task.due_at is not None else None
        sentence = work_item_sentence(
            "Task",
            record.title,
            task.status.value,
            due,
            label="due date",
            today=datetime.now(zone).date(),
        )
        return card_result(
            structured.model_dump(mode="json"),
            record_card_text(
                sentence,
                record_ref(record.id, record.version, record.title, parent=task_parent(record)),
                task_detail_lines(record, detail.steps),
            ),
        )


def _register_create_task(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="create_task",
        description=(
            "Use this when the user wants a new task, standalone or under a Project or Process. "
            "Pass project_id or process_id to file it there, domain_id for its Domain, and "
            "contact_ids to link Contacts in the same call. due_at is an ISO datetime with an "
            "offset, or a bare date (YYYY-MM-DD) meaning end of that day, 23:59 in the owner's "
            "zone. This writes durable state and requires a retry-safe idempotency key."
        ),
        output_schema=output_schema(TaskOutput),
        annotations=WRITE,
    )
    @ctx.instrument("create_task")
    def create_task(
        title: Annotated[str, Field(min_length=1, max_length=200), NoImageData],
        idempotency_key: IdempotencyKey,
        project_id: UUID | None = None,
        domain_id: UUID | None = None,
        process_id: UUID | None = None,
        contact_ids: Annotated[list[UUID] | None, Field(max_length=10)] = None,
        description: Annotated[str | None, Field(max_length=10_000), NoImageData] = None,
        priority: WritePriority = "normal",
        due_at: DueAtInput = None,
        not_before: datetime | None = None,
        estimated_minutes: Annotated[int | None, Field(ge=1, le=MAX_ESTIMATED_MINUTES)] = None,
        tags: Annotated[
            list[Annotated[str, NoImageData]] | None,
            Field(max_length=MAX_TAGS_PER_RECORD),
        ] = None,
    ) -> ToolResult:
        structured = create_task_structured(
            ctx.container,
            ctx.actor_provider(),
            title=title,
            idempotency_key=idempotency_key,
            project_id=project_id,
            domain_id=domain_id,
            process_id=process_id,
            contact_ids=contact_ids or (),
            description=description,
            priority=priority,
            due_at=due_at,
            not_before=not_before,
            estimated_minutes=estimated_minutes,
            tags=tags or (),
            correlation_id=request_correlation_id_or_new(),
        )
        return _task_reply(structured, "Created")


def _register_update_task(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="update_task",
        description=(
            "Update explicit fields of one owned task at its current version; retry-safe with "
            "the same idempotency key."
        ),
        output_schema=output_schema(TaskOutput),
        annotations=WRITE,
    )
    @ctx.instrument("update_task")
    def update_task(
        task_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
        changes: TaskChanges,
    ) -> ToolResult:
        structured = update_task_structured(
            ctx.container,
            ctx.actor_provider(),
            task_id,
            version=version,
            idempotency_key=idempotency_key,
            changes=changes,
            correlation_id=request_correlation_id_or_new(),
        )
        return _task_reply(structured, "Updated")


def _register_complete_task(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="complete_task",
        description=(
            "Mark one owned task complete using its current version. Its open steps and their "
            "actions are completed with it; a status change back to todo opens again what this "
            "closed. A repeating task starts all its steps and actions over for the next run. "
            "Repeating the same idempotency key safely returns the committed result."
        ),
        output_schema=output_schema(TaskOutput),
        annotations=WRITE,
    )
    @ctx.instrument("complete_task")
    def complete_task(
        task_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> ToolResult:
        structured = complete_task_structured(
            ctx.container,
            ctx.actor_provider(),
            task_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return _task_reply(structured, "Completed")


# The restored Task in brief (get_task reads the rest): one more full Task schema would cost about
# 4 200 characters of the model-visible outputSchema ceiling.
class RestoredTaskOutput(Output):
    id: UUID
    version: int
    title: str
    status: str
    archived: bool


def _register_restore_task(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="restore_task",
        description=(
            "Bring back one archived task so it is active again, using its current version: "
            "the undo of archive, e.g. after review_tasks. Repeating the same idempotency key "
            "safely returns the committed result."
        ),
        output_schema=output_schema(RestoredTaskOutput),
        annotations=WRITE,
    )
    @ctx.instrument("restore_task")
    def restore_task(
        task_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> ToolResult:
        task = ctx.container.tasks.restore(
            ctx.actor_provider(),
            task_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = RestoredTaskOutput(
            id=task.id,
            version=task.version,
            title=task.title,
            status=task.status.value,
            archived=task.archived_at is not None,
        )
        return result(
            structured.model_dump(mode="json"),
            spoken_line(
                f"Restored task {cell(task.title)}.",
                record_ref(task.id, task.version, task.title),
            ),
        )


_REGISTRARS = (
    _register_get_task,
    _register_create_task,
    _register_update_task,
    _register_complete_task,
    _register_restore_task,
)


def register_task_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    for register in _REGISTRARS:
        register(mcp, ctx)

"""The Task tools: get, create, update and complete."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
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
from sidekick.structured.work import (
    complete_task_structured,
    task_detail_structured,
    update_task_structured,
    with_tags,
)
from sidekick.structured.work_records import (
    DueAtInput,
    TaskChanges,
    TaskDetailOutput,
    TaskOutput,
    TaskRecord,
    WritePriority,
    end_of_day_due_at,
)
from sidekick.tasks.application.service import task_public_data
from sidekick.tasks.domain import Priority
from sidekick.work.domain.planning import (
    MAX_ESTIMATED_MINUTES,
    MAX_TAGS_PER_RECORD,
)

# Parameter types shared by several tools; the JSON schema each produces is pinned by the contract.
_Version = Annotated[int, Field(ge=1)]


def _task_reply(structured: dict[str, Any], verb: str) -> Any:
    """`<verb> task <title>.` and the task's reference line, as the tool result."""
    record = structured["task"]
    return result(
        structured,
        spoken_line(
            f"{verb} task {cell(record['title'])}.",
            record_ref(record, parent=task_parent(record)),
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
    def get_task(task_id: UUID) -> Any:
        structured, detail = task_detail_structured(ctx.container, ctx.actor_provider(), task_id)
        task = detail.task
        record = structured["task"]
        zone = ctx.container.settings.owner_zone
        due = task.due_at.astimezone(zone).date() if task.due_at is not None else None
        sentence = work_item_sentence(
            "Task",
            record["title"],
            task.status.value,
            due,
            label="due date",
            today=datetime.now(zone).date(),
        )
        return card_result(
            structured,
            record_card_text(
                sentence,
                record_ref(record, parent=task_parent(record)),
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
    ) -> Any:
        container = ctx.container
        actor = ctx.actor_provider()
        # The reply lists the tags (projects:read), so refuse before anything is written.
        container.work_tags.require_record_tags_readable(actor)
        # Task and contact links share one transaction in the service: an unknown Contact
        # fails the whole call with not-found and leaves no Task behind.
        task = container.tasks.create(
            actor,
            title=title,
            idempotency_key=idempotency_key,
            project_id=project_id,
            domain_id=domain_id,
            process_id=process_id,
            description=description,
            priority=Priority(priority),
            due_at=end_of_day_due_at(due_at, container.settings.owner_zone),
            not_before=not_before,
            estimated_minutes=estimated_minutes,
            tags=tuple(tags or ()),
            contact_ids=tuple(contact_ids or ()),
            correlation_id=request_correlation_id_or_new(),
        )
        slugs = [tag.slug for tag in container.work_tags.for_record(actor, "task", task.id)]
        structured = TaskOutput(
            task=TaskRecord.model_validate(with_tags(task_public_data(task), slugs))
        ).model_dump(mode="json")
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
    ) -> Any:
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
            "Mark one owned task complete using its current version. Repeating the same "
            "idempotency key safely returns the committed result."
        ),
        output_schema=output_schema(TaskOutput),
        annotations=WRITE,
    )
    @ctx.instrument("complete_task")
    def complete_task(
        task_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        structured = complete_task_structured(
            ctx.container,
            ctx.actor_provider(),
            task_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return _task_reply(structured, "Completed")


_REGISTRARS = (
    _register_get_task,
    _register_create_task,
    _register_update_task,
    _register_complete_task,
)


def register_task_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    for register in _REGISTRARS:
        register(mcp, ctx)

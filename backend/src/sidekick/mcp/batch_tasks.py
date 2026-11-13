"""create_tasks: 1 to 20 Tasks, each with up to 10 ordered Steps, in one atomic, retry-safe call.

`create_tasks` calls `TaskBulkService.create_batch`, which runs every Task through the same
`create_in_session` as `create_task` and saves its Steps in the same session. Any failing item
rejects the whole call, so a photographed whiteboard becomes one Project with all its Tasks, or
nothing. A bare due date becomes 23:59 in the owner's zone through `end_of_day_due_at`, as in
create_task.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field

from sidekick.mcp.annotations import WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.text_guard import NoImageData
from sidekick.structured.base import Output
from sidekick.structured.work_records import (
    DueAtInput,
    TaskRecord,
    WritePriority,
    end_of_day_due_at,
)
from sidekick.tasks.application.models import (
    MAX_BATCH_CREATE_TASKS,
    MAX_BATCH_STEPS_PER_TASK,
    NewTaskItem,
)
from sidekick.tasks.application.serialization import task_public_data
from sidekick.tasks.domain import Priority
from sidekick.work.domain.planning import MAX_TAGS_PER_RECORD


class BatchTaskInput(Output):
    """One Task of the batch; `steps` are step titles, created in the order given."""

    title: Annotated[str, Field(min_length=1, max_length=200), NoImageData]
    due_at: DueAtInput = None
    priority: WritePriority = "normal"
    tags: Annotated[
        list[Annotated[str, NoImageData]] | None,
        Field(max_length=MAX_TAGS_PER_RECORD),
    ] = None
    steps: list[Annotated[str, Field(min_length=1, max_length=200), NoImageData]] = Field(
        default_factory=list, max_length=MAX_BATCH_STEPS_PER_TASK
    )


class BatchStepRecord(Output):
    id: UUID
    title: str
    position: int
    version: int


class CreatedTaskRecord(TaskRecord):
    """A created Task as create_task returns it, plus its Steps in creation order."""

    steps: list[BatchStepRecord] = Field(default_factory=list[BatchStepRecord])


class CreateTasksOutput(Output):
    count: int
    tasks: list[CreatedTaskRecord]


def _line(record: CreatedTaskRecord) -> str:
    title = " ".join(record.title.split())
    return f"{record.id} v{record.version}: {title}"


def register_batch_task_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register `create_tasks`; it opens no app card."""

    @mcp.tool(
        name="create_tasks",
        description=(
            "Use this when the user wants several new tasks at once, for example from a photo "
            "of a whiteboard or a list. Pass 1 to 20 tasks, each with a title and optional "
            "due_at, priority, tags and up to 10 ordered step titles. Pass project_id or "
            "domain_id to file all of them there. The whole call fails if any item is invalid, "
            "so nothing is created. due_at is an ISO datetime with an offset, or a bare date "
            "(YYYY-MM-DD) meaning 23:59 in the owner's zone. Retry-safe with the same "
            "idempotency key."
        ),
        output_schema=output_schema(CreateTasksOutput),
        annotations=WRITE,
    )
    @ctx.instrument("create_tasks")
    def create_tasks(
        tasks: Annotated[
            list[BatchTaskInput], Field(min_length=1, max_length=MAX_BATCH_CREATE_TASKS)
        ],
        idempotency_key: IdempotencyKey,
        project_id: UUID | None = None,
        domain_id: UUID | None = None,
    ) -> Any:
        actor = ctx.actor_provider()
        # The reply lists each task's tags (projects:read), so refuse before anything is written.
        ctx.container.work_tags.require_record_tags_readable(actor, "task")
        zone = ctx.container.settings.owner_zone
        batch = ctx.container.task_bulk.create_batch(
            actor,
            [
                NewTaskItem(
                    title=item.title,
                    due_at=end_of_day_due_at(item.due_at, zone),
                    priority=Priority(item.priority),
                    tags=tuple(item.tags or ()),
                    step_titles=tuple(item.steps),
                )
                for item in tasks
            ],
            idempotency_key=idempotency_key,
            project_id=project_id,
            domain_id=domain_id,
            correlation_id=request_correlation_id_or_new(),
        )
        records: list[CreatedTaskRecord] = []
        for created in batch.tasks:
            tags = ctx.container.work_tags.for_record(actor, "task", created.task.id)
            data = {
                **task_public_data(created.task),
                "tags": [tag.slug for tag in tags],
                "steps": list(created.steps),
            }
            records.append(CreatedTaskRecord.model_validate(data))
        structured = CreateTasksOutput(count=len(records), tasks=records).model_dump(mode="json")
        noun = "task" if len(records) == 1 else "tasks"
        if batch.container_label:
            head = f"Created {len(records)} {noun} in {batch.container_label}."
        else:
            head = f"Created {len(records)} {noun}."
        return result(structured, "\n".join([head, *(_line(record) for record in records)]))

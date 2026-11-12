"""The Step and Action tools."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import BaseModel, Field

from sidekick.mcp.annotations import READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.tool_context import ToolContext
from sidekick.mcp.work_text import cell, found_sentence, list_text, record_ref, spoken_line
from sidekick.shared.types import MAX_CURSOR_LENGTH, UNSET
from sidekick.structured.work import (
    action_record,
    complete_step_structured,
    step_record,
    task_steps_structured,
)
from sidekick.structured.work_records import (
    ActionChanges,
    ActionOutput,
    ActionPageOutput,
    ActionRecord,
    ReorderItem,
    StepChanges,
    StepOutput,
    StepPageOutput,
)
from sidekick.work.application.steps_service import MAX_REORDER_STEPS

# Parameter types shared by several tools; the JSON schema each produces is pinned by the contract.
_Limit100 = Annotated[int, Field(ge=1, le=100)]
_Cursor = Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)]
_Version = Annotated[int, Field(ge=1)]
_Title = Annotated[str, Field(min_length=1, max_length=200)]
_ReorderSteps = Annotated[list[ReorderItem], Field(min_length=1, max_length=MAX_REORDER_STEPS)]
# An Action reorder still reads one page of 100 Actions, so its input stays at 100.
_ReorderActions = Annotated[list[ReorderItem], Field(min_length=1, max_length=100)]

_PARENT_KEY = {"step": "task_id", "action": "step_id"}
_PARENT_KIND = {"step": "task", "action": "step"}


def _record_reply(kind: str, verb: str, record: dict[str, Any]) -> Any:
    """A Step or Action result with one spoken line naming it and its parent."""

    return result(
        {kind: record},
        spoken_line(
            f"{verb} {kind} {cell(record['title'])}.",
            record_ref(record, parent=(_PARENT_KIND[kind], record[_PARENT_KEY[kind]])),
        ),
    )


def _changed(changes: BaseModel, *names: str) -> dict[str, Any]:
    """The named fields the caller set; the rest are UNSET, so an explicit null still applies."""

    fields = changes.model_dump()
    return {name: fields[name] if name in changes.model_fields_set else UNSET for name in names}


def _register_list_task_steps(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_task_steps",
        description="List bounded ordered Steps for one owned Task; next_cursor continues.",
        output_schema=output_schema(StepPageOutput),
        annotations=READ,
    )
    @ctx.instrument("list_task_steps")
    def list_task_steps(task_id: UUID, limit: _Limit100 = 100, cursor: _Cursor = None) -> Any:
        data = task_steps_structured(
            ctx.container, ctx.actor_provider(), task_id, limit=limit, cursor=cursor
        )
        return result(
            data,
            list_text(
                found_sentence(
                    len(data["items"]),
                    "step",
                    "steps",
                    [item["title"] for item in data["items"]],
                ),
                data["items"],
                locale=ctx.container.settings.mcp_app_locale,
            ),
        )


def _register_list_step_actions(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_step_actions",
        description=(
            "List bounded display-ordered Actions for one owned Step; next_cursor continues."
        ),
        output_schema=output_schema(ActionPageOutput),
        annotations=READ,
    )
    @ctx.instrument("list_step_actions")
    def list_step_actions(step_id: UUID, limit: _Limit100 = 100, cursor: _Cursor = None) -> Any:
        page = ctx.container.steps.list_actions(
            ctx.actor_provider(), step_id, limit=limit, cursor=cursor
        )
        data: dict[str, Any] = {
            "items": [
                ActionRecord.model_validate(
                    {
                        "id": x.id,
                        "step_id": x.step_id,
                        "title": x.title,
                        "status": x.status.value,
                        "position": x.position,
                        "due_at": x.due_at,
                        "version": x.version,
                        "attention_requested": x.attention_requested,
                        "archived_at": x.archived_at,
                    }
                ).model_dump(mode="json")
                for x in page.items
            ],
            "next_cursor": page.next_cursor,
        }
        return result(
            data,
            list_text(
                found_sentence(
                    len(page.items),
                    "action",
                    "actions",
                    [item["title"] for item in data["items"]],
                ),
                data["items"],
                locale=ctx.container.settings.mcp_app_locale,
            ),
        )


def _register_create_task_step(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="create_task_step",
        description="Create an ordered Step under one owned Task with a retry-safe key.",
        output_schema=output_schema(StepOutput),
        annotations=WRITE,
    )
    @ctx.instrument("create_task_step")
    def create_task_step(
        task_id: UUID,
        title: _Title,
        idempotency_key: IdempotencyKey,
        due_at: datetime | None = None,
    ) -> Any:
        step = ctx.container.steps.create_step(
            ctx.actor_provider(),
            task_id,
            title=title,
            due_at=due_at,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = {
            "id": str(step.id),
            "task_id": str(step.task_id),
            "title": step.title,
            "status": step.status.value,
            "position": step.position,
            "due_at": step.due_at,
            "version": step.version,
            "attention_requested": step.attention_requested,
            "archived_at": step.archived_at,
        }
        return _record_reply("step", "Created", record)


def _register_create_step_action(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="create_step_action",
        description="Create an ordered Action under one owned Step with a retry-safe key.",
        output_schema=output_schema(ActionOutput),
        annotations=WRITE,
    )
    @ctx.instrument("create_step_action")
    def create_step_action(
        step_id: UUID,
        title: _Title,
        idempotency_key: IdempotencyKey,
        due_at: datetime | None = None,
    ) -> Any:
        action = ctx.container.steps.create_action(
            ctx.actor_provider(),
            step_id,
            title=title,
            due_at=due_at,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = {
            "id": str(action.id),
            "step_id": str(action.step_id),
            "title": action.title,
            "status": action.status.value,
            "position": action.position,
            "due_at": action.due_at,
            "version": action.version,
            "attention_requested": action.attention_requested,
            "archived_at": action.archived_at,
        }
        return _record_reply("action", "Created", record)


def _register_update_task_step(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="update_task_step",
        description="Update a Step with optimistic version checking.",
        output_schema=output_schema(StepOutput),
        annotations=WRITE,
    )
    @ctx.instrument("update_task_step")
    def update_task_step(
        step_id: UUID,
        version: _Version,
        changes: StepChanges,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        step = ctx.container.steps.update_step(
            ctx.actor_provider(),
            step_id,
            version=version,
            idempotency_key=idempotency_key,
            **_changed(changes, "title", "status", "due_at", "attention_requested"),
            correlation_id=request_correlation_id_or_new(),
        )
        record = step_record(step)
        return _record_reply("step", "Updated", record)


def _register_complete_task_step(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="complete_task_step",
        description="Complete a Step with optimistic version checking.",
        output_schema=output_schema(StepOutput),
        annotations=WRITE,
    )
    @ctx.instrument("complete_task_step")
    def complete_task_step(
        step_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        structured = complete_step_structured(
            ctx.container,
            ctx.actor_provider(),
            step_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = structured["step"]
        return result(
            structured,
            spoken_line(
                f"Completed step {cell(record['title'])}.",
                record_ref(record, parent=("task", record["task_id"])),
            ),
        )


def _register_archive_task_step(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="archive_task_step",
        description="Archive a Step with optimistic version checking.",
        output_schema=output_schema(StepOutput),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("archive_task_step")
    def archive_task_step(
        step_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        step = ctx.container.steps.archive_step(
            ctx.actor_provider(),
            step_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = step_record(step)
        return _record_reply("step", "Archived", record)


def _register_restore_task_step(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="restore_task_step",
        description="Restore a Step with optimistic version checking.",
        output_schema=output_schema(StepOutput),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("restore_task_step")
    def restore_task_step(
        step_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        step = ctx.container.steps.restore_step(
            ctx.actor_provider(),
            step_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = step_record(step)
        return _record_reply("step", "Restored", record)


def _register_reorder_task_steps(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="reorder_task_steps",
        description="Reorder every active Step atomically with version checks.",
        output_schema=output_schema(StepPageOutput),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("reorder_task_steps")
    def reorder_task_steps(
        task_id: UUID,
        items: _ReorderSteps,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        page = ctx.container.steps.reorder_steps(
            ctx.actor_provider(),
            task_id,
            items=[(item.id, item.version) for item in items],
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return result(
            {"items": [step_record(item) for item in page.items], "next_cursor": page.next_cursor},
            f"Reordered {len(page.items)} steps in task {task_id}.",
        )


def _register_update_step_action(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="update_step_action",
        description="Update an Action with optimistic version checking.",
        output_schema=output_schema(ActionOutput),
        annotations=WRITE,
    )
    @ctx.instrument("update_step_action")
    def update_step_action(
        action_id: UUID,
        version: _Version,
        changes: ActionChanges,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        action = ctx.container.steps.update_action(
            ctx.actor_provider(),
            action_id,
            version=version,
            idempotency_key=idempotency_key,
            **_changed(changes, "title", "due_at", "attention_requested"),
            correlation_id=request_correlation_id_or_new(),
        )
        record = action_record(action)
        return _record_reply("action", "Updated", record)


def _register_complete_step_action(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="complete_step_action",
        description="Complete an Action with optimistic version checking.",
        output_schema=output_schema(ActionOutput),
        annotations=WRITE,
    )
    @ctx.instrument("complete_step_action")
    def complete_step_action(
        action_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        action = ctx.container.steps.complete_action(
            ctx.actor_provider(),
            action_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = action_record(action)
        return _record_reply("action", "Completed", record)


def _register_archive_step_action(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="archive_step_action",
        description="Archive an Action with optimistic version checking.",
        output_schema=output_schema(ActionOutput),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("archive_step_action")
    def archive_step_action(
        action_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        action = ctx.container.steps.archive_action(
            ctx.actor_provider(),
            action_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = action_record(action)
        return _record_reply("action", "Archived", record)


def _register_restore_step_action(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="restore_step_action",
        description="Restore an Action with optimistic version checking.",
        output_schema=output_schema(ActionOutput),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("restore_step_action")
    def restore_step_action(
        action_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        action = ctx.container.steps.restore_action(
            ctx.actor_provider(),
            action_id,
            version=version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        record = action_record(action)
        return _record_reply("action", "Restored", record)


def _register_reorder_step_actions(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="reorder_step_actions",
        description="Reorder every active Action atomically with version checks.",
        output_schema=output_schema(ActionPageOutput),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("reorder_step_actions")
    def reorder_step_actions(
        step_id: UUID,
        items: _ReorderActions,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        page = ctx.container.steps.reorder_actions(
            ctx.actor_provider(),
            step_id,
            items=[(item.id, item.version) for item in items],
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return result(
            {
                "items": [action_record(item) for item in page.items],
                "next_cursor": page.next_cursor,
            },
            f"Reordered {len(page.items)} actions in step {step_id}.",
        )


_REGISTRARS = (
    _register_list_task_steps,
    _register_list_step_actions,
    _register_create_task_step,
    _register_create_step_action,
    _register_update_task_step,
    _register_complete_task_step,
    _register_archive_task_step,
    _register_restore_task_step,
    _register_reorder_task_steps,
    _register_update_step_action,
    _register_complete_step_action,
    _register_archive_step_action,
    _register_restore_step_action,
    _register_reorder_step_actions,
)


def register_step_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the Step and Action tools."""
    for register in _REGISTRARS:
        register(mcp, ctx)

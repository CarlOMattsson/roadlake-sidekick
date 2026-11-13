"""The Contact link tools: relate a Contact to a Project or a Task, and remove the relation."""

# En dashes are intentional human-facing tool copy preserved by contract snapshots.
# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult

from sidekick.mcp.annotations import DESTRUCTIVE, WRITE
from sidekick.mcp.contact_records import ProjectContactResult, TaskContactResult
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.text import flat
from sidekick.mcp.tool_context import ToolContext


def _linked_contact_name(ctx: ToolContext, contact_id: UUID) -> str:
    """The Contact's name for a link reply. Without contacts:read the reply stays generic."""
    actor = ctx.actor_provider()
    if "contacts:read" not in actor.scopes:
        return "the Contact"
    return flat(ctx.container.contacts.get(actor, contact_id).display_name)


def _project_link_result(res: Mapping[str, object]) -> dict[str, object]:
    return ProjectContactResult(
        contact_id=UUID(str(res["contact_id"])),
        project_id=UUID(str(res["project_id"])),
        linked=bool(res["linked"]),
    ).model_dump(mode="json")


def _task_link_result(res: Mapping[str, object]) -> dict[str, object]:
    return TaskContactResult(
        contact_id=UUID(str(res["contact_id"])),
        task_id=UUID(str(res["task_id"])),
        linked=bool(res["linked"]),
    ).model_dump(mode="json")


def _register_link_contact_to_project(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="link_contact_to_project",
        description=(
            "Use this after the Contact and Project ids are known, for example from list_contacts, "
            "create_contact, list_projects or get_work_hierarchy. "
            "It records that the Project involves the Contact; it does not alter either "
            "record or contact an external system."
        ),
        output_schema=output_schema(ProjectContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("link_contact_to_project")
    def link_contact_to_project(
        contact_id: UUID, project_id: UUID, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        res = ctx.container.contact_relations.link_project(
            ctx.actor_provider(),
            contact_id=contact_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        name = _linked_contact_name(ctx, contact_id)
        return result(_project_link_result(res), f"Linked {name} and the Project.")


def _register_unlink_contact_from_project(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="unlink_contact_from_project",
        description=(
            "Use this only when the user wants to remove the known Contact–Project relation. "
            "It deletes the semantic link but does not delete or edit the Contact or Project."
        ),
        output_schema=output_schema(ProjectContactResult),
        annotations=DESTRUCTIVE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("unlink_contact_from_project")
    def unlink_contact_from_project(
        contact_id: UUID, project_id: UUID, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        res = ctx.container.contact_relations.unlink_project(
            ctx.actor_provider(),
            contact_id=contact_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return result(_project_link_result(res), "Removed the Contact–Project link.")


def _register_link_contact_to_task(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="link_contact_to_task",
        description=(
            "Use this after the Contact and Task ids are known, for example from list_contacts, "
            "create_contact, list_projects or get_work_hierarchy. "
            "It records that the Task concerns the Contact; it does not alter either "
            "record or contact an external system."
        ),
        output_schema=output_schema(TaskContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("link_contact_to_task")
    def link_contact_to_task(
        contact_id: UUID, task_id: UUID, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        res = ctx.container.contact_relations.link_task(
            ctx.actor_provider(),
            contact_id=contact_id,
            task_id=task_id,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        name = _linked_contact_name(ctx, contact_id)
        return result(_task_link_result(res), f"Linked {name} and the Task.")


def _register_unlink_contact_from_task(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="unlink_contact_from_task",
        description=(
            "Use this only when the user wants to remove the known Contact–Task relation. "
            "It deletes the semantic link but does not delete or edit the Contact or Task."
        ),
        output_schema=output_schema(TaskContactResult),
        annotations=DESTRUCTIVE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("unlink_contact_from_task")
    def unlink_contact_from_task(
        contact_id: UUID, task_id: UUID, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        res = ctx.container.contact_relations.unlink_task(
            ctx.actor_provider(),
            contact_id=contact_id,
            task_id=task_id,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return result(_task_link_result(res), "Removed the Contact–Task link.")


def register_contact_link_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the four Contact link tools."""

    _register_link_contact_to_project(mcp, ctx)
    _register_unlink_contact_from_project(mcp, ctx)
    _register_link_contact_to_task(mcp, ctx)
    _register_unlink_contact_from_task(mcp, ctx)

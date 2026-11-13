"""The Project, Domain and Process tools."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import BaseModel, Field

from sidekick.mcp.annotations import READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import card_result, output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import (
    EMPTY_WORK_NOTE,
)
from sidekick.mcp.tool_context import ToolContext
from sidekick.mcp.work_text import (
    TextRow,
    cell,
    found_sentence,
    list_text,
    project_detail_lines,
    record_card_text,
    record_ref,
    spoken_line,
    work_item_sentence,
)
from sidekick.projects.application import UpdateProjectCommand
from sidekick.projects.application.service import project_public_data
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.types import MAX_CURSOR_LENGTH, Actor
from sidekick.structured.work import (
    domain_structured,
    process_structured,
    project_detail_structured,
    with_description_excerpt,
    with_tags,
)
from sidekick.structured.work_records import (
    DOMAIN_ACCENT_DESCRIPTION,
    DomainAccent,
    DomainChanges,
    DomainOutput,
    DomainPageOutput,
    DomainRecord,
    ProcessChanges,
    ProcessOutput,
    ProcessPageOutput,
    ProcessRecord,
    ProjectChanges,
    ProjectDetailOutput,
    ProjectListRecord,
    ProjectOutput,
    ProjectPageOutput,
    ProjectRecord,
)
from sidekick.work.application.models import UpdateContextCommand
from sidekick.work.application.serialization import domain_public_data, process_public_data

# Parameter types shared by several tools; the JSON schema each produces is pinned by the contract.
_Limit100 = Annotated[int, Field(ge=1, le=100)]
_Cursor = Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)]
_Version = Annotated[int, Field(ge=1)]
_Name = Annotated[str, Field(min_length=1, max_length=200)]
_Description = Annotated[str | None, Field(max_length=10_000)]


def _tag_safe_patch(ctx: ToolContext, actor: Actor, changes: BaseModel) -> dict[str, Any]:
    """The explicit changes of an update, refused before anything is written without tag access.

    The reply lists the record's tags (projects:read), so the actor must be able to read them.
    """

    ctx.container.work_tags.require_record_tags_readable(actor, "project")
    patch = changes.model_dump(exclude_unset=True)
    if "tags" in patch:
        patch["tags"] = tuple(patch["tags"] or ())
    return patch


def _register_list_projects(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_projects",
        description=(
            "Use this for a bounded list of the user's projects. Rows have description_excerpt "
            "(about 160 characters) and description_truncated; when true, call get_project for "
            "the full text. Not for tasks or other users' data."
        ),
        output_schema=output_schema(ProjectPageOutput),
        annotations=READ,
    )
    @ctx.instrument("list_projects")
    def list_projects(
        limit: _Limit100 = 25,
        status: ProjectStatus | None = None,
        cursor: _Cursor = None,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        page = ctx.container.projects.list(actor, limit=limit, status=status, cursor=cursor)
        slugs = ctx.container.work_tags.slug_map(actor)
        structured = ProjectPageOutput(
            projects=[
                ProjectListRecord.model_validate(
                    with_description_excerpt(
                        with_tags(
                            project_public_data(item), list(slugs.get(("project", item.id), ()))
                        )
                    )
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
        )
        return result(
            structured.model_dump(mode="json"),
            list_text(
                found_sentence(
                    len(page.items),
                    "project",
                    "projects",
                    [project.title for project in structured.projects],
                ),
                [
                    TextRow(p.id, p.title, version=p.version, status=p.status)
                    for p in structured.projects
                ],
                locale=ctx.container.settings.mcp_app_locale,
            ),
        )


def _register_get_project(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="get_project",
        description=(
            "Get one owned project by its Sidekick UUID, including its current fields. "
            "Returns no cross-user existence detail."
        ),
        output_schema=output_schema(ProjectDetailOutput),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_project")
    def get_project(project_id: UUID) -> ToolResult:
        actor = ctx.actor_provider()
        structured, project = project_detail_structured(ctx.container, actor, project_id)
        record = structured.project
        sentence = work_item_sentence(
            "Project",
            record.title,
            project.status.value,
            project.target_date,
            label="target date",
            today=datetime.now(ctx.container.settings.owner_zone).date(),
        )
        return card_result(
            structured.model_dump(mode="json"),
            record_card_text(
                sentence,
                record_ref(
                    record.id, record.version, record.title, parent=("domain", record.domain_id)
                ),
                project_detail_lines(record),
            ),
        )


def _register_create_project(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="create_project",
        description=(
            "Use this when the user wants a new project. A project requires a domain_id: find "
            "the Domain with list_domains and ask if several match. This writes durable state "
            "and requires a retry-safe idempotency key."
        ),
        output_schema=output_schema(ProjectOutput),
        annotations=WRITE,
    )
    @ctx.instrument("create_project")
    def create_project(
        domain_id: UUID,
        title: Annotated[str, Field(min_length=1, max_length=200)],
        idempotency_key: IdempotencyKey,
        description: _Description = None,
        start_date: date | None = None,
        target_date: date | None = None,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        # The reply lists the record's tags (projects:read); refuse before anything is written.
        ctx.container.work_tags.require_record_tags_readable(actor, "project")
        project = ctx.container.projects.create(
            actor,
            title=title,
            domain_id=domain_id,
            description=description,
            start_date=start_date,
            target_date=target_date,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        slugs = [
            tag.slug for tag in ctx.container.work_tags.for_record(actor, "project", project.id)
        ]
        structured = ProjectOutput(
            project=ProjectRecord.model_validate(with_tags(project_public_data(project), slugs))
        )
        record = structured.project
        return result(
            structured.model_dump(mode="json"),
            spoken_line(
                f"Created project {cell(record.title)}.",
                record_ref(
                    record.id, record.version, record.title, parent=("domain", record.domain_id)
                ),
            ),
        )


def _register_update_project(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="update_project",
        description=(
            "Update explicit fields of one owned project at its current version; retry-safe with "
            "the same idempotency key."
        ),
        output_schema=output_schema(ProjectOutput),
        annotations=WRITE,
    )
    @ctx.instrument("update_project")
    def update_project(
        project_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
        changes: ProjectChanges,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        patch = _tag_safe_patch(ctx, actor, changes)
        project = ctx.container.projects.update(
            actor,
            project_id,
            version=version,
            idempotency_key=idempotency_key,
            command=UpdateProjectCommand(**patch),
            correlation_id=request_correlation_id_or_new(),
        )
        slugs = [
            tag.slug for tag in ctx.container.work_tags.for_record(actor, "project", project_id)
        ]
        structured = ProjectOutput(
            project=ProjectRecord.model_validate(with_tags(project_public_data(project), slugs))
        )
        record = structured.project
        return result(
            structured.model_dump(mode="json"),
            spoken_line(
                f"Updated project {cell(record.title)}.",
                record_ref(
                    record.id, record.version, record.title, parent=("domain", record.domain_id)
                ),
            ),
        )


def _register_list_domains(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_domains",
        description="List bounded domains owned by the authenticated user.",
        output_schema=output_schema(DomainPageOutput),
        annotations=READ,
    )
    @ctx.instrument("list_domains")
    def list_domains(
        limit: _Limit100 = 25,
        cursor: _Cursor = None,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        page = ctx.container.contexts.list_domains(actor, limit=limit, cursor=cursor)
        slugs = ctx.container.work_tags.slug_map(actor)
        structured = DomainPageOutput(
            domains=[
                DomainRecord.model_validate(
                    domain_public_data(item, list(slugs.get(("domain", item.id), ())))
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
        )
        text = list_text(
            found_sentence(
                len(page.items),
                "domain",
                "domains",
                [domain.name for domain in structured.domains],
            ),
            [TextRow(d.id, d.name, version=d.version, status=d.status) for d in structured.domains],
            locale=ctx.container.settings.mcp_app_locale,
        )
        if not page.items:
            text = f"{text}\n{EMPTY_WORK_NOTE}"
        return result(structured.model_dump(mode="json"), text)


def _register_get_domain(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="get_domain",
        description="Get one owned domain by its Sidekick UUID.",
        output_schema=output_schema(DomainOutput),
        annotations=READ,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("get_domain")
    def get_domain(domain_id: UUID) -> ToolResult:
        actor = ctx.actor_provider()
        structured = domain_structured(ctx.container, actor, domain_id)
        record = structured.domain
        return result(
            structured.model_dump(mode="json"),
            spoken_line(
                f"Domain {cell(record.name)}.",
                record_ref(record.id, record.version, record.name),
            ),
        )


def _register_create_domain(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="create_domain",
        description=(
            "Use this when the user wants a new Domain, the top-level area that groups Projects "
            "and Processes; create it before a Project that needs it. Owner-scoped, with a "
            "retry-safe idempotency key."
        ),
        output_schema=output_schema(DomainOutput),
        annotations=WRITE,
    )
    @ctx.instrument("create_domain")
    def create_domain(
        name: _Name,
        idempotency_key: IdempotencyKey,
        description: _Description = None,
        accent: Annotated[DomainAccent | None, Field(description=DOMAIN_ACCENT_DESCRIPTION)] = None,
    ) -> ToolResult:
        domain = ctx.container.contexts.create_domain(
            ctx.actor_provider(),
            name=name,
            description=description,
            idempotency_key=idempotency_key,
            accent=accent,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = DomainOutput(domain=DomainRecord.model_validate(domain_public_data(domain)))
        record = structured.domain
        return result(
            structured.model_dump(mode="json"),
            spoken_line(
                f"Created domain {cell(record.name)}.",
                record_ref(record.id, record.version, record.name),
            ),
        )


def _register_update_domain(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="update_domain",
        description=(
            "Update explicit fields of one owned domain at its current version; retry-safe with "
            "the same idempotency key."
        ),
        output_schema=output_schema(DomainOutput),
        annotations=WRITE,
    )
    @ctx.instrument("update_domain")
    def update_domain(
        domain_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
        changes: DomainChanges,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        patch = _tag_safe_patch(ctx, actor, changes)
        domain = ctx.container.contexts.update_domain(
            actor,
            domain_id,
            version=version,
            idempotency_key=idempotency_key,
            command=UpdateContextCommand(**patch),
            correlation_id=request_correlation_id_or_new(),
        )
        slugs = [tag.slug for tag in ctx.container.work_tags.for_record(actor, "domain", domain_id)]
        structured = DomainOutput(
            domain=DomainRecord.model_validate(domain_public_data(domain, slugs))
        )
        record = structured.domain
        return result(
            structured.model_dump(mode="json"),
            spoken_line(
                f"Updated domain {cell(record.name)}.",
                record_ref(record.id, record.version, record.name),
            ),
        )


def _register_create_process(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="create_process",
        description=(
            "Create one ongoing Process under an owned Domain with a retry-safe idempotency key."
        ),
        output_schema=output_schema(ProcessOutput),
        annotations=WRITE,
    )
    @ctx.instrument("create_process")
    def create_process(
        domain_id: UUID,
        name: _Name,
        idempotency_key: IdempotencyKey,
        description: _Description = None,
    ) -> ToolResult:
        process = ctx.container.contexts.create_process(
            ctx.actor_provider(),
            domain_id=domain_id,
            name=name,
            description=description,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = ProcessOutput(
            process=ProcessRecord.model_validate(process_public_data(process))
        )
        record = structured.process
        ref = record_ref(
            record.id, record.version, record.name, parent=("domain", record.domain_id)
        )
        return result(
            structured.model_dump(mode="json"),
            spoken_line(f"Created process {cell(record.name)}.", ref),
        )


def _register_update_process(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="update_process",
        description=(
            "Update explicit fields of one owned Process at its current version; retry-safe with "
            "the same idempotency key."
        ),
        output_schema=output_schema(ProcessOutput),
        annotations=WRITE,
    )
    @ctx.instrument("update_process")
    def update_process(
        process_id: UUID,
        version: _Version,
        idempotency_key: IdempotencyKey,
        changes: ProcessChanges,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        patch = _tag_safe_patch(ctx, actor, changes)
        process = ctx.container.contexts.update_process(
            actor,
            process_id,
            version=version,
            idempotency_key=idempotency_key,
            command=UpdateContextCommand(**patch),
            correlation_id=request_correlation_id_or_new(),
        )
        slugs = [
            tag.slug for tag in ctx.container.work_tags.for_record(actor, "process", process_id)
        ]
        structured = ProcessOutput(
            process=ProcessRecord.model_validate(process_public_data(process, slugs))
        )
        record = structured.process
        ref = record_ref(
            record.id, record.version, record.name, parent=("domain", record.domain_id)
        )
        return result(
            structured.model_dump(mode="json"),
            spoken_line(f"Updated process {cell(record.name)}.", ref),
        )


def _register_list_processes(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_processes",
        description=(
            "List bounded ongoing Processes owned by the authenticated user, optionally by Domain."
        ),
        output_schema=output_schema(ProcessPageOutput),
        annotations=READ,
    )
    @ctx.instrument("list_processes")
    def list_processes(
        domain_id: UUID | None = None,
        limit: _Limit100 = 25,
        cursor: _Cursor = None,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        page = ctx.container.contexts.list_processes(
            actor, domain_id=domain_id, limit=limit, cursor=cursor
        )
        slugs = ctx.container.work_tags.slug_map(actor)
        structured = ProcessPageOutput(
            processes=[
                ProcessRecord.model_validate(
                    process_public_data(item, list(slugs.get(("process", item.id), ())))
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
        )
        return result(
            structured.model_dump(mode="json"),
            list_text(
                found_sentence(
                    len(page.items),
                    "process",
                    "processes",
                    [process.name for process in structured.processes],
                ),
                [
                    TextRow(p.id, p.name, version=p.version, status=p.status)
                    for p in structured.processes
                ],
                locale=ctx.container.settings.mcp_app_locale,
            ),
        )


def _register_get_process(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="get_process",
        description="Get one owned Process by its Sidekick UUID.",
        output_schema=output_schema(ProcessOutput),
        annotations=READ,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("get_process")
    def get_process(process_id: UUID) -> ToolResult:
        actor = ctx.actor_provider()
        structured = process_structured(ctx.container, actor, process_id)
        record = structured.process
        return result(
            structured.model_dump(mode="json"),
            spoken_line(
                f"Process {cell(record.name)}.",
                record_ref(
                    record.id,
                    record.version,
                    record.name,
                    parent=("domain", record.domain_id),
                ),
            ),
        )


_REGISTRARS = (
    _register_list_projects,
    _register_get_project,
    _register_create_project,
    _register_update_project,
    _register_list_domains,
    _register_get_domain,
    _register_create_domain,
    _register_update_domain,
    _register_create_process,
    _register_update_process,
    _register_list_processes,
    _register_get_process,
)


def register_project_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the Project, Domain and Process tools."""
    for register in _REGISTRARS:
        register(mcp, ctx)

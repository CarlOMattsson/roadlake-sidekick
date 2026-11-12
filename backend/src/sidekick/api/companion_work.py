"""`/companion/v1/` read routes of Work: agenda, Today, hierarchy, Projects, Domains, Processes.

Added to the companion router by `create_companion_router` (sidekick.api.companion), which also
supplies the route class, so every refusal here is the same versioned problem envelope and the
request log carries only the operation name and the outcome. Each route verifies the credential,
checks the operation's capability, and calls one fixed use case with its scopes. The routes are
listed in the module docstring of `sidekick.api.companion`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from sidekick.api.companion import (
    API_VERSION,
    CompanionRouter,
    CompanionRouteSpec,
    credential_for,
    iso,
    no_store_headers,
)
from sidekick.companion.operations import (
    DOMAIN_DETAIL,
    PROCESS_DETAIL,
    PROJECT_DETAIL,
    PROJECT_TASKS,
    WORK_AGENDA,
    WORK_HIERARCHY,
    WORK_TODAY,
    operation_actor,
)
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.work import (
    WorkAgendaArguments,
    domain_structured,
    process_structured,
    project_detail_structured,
    task_page_structured,
    work_agenda_structured,
    work_hierarchy_structured,
)
from sidekick.tasks.domain import Priority, TaskStatus
from sidekick.work.application.models import WorkToday
from sidekick.work.domain import MAX_ESTIMATED_MINUTES, MAX_TAG_FILTER_VALUES

DEFAULT_TODAY_LIMIT = 20
MAX_TODAY_LIMIT = 50


def _today_json(today: WorkToday, timezone: str, limit: int) -> dict[str, Any]:
    """The widget's Idag: ids, titles, versions and markers only; no description or contact."""

    return {
        "api_version": API_VERSION,
        "day": today.day.isoformat(),
        "timezone": timezone,
        "calculated_at": today.calculated_at.isoformat(),
        "limit": limit,
        "total": today.total,
        "overdue_total": today.overdue_total,
        "today_total": today.today_total,
        "has_more": today.next_cursor is not None,
        "next_cursor": today.next_cursor,
        "items": [
            {
                "id": str(item.id),
                "title": item.title,
                "version": item.version,
                "status": item.status,
                "group": item.agenda_group,
                "due_at": iso(item.due_at),
                "project_title": item.project_title,
            }
            for item in today.items
        ],
    }


async def work_agenda(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: TaskStatus | None = None,
    priority: Priority | None = None,
    attention: Literal["all", "requested"] = "all",
    archive: Literal["active", "archived", "all"] = "active",
    kind: Literal["all", "domain", "process", "project", "task", "step", "action"] = "all",
    sort: Literal[
        "updated_desc",
        "due_asc",
        "title_asc",
        "priority_desc",
        "not_before_asc",
        "estimate_asc",
    ] = "due_asc",
    group: Literal["none", "kind", "status", "context"] = "none",
    tags: Annotated[list[str] | None, Query(max_length=MAX_TAG_FILTER_VALUES)] = None,
    tag_match: Literal["any", "all"] = "any",
    actionable: Literal["all", "now", "later"] = "all",
    waiting: Literal["all", "waiting", "not_waiting"] = "all",
    estimate: Literal["all", "estimated", "unestimated"] = "all",
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
    max_minutes: Annotated[int | None, Query(ge=1, le=MAX_ESTIMATED_MINUTES)] = None,
    include_undated: bool = False,
) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, WORK_AGENDA)
    arguments = WorkAgendaArguments(
        limit=limit,
        q=q,
        status=status,
        priority=priority,
        attention=attention,
        archive=archive,
        kind=kind,
        sort=sort,
        group=group,
        tags=tuple(tags) if tags is not None else None,
        tag_match=tag_match,
        actionable=actionable,
        waiting=waiting,
        estimate=estimate,
        cursor=cursor,
        max_minutes=max_minutes,
        include_undated=include_undated,
    )
    container = request.app.state.container
    structured = await run_in_threadpool(work_agenda_structured, container, actor, arguments)
    return JSONResponse(headers=no_store_headers, content=structured)


async def work_today(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=MAX_TODAY_LIMIT)] = DEFAULT_TODAY_LIMIT,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, WORK_TODAY)
    container = request.app.state.container
    today = await run_in_threadpool(
        lambda: container.work_lists.work_today_page(actor, limit=limit, cursor=cursor)
    )
    return JSONResponse(
        headers=no_store_headers,
        content=_today_json(today, container.settings.owner_timezone, limit),
    )


async def work_hierarchy(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    include_tasks: bool = False,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
    process_id: UUID | None = None,
) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, WORK_HIERARCHY)
    container = request.app.state.container
    structured = await run_in_threadpool(
        lambda: work_hierarchy_structured(
            container,
            actor,
            limit=limit,
            cursor=cursor,
            include_tasks=include_tasks,
            process_id=process_id,
        )
    )
    return JSONResponse(headers=no_store_headers, content=structured)


async def project_detail(request: Request, project_id: UUID) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, PROJECT_DETAIL)
    container = request.app.state.container
    structured, _project = await run_in_threadpool(
        project_detail_structured, container, actor, project_id
    )
    return JSONResponse(headers=no_store_headers, content=structured)


async def project_tasks(
    request: Request,
    project_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, PROJECT_TASKS)
    container = request.app.state.container

    def read() -> dict[str, Any]:
        # The MCP tool takes any id and returns an empty page; a Project that is not the
        # owner's must be a 404 here, so it is read first (same scopes, owner-checked).
        container.projects.get(actor, project_id)
        return task_page_structured(
            container, actor, limit=limit, project_id=project_id, cursor=cursor
        )

    return JSONResponse(headers=no_store_headers, content=await run_in_threadpool(read))


async def domain_detail(request: Request, domain_id: UUID) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, DOMAIN_DETAIL)
    container = request.app.state.container
    structured = await run_in_threadpool(domain_structured, container, actor, domain_id)
    return JSONResponse(headers=no_store_headers, content=structured)


async def process_detail(request: Request, process_id: UUID) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, PROCESS_DETAIL)
    container = request.app.state.container
    structured = await run_in_threadpool(process_structured, container, actor, process_id)
    return JSONResponse(headers=no_store_headers, content=structured)


def add_work_routes(router: CompanionRouter) -> None:
    """Register the Work read routes on the companion router."""

    router.add(CompanionRouteSpec("GET", "/work/agenda", WORK_AGENDA.name), work_agenda)
    router.add(CompanionRouteSpec("GET", "/work/today", WORK_TODAY.name), work_today)
    router.add(CompanionRouteSpec("GET", "/work/hierarchy", WORK_HIERARCHY.name), work_hierarchy)
    router.add(
        CompanionRouteSpec("GET", "/projects/{project_id}", PROJECT_DETAIL.name), project_detail
    )
    router.add(
        CompanionRouteSpec("GET", "/projects/{project_id}/tasks", PROJECT_TASKS.name), project_tasks
    )
    router.add(CompanionRouteSpec("GET", "/domains/{domain_id}", DOMAIN_DETAIL.name), domain_detail)
    router.add(
        CompanionRouteSpec("GET", "/processes/{process_id}", PROCESS_DETAIL.name), process_detail
    )

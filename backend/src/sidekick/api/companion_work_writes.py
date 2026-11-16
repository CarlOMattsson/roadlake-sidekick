"""`/companion/v1/` write routes of Work: create and edit a Task, change a Project (ADR-005).

For the moments the owner cannot talk to Claude; Claude stays the main way in. Added to the
companion router by `create_companion_router` (sidekick.api.companion), which also supplies the
route class, so every refusal here is the same versioned problem envelope and the request log
carries only the operation name and the outcome. Each route verifies the credential, checks the
operation's capability (`companion:work:write`, and the read capability the answer needs), and
calls the same use case the MCP tool of the same name calls, answering that tool's structured
content:

- `POST /companion/v1/tasks`                        = `create_task`
  (`{"title", "due_at", "description", "priority"}` and at most one place: `project_id`,
  `process_id` or `domain_id`; `due_at` is a bare date or an ISO datetime with an offset)
- `POST /companion/v1/tasks/{task_id}/update`       = `update_task` (`{"version", ...}` and at
  least one of `title`, `description`, `due_at`, `project_id`, `process_id`, `domain_id`,
  `priority`; null clears a due date, a description or a place; status changes keep their own
  routes)
- `POST /companion/v1/projects/{project_id}/update` = `update_project` (`{"version", ...}` and at
  least one of `title`, `status`, `description`, `start_date`, `target_date`; null clears a
  description or a date)

Every write carries `Idempotency-Key`; a stale `version` is 409 `stale_version`, another owner's
id is 404, and the owner is always the credential's. The body names only the fields the app's
form can change, and an unknown field is a plain 422 that echoes nothing.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

import pydantic_core
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from sidekick.api.companion import (
    CompanionRouter,
    CompanionRouteSpec,
    Credential,
    IdempotencyKey,
    RequestBody,
    no_store_headers,
)
from sidekick.companion.operations import (
    PROJECT_UPDATE,
    TASK_CREATE,
    TASK_UPDATE,
    operation_actor,
)
from sidekick.companion.push_outbox_store import acting_device
from sidekick.composition import container_of
from sidekick.projects.application import UpdateProjectCommand
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.text_guard import NoImageData
from sidekick.structured.work import update_task_structured
from sidekick.structured.work_records import DueAtInput, TaskChanges, WritePriority
from sidekick.structured.work_writes import create_task_structured, update_project_structured

MAX_WORK_WRITE_BODY_BYTES = 64 * 1024

Version = Annotated[int, Field(ge=1)]
Title = Annotated[str, Field(min_length=1, max_length=200), NoImageData]
Description = Annotated[str, Field(max_length=10_000), NoImageData]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateTaskBody(_Body):
    title: Title
    due_at: DueAtInput = None
    project_id: UUID | None = None
    process_id: UUID | None = None
    domain_id: UUID | None = None
    description: Description | None = None
    priority: WritePriority = "normal"


class UpdateTaskBody(_Body):
    """The fields a Task form changes. An omitted field stays; null clears `due_at`,
    `description` and `project_id`; `title` and `priority` cannot be cleared."""

    version: Version
    title: Title | None = None
    description: Description | None = None
    due_at: DueAtInput = None
    project_id: UUID | None = None
    process_id: UUID | None = None
    domain_id: UUID | None = None
    priority: WritePriority | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> UpdateTaskBody:
        sent = self.model_fields_set - {"version"}
        if not sent:
            raise ValueError("at least one change is required")
        if "title" in sent and self.title is None:
            raise ValueError("title cannot be null")
        if "priority" in sent and self.priority is None:
            raise ValueError("priority cannot be null")
        return self


class UpdateProjectBody(_Body):
    """The fields a Project form changes. An omitted field stays; null clears `description`,
    `start_date` and `target_date`; `title` and `status` cannot be cleared. Tags, the definition
    of done and moving the Project to another Domain stay with Claude."""

    version: Version
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    status: ProjectStatus | None = None
    description: Annotated[str, Field(max_length=10_000)] | None = None
    start_date: date | None = None
    target_date: date | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> UpdateProjectBody:
        sent = self.model_fields_set - {"version"}
        if not sent:
            raise ValueError("at least one change is required")
        if "title" in sent and self.title is None:
            raise ValueError("title cannot be null")
        if "status" in sent and self.status is None:
            raise ValueError("status cannot be null")
        return self


CREATE_TASK_BODY = RequestBody(CreateTaskBody, MAX_WORK_WRITE_BODY_BYTES)
UPDATE_TASK_BODY = RequestBody(UpdateTaskBody, MAX_WORK_WRITE_BODY_BYTES)
UPDATE_PROJECT_BODY = RequestBody(UpdateProjectBody, MAX_WORK_WRITE_BODY_BYTES)


def _answer(structured: BaseModel) -> JSONResponse:
    return JSONResponse(
        headers=no_store_headers,
        content=pydantic_core.to_jsonable_python(structured.model_dump(mode="json")),
    )


def _correlation(request: Request) -> str | None:
    return request.scope.get("sidekick.correlation_id")


def add_work_write_routes(router: CompanionRouter) -> None:
    """Register the Work write routes on the companion router."""

    @router.register(CompanionRouteSpec("POST", "/tasks", TASK_CREATE.name, body=CREATE_TASK_BODY))
    async def task_create(
        request: Request, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, TASK_CREATE)
        body = await CREATE_TASK_BODY.read(request)
        container = container_of(request)

        def create() -> BaseModel:
            # The device's own change queues no wake push for itself (D-078).
            with acting_device(credential.device_id):
                return create_task_structured(
                    container,
                    actor,
                    title=body.title,
                    idempotency_key=idempotency_key,
                    project_id=body.project_id,
                    process_id=body.process_id,
                    domain_id=body.domain_id,
                    description=body.description,
                    priority=body.priority,
                    due_at=body.due_at,
                    correlation_id=_correlation(request),
                )

        return _answer(await run_in_threadpool(create))

    @router.register(
        CompanionRouteSpec(
            "POST", "/tasks/{task_id}/update", TASK_UPDATE.name, body=UPDATE_TASK_BODY
        )
    )
    async def task_update(
        request: Request, task_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, TASK_UPDATE)
        body = await UPDATE_TASK_BODY.read(request)
        container = container_of(request)
        # The companion's own clients send null to clear a field.
        changes = TaskChanges.from_sent(
            {name: getattr(body, name) for name in body.model_fields_set - {"version"}}
        )

        def update() -> BaseModel:
            with acting_device(credential.device_id):
                return update_task_structured(
                    container,
                    actor,
                    task_id,
                    version=body.version,
                    idempotency_key=idempotency_key,
                    changes=changes,
                    correlation_id=_correlation(request),
                )

        return _answer(await run_in_threadpool(update))

    @router.register(
        CompanionRouteSpec(
            "POST", "/projects/{project_id}/update", PROJECT_UPDATE.name, body=UPDATE_PROJECT_BODY
        )
    )
    async def project_update(
        request: Request,
        project_id: UUID,
        credential: Credential,
        idempotency_key: IdempotencyKey,
    ) -> JSONResponse:
        actor = operation_actor(credential, PROJECT_UPDATE)
        body = await UPDATE_PROJECT_BODY.read(request)
        container = container_of(request)
        command = UpdateProjectCommand(
            **{name: getattr(body, name) for name in body.model_fields_set - {"version"}}
        )

        def update() -> BaseModel:
            with acting_device(credential.device_id):
                return update_project_structured(
                    container,
                    actor,
                    project_id,
                    version=body.version,
                    idempotency_key=idempotency_key,
                    command=command,
                    correlation_id=_correlation(request),
                )

        return _answer(await run_in_threadpool(update))

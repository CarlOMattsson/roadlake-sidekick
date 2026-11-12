"""`/companion/v1/` routes of Tasks and Steps: detail, lists, complete and reopen.

Added to the companion router by `create_companion_router` (sidekick.api.companion), which also
supplies the route class, so every refusal here is the same versioned problem envelope and the
request log carries only the operation name and the outcome. Each route verifies the credential,
checks the operation's capability, and calls one fixed use case with its scopes; the writes also
queue no wake push for the device that made the change (D-078). The routes are listed in the
module docstring of `sidekick.api.companion`.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from sidekick.api.companion import (
    TASK_BODY,
    CompanionRouter,
    CompanionRouteSpec,
    Credential,
    IdempotencyKey,
    credential_for,
    no_store_headers,
    task_body,
)
from sidekick.companion.operations import (
    STEP_COMPLETE,
    STEP_REOPEN,
    TASK_COMPLETE,
    TASK_CONTACTS,
    TASK_DETAIL,
    TASK_EXTERNAL_REFERENCES,
    TASK_REOPEN,
    TASK_STEPS,
    operation_actor,
)
from sidekick.companion.push_outbox_store import acting_device
from sidekick.shared.auth import CompanionCredential
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.contacts import task_contacts_structured
from sidekick.structured.work import (
    complete_step_structured,
    complete_task_structured,
    reopen_step_structured,
    task_detail_structured,
    task_steps_structured,
    update_task_structured,
)
from sidekick.structured.work_records import TaskChanges
from sidekick.tasks.domain import TaskStatus


def _write_result(credential: CompanionCredential, structured: dict[str, Any]) -> dict[str, Any]:
    """The answer to a completion or undo: the full Task only for a device that may read Tasks.

    A device holding only `companion:tasks:complete` gets a receipt (id, new version, status),
    never the title, description or other fields: a write capability must not read.
    """

    return _receipt_or_full(credential, structured, "task")


def _step_write_result(
    credential: CompanionCredential, structured: dict[str, Any]
) -> dict[str, Any]:
    """The answer to a Step tick or undo: the full Step only for a device that may read Tasks,
    else a receipt (id, new version, status), as for a Task (`_write_result`)."""

    return _receipt_or_full(credential, structured, "step")


def _receipt_or_full(
    credential: CompanionCredential, structured: dict[str, Any], key: str
) -> dict[str, Any]:
    if "companion:tasks:read" in credential.scopes:
        return structured
    record = structured[key]
    return {
        "ok": True,
        "id": record["id"],
        "version": record["version"],
        "status": record["status"],
    }


async def task_detail(request: Request, task_id: UUID) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, TASK_DETAIL)
    container = request.app.state.container
    structured, _detail = await run_in_threadpool(task_detail_structured, container, actor, task_id)
    return JSONResponse(headers=no_store_headers, content=structured)


async def task_steps(
    request: Request,
    task_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, TASK_STEPS)
    container = request.app.state.container
    structured = await run_in_threadpool(
        lambda: task_steps_structured(container, actor, task_id, limit=limit, cursor=cursor)
    )
    return JSONResponse(headers=no_store_headers, content=structured)


async def task_contacts(
    request: Request,
    task_id: UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, TASK_CONTACTS)
    container = request.app.state.container
    structured = await run_in_threadpool(
        lambda: task_contacts_structured(container, actor, task_id, limit=limit, cursor=cursor)
    )
    return JSONResponse(headers=no_store_headers, content=structured)


async def task_external_references(
    request: Request,
    task_id: UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, TASK_EXTERNAL_REFERENCES)
    container = request.app.state.container
    structured = await run_in_threadpool(
        lambda: container.references.list_for_task(actor, task_id, limit=limit, cursor=cursor)
    )
    return JSONResponse(headers=no_store_headers, content=structured)


async def task_reopen(
    request: Request,
    task_id: UUID,
    credential: Credential,
    idempotency_key: IdempotencyKey,
) -> JSONResponse:
    actor = operation_actor(credential, TASK_REOPEN)
    body = await task_body(request)
    container = request.app.state.container

    # Only the undo of a completion. The status guard runs inside the use case, on the Task
    # row locked in the write's own transaction and after the idempotency replay check, so a
    # replay answers with the stored result and a concurrent edit cannot slip past it.
    def reopen() -> dict[str, Any]:
        # The device's own change queues no wake push for itself (D-078).
        with acting_device(credential.device_id):
            return update_task_structured(
                container,
                actor,
                task_id,
                version=body.version,
                idempotency_key=idempotency_key,
                changes=TaskChanges(status=TaskStatus.TODO),
                correlation_id=request.scope.get("sidekick.correlation_id"),
                only_if_status=TaskStatus.COMPLETED,
            )

    structured = await run_in_threadpool(reopen)
    return JSONResponse(headers=no_store_headers, content=_write_result(credential, structured))


async def task_complete(
    request: Request,
    task_id: UUID,
    credential: Credential,
    idempotency_key: IdempotencyKey,
) -> JSONResponse:
    actor = operation_actor(credential, TASK_COMPLETE)
    body = await task_body(request)
    container = request.app.state.container

    def complete() -> dict[str, Any]:
        # The device's own change queues no wake push for itself (D-078).
        with acting_device(credential.device_id):
            return complete_task_structured(
                container,
                actor,
                task_id,
                version=body.version,
                idempotency_key=idempotency_key,
                correlation_id=request.scope.get("sidekick.correlation_id"),
            )

    structured = await run_in_threadpool(complete)
    return JSONResponse(headers=no_store_headers, content=_write_result(credential, structured))


async def step_complete(
    request: Request,
    step_id: UUID,
    credential: Credential,
    idempotency_key: IdempotencyKey,
) -> JSONResponse:
    actor = operation_actor(credential, STEP_COMPLETE)
    body = await task_body(request)
    container = request.app.state.container

    def complete() -> dict[str, Any]:
        with acting_device(credential.device_id):
            return complete_step_structured(
                container,
                actor,
                step_id,
                version=body.version,
                idempotency_key=idempotency_key,
                correlation_id=request.scope.get("sidekick.correlation_id"),
            )

    structured = await run_in_threadpool(complete)
    return JSONResponse(
        headers=no_store_headers, content=_step_write_result(credential, structured)
    )


async def step_reopen(
    request: Request,
    step_id: UUID,
    credential: Credential,
    idempotency_key: IdempotencyKey,
) -> JSONResponse:
    actor = operation_actor(credential, STEP_REOPEN)
    body = await task_body(request)
    container = request.app.state.container

    def reopen() -> dict[str, Any]:
        with acting_device(credential.device_id):
            return reopen_step_structured(
                container,
                actor,
                step_id,
                version=body.version,
                idempotency_key=idempotency_key,
                correlation_id=request.scope.get("sidekick.correlation_id"),
            )

    structured = await run_in_threadpool(reopen)
    return JSONResponse(
        headers=no_store_headers, content=_step_write_result(credential, structured)
    )


def add_task_routes(router: CompanionRouter) -> None:
    """Register the Task and Step routes on the companion router."""

    router.add(CompanionRouteSpec("GET", "/tasks/{task_id}", TASK_DETAIL.name), task_detail)
    router.add(CompanionRouteSpec("GET", "/tasks/{task_id}/steps", TASK_STEPS.name), task_steps)
    router.add(
        CompanionRouteSpec("GET", "/tasks/{task_id}/contacts", TASK_CONTACTS.name), task_contacts
    )
    router.add(
        CompanionRouteSpec(
            "GET", "/tasks/{task_id}/external-references", TASK_EXTERNAL_REFERENCES.name
        ),
        task_external_references,
    )
    router.add(
        CompanionRouteSpec("POST", "/tasks/{task_id}/reopen", TASK_REOPEN.name, body=TASK_BODY),
        task_reopen,
    )
    router.add(
        CompanionRouteSpec("POST", "/tasks/{task_id}/complete", TASK_COMPLETE.name, body=TASK_BODY),
        task_complete,
    )
    router.add(
        CompanionRouteSpec("POST", "/steps/{step_id}/complete", STEP_COMPLETE.name, body=TASK_BODY),
        step_complete,
    )
    router.add(
        CompanionRouteSpec("POST", "/steps/{step_id}/reopen", STEP_REOPEN.name, body=TASK_BODY),
        step_reopen,
    )

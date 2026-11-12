"""`/companion/v1/` push and reminder routes (ADR-005, D-078): `/push/...` and `/reminders/...`.

Added to the companion router by `create_companion_router` (sidekick.api.companion), which also
supplies the route class, so every refusal here is the same versioned problem envelope and the
request log carries only the operation name and the outcome. The routes are listed in the module
docstring of `sidekick.api.companion`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from sidekick.api.companion import (
    CompanionProblem,
    CompanionRouter,
    CompanionRouteSpec,
    Credential,
    RequestBody,
    credential_for,
    iso,
    no_store_headers,
    reminder_service,
)
from sidekick.companion.operations import (
    PUSH_REMINDERS,
    PUSH_SUBSCRIPTION,
    operation_actor,
)
from sidekick.companion.push import (
    MAX_ENDPOINT_LENGTH,
    EndpointRejected,
    PairingNotFound,
    PushSubscriptionService,
)
from sidekick.companion.push_reminders import (
    MAX_ACK_IDS,
    NoActiveSubscription,
    PendingReminders,
    PushTestRateLimited,
)

MAX_PUSH_BODY_BYTES = 2048
MAX_ACK_BODY_BYTES = 4096


class PushSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The service validates the endpoint (SSRF rules); the cap here keeps the model cheap.
    endpoint: str = Field(min_length=1, max_length=MAX_ENDPOINT_LENGTH)


class AckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(min_length=1, max_length=MAX_ACK_IDS)


SUBSCRIPTION_BODY = RequestBody(PushSubscriptionRequest, MAX_PUSH_BODY_BYTES)
ACK_BODY = RequestBody(AckRequest, MAX_ACK_BODY_BYTES)


def _push_service(request: Request) -> PushSubscriptionService:
    container = request.app.state.container
    return PushSubscriptionService(
        container.session_factory, container.settings.push_allowed_host_set
    )


def _reminders_json(pending: PendingReminders, timezone: str) -> dict[str, Any]:
    """The phone's reminders: ids, a title and times. No description, no other Task field."""

    return {
        "timezone": timezone,
        "items": [
            {
                "id": str(item.id),
                "kind": item.kind,
                "title": item.title,
                "task_id": str(item.task_id) if item.task_id is not None else None,
                "due_at": iso(item.due_at),
            }
            for item in pending.items
        ],
        "summary": (
            {
                "id": str(pending.summary.id),
                "today": pending.summary.today,
                "overdue": pending.summary.overdue,
            }
            if pending.summary is not None
            else None
        ),
    }


async def push_subscribe(request: Request, credential: Credential) -> JSONResponse:
    actor = operation_actor(credential, PUSH_SUBSCRIPTION)
    body = await SUBSCRIPTION_BODY.read(request)
    try:
        await run_in_threadpool(
            lambda: _push_service(request).subscribe(
                actor.user_id,
                credential.device_id,
                body.endpoint,
                correlation_id=request.scope.get("sidekick.correlation_id"),
            )
        )
    except EndpointRejected:
        # A closed reason; neither the endpoint nor the rule that failed is echoed.
        raise CompanionProblem(
            422, "validation_error", "Request validation failed", reason="endpoint_not_allowed"
        ) from None
    except PairingNotFound:
        raise CompanionProblem(401, "unauthorized", "Authentication required") from None
    return JSONResponse(headers=no_store_headers, content={"ok": True})


async def push_unsubscribe(request: Request, credential: Credential) -> Response:
    actor = operation_actor(credential, PUSH_SUBSCRIPTION)
    await run_in_threadpool(
        lambda: _push_service(request).unsubscribe(
            actor.user_id,
            credential.device_id,
            correlation_id=request.scope.get("sidekick.correlation_id"),
        )
    )
    return Response(status_code=204, headers=no_store_headers)


async def push_test(request: Request, credential: Credential) -> JSONResponse:
    actor = operation_actor(credential, PUSH_REMINDERS)
    if not request.app.state.container.settings.push_enabled:
        raise CompanionProblem(404, "not_found", "Not found")
    try:
        await run_in_threadpool(
            lambda: reminder_service(request).queue_test(
                actor.user_id,
                credential.device_id,
                correlation_id=request.scope.get("sidekick.correlation_id"),
            )
        )
    except PushTestRateLimited:
        raise CompanionProblem(
            429, "rate_limited", "Too many requests", headers={"Retry-After": "3600"}
        ) from None
    except NoActiveSubscription:
        raise CompanionProblem(409, "conflict", "Conflict", reason="no_subscription") from None
    return JSONResponse(status_code=202, headers=no_store_headers, content={"ok": True})


async def reminders_pending(request: Request) -> JSONResponse:
    credential = await credential_for(request)
    actor = operation_actor(credential, PUSH_REMINDERS)
    pending = await run_in_threadpool(reminder_service(request).pending, actor.user_id)
    return JSONResponse(
        headers=no_store_headers,
        content=_reminders_json(pending, request.app.state.container.settings.owner_timezone),
    )


async def reminders_ack(request: Request, credential: Credential) -> Response:
    actor = operation_actor(credential, PUSH_REMINDERS)
    body = await ACK_BODY.read(request)
    await run_in_threadpool(reminder_service(request).ack, actor.user_id, body.ids)
    return Response(status_code=204, headers=no_store_headers)


def add_push_routes(router: CompanionRouter) -> None:
    """Register the push subscription and reminder routes on the companion router."""

    router.add(
        CompanionRouteSpec(
            "PUT", "/push/subscription", PUSH_SUBSCRIPTION.name, body=SUBSCRIPTION_BODY
        ),
        push_subscribe,
    )
    router.add(
        CompanionRouteSpec(
            "DELETE", "/push/subscription", f"{PUSH_SUBSCRIPTION.name}.remove", status_code=204
        ),
        push_unsubscribe,
    )
    router.add(
        CompanionRouteSpec("POST", "/push/test", f"{PUSH_REMINDERS.name}.test", status_code=202),
        push_test,
    )
    router.add(
        CompanionRouteSpec("GET", "/reminders/pending", f"{PUSH_REMINDERS.name}.pending"),
        reminders_pending,
    )
    router.add(
        CompanionRouteSpec(
            "POST", "/reminders/ack", f"{PUSH_REMINDERS.name}.ack", body=ACK_BODY, status_code=204
        ),
        reminders_ack,
    )

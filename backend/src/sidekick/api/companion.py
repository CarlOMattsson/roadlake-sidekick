"""`/companion/v1/`: the paired companion app's adapter (ADR-005).

A thin transport over the same use cases and the same result builders as the MCP tools, so the
app's React rooms read exactly the structured content they read in Claude:

- `GET  /companion/v1/work/agenda`              = `get_work_agenda` (same arguments as query)
- `GET  /companion/v1/work/today`               Arbetes Idag (`limit` 1-50, default 20, `cursor`):
  today's Tasks first, then the overdue ones, open Tasks only (`ContextService.work_today_page`)
- `GET  /companion/v1/tasks/{task_id}`          = `get_task`
- `GET  /companion/v1/tasks/{task_id}/steps`    = `list_task_steps` (`limit`, `cursor`)
- `GET  /companion/v1/tasks/{task_id}/contacts` = `list_task_contacts` (`limit`, `cursor`)
- `GET  /companion/v1/tasks/{task_id}/external-references` = `list_task_external_references`
  (`limit`, `cursor`)
- `POST /companion/v1/tasks/{task_id}/complete` = `complete_task` (`{"version"}` +
  `Idempotency-Key`)
- `POST /companion/v1/tasks/{task_id}/reopen`   = `update_task` with `changes={"status": "todo"}`,
  only for a completed Task (the undo of a completion; `{"version"}` + `Idempotency-Key`)
- `GET  /companion/v1/work/hierarchy`          = `get_work_hierarchy` (`limit`, `cursor`,
  `include_tasks`, and with it `process_id` for only that Process's node and Tasks)
- `GET  /companion/v1/projects/{project_id}`    = `get_project`
- `GET  /companion/v1/projects/{project_id}/tasks` = `list_tasks` with `project_id`
  (`limit`, `cursor`)
- `GET  /companion/v1/domains/{domain_id}`      = `get_domain`
- `GET  /companion/v1/processes/{process_id}`   = `get_process`
- `POST /companion/v1/steps/{step_id}/complete` = `complete_task_step` (`{"version"}` +
  `Idempotency-Key`)
- `POST /companion/v1/steps/{step_id}/reopen`   = `update_task_step` with `changes={"status":
  "todo"}`, only for a completed Step (the undo of a tick; `{"version"}` + `Idempotency-Key`)
- `POST /companion/v1/pair`                     exchange a pairing secret for a device credential
- `GET  /companion/v1/device`                   this device's own status, and `enabled_rooms`: the
  rooms this instance shows (`SIDEKICK_ENABLED_ROOMS`, in the app's order, `work` always), which the
  app reads so it draws no room that is switched off; `/pair` and `/device/renew` answer it too,
  and `timezone`: the owner's IANA zone (`SIDEKICK_OWNER_TIMEZONE`), which the app declares so its
  dates and reminder times are the owner's, not the phone's, and `push_enabled`: whether the server
  delivers push (`SIDEKICK_PUSH_ENABLED`), which the app reads so it hides its push row when off
- `POST /companion/v1/device/renew`             a new credential for this device, only in the last
  7 days before the current one expires (409 `renewal_not_due` with `renew_after` otherwise);
  no body (or `{}`, at most 256 B); 200 like `/pair`; the old credential works until the new
  one is first used, at most 10 minutes; five a day (429 + `Retry-After`)
- `DELETE /companion/v1/device`                 the device unpairs itself
- `PUT  /companion/v1/push/subscription`        register (replace) the device's UnifiedPush endpoint
  (`{"endpoint"}`, `companion:push`; https, an allowed host, port 443; 200 `{"ok": true}`)
- `DELETE /companion/v1/push/subscription`      remove it (204, idempotent)
- `POST /companion/v1/push/test`                 queue a visible test notification to this device
  (202; five an hour per device; only with `SIDEKICK_PUSH_ENABLED`)
- `GET  /companion/v1/reminders/pending`        the reminders not yet shown: `{"timezone", "items":
  [{"id","kind","title","task_id","due_at"}], "summary": {"id","today","overdue"} | null}` (at
  most 20 items, no description; `companion:push`)
- `POST /companion/v1/reminders/ack`            `{"ids": [...]}` (1-50): shown; 204, idempotent,
  the owner's own only

`GET`/`PUT /companion/v1/license` (the instance's license key, D-081) are in
`sidekick.api.companion_license`; the display state also rides as `license` in the `/pair`,
`/device` and `/device/renew` answers.

The route groups live in sibling modules, each added to this router by `create_companion_router`:
pairing and the device's own routes in `sidekick.api.companion_device`, push and reminders in
`sidekick.api.companion_push`, the Work reads in `sidekick.api.companion_work`, Tasks and Steps in
`sidekick.api.companion_tasks`, and the rooms Shopping and Journal (`/companion/v1/shopping/...`,
`/companion/v1/journal/...`) in `sidekick.api.companion_rooms`. This module holds what they share:
the problem envelope, the route class, authentication and the body helpers.

Every authenticated route verifies the bearer as a companion credential on each request (digest,
purpose, expiry, revocation, active owner), checks the operation's device capability, and calls
the use case with the operation's fixed application scopes (`sidekick.companion.operations`).
The owner is always the credential's; no route takes an owner id. Errors use one versioned
problem envelope with a closed vocabulary and never echo input, titles or server text. Nothing
here logs a token, a secret, a title or a query value; the request log carries only the
operation name and the outcome.

Off unless `SIDEKICK_COMPANION_ENABLED=true`; the routes are then not registered at all. They are
kept out of the browser OpenAPI document (the browser client never calls them): the result shapes
are the MCP tools' output schemas (`contracts/mcp-tools.generated.json`), and the routes, their
inputs and the refusal vocabulary (`PROBLEMS`) are published for the app's client as
`contracts/companion-api.generated.json`, generated by `sidekick.api.export_companion_contract`.
A route declares its JSON body in its `CompanionRouteSpec(..., body=RequestBody(...))` and reads it
with `RequestBody.read`, so the contract and the handler cannot disagree.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection, Coroutine
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from starlette.concurrency import run_in_threadpool

from sidekick.api.ingress_problem import problem_response as _problem_response
from sidekick.api.pairing_budget import (
    DEFAULT_FAILURES_GLOBAL_PER_MINUTE,
    DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE,
    DEFAULT_RESERVE_PER_MINUTE,
    PairingBudget,
)
from sidekick.companion.operations import CapabilityMissing
from sidekick.companion.push_reminders import ReminderService
from sidekick.companion.response_budget import ensure_within_budget
from sidekick.shared.auth import CompanionCredential
from sidekick.shared.errors import (
    CLIENT_INPUT_ERRORS,
    ConflictError,
    IdempotencyKeyReusedError,
    NotFoundError,
)
from sidekick.shared.errors import ValidationError as SidekickValidationError
from sidekick.shared.errors.core import InternalFaultError, PermissionDeniedError, SidekickError
from sidekick.shared.observability import safe_log_fields
from sidekick.shared.rooms import ROOMS, ordered
from sidekick.shared.text_guard import contains_nul

LOGGER = logging.getLogger("sidekick.companion")

COMPANION_PREFIX = "/companion/v1"
API_VERSION = "companion.v1"
# Only failed exchanges spend the pairing budgets (see `sidekick.api.pairing_budget`). The secret
# has 256 bits, so the limits are no guard against guessing; they bound the unauthenticated work
# (a digest and one UPDATE) a caller who knows the URL can make the server do. Each client address
# may fail 10 times a minute, all clients together 30, ten times what a person mistyping or
# retrying a scan produces. A client that has spent its own budget is refused with 429 before any
# database work; the global budget only gates clients that failed recently, so one stranger's
# failures cannot refuse the owner's valid code from another address.
PAIR_FAILURES_PER_CLIENT_PER_MINUTE = DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE
PAIR_FAILURES_PER_MINUTE = DEFAULT_FAILURES_GLOBAL_PER_MINUTE
PAIR_RESERVE_PER_MINUTE = DEFAULT_RESERVE_PER_MINUTE
MAX_TASK_BODY_BYTES = 4096
_NO_STORE = {"Cache-Control": "no-store"}


@dataclass(frozen=True, slots=True)
class ProblemKind:
    """One entry of the closed vocabulary of refusals: the status and code a client can see, the
    closed `reason` values that code may carry, and the headers and extra fields it adds."""

    status: int
    code: str
    title: str
    reasons: tuple[str, ...] = ()
    headers: tuple[str, ...] = ()
    extra_fields: tuple[str, ...] = ()


# Every refusal a companion route can answer. `tests/unit/test_companion_contract.py` checks that
# each `CompanionProblem` raised in `sidekick.api.companion*` is listed here, and the published
# contract (`contracts/companion-api.generated.json`) is built from it.
PROBLEMS: tuple[ProblemKind, ...] = (
    ProblemKind(400, "bad_request", "Bad request"),
    ProblemKind(401, "unauthorized", "Authentication required", headers=("WWW-Authenticate",)),
    ProblemKind(401, "pairing_invalid", "Pairing secret is invalid, expired or already used"),
    ProblemKind(403, "forbidden", "Forbidden", reasons=("capability_missing",)),
    ProblemKind(404, "not_found", "Not found"),
    ProblemKind(405, "method_not_allowed", "Method not allowed"),
    ProblemKind(
        409,
        "conflict",
        "Conflict",
        reasons=(
            "idempotency_key_reused",
            "stale_version",
            "not_completed",
            "no_subscription",
            "renewal_not_due",
        ),
        extra_fields=("renew_after",),
    ),
    ProblemKind(413, "payload_too_large", "Payload too large"),
    ProblemKind(415, "unsupported_media_type", "Unsupported media type"),
    ProblemKind(
        422, "validation_error", "Request validation failed", reasons=("endpoint_not_allowed",)
    ),
    ProblemKind(429, "rate_limited", "Too many requests", headers=("Retry-After",)),
)


class CompanionProblem(Exception):
    """A refusal with a closed code; the route class renders it as the versioned envelope."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        *,
        reason: str | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.title = title
        self.reason = reason
        self.headers = headers
        self.extra = extra


def _nul_problem() -> CompanionProblem:
    return CompanionProblem(422, "validation_error", "Request validation failed")


def problem_response(request: Request, problem: CompanionProblem) -> JSONResponse:
    extra: dict[str, Any] = {"api_version": API_VERSION}
    if problem.reason is not None:
        extra["reason"] = problem.reason
    if problem.extra is not None:
        extra.update(problem.extra)
    return _problem_response(
        request.scope,
        status=problem.status,
        code=problem.code,
        title=problem.title,
        headers={**_NO_STORE, **(problem.headers or {})},
        type_prefix="urn:sidekick:companion:v1:error",
        extra=extra,
    )


def _translate(error: Exception) -> CompanionProblem | None:
    """The envelope for a known failure; `None` lets anything else become a server error."""

    if isinstance(error, CompanionProblem):
        return error
    if isinstance(error, (RequestValidationError, SidekickValidationError)):
        return CompanionProblem(422, "validation_error", "Request validation failed")
    if isinstance(error, InternalFaultError):
        return None
    if isinstance(error, CapabilityMissing):
        return CompanionProblem(403, "forbidden", "Forbidden", reason="capability_missing")
    if isinstance(error, PermissionDeniedError):
        return CompanionProblem(403, "forbidden", "Forbidden")
    if isinstance(error, NotFoundError):
        return CompanionProblem(404, "not_found", "Not found")
    if isinstance(error, ConflictError):
        # Closed reasons only; the error's own text and subject (a title) are never sent.
        reason: str | None = None
        if isinstance(error, IdempotencyKeyReusedError):
            reason = "idempotency_key_reused"
        elif error.reason in ("stale_version", "not_completed"):
            reason = error.reason
        return CompanionProblem(409, "conflict", "Conflict", reason=reason)
    if isinstance(error, SidekickError):
        return CompanionProblem(400, "bad_request", "Bad request")
    if isinstance(error, CLIENT_INPUT_ERRORS):
        return CompanionProblem(400, "bad_request", "Bad request")
    if isinstance(error, HTTPException):
        codes = {
            401: ("unauthorized", "Authentication required"),
            403: ("forbidden", "Forbidden"),
            404: ("not_found", "Not found"),
            405: ("method_not_allowed", "Method not allowed"),
        }
        code, title = codes.get(error.status_code, ("bad_request", "Bad request"))
        return CompanionProblem(error.status_code, code, title)
    return None


class CompanionRoute(APIRoute):
    """Render every refusal of a companion route, request validation included, as the
    versioned companion envelope, and record one content-free log line per request."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        operation = str(self.operation_id or self.name)

        async def companion_handler(request: Request) -> Response:
            try:
                # A NUL cannot be stored, so it is a client error, not a database failure. The URL
                # is structure, not data: refusing it before authentication reveals nothing.
                url_values = [*request.query_params.multi_items(), *request.path_params.items()]
                if contains_nul(url_values):
                    raise _nul_problem()
                response = await handler(request)
                ensure_within_budget(bytes(response.body))
            except Exception as error:
                problem = _translate(error)
                if problem is None:
                    _log(request, operation, 500)
                    raise
                _log(request, operation, problem.status, problem.code)
                return problem_response(request, problem)
            _log(request, operation, response.status_code)
            return response

        return companion_handler


def _log(request: Request, operation: str, status: int, code: str | None = None) -> None:
    fields: dict[str, object] = {
        "correlation_id": request.scope.get("sidekick.correlation_id", "unknown"),
        "companion_operation": operation,
        "http_status": status,
        "outcome": "success" if status < 400 else "denied" if status < 500 else "failure",
    }
    if code is not None:
        fields["companion_error"] = code
    request.app.state.container.telemetry.count(
        "sidekick.companion.requests",
        {"companion.operation": operation, "outcome": str(fields["outcome"])},
    )
    LOGGER.info("companion_request", extra=safe_log_fields(fields))


@dataclass(frozen=True, slots=True)
class RequestBody[Model: BaseModel]:
    """A route's JSON body: the model, and the largest body that is read for it.

    The route declares it once in its `CompanionRouteSpec(..., body=...)` and reads it with
    `read`, so the published contract and the handler cannot name different models or limits.
    `required=False` is for a body that may be left out entirely (an empty object is then the
    only legal value).
    """

    model: type[Model]
    max_bytes: int
    required: bool = True

    async def read(self, request: Request) -> Model:
        """The JSON body, read only after authentication and capped; a refusal never echoes it."""

        if "application/json" not in request.headers.get("content-type", ""):
            raise CompanionProblem(415, "unsupported_media_type", "Unsupported media type")
        body = await _bounded_body(request, self.max_bytes)
        try:
            parsed = self.model.model_validate_json(body)
        except PydanticValidationError:
            raise CompanionProblem(422, "validation_error", "Request validation failed") from None
        if contains_nul(parsed.model_dump()):
            raise _nul_problem()
        return parsed


@dataclass(frozen=True, slots=True)
class CompanionRouteSpec:
    """What one companion route is, declared once where it is registered: the HTTP method, the
    path under `COMPANION_PREFIX`, the operation name (the log line, the capability check and the
    published contract's `operationId`), its JSON body, and the response status.
    `unauthenticated` is only for the pairing exchange."""

    method: str
    path: str
    operation: str
    body: RequestBody[Any] | None = None
    unauthenticated: bool = False
    status_code: int | None = None


class CompanionRouter(APIRouter):
    """The companion router. Every route is registered through a `CompanionRouteSpec`, and the
    router keeps the specs, so the log line, the tests and the contract export read the registry
    and not the handlers, which stay plain functions."""

    def __init__(self) -> None:
        super().__init__(prefix=COMPANION_PREFIX, route_class=CompanionRoute)
        self.specs: list[CompanionRouteSpec] = []

    def add(self, spec: CompanionRouteSpec, endpoint: Callable[..., Any]) -> None:
        """Register one companion route; none of them is part of the OpenAPI document. A method
        and path, or an operation name, cannot be registered twice."""

        for known in self.specs:
            if (known.method, known.path) == (spec.method, spec.path):
                raise ValueError(f"companion route registered twice: {spec.method} {spec.path}")
            if known.operation == spec.operation:
                raise ValueError(f"companion operation registered twice: {spec.operation}")
        self.specs.append(spec)
        self.add_api_route(
            spec.path,
            endpoint,
            methods=[spec.method],
            include_in_schema=False,
            status_code=spec.status_code,
            operation_id=spec.operation,
        )

    def register(
        self, spec: CompanionRouteSpec
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """A decorator that registers the function under `spec` and returns it unchanged."""

        def decorate(endpoint: Callable[..., Any]) -> Callable[..., Any]:
            self.add(spec, endpoint)
            return endpoint

        return decorate

    def spec_for(self, route: object) -> CompanionRouteSpec | None:
        """The spec a route was registered under, or `None` for a route that has none."""

        if not isinstance(route, APIRoute):
            return None
        return next((spec for spec in self.specs if spec.operation == route.operation_id), None)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    token = value.strip()
    if scheme.lower() != "bearer" or not token or len(token) > 256:
        raise CompanionProblem(
            401,
            "unauthorized",
            "Authentication required",
            headers={"WWW-Authenticate": 'Bearer realm="sidekick-companion"'},
        )
    return token


def companion_credential(request: Request) -> CompanionCredential:
    """The verified device behind this request, checked afresh on every call."""

    credential = request.app.state.container.auth.verify_companion_token(_bearer(request))
    if not isinstance(credential, CompanionCredential):
        raise CompanionProblem(
            401,
            "unauthorized",
            "Authentication required",
            headers={
                "WWW-Authenticate": 'Bearer realm="sidekick-companion", error="invalid_token"'
            },
        )
    return credential


class CompleteTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _bounded_body(request: Request, limit: int) -> bytes:
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > limit:
            raise CompanionProblem(413, "payload_too_large", "Payload too large")
    return bytes(received)


# The helpers the sibling `sidekick.api.companion_*` modules share with this module.
no_store_headers = _NO_STORE
bounded_body = _bounded_body
bearer_token = _bearer


async def authenticated(request: Request) -> CompanionCredential:
    """Dependency of the write routes: a caller without a valid token is refused with 401
    before the body is read or parsed."""

    return await run_in_threadpool(companion_credential, request)


def credential_for(request: Request) -> Awaitable[CompanionCredential]:
    """The verified device behind this request, for routes that read no body."""

    return run_in_threadpool(companion_credential, request)


Credential = Annotated[CompanionCredential, Depends(authenticated)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


TASK_BODY = RequestBody(CompleteTaskRequest, MAX_TASK_BODY_BYTES)


async def task_body(request: Request) -> CompleteTaskRequest:
    """The `{"version"}` body of complete and reopen, read only after authentication and capped
    at `MAX_TASK_BODY_BYTES`; FastAPI's own body model would read it before any dependency."""

    return await TASK_BODY.read(request)


def reminder_service(request: Request) -> ReminderService:
    container = request.app.state.container
    return ReminderService(container.session_factory, locale=container.settings.mcp_app_locale)


def create_companion_router(
    clock: Callable[[], float] = monotonic, rooms: Collection[str] = ROOMS
) -> CompanionRouter:
    """The companion routes, with this app's own pairing rate limit."""

    router = CompanionRouter()
    failed_pairings = PairingBudget(
        PAIR_FAILURES_PER_CLIENT_PER_MINUTE,
        PAIR_FAILURES_PER_MINUTE,
        PAIR_RESERVE_PER_MINUTE,
        clock,
    )
    # Additive: an older app reads `device` and ignores this field.
    enabled_rooms = list(ordered(rooms))

    # The route groups live in sibling modules, which import this one; the imports wait until
    # this module is complete.
    from sidekick.api.companion_device import add_device_routes
    from sidekick.api.companion_license import add_license_routes
    from sidekick.api.companion_push import add_push_routes
    from sidekick.api.companion_rooms import add_room_routes
    from sidekick.api.companion_tasks import add_task_routes
    from sidekick.api.companion_work import add_work_routes

    add_device_routes(router, failed_pairings, enabled_rooms)
    add_push_routes(router)
    add_work_routes(router)
    add_task_routes(router)
    add_room_routes(router, rooms)
    add_license_routes(router)
    return router

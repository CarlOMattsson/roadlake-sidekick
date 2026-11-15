"""`/webhooks/v1/`: a narrow, token-protected entrance for home and phone automation.

Home Assistant, Tasker and similar tools push one small fact into Sidekick with a fixed action:

- `POST /webhooks/v1/shopping-items`  add one item to a list (`{"name", "quantity", "unit",
  "note", "list_id"}`; only `name` is required; without `list_id` the owner's oldest active list)
- `POST /webhooks/v1/tasks`           create one Task (`{"title", "due"}`; `due` is a date, meaning
  the end of that day in the owner's zone, or a datetime with an offset)

Both need `Authorization: Bearer <webhook token>` and an `Idempotency-Key` header (8 to 128
characters): a retry with the same key and the same body answers the first answer again and writes
nothing twice. A token holds the scopes `webhook:shopping:add` and/or `webhook:tasks:create` and
nothing else; it is not an MCP or companion credential, and neither of those is accepted here.

Every call is checked on every request (digest, expiry, revocation, active owner, scope), then
rate limited per token (the token's own limit per minute, per process: 429 with `Retry-After`),
then runs one use case with an actor that carries only that operation's application scopes
(`sidekick.webhooks.operations`). The owner is always the token's. The write is an ordinary Shopping
or Task write, so it appears in the activity and audit trail like the owner's own.

Errors use one closed problem envelope and never echo input. The request log carries only the
operation name, the outcome, a closed error code and the token's record id: never a token, a
payload value, a title or a list name. Off unless `SIDEKICK_WEBHOOKS_ENABLED=true`; the routes are
then not registered at all, and they are not part of the browser OpenAPI document.
"""

import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from decimal import Decimal
from time import monotonic
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from sidekick.api.companion import (
    CompanionProblem,
    IdempotencyKey,
    RequestBody,
    translate_error,
)
from sidekick.api.failed_auth import bearer_token
from sidekick.api.ingress_problem import problem_response as _problem_response
from sidekick.api.public_surface import TokenBucket
from sidekick.composition import container_of
from sidekick.shared.observability import safe_log_fields
from sidekick.shared.text_guard import NoImageData, contains_nul
from sidekick.shopping.application.schemas import BatchItem
from sidekick.structured.work_records import DueAtInput, end_of_day_due_at
from sidekick.webhooks.actions import ITEM_CLIENT_REF, add_shopping_item
from sidekick.webhooks.operations import (
    SHOPPING_ITEM_ADD,
    TASK_CREATE,
    WebhookScopeMissing,
    operation_actor,
)
from sidekick.webhooks.tokens import WebhookCredential

LOGGER = logging.getLogger("sidekick.webhooks")

WEBHOOKS_PREFIX = "/webhooks/v1"
API_VERSION = "webhooks.v1"
# A webhook body is a few short fields; this is far above the largest legal one.
MAX_WEBHOOK_BODY_BYTES = 4096
MAX_TOKEN_LENGTH = 256
_NO_STORE = {"Cache-Control": "no-store"}
# Where the router's authentication leaves the verified credential on the ASGI scope.
CREDENTIAL_SCOPE_KEY = "sidekick.webhook_credential"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShoppingItemBody(_Body):
    name: Annotated[str, Field(min_length=1, max_length=200), NoImageData]
    quantity: Annotated[Decimal, Field(gt=0, le=999999.999, max_digits=9, decimal_places=3)] = (
        Decimal("1")
    )
    unit: Annotated[str | None, Field(max_length=30), NoImageData] = None
    note: Annotated[str | None, Field(max_length=2000), NoImageData] = None
    list_id: UUID | None = None


class TaskBody(_Body):
    title: Annotated[str, Field(min_length=1, max_length=200), NoImageData]
    due: DueAtInput = None


SHOPPING_ITEM_BODY = RequestBody(ShoppingItemBody, MAX_WEBHOOK_BODY_BYTES)
TASK_BODY = RequestBody(TaskBody, MAX_WEBHOOK_BODY_BYTES)


def _unauthorized(*, invalid: bool) -> CompanionProblem:
    challenge = 'Bearer realm="sidekick-webhooks"' + (', error="invalid_token"' if invalid else "")
    return CompanionProblem(
        401, "unauthorized", "Authentication required", headers={"WWW-Authenticate": challenge}
    )


class WebhookRateLimiter:
    """A refilling budget per token: the token's own requests per minute, kept in this process.

    A process that restarts starts with full budgets, and several processes each keep their own,
    so the limit is a guard against a runaway automation, not an exact quota.
    """

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._buckets: dict[UUID, TokenBucket] = {}

    def check(self, credential: WebhookCredential) -> None:
        """Spend one request of the token's budget, or refuse with 429 and `Retry-After`."""

        bucket = self._buckets.get(credential.token_id)
        if bucket is None:
            bucket = self._buckets[credential.token_id] = TokenBucket(
                credential.rate_limit_per_minute, self._clock
            )
        if not bucket.take():
            raise CompanionProblem(
                429,
                "rate_limited",
                "Too many requests",
                headers={"Retry-After": str(bucket.seconds_until_budget())},
            )


class WebhookRoute(APIRoute):
    """Render every refusal of a webhook route, request validation included, as the closed
    envelope, and record one content-free log line per request."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        operation = str(self.operation_id or self.name)

        async def webhook_handler(request: Request) -> Response:
            try:
                # A NUL cannot be stored, so it is a client error, not a database failure.
                if contains_nul(
                    [*request.query_params.multi_items(), *request.path_params.items()]
                ):
                    raise CompanionProblem(422, "validation_error", "Request validation failed")
                response = await handler(request)
            except Exception as error:
                problem = _problem_of(error)
                if problem is None:
                    _log(request, operation, 500)
                    raise
                _log(request, operation, problem.status, problem.code)
                return _render(request, problem)
            _log(request, operation, response.status_code)
            return response

        return webhook_handler


def _problem_of(error: Exception) -> CompanionProblem | None:
    if isinstance(error, WebhookScopeMissing):
        return CompanionProblem(403, "forbidden", "Forbidden", reason="scope_missing")
    return translate_error(error)


def _render(request: Request, problem: CompanionProblem) -> JSONResponse:
    extra: dict[str, Any] = {"api_version": API_VERSION}
    if problem.reason is not None:
        extra["reason"] = problem.reason
    return _problem_response(
        request.scope,
        status=problem.status,
        code=problem.code,
        title=problem.title,
        headers={**_NO_STORE, **(problem.headers or {})},
        type_prefix="urn:sidekick:webhooks:v1:error",
        extra=extra,
    )


def _log(request: Request, operation: str, status: int, code: str | None = None) -> None:
    fields: dict[str, object] = {
        "correlation_id": request.scope.get("sidekick.correlation_id", "unknown"),
        "webhook_operation": operation,
        "http_status": status,
        "outcome": "success" if status < 400 else "denied" if status < 500 else "failure",
    }
    credential: WebhookCredential | None = request.scope.get(CREDENTIAL_SCOPE_KEY)
    if credential is not None:
        fields["webhook_token_id"] = str(credential.token_id)
    if code is not None:
        fields["webhook_error"] = code
    container_of(request).telemetry.count(
        "sidekick.webhooks.requests",
        {"webhook.operation": operation, "outcome": str(fields["outcome"])},
    )
    LOGGER.info("webhook_request", extra=safe_log_fields(fields))


def _answer(content: dict[str, str]) -> JSONResponse:
    return JSONResponse(status_code=201, headers=_NO_STORE, content=content)


def _correlation(request: Request) -> str | None:
    return request.scope.get("sidekick.correlation_id")


def verified_credential(request: Request) -> WebhookCredential:
    """The credential that the router's authentication verified for this request."""

    credential: WebhookCredential = request.scope[CREDENTIAL_SCOPE_KEY]
    return credential


Credential = Annotated[WebhookCredential, Depends(verified_credential)]


def create_webhooks_router(clock: Callable[[], float] = monotonic) -> APIRouter:
    """The webhook routes, with this app's own per-token rate limiter."""

    limiter = WebhookRateLimiter(clock)

    async def authenticate(request: Request) -> None:
        """Verify the token and spend its rate limit; a caller without a valid token is refused
        with 401 before the body is read or parsed."""

        raw = bearer_token(request.scope)
        if raw is None or len(raw) > MAX_TOKEN_LENGTH:
            raise _unauthorized(invalid=False)
        container = container_of(request)
        credential = await run_in_threadpool(container.webhook_tokens.verify, raw.decode("latin-1"))
        if credential is None:
            raise _unauthorized(invalid=True)
        request.scope[CREDENTIAL_SCOPE_KEY] = credential
        limiter.check(credential)

    router = APIRouter(
        prefix=WEBHOOKS_PREFIX, route_class=WebhookRoute, dependencies=[Depends(authenticate)]
    )

    @router.post("/shopping-items", operation_id=SHOPPING_ITEM_ADD.name, include_in_schema=False)
    async def shopping_item_add(
        request: Request, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, SHOPPING_ITEM_ADD)
        body = await SHOPPING_ITEM_BODY.read(request)
        item = BatchItem(
            client_ref=ITEM_CLIENT_REF,
            name=body.name,
            quantity=body.quantity,
            unit=body.unit,
            note=body.note,
        )
        container = container_of(request)
        added = await run_in_threadpool(
            lambda: add_shopping_item(
                container.shopping,
                actor,
                item,
                body.list_id,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
            )
        )
        return _answer({"list_id": str(added.list_id), "item_id": str(added.item_id)})

    @router.post("/tasks", operation_id=TASK_CREATE.name, include_in_schema=False)
    async def task_create(
        request: Request, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, TASK_CREATE)
        body = await TASK_BODY.read(request)
        container = container_of(request)
        due_at: datetime | None = end_of_day_due_at(body.due, container.settings.owner_zone)
        task = await run_in_threadpool(
            lambda: container.tasks.create(
                actor,
                title=body.title,
                due_at=due_at,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
            )
        )
        return _answer({"task_id": str(task.id)})

    return router

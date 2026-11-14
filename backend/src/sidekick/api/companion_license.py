"""`/companion/v1/license`: the instance's license key from the companion app (D-081: offline
signed license keys).

Added to the companion router by `create_companion_router` (sidekick.api.companion), which supplies
the route class, so every refusal is the same versioned problem envelope and the request log
carries only the operation name and the outcome.

- `GET /companion/v1/license`  the display state, flat: `{"api_version", "state", "licensee",
  "kind", "expires"}` (`licensee`, `kind` and `expires` only for `licensed` and `expired`;
  `companion:license`)
- `PUT /companion/v1/license`  `{"key"}` (at most 2 KiB): enter a key (`companion:license`, and the
  credential's user must be the installation's only owner, else 403). 200 with the display state
  as for GET plus `accepted`; a key that does not verify is `accepted: false` and changes nothing.
  The call is idempotent by nature: entering the key that is stored again changes and audits
  nothing, so it needs no `Idempotency-Key`.

The key is read from the body only after authentication, capped, and never echoed, logged or put in
an error. The same display state also rides in the `/companion/v1/device` and `/pair` answers.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from sidekick.api.companion import (
    API_VERSION,
    CompanionRouter,
    CompanionRouteSpec,
    Credential,
    RequestBody,
    no_store_headers,
)
from sidekick.companion.operations import LICENSE_SET, LICENSE_SHOW, operation_actor
from sidekick.composition import container_of
from sidekick.license.key import MAX_KEY_LENGTH

MAX_LICENSE_BODY_BYTES = 2048
# A key is about 250 characters; room for it pasted over several lines.
MAX_KEY_FIELD_LENGTH = MAX_KEY_LENGTH + MAX_KEY_LENGTH // 2


class LicenseKeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, Field(min_length=1, max_length=MAX_KEY_FIELD_LENGTH)]


LICENSE_KEY_BODY = RequestBody(LicenseKeyBody, MAX_LICENSE_BODY_BYTES)


def add_license_routes(router: CompanionRouter) -> None:
    """Register the license routes on the companion router."""

    @router.register(CompanionRouteSpec("GET", "/license", LICENSE_SHOW.name))
    async def license_show(request: Request, credential: Credential) -> JSONResponse:
        operation_actor(credential, LICENSE_SHOW)
        view = await run_in_threadpool(container_of(request).license.view)
        return JSONResponse(
            headers=no_store_headers,
            content={"api_version": API_VERSION, **view.as_json()},
        )

    @router.register(CompanionRouteSpec("PUT", "/license", LICENSE_SET.name, body=LICENSE_KEY_BODY))
    async def license_set(request: Request, credential: Credential) -> JSONResponse:
        actor = operation_actor(credential, LICENSE_SET)
        body = await LICENSE_KEY_BODY.read(request)
        service = container_of(request).license
        outcome = await run_in_threadpool(
            lambda: service.set_by_owner(
                actor.user_id,
                body.key,
                correlation_id=request.scope.get("sidekick.correlation_id"),
            )
        )
        return JSONResponse(
            headers=no_store_headers,
            content={
                "api_version": API_VERSION,
                **outcome.view.as_json(),
                "accepted": outcome.accepted,
            },
        )

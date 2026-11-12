"""`/companion/v1/` pairing and device routes (ADR-005): `/pair` and `/device...`.

Added to the companion router by `create_companion_router` (sidekick.api.companion), which also
supplies the route class, so every refusal here is the same versioned problem envelope and the
request log carries only the operation name and the outcome. The routes are listed in the module
docstring of `sidekick.api.companion`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from sidekick.api.companion import (
    API_VERSION,
    CompanionProblem,
    CompanionRouter,
    CompanionRouteSpec,
    Credential,
    RequestBody,
    bearer_token,
    bounded_body,
    credential_for,
    iso,
    no_store_headers,
)
from sidekick.api.public_surface import TokenBucket
from sidekick.companion.persistence import CompanionDeviceStore
from sidekick.companion.service import (
    MAX_PAIRING_SECRET_LENGTH,
    CompanionDeviceService,
    CompanionDeviceView,
    PairedDevice,
    RenewalNotDue,
    RenewalRateLimited,
)
from sidekick.shared.auth import CompanionCredential

MAX_PAIR_BODY_BYTES = 1024
MAX_RENEW_BODY_BYTES = 256


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pairing_secret: str = Field(min_length=16, max_length=MAX_PAIRING_SECRET_LENGTH)


class RenewRequest(BaseModel):
    """The renewal takes no input: the body is left out, or is an empty object."""

    model_config = ConfigDict(extra="forbid")


PAIR_BODY = RequestBody(PairRequest, MAX_PAIR_BODY_BYTES)
RENEW_BODY = RequestBody(RenewRequest, MAX_RENEW_BODY_BYTES, required=False)


def device_service(request: Request) -> CompanionDeviceService:
    container = request.app.state.container
    return CompanionDeviceService(CompanionDeviceStore(container.session_factory), container.auth)


def _device_json(device: CompanionDeviceView) -> dict[str, Any]:
    return {
        "id": str(device.id),
        "label": device.label,
        "scopes": list(device.scopes),
        "expires_at": iso(device.expires_at),
        "renew_after": iso(device.renew_after),
        "created_at": iso(device.created_at),
        "last_used_at": iso(device.last_used_at),
    }


async def _license_state(request: Request) -> dict[str, Any]:
    """The license display state that rides in every pair, device and renew answer."""

    view = await run_in_threadpool(request.app.state.container.license.display)
    return view.as_json()


def _count_pairing_failure(request: Request, *, limited: bool) -> None:
    request.app.state.container.telemetry.count(
        "sidekick.companion.pairing_failures", {"companion.limited": str(limited).lower()}
    )


def _spend_pairing_budget(request: Request, failed_pairings: TokenBucket) -> None:
    """Reserve one token BEFORE awaiting the exchange. Checking first and spending after would
    let any number of concurrent requests pass the check before the first one spends, so the
    budget is taken up front, atomically (no await between check and take). One budget for all
    callers (behind a tunnel every visitor has the same peer address). With the budget spent we
    refuse before any database work or exchange call; a valid secret is refused too until the
    budget refills, because validity is only known after the exchange. A refused attempt writes
    no audit row, only a content-free counter."""

    if failed_pairings.take():
        return
    _count_pairing_failure(request, limited=True)
    raise CompanionProblem(
        429,
        "rate_limited",
        "Too many requests",
        headers={"Retry-After": str(failed_pairings.seconds_until_budget())},
    )


def _owner_timezone(request: Request) -> str:
    """The owner's IANA zone: the one the server counts "today" in, which the phone must follow."""

    return str(request.app.state.container.settings.owner_timezone)


def _push_enabled(request: Request) -> bool:
    """Whether the server delivers push (`SIDEKICK_PUSH_ENABLED`); the app hides its row if off."""

    return bool(request.app.state.container.settings.push_enabled)


def make_pair(
    failed_pairings: TokenBucket, enabled_rooms: list[str]
) -> Callable[[Request], Awaitable[JSONResponse]]:
    """The `POST /pair` handler, bound to this router's pairing budget and enabled rooms."""

    async def pair(request: Request) -> JSONResponse:
        payload = await PAIR_BODY.read(request)
        _spend_pairing_budget(request, failed_pairings)
        paired = await run_in_threadpool(
            device_service(request).exchange,
            payload.pairing_secret,
            correlation_id=request.scope.get("sidekick.correlation_id"),
        )
        if paired is None:
            # The reservation stays spent: failures are what consume the budget.
            _count_pairing_failure(request, limited=False)
            raise CompanionProblem(
                401, "pairing_invalid", "Pairing secret is invalid, expired or already used"
            )
        # A successful pairing does not consume budget: give the reservation back.
        failed_pairings.refund()
        return JSONResponse(
            status_code=201,
            headers=no_store_headers,
            content={
                "api_version": API_VERSION,
                "token_type": "Bearer",
                "access_token": paired.token,
                "device": _device_json(paired.device),
                "license": await _license_state(request),
                "enabled_rooms": enabled_rooms,
                "timezone": _owner_timezone(request),
                "push_enabled": _push_enabled(request),
            },
        )

    return pair


def make_device_status(
    enabled_rooms: list[str],
) -> Callable[[Request], Awaitable[JSONResponse]]:
    """The `GET /device` handler, bound to this router's enabled rooms."""

    async def device_status(request: Request) -> JSONResponse:
        credential = await credential_for(request)
        device = await run_in_threadpool(
            device_service(request).get_device, credential.user_id, credential.device_id
        )
        if device is None:
            raise CompanionProblem(401, "unauthorized", "Authentication required")
        return JSONResponse(
            headers=no_store_headers,
            content={
                "api_version": API_VERSION,
                "device": _device_json(device),
                "license": await _license_state(request),
                "enabled_rooms": enabled_rooms,
                "timezone": _owner_timezone(request),
                "push_enabled": _push_enabled(request),
            },
        )

    return device_status


async def _renew(request: Request, credential: CompanionCredential) -> PairedDevice:
    """Renew the calling device's credential, or raise the closed refusal for why not."""

    try:
        renewed = await run_in_threadpool(
            lambda: device_service(request).renew(
                credential.user_id,
                credential.device_id,
                bearer_token(request),
                correlation_id=request.scope.get("sidekick.correlation_id"),
            )
        )
    except RenewalNotDue as not_due:
        raise CompanionProblem(
            409,
            "conflict",
            "Conflict",
            reason="renewal_not_due",
            extra={"renew_after": not_due.renew_after.isoformat()},
        ) from None
    except RenewalRateLimited as limited:
        raise CompanionProblem(
            429,
            "rate_limited",
            "Too many requests",
            headers={"Retry-After": str(limited.retry_after_seconds)},
        ) from None
    if renewed is None:
        raise CompanionProblem(
            401,
            "unauthorized",
            "Authentication required",
            headers={
                "WWW-Authenticate": 'Bearer realm="sidekick-companion", error="invalid_token"'
            },
        )
    return renewed


def make_device_renew(
    enabled_rooms: list[str],
) -> Callable[..., Awaitable[JSONResponse]]:
    """The `POST /device/renew` handler, bound to this router's enabled rooms."""

    async def device_renew(request: Request, credential: Credential) -> JSONResponse:
        # Any valid credential of the pairing may renew, so no capability is checked (as for
        # `device.status`); it reaches no domain use case and holds no application scope.
        # Authentication has run before the body is read.
        if (await bounded_body(request, RENEW_BODY.max_bytes)).strip() not in (b"", b"{}"):
            raise CompanionProblem(422, "validation_error", "Request validation failed")
        renewed = await _renew(request, credential)
        return JSONResponse(
            headers=no_store_headers,
            content={
                "api_version": API_VERSION,
                "token_type": "Bearer",
                "access_token": renewed.token,
                "device": _device_json(renewed.device),
                "enabled_rooms": enabled_rooms,
                "timezone": _owner_timezone(request),
                "push_enabled": _push_enabled(request),
                "license": await _license_state(request),
            },
        )

    return device_renew


async def device_unpair(request: Request) -> Response:
    credential = await credential_for(request)
    await run_in_threadpool(
        lambda: device_service(request).revoke_device(
            credential.user_id,
            credential.device_id,
            by_device=True,
            correlation_id=request.scope.get("sidekick.correlation_id"),
        )
    )
    return Response(status_code=204, headers=no_store_headers)


def add_device_routes(
    router: CompanionRouter, failed_pairings: TokenBucket, enabled_rooms: list[str]
) -> None:
    """Register pairing and the device's own routes on the companion router."""

    router.add(
        CompanionRouteSpec(
            "POST", "/pair", "device.pair", body=PAIR_BODY, unauthenticated=True, status_code=201
        ),
        make_pair(failed_pairings, enabled_rooms),
    )
    router.add(
        CompanionRouteSpec("GET", "/device", "device.status"), make_device_status(enabled_rooms)
    )
    router.add(
        CompanionRouteSpec("POST", "/device/renew", "device.renew", body=RENEW_BODY),
        make_device_renew(enabled_rooms),
    )
    router.add(
        CompanionRouteSpec("DELETE", "/device", "device.unpair", status_code=204), device_unpair
    )

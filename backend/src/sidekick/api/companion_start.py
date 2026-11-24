"""`/companion/v1/` routes of Start and the suggestion inbox (ADR-005, ADR-013).

For the moments the owner cannot talk to Claude; Claude stays the main way in. Added to the
companion router by `create_companion_router` (sidekick.api.companion), which also supplies the
route class, so every refusal here is the same versioned problem envelope and the request log
carries only the operation name and the outcome. Each route verifies the credential, checks the
operation's capability and calls the use case the MCP tool of the same name calls, answering that
tool's structured content, so the phone's Start room reads what it reads in Claude:

- `GET  /companion/v1/start`                = `get_start` (`companion:start:read`)
- `GET  /companion/v1/suggestions`          = `list_suggestions` (`state`, `automation_id`, `group`,
  `limit` 1-25, `cursor`; `companion:suggestions:read`)
- `GET  /companion/v1/suggestions/{suggestion_id}` = `get_suggestion`
- `POST /companion/v1/suggestions/decisions` = `decide_suggestions` (`{"items": [{"suggestion_id",
  "expected_version", "decision", "confirmed"}]`, one to three cards;
  `companion:suggestions:decide`)
- `POST /companion/v1/suggestions/group-approvals` = `approve_suggestion_group`
  (`{"group_digest", "suggestion_ids"}`: the high-confidence group the owner was shown, refused as
  a whole when it changed; `companion:suggestions:decide`)
- `POST /companion/v1/suggestions/{suggestion_id}/undo` = `undo_suggestion`
  (`{"expected_version"}`; `companion:suggestions:decide`)

Deciding is the owner's act. In Claude a group is approved only by the app, proved by a decision
ticket (`sidekick.mcp.decision_ticket`); the phone has no ticket, so deciding here needs the device
capability `companion:suggestions:decide`, which is granted on its own and is never part of reading,
and the use case records the `companion` decision channel on the card. Every write carries
`Idempotency-Key`, and a replay answers with each card as it is now. An edit of a card's payload
is not offered here: the body names no `edits`. An unknown or another owner's card is 404, a stale
version is a refusal inside the answer (`error_code`), and the owner is always the credential's.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Annotated
from uuid import UUID

import pydantic_core
from fastapi import Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from sidekick.api.companion import (
    CompanionRouter,
    CompanionRouteSpec,
    Credential,
    IdempotencyKey,
    RequestBody,
    credential_for,
    no_store_headers,
)
from sidekick.automations.application.suggestion_reads import MAX_PAGE, GroupFilter
from sidekick.automations.application.suggestions import DecisionItem
from sidekick.automations.domain.suggestion import Decision, DecisionChannel, SuggestionState
from sidekick.companion.operations import (
    START_READ,
    SUGGESTION_APPROVE_GROUP,
    SUGGESTION_DECIDE,
    SUGGESTION_DETAIL,
    SUGGESTION_UNDO,
    SUGGESTIONS_READ,
    operation_actor,
)
from sidekick.companion.push_outbox_store import acting_device
from sidekick.composition import container_of
from sidekick.shared.rooms import disabled_scopes
from sidekick.shared.types import MAX_CURSOR_LENGTH, Actor
from sidekick.structured.automation_suggestion_records import (
    GroupIdsInput,
    decisions_output,
    page_output,
    suggestion_output,
    undo_output,
)
from sidekick.structured.start import start_structured

MAX_DECISION_BODY_BYTES = 4096
MAX_GROUP_BODY_BYTES = 4096

_Digest = Annotated[str, Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionBodyItem(_Body):
    """One decision of the owner. No `edits`: the phone approves or dismisses a card as written."""

    suggestion_id: UUID
    expected_version: Annotated[int, Field(ge=1)]
    decision: Decision
    confirmed: bool = False


class DecisionsBody(_Body):
    items: Annotated[list[DecisionBodyItem], Field(min_length=1, max_length=3)]


class GroupApprovalBody(_Body):
    group_digest: _Digest
    suggestion_ids: GroupIdsInput


class UndoBody(_Body):
    expected_version: Annotated[int, Field(ge=1)]


DECISIONS_BODY = RequestBody(DecisionsBody, MAX_DECISION_BODY_BYTES)
GROUP_BODY = RequestBody(GroupApprovalBody, MAX_GROUP_BODY_BYTES)
UNDO_BODY = RequestBody(UndoBody, MAX_DECISION_BODY_BYTES)


def _answer(structured: BaseModel) -> JSONResponse:
    return JSONResponse(
        headers=no_store_headers,
        content=pydantic_core.to_jsonable_python(structured.model_dump(mode="json")),
    )


def _correlation(request: Request) -> str:
    return request.scope.get("sidekick.correlation_id") or "unknown"


def _release_stale_checks(request: Request, actor: Actor) -> None:
    """End the wait of the owner's runs for a check nobody does, so their cards can be decided.

    The same step as the MCP tools take before they read the inbox.
    """

    container_of(request).automation_runs.release_stale_checks(actor.user_id)


def _within_rooms(actor: Actor, rooms: Collection[str]) -> Actor:
    """The actor minus the scopes of the rooms this instance switches off.

    The MCP surface narrows its actor the same way (`room_actor_provider`), so Start and the inbox
    never show or apply what belongs to a room that is off, whatever the device was granted.
    """

    off = disabled_scopes(rooms)
    return Actor(actor.user_id, actor.scopes - off) if off else actor


def add_start_routes(router: CompanionRouter, rooms: Collection[str]) -> None:
    """Register Start and the suggestion inbox. Start is a room that is always on."""

    @router.register(CompanionRouteSpec("GET", "/start", START_READ.name))
    async def start(request: Request) -> JSONResponse:
        credential = await credential_for(request)
        actor = _within_rooms(operation_actor(credential, START_READ), rooms)
        container = container_of(request)
        built = await run_in_threadpool(
            lambda: start_structured(container, actor, correlation_id=_correlation(request))
        )
        # Parts the device may not read are left out, as in Claude (`exclude_unset`).
        return JSONResponse(
            headers=no_store_headers,
            content=built.output.model_dump(mode="json", exclude_unset=True),
        )

    _add_inbox_reads(router, rooms)
    _add_inbox_decisions(router, rooms)


def _add_inbox_reads(router: CompanionRouter, rooms: Collection[str]) -> None:
    @router.register(CompanionRouteSpec("GET", "/suggestions", SUGGESTIONS_READ.name))
    async def suggestions_list(
        request: Request,
        state: SuggestionState = SuggestionState.PENDING,
        automation_id: UUID | None = None,
        group: GroupFilter = GroupFilter.ALL,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = MAX_PAGE,
        cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> JSONResponse:
        credential = await credential_for(request)
        actor = _within_rooms(operation_actor(credential, SUGGESTIONS_READ), rooms)
        container = container_of(request)

        def read() -> BaseModel:
            _release_stale_checks(request, actor)
            return page_output(
                container.automation_suggestions.list_suggestions(
                    actor,
                    state=state,
                    automation_id=automation_id,
                    group=group,
                    limit=limit,
                    cursor=cursor,
                )
            )

        return _answer(await run_in_threadpool(read))

    @router.register(
        CompanionRouteSpec("GET", "/suggestions/{suggestion_id}", SUGGESTION_DETAIL.name)
    )
    async def suggestion_get(request: Request, suggestion_id: UUID) -> JSONResponse:
        credential = await credential_for(request)
        actor = _within_rooms(operation_actor(credential, SUGGESTION_DETAIL), rooms)
        container = container_of(request)

        def read() -> BaseModel:
            _release_stale_checks(request, actor)
            return suggestion_output(container.automation_suggestions.get(actor, suggestion_id))

        return _answer(await run_in_threadpool(read))


def _add_inbox_decisions(router: CompanionRouter, rooms: Collection[str]) -> None:
    @router.register(
        CompanionRouteSpec(
            "POST", "/suggestions/decisions", SUGGESTION_DECIDE.name, body=DECISIONS_BODY
        )
    )
    async def suggestions_decide(
        request: Request, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = _within_rooms(operation_actor(credential, SUGGESTION_DECIDE), rooms)
        body = await DECISIONS_BODY.read(request)
        container = container_of(request)

        def decide() -> BaseModel:
            # The device's own change queues no wake push for itself (D-078).
            with acting_device(credential.device_id):
                outcomes = container.automation_suggestions.decide(
                    actor,
                    [
                        DecisionItem(
                            item.suggestion_id,
                            item.expected_version,
                            item.decision,
                            None,
                            item.confirmed,
                        )
                        for item in body.items
                    ],
                    channel=DecisionChannel.COMPANION,
                    session_id=None,
                    idempotency_key=idempotency_key,
                    correlation_id=_correlation(request),
                )
            return decisions_output(outcomes)

        return _answer(await run_in_threadpool(decide))

    @router.register(
        CompanionRouteSpec(
            "POST",
            "/suggestions/group-approvals",
            SUGGESTION_APPROVE_GROUP.name,
            body=GROUP_BODY,
        )
    )
    async def suggestions_approve_group(
        request: Request, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = _within_rooms(operation_actor(credential, SUGGESTION_APPROVE_GROUP), rooms)
        body = await GROUP_BODY.read(request)
        container = container_of(request)

        def approve() -> BaseModel:
            with acting_device(credential.device_id):
                outcomes = container.automation_suggestions.approve_group(
                    actor,
                    group_digest=body.group_digest,
                    suggestion_ids=body.suggestion_ids,
                    idempotency_key=idempotency_key,
                    channel=DecisionChannel.COMPANION,
                    correlation_id=_correlation(request),
                )
            return decisions_output(outcomes)

        return _answer(await run_in_threadpool(approve))

    @router.register(
        CompanionRouteSpec(
            "POST", "/suggestions/{suggestion_id}/undo", SUGGESTION_UNDO.name, body=UNDO_BODY
        )
    )
    async def suggestion_undo(
        request: Request,
        suggestion_id: UUID,
        credential: Credential,
        idempotency_key: IdempotencyKey,
    ) -> JSONResponse:
        actor = _within_rooms(operation_actor(credential, SUGGESTION_UNDO), rooms)
        body = await UNDO_BODY.read(request)
        container = container_of(request)

        def undo() -> BaseModel:
            with acting_device(credential.device_id):
                outcome = container.automation_suggestions.undo(
                    actor,
                    suggestion_id,
                    expected_version=body.expected_version,
                    idempotency_key=idempotency_key,
                    correlation_id=_correlation(request),
                )
            return undo_output(outcome)

        return _answer(await run_in_threadpool(undo))

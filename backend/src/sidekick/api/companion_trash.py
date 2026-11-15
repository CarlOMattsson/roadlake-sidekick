"""`/companion/v1/` routes of the trash: delete with undo, list, restore and empty (ADR-005).

For the moments the owner cannot talk to Claude; Claude stays the main way in. Added to the
companion router by `create_companion_router` (sidekick.api.companion), which also supplies the
route class, so every refusal here is the same versioned problem envelope and the request log
carries only the operation name and the outcome. Each route verifies the credential, checks the
operation's capability (the room's write capability, and its read capability, because the answer
names the record) and calls the lifecycle use case the MCP tools `move_to_trash` and
`restore_from_trash` call, answering that tool's structured content (`TrashItemRecord`):

- `POST /companion/v1/tasks/{task_id}/trash`, `.../untrash`
- `POST /companion/v1/journal/entries/{entry_id}/trash`, `.../untrash`
- `POST /companion/v1/shopping/items/{item_id}/trash`, `.../untrash`
  (`{"version"}`: the record's version for `trash`, the trash record's version for `untrash`)
- `GET  /companion/v1/trash`  = `list_trash` over the kinds above that the device may trash
  (`limit` 1-100, default 50, `cursor`; `kind` narrows it to one of them; the answer also says
  `can_erase`, whether this device holds `companion:work:erase`)
- `POST /companion/v1/tasks/{task_id}/erase`  removes one trashed Task for good
  (`{"version", "confirm": true}`; answers `{"removed": true}`; needs `companion:work:erase`)
- `POST /companion/v1/trash/empty`  removes every trashed Task that can be removed
  (`{"confirm": true}`, no key needed; answers `{"removed", "kept"}`, the counts of Tasks)

Permanent removal is not an MCP tool (D-031). Here it is a human action in the app: it needs an
explicit `confirm: true` in the body, only a Task already in the trash can be removed (the use case
refuses everything else, and a Journal entry or a Shopping item can never be removed this way), and
a Task that still has Steps stays (409). Every other write carries `Idempotency-Key`; a stale
`version` is 409 `stale_version`, another owner's id is 404, and the owner is always the
credential's.
A room that is switched off (`SIDEKICK_ENABLED_ROOMS`) gets no trash route of its own.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Annotated, Literal
from uuid import UUID

import pydantic_core
from fastapi import Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
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
from sidekick.companion.operations import (
    JOURNAL_ENTRY_TRASH,
    JOURNAL_ENTRY_UNTRASH,
    SHOPPING_ITEM_TRASH,
    SHOPPING_ITEM_UNTRASH,
    TASK_ERASE,
    TASK_TRASH,
    TASK_UNTRASH,
    TRASH_EMPTY,
    CapabilityMissing,
    CompanionOperation,
    operation_actor,
    trash_listing_actor,
)
from sidekick.companion.push_outbox_store import acting_device
from sidekick.composition import container_of
from sidekick.lifecycle import RecordKind
from sidekick.lifecycle.application.empty_trash import empty_owner_trash
from sidekick.shared.auth import CompanionCredential
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.trash import (
    list_trash_structured,
    move_to_trash_structured,
    restore_from_trash_structured,
)

MAX_TRASH_BODY_BYTES = 4096

Version = Annotated[int, Field(ge=1)]
# The kinds the list may be narrowed to: the kinds with a trash route of this module.
ListedKind = Literal["task", "journal_entry", "shopping_item"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionBody(_Body):
    version: Version


def _only_true(value: object) -> object:
    # `1 == True` in Python, so a Literal alone would let the number 1 confirm.
    if value is not True:
        raise ValueError("confirm must be the JSON value true")
    return value


# Only the JSON `true` confirms (not 1, not "true", not null).
Confirmed = Annotated[Literal[True], BeforeValidator(_only_true)]


class EraseBody(_Body):
    """Permanent removal needs the explicit `confirm: true`; anything else is a plain 422."""

    version: Version
    confirm: Confirmed


class EmptyBody(_Body):
    confirm: Confirmed


VERSION_BODY = RequestBody(VersionBody, MAX_TRASH_BODY_BYTES)
ERASE_BODY = RequestBody(EraseBody, MAX_TRASH_BODY_BYTES)
EMPTY_BODY = RequestBody(EmptyBody, MAX_TRASH_BODY_BYTES)


def _answer(structured: BaseModel | Mapping[str, object]) -> JSONResponse:
    content = (
        structured.model_dump(mode="json") if isinstance(structured, BaseModel) else structured
    )
    return JSONResponse(headers=no_store_headers, content=pydantic_core.to_jsonable_python(content))


def _correlation(request: Request) -> str | None:
    return request.scope.get("sidekick.correlation_id")


async def _transition(
    request: Request,
    credential: CompanionCredential,
    idempotency_key: str,
    *,
    kind: RecordKind,
    record_id: UUID,
    operation: CompanionOperation,
    to_trash: bool,
) -> JSONResponse:
    """Move one record to the trash or take it back, under `operation`'s fixed actor."""

    actor = operation_actor(credential, operation)
    body = await VERSION_BODY.read(request)
    container = container_of(request)
    move = move_to_trash_structured if to_trash else restore_from_trash_structured

    def run() -> BaseModel:
        # The device's own change queues no wake push for itself (D-078).
        with acting_device(credential.device_id):
            return move(
                container,
                actor,
                kind,
                record_id,
                version=body.version,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
            )

    return _answer(await run_in_threadpool(run))


def add_trash_routes(router: CompanionRouter, rooms: Collection[str]) -> None:
    """Register the trash routes of the rooms this instance shows (Work is always on)."""

    _add_task_routes(router)
    if "journal" in rooms:
        _add_journal_routes(router)
    if "shopping" in rooms:
        _add_shopping_routes(router)
    _add_list_and_empty_routes(router, rooms)


def _spec(path: str, operation: CompanionOperation) -> CompanionRouteSpec:
    return CompanionRouteSpec("POST", path, operation.name, body=VERSION_BODY)


def _add_journal_routes(router: CompanionRouter) -> None:
    @router.register(_spec("/journal/entries/{entry_id}/trash", JOURNAL_ENTRY_TRASH))
    async def journal_entry_trash(
        request: Request, entry_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        return await _transition(
            request,
            credential,
            idempotency_key,
            kind=RecordKind.JOURNAL_ENTRY,
            record_id=entry_id,
            operation=JOURNAL_ENTRY_TRASH,
            to_trash=True,
        )

    @router.register(_spec("/journal/entries/{entry_id}/untrash", JOURNAL_ENTRY_UNTRASH))
    async def journal_entry_untrash(
        request: Request, entry_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        return await _transition(
            request,
            credential,
            idempotency_key,
            kind=RecordKind.JOURNAL_ENTRY,
            record_id=entry_id,
            operation=JOURNAL_ENTRY_UNTRASH,
            to_trash=False,
        )


def _add_shopping_routes(router: CompanionRouter) -> None:
    @router.register(_spec("/shopping/items/{item_id}/trash", SHOPPING_ITEM_TRASH))
    async def shopping_item_trash(
        request: Request, item_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        return await _transition(
            request,
            credential,
            idempotency_key,
            kind=RecordKind.SHOPPING_ITEM,
            record_id=item_id,
            operation=SHOPPING_ITEM_TRASH,
            to_trash=True,
        )

    @router.register(_spec("/shopping/items/{item_id}/untrash", SHOPPING_ITEM_UNTRASH))
    async def shopping_item_untrash(
        request: Request, item_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        return await _transition(
            request,
            credential,
            idempotency_key,
            kind=RecordKind.SHOPPING_ITEM,
            record_id=item_id,
            operation=SHOPPING_ITEM_UNTRASH,
            to_trash=False,
        )


def _add_task_routes(router: CompanionRouter) -> None:
    @router.register(_spec("/tasks/{task_id}/trash", TASK_TRASH))
    async def task_trash(
        request: Request, task_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        return await _transition(
            request,
            credential,
            idempotency_key,
            kind=RecordKind.TASK,
            record_id=task_id,
            operation=TASK_TRASH,
            to_trash=True,
        )

    @router.register(_spec("/tasks/{task_id}/untrash", TASK_UNTRASH))
    async def task_untrash(
        request: Request, task_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        return await _transition(
            request,
            credential,
            idempotency_key,
            kind=RecordKind.TASK,
            record_id=task_id,
            operation=TASK_UNTRASH,
            to_trash=False,
        )

    @router.register(
        CompanionRouteSpec("POST", "/tasks/{task_id}/erase", TASK_ERASE.name, body=ERASE_BODY)
    )
    async def task_erase(
        request: Request, task_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, TASK_ERASE)
        body = await ERASE_BODY.read(request)
        container = container_of(request)

        def run() -> None:
            with acting_device(credential.device_id):
                container.lifecycle.permanently_remove(
                    actor,
                    RecordKind.TASK,
                    task_id,
                    version=body.version,
                    idempotency_key=idempotency_key,
                    correlation_id=_correlation(request),
                )

        await run_in_threadpool(run)
        return _answer({"removed": True})


def _add_list_and_empty_routes(router: CompanionRouter, rooms: Collection[str]) -> None:
    @router.register(CompanionRouteSpec("GET", "/trash", "trash.list"))
    async def trash_list(
        request: Request,
        kind: ListedKind | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> JSONResponse:
        credential = await credential_for(request)
        actor, kinds = trash_listing_actor(credential)
        # A room that is switched off lists nothing, even if records of its kind sit in the trash.
        kinds = kinds & _shown_kinds(rooms)
        container = container_of(request)
        listed = await run_in_threadpool(
            list_trash_structured,
            container,
            actor,
            kind=RecordKind(kind) if kind else None,
            limit=limit,
            cursor=cursor,
            within=kinds,
        )
        # Additive: the app reads this to offer permanent removal only where it is allowed.
        return _answer({**listed.model_dump(mode="json"), "can_erase": _may_erase(credential)})

    @router.register(CompanionRouteSpec("POST", "/trash/empty", TRASH_EMPTY.name, body=EMPTY_BODY))
    async def trash_empty(request: Request, credential: Credential) -> JSONResponse:
        # Repeating it is harmless without a key of its own: every record is removed under its own
        # key (`empty-trash-{id}-{version}`) and a removed record is gone.
        actor = operation_actor(credential, TRASH_EMPTY)
        await EMPTY_BODY.read(request)
        container = container_of(request)

        def run() -> dict[str, int]:
            with acting_device(credential.device_id):
                result = empty_owner_trash(
                    container.lifecycle,
                    actor,
                    kinds=frozenset({RecordKind.TASK}),
                    correlation_id=_correlation(request),
                )
            return {
                "removed": result.removed[RecordKind.TASK],
                "kept": result.kept[RecordKind.TASK],
            }

        return _answer(await run_in_threadpool(run))


def _may_erase(credential: CompanionCredential) -> bool:
    try:
        operation_actor(credential, TASK_ERASE)
    except CapabilityMissing:
        return False
    return True


def _shown_kinds(rooms: Collection[str]) -> frozenset[RecordKind]:
    shown = {RecordKind.TASK}
    if "journal" in rooms:
        shown.add(RecordKind.JOURNAL_ENTRY)
    if "shopping" in rooms:
        shown.add(RecordKind.SHOPPING_ITEM)
    return frozenset(shown)

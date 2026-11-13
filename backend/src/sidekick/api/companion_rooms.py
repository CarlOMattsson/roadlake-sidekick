"""`/companion/v1/` routes of the rooms Shopping and Journal (ADR-005; D-076: the journal is
written by hand).

Added to the companion router by `create_companion_router` (sidekick.api.companion), which also
supplies the route class, so every refusal here is the same versioned problem envelope and the
request log carries only the operation name and the outcome. Like the Idag routes, each one is a
thin transport over the use case the MCP tool of the same name calls, and answers that tool's
structured content, so the React rooms read what they read in Claude.

Shopping (`companion:shopping:read`; the writes also `companion:shopping:write`):

- `GET  /companion/v1/shopping/lists`                       = `list_shopping_lists`
- `GET  /companion/v1/shopping/lists/{list_id}`             = `get_shopping_list`
- `POST /companion/v1/shopping/lists`                       = `create_shopping_list` (`{"name"}`)
- `POST /companion/v1/shopping/lists/{list_id}/update`      = `update_shopping_list`
  (`{"name", "archived", "version"}`)
- `POST /companion/v1/shopping/lists/{list_id}/items`       = `add_shopping_items`
  (`{"items", "merge_duplicates"}`)
- `POST /companion/v1/shopping/items/{item_id}/update`      = `update_shopping_item`
  (`{"item", "version"}`)
- `POST /companion/v1/shopping/items/{item_id}/purchased`   = `set_shopping_item_purchased`
  (`{"purchased", "version"}`; the undo is the same call with `purchased: false`)

Journal (`companion:journal:read`; the writes also `companion:journal:write`), only the owner's
manual writing (D-076: the journal is written by hand, no AI) and the text of a source read back,
no draft or summary flow:

- `GET  /companion/v1/journal/days/{journal_date}`          = `get_journal_day`
- `GET  /companion/v1/journal/entries`                      = `list_journal_entries`
- `GET  /companion/v1/journal/entries/{entry_id}`           = `get_journal_entry`
- `GET  /companion/v1/journal/sources/{source_id}`          = `get_journal_source`
- `POST /companion/v1/journal/entries`                      = `write_journal_entry`
- `POST /companion/v1/journal/entries/{entry_id}/update`    = `update_journal_entry`
  (`{"version", ...}`: `version` is the tool's `expected_version`)

Every write carries `Idempotency-Key`; a stale `version` is 409 `stale_version`, another owner's id
is 404, and the owner is always the credential's.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

import pydantic_core
from fastapi import Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
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
    JOURNAL_DAY,
    JOURNAL_ENTRIES,
    JOURNAL_ENTRY,
    JOURNAL_ENTRY_UPDATE,
    JOURNAL_ENTRY_WRITE,
    JOURNAL_SOURCE,
    SHOPPING_ITEM_PURCHASED,
    SHOPPING_ITEM_UPDATE,
    SHOPPING_ITEMS_ADD,
    SHOPPING_LIST,
    SHOPPING_LIST_CREATE,
    SHOPPING_LIST_UPDATE,
    SHOPPING_LISTS,
    operation_actor,
)
from sidekick.companion.response_budget import TRIMMED_HEADER, fit_to_budget
from sidekick.shared.text_guard import NoImageData
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.shopping.application.schemas import BatchItem
from sidekick.structured.journal import (
    JournalKeyPointInput,
    journal_day_structured,
    journal_entries_structured,
    journal_entry_structured,
    journal_source_structured,
    update_journal_entry_structured,
    write_journal_entry_structured,
)
from sidekick.structured.shopping import ItemPatchInput, item_patch

# Caps on what is read, after authentication. The phone's own plugin refuses a body over 256 KiB
# (`RequestPolicy.MAX_BODY_BYTES`); these are the server's ceilings for the largest legal body
# (50 items; a 100 000 character entry).
MAX_SHOPPING_BODY_BYTES = 128 * 1024
MAX_JOURNAL_BODY_BYTES = 256 * 1024

Version = Annotated[int, Field(ge=1)]
IdList = Annotated[list[UUID], Field(max_length=25, json_schema_extra={"uniqueItems": True})]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateListBody(_Body):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class UpdateListBody(CreateListBody):
    archived: bool
    version: Version


class AddItemsBody(_Body):
    items: Annotated[list[BatchItem], Field(min_length=1, max_length=50)]
    merge_duplicates: bool = False


class UpdateItemBody(_Body):
    item: ItemPatchInput
    version: Version


class PurchasedBody(_Body):
    purchased: bool
    version: Version


class WriteEntryBody(_Body):
    journal_date: date
    title: Annotated[str, Field(min_length=1, max_length=200), NoImageData]
    source_text: Annotated[str, Field(min_length=1, max_length=100_000), NoImageData]
    summary: Annotated[str, Field(max_length=10_000), NoImageData] | None = None
    key_points: Annotated[list[JournalKeyPointInput], Field(max_length=50)] | None = None
    project_ids: IdList | None = None
    task_ids: IdList | None = None
    contact_ids: IdList | None = None
    occurred_at: datetime | None = None
    language: Annotated[str, Field(min_length=2, max_length=35)] | None = None


class UpdateEntryBody(_Body):
    version: Version
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    summary: Annotated[str, Field(max_length=10_000)] | None = None
    key_points: Annotated[list[JournalKeyPointInput], Field(max_length=50)] | None = None
    append_key_points: Annotated[list[JournalKeyPointInput], Field(max_length=50)] | None = None
    append_text: Annotated[str, Field(min_length=1, max_length=100_000), NoImageData] | None = None
    # No link fields (add/remove project or contact ids): changing a link needs `projects:read` or
    # `contacts:read`, which a Journal device does not hold. `extra="forbid"` refuses them as a
    # plain 422 that echoes nothing, instead of letting the use case answer 403 after the fact.


CREATE_LIST_BODY = RequestBody(CreateListBody, MAX_SHOPPING_BODY_BYTES)
UPDATE_LIST_BODY = RequestBody(UpdateListBody, MAX_SHOPPING_BODY_BYTES)
ADD_ITEMS_BODY = RequestBody(AddItemsBody, MAX_SHOPPING_BODY_BYTES)
UPDATE_ITEM_BODY = RequestBody(UpdateItemBody, MAX_SHOPPING_BODY_BYTES)
PURCHASED_BODY = RequestBody(PurchasedBody, MAX_SHOPPING_BODY_BYTES)
WRITE_ENTRY_BODY = RequestBody(WriteEntryBody, MAX_JOURNAL_BODY_BYTES)
UPDATE_ENTRY_BODY = RequestBody(UpdateEntryBody, MAX_JOURNAL_BODY_BYTES)


def _answer(structured: dict[str, Any], trimmed: str | None = None) -> JSONResponse:
    headers = dict(no_store_headers)
    if trimmed is not None:
        headers[TRIMMED_HEADER] = trimmed
    return JSONResponse(headers=headers, content=pydantic_core.to_jsonable_python(structured))


def _correlation(request: Request) -> str | None:
    return request.scope.get("sidekick.correlation_id")


def add_room_routes(router: CompanionRouter, rooms: Collection[str]) -> None:
    """Register the routes of the rooms Shopping and Journal that this instance shows.

    A room that is switched off (`SIDEKICK_ENABLED_ROOMS`) gets no route, so its paths answer 404.
    """

    if "shopping" in rooms:
        add_shopping_routes(router)
    if "journal" in rooms:
        add_journal_routes(router)


def add_shopping_routes(router: CompanionRouter) -> None:
    """Register the Shopping routes on the companion router."""

    _add_shopping_read_routes(router)
    _add_shopping_list_write_routes(router)
    _add_shopping_item_write_routes(router)


def _add_shopping_read_routes(router: CompanionRouter) -> None:

    @router.register(CompanionRouteSpec("GET", "/shopping/lists", SHOPPING_LISTS.name))
    async def shopping_lists(
        request: Request,
        credential: Credential,
        include_archived: bool = False,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    ) -> JSONResponse:
        actor = operation_actor(credential, SHOPPING_LISTS)
        service = request.app.state.container.shopping
        data = await run_in_threadpool(
            lambda: service.list_lists(
                actor, include_archived=include_archived, limit=limit, offset=offset
            )
        )
        return _answer(data)

    @router.register(CompanionRouteSpec("GET", "/shopping/lists/{list_id}", SHOPPING_LIST.name))
    async def shopping_list(
        request: Request,
        list_id: UUID,
        credential: Credential,
        on_date: date | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
        store: Annotated[str | None, Query(max_length=200)] = None,
    ) -> JSONResponse:
        actor = operation_actor(credential, SHOPPING_LIST)
        service = request.app.state.container.shopping
        data = await run_in_threadpool(
            lambda: service.get_list(
                actor, list_id, on_date=on_date, limit=limit, offset=offset, store=store
            )
        )
        return _answer(data)


def _add_shopping_list_write_routes(router: CompanionRouter) -> None:
    @router.register(
        CompanionRouteSpec(
            "POST", "/shopping/lists", SHOPPING_LIST_CREATE.name, body=CREATE_LIST_BODY
        )
    )
    async def shopping_list_create(
        request: Request, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, SHOPPING_LIST_CREATE)
        body = await CREATE_LIST_BODY.read(request)
        service = request.app.state.container.shopping
        data = await run_in_threadpool(
            lambda: service.create_list(
                actor,
                body.name,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
            )
        )
        return _answer(data)

    @router.register(
        CompanionRouteSpec(
            "POST",
            "/shopping/lists/{list_id}/update",
            SHOPPING_LIST_UPDATE.name,
            body=UPDATE_LIST_BODY,
        )
    )
    async def shopping_list_update(
        request: Request, list_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, SHOPPING_LIST_UPDATE)
        body = await UPDATE_LIST_BODY.read(request)
        service = request.app.state.container.shopping
        data = await run_in_threadpool(
            lambda: service.update_list(
                actor,
                list_id,
                name=body.name,
                archived=body.archived,
                version=body.version,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
            )
        )
        return _answer(data)

    @router.register(
        CompanionRouteSpec(
            "POST", "/shopping/lists/{list_id}/items", SHOPPING_ITEMS_ADD.name, body=ADD_ITEMS_BODY
        )
    )
    async def shopping_items_add(
        request: Request, list_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, SHOPPING_ITEMS_ADD)
        body = await ADD_ITEMS_BODY.read(request)
        service = request.app.state.container.shopping
        data = await run_in_threadpool(
            lambda: service.add_items(
                actor,
                list_id,
                body.items,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
                merge_duplicates=body.merge_duplicates,
            )
        )
        return _answer(data)


def _add_shopping_item_write_routes(router: CompanionRouter) -> None:
    @router.register(
        CompanionRouteSpec(
            "POST",
            "/shopping/items/{item_id}/update",
            SHOPPING_ITEM_UPDATE.name,
            body=UPDATE_ITEM_BODY,
        )
    )
    async def shopping_item_update(
        request: Request, item_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, SHOPPING_ITEM_UPDATE)
        body = await UPDATE_ITEM_BODY.read(request)
        service = request.app.state.container.shopping
        data = await run_in_threadpool(
            lambda: service.update_item(
                actor,
                item_id,
                item_patch(body.item),
                version=body.version,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
            )
        )
        return _answer(data)

    @router.register(
        CompanionRouteSpec(
            "POST",
            "/shopping/items/{item_id}/purchased",
            SHOPPING_ITEM_PURCHASED.name,
            body=PURCHASED_BODY,
        )
    )
    async def shopping_item_purchased(
        request: Request, item_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, SHOPPING_ITEM_PURCHASED)
        body = await PURCHASED_BODY.read(request)
        service = request.app.state.container.shopping
        data = await run_in_threadpool(
            lambda: service.set_purchased(
                actor,
                item_id,
                purchased=body.purchased,
                version=body.version,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
            )
        )
        # An internal flag of the use case, not an output field (the MCP tool drops it as well).
        data.pop("unchanged", None)
        return _answer(data)


def add_journal_routes(router: CompanionRouter) -> None:
    """Register the Journal routes on the companion router."""
    _add_journal_read_routes(router)
    _add_journal_write_routes(router)


def _add_journal_read_routes(router: CompanionRouter) -> None:

    @router.register(CompanionRouteSpec("GET", "/journal/days/{journal_date}", JOURNAL_DAY.name))
    async def journal_day(
        request: Request,
        journal_date: date,
        credential: Credential,
        include_content: bool = True,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
        cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> JSONResponse:
        actor = operation_actor(credential, JOURNAL_DAY)
        container = request.app.state.container
        structured, trimmed = await run_in_threadpool(
            lambda: fit_to_budget(
                lambda page_limit, content: journal_day_structured(
                    container,
                    actor,
                    journal_date,
                    include_archived=False,
                    include_content=content,
                    limit=page_limit,
                    cursor=cursor,
                ),
                limit=limit,
                include_content=include_content,
            )
        )
        return _answer(structured, trimmed)

    @router.register(CompanionRouteSpec("GET", "/journal/entries", JOURNAL_ENTRIES.name))
    async def journal_entries(
        request: Request,
        credential: Credential,
        from_date: date | None = None,
        to_date: date | None = None,
        include_content: bool = True,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
        cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> JSONResponse:
        actor = operation_actor(credential, JOURNAL_ENTRIES)
        container = request.app.state.container
        structured, trimmed = await run_in_threadpool(
            lambda: fit_to_budget(
                lambda page_limit, content: journal_entries_structured(
                    container,
                    actor,
                    from_date=from_date,
                    to_date=to_date,
                    include_archived=False,
                    include_content=content,
                    limit=page_limit,
                    cursor=cursor,
                ),
                limit=limit,
                include_content=include_content,
            )
        )
        return _answer(structured, trimmed)

    @router.register(CompanionRouteSpec("GET", "/journal/entries/{entry_id}", JOURNAL_ENTRY.name))
    async def journal_entry(
        request: Request,
        entry_id: UUID,
        credential: Credential,
        include_content: bool = True,
    ) -> JSONResponse:
        actor = operation_actor(credential, JOURNAL_ENTRY)
        container = request.app.state.container
        structured, trimmed = await run_in_threadpool(
            lambda: fit_to_budget(
                lambda _limit, content: journal_entry_structured(
                    container, actor, entry_id, include_content=content
                ),
                limit=1,
                include_content=include_content,
            )
        )
        return _answer(structured, trimmed)

    @router.register(CompanionRouteSpec("GET", "/journal/sources/{source_id}", JOURNAL_SOURCE.name))
    async def journal_source(
        request: Request,
        source_id: UUID,
        credential: Credential,
        include_content: bool = True,
    ) -> JSONResponse:
        actor = operation_actor(credential, JOURNAL_SOURCE)
        container = request.app.state.container
        structured = await run_in_threadpool(
            lambda: journal_source_structured(
                container, actor, source_id, include_content=include_content
            )
        )
        return _answer(structured)


def _add_journal_write_routes(router: CompanionRouter) -> None:
    @router.register(
        CompanionRouteSpec(
            "POST", "/journal/entries", JOURNAL_ENTRY_WRITE.name, body=WRITE_ENTRY_BODY
        )
    )
    async def journal_entry_write(
        request: Request,
        credential: Credential,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=8, max_length=120)
        ],
    ) -> JSONResponse:
        actor = operation_actor(credential, JOURNAL_ENTRY_WRITE)
        body = await WRITE_ENTRY_BODY.read(request)
        container = request.app.state.container
        structured = await run_in_threadpool(
            lambda: write_journal_entry_structured(
                container,
                actor,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
                **{name: getattr(body, name) for name in type(body).model_fields},
            )
        )
        return _answer(structured)

    @router.register(
        CompanionRouteSpec(
            "POST",
            "/journal/entries/{entry_id}/update",
            JOURNAL_ENTRY_UPDATE.name,
            body=UPDATE_ENTRY_BODY,
        )
    )
    async def journal_entry_update(
        request: Request, entry_id: UUID, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, JOURNAL_ENTRY_UPDATE)
        body = await UPDATE_ENTRY_BODY.read(request)
        container = request.app.state.container
        changes = {
            name: getattr(body, name) for name in type(body).model_fields if name != "version"
        }
        structured, _before = await run_in_threadpool(
            lambda: update_journal_entry_structured(
                container,
                actor,
                entry_id,
                expected_version=body.version,
                idempotency_key=idempotency_key,
                correlation_id=_correlation(request),
                **changes,
            )
        )
        return _answer(structured)

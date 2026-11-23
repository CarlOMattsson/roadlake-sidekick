"""The five Journal photo tools. All of them are app-only: the model never lists or calls them.

A photo reaches the server only from the Sidekick app (here, as base64) or from the Android app
(the companion's multipart route). A model is never handed the bytes of a photo and never sends
them: `visibility=["app"]` keeps these tools out of its tool list, and `REQUIRES_APP_META` makes
the server refuse a call to one that does not come from the app, so nothing the model says can
upload or read a photo. They call the same use cases as the companion route. Removing a photo is
the trash: `trash_journal_photo` and `restore_journal_photo` move it in and out, and only the
trash sweep erases it. Photos, captions and places never go to memory.

The host's limit on one tool call is OPEN (the server reads at most `MAX_MCP_BODY_BYTES` of a
request), so the app sends the photo and its thumbnail in one call only while both fit.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.journal.domain.photo import MAX_ALT_TEXT, MAX_CAMERA, PhotoSize
from sidekick.mcp.annotations import READ, WRITE
from sidekick.mcp.change_source import REQUIRES_APP_META
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.journal_records import VersionParam
from sidekick.mcp.journal_text import JournalToolContext
from sidekick.mcp.patch import CLEAR_SENTENCE, ignored_nulls_note
from sidekick.mcp.results import card_result, output_schema
from sidekick.shared.text_guard import NoImageData
from sidekick.structured.base import CLEAR_FIELDS
from sidekick.structured.journal_photos import (
    MAX_PHOTO_BASE64,
    MAX_THUMBNAIL_BASE64,
    JournalPhotoFileResult,
    JournalPhotoResult,
    JournalPhotoTrashResult,
    PhotoChangesInput,
    PhotoClear,
    PhotoLocationInput,
    UpdatedJournalPhotoResult,
    add_journal_photo_structured,
    decode_photo_data,
    get_journal_photo_structured,
    restore_journal_photo_structured,
    trash_journal_photo_structured,
    update_journal_photo_structured,
)

JOURNAL_PHOTO_TOOL_NAMES = (
    "add_journal_photo",
    "get_journal_photo",
    "update_journal_photo",
    "trash_journal_photo",
    "restore_journal_photo",
)
# What each tool needs in effect: add and update answer with the stored caption and place, so they
# need the read scope too (the reply rule of `reply_scopes`); trash and restore answer with an id.
JOURNAL_PHOTO_TOOL_SCOPES = {
    "add_journal_photo": {"journal:read", "journal:write"},
    "get_journal_photo": {"journal:read"},
    "update_journal_photo": {"journal:read", "journal:write"},
    "trash_journal_photo": {"journal:write"},
    "restore_journal_photo": {"journal:write"},
}

_APP_ONLY = AppConfig(visibility=["app"])
# The server also refuses a call that does not come from the app (`OwnerDecisionsFromTheApp`).
_REQUIRES_APP = {REQUIRES_APP_META: True}


def _register_add_journal_photo(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="add_journal_photo",
        description=(
            "App only: the Sidekick app adds one photo the owner chose to a journal entry "
            "(entry_id) or to a day (journal_date), exactly one of them. The app has already "
            "shrunk the photo (JPEG or WebP, long edge at most 2048 px, at most 4 MiB, no "
            "metadata inside) and sends its thumbnail (at most 320 px) as base64, beside the "
            "fields it read from the file: taken_at, location, camera, orientation. The server "
            "refuses a file that still carries metadata. At most 20 photos per entry or day. "
            "Retrying with the same idempotency_key stores the photo once."
        ),
        output_schema=output_schema(JournalPhotoResult),
        annotations=WRITE,
        app=_APP_ONLY,
        meta=_REQUIRES_APP,
    )
    @ctx.instrument("add_journal_photo")
    def add_journal_photo(
        photo: Annotated[str, Field(min_length=4, max_length=MAX_PHOTO_BASE64)],
        thumbnail: Annotated[str, Field(min_length=4, max_length=MAX_THUMBNAIL_BASE64)],
        idempotency_key: IdempotencyKey,
        entry_id: UUID | None = None,
        journal_date: date | None = None,
        alt_text: Annotated[str, Field(max_length=MAX_ALT_TEXT), NoImageData] | None = None,
        taken_at: datetime | None = None,
        location: PhotoLocationInput | None = None,
        camera: Annotated[str, Field(max_length=MAX_CAMERA), NoImageData] | None = None,
        orientation: Annotated[int, Field(ge=1, le=8)] | None = None,
    ) -> ToolResult:
        stored = add_journal_photo_structured(
            ctx.container,
            ctx.actor_provider(),
            entry_id=entry_id,
            journal_date=journal_date,
            photo=decode_photo_data(photo),
            thumbnail=decode_photo_data(thumbnail),
            alt_text=alt_text,
            taken_at=taken_at,
            location=location,
            camera=camera,
            orientation=orientation,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return card_result(stored.model_dump(mode="json"), "Added the photo.")


def _register_get_journal_photo(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="get_journal_photo",
        description=(
            "App only: the Sidekick app reads one photo of the owner's journal by id (the ids a "
            "journal record lists under attachments). size is thumb (the small picture, the "
            "default) or photo (the full file). The bytes come back as base64 in data, with the "
            "photo's fields; a photo in the trash, or on an entry in the trash, is not found."
        ),
        output_schema=output_schema(JournalPhotoFileResult),
        annotations=READ,
        app=_APP_ONLY,
        meta=_REQUIRES_APP,
    )
    @ctx.instrument("get_journal_photo")
    def get_journal_photo(photo_id: UUID, size: PhotoSize = "thumb") -> ToolResult:
        data = get_journal_photo_structured(ctx.container, ctx.actor_provider(), photo_id, size)
        return card_result(data.model_dump(mode="json"), "Returned the photo.")


def _register_update_journal_photo(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="update_journal_photo",
        description=(
            "App only: the Sidekick app changes one photo's caption (alt_text), place, time, "
            "camera, orientation or position, at the photo's current version. Only sent fields "
            f"change. {CLEAR_SENTENCE} The place is the owner's: it can be changed or removed "
            "at any time. A stale version conflicts."
        ),
        output_schema=output_schema(UpdatedJournalPhotoResult),
        annotations=WRITE,
        app=_APP_ONLY,
        meta=_REQUIRES_APP,
    )
    @ctx.instrument("update_journal_photo")
    def update_journal_photo(
        photo_id: UUID,
        changes: PhotoChangesInput,
        expected_version: VersionParam,
        idempotency_key: IdempotencyKey,
        clear: Annotated[list[PhotoClear], CLEAR_FIELDS] | None = None,
    ) -> ToolResult:
        saved = update_journal_photo_structured(
            ctx.container,
            ctx.actor_provider(),
            photo_id,
            changes,
            clear,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return card_result(
            saved.model_dump(mode="json"),
            f"Updated the photo.{ignored_nulls_note(changes.ignored_nulls)}",
        )


def _register_trash_journal_photo(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="trash_journal_photo",
        description=(
            "App only: the Sidekick app moves one photo to the trash, at its current version. "
            "It can be taken back with restore_journal_photo until the owner empties the trash, "
            "which erases it. A stale version conflicts."
        ),
        output_schema=output_schema(JournalPhotoTrashResult),
        annotations=WRITE,
        app=_APP_ONLY,
        meta=_REQUIRES_APP,
    )
    @ctx.instrument("trash_journal_photo")
    def trash_journal_photo(
        photo_id: UUID, expected_version: VersionParam, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        moved = trash_journal_photo_structured(
            ctx.container,
            ctx.actor_provider(),
            photo_id,
            version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return card_result(moved.model_dump(mode="json"), "Moved the photo to the trash.")


def _register_restore_journal_photo(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="restore_journal_photo",
        description=(
            "App only: the Sidekick app takes one photo back from the trash (the undo of "
            "trash_journal_photo), at the version that call returned. A stale version, or a "
            "photo that is not in the trash, conflicts."
        ),
        output_schema=output_schema(JournalPhotoTrashResult),
        annotations=WRITE,
        app=_APP_ONLY,
        meta=_REQUIRES_APP,
    )
    @ctx.instrument("restore_journal_photo")
    def restore_journal_photo(
        photo_id: UUID, expected_version: VersionParam, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        taken_back = restore_journal_photo_structured(
            ctx.container,
            ctx.actor_provider(),
            photo_id,
            version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return card_result(taken_back.model_dump(mode="json"), "Took the photo back.")


def register_journal_photo_tools(mcp: FastMCP, ctx: JournalToolContext) -> None:
    """Register the five app-only photo tools."""

    _register_add_journal_photo(mcp, ctx)
    _register_get_journal_photo(mcp, ctx)
    _register_update_journal_photo(mcp, ctx)
    _register_trash_journal_photo(mcp, ctx)
    _register_restore_journal_photo(mcp, ctx)


__all__ = [
    "JOURNAL_PHOTO_TOOL_NAMES",
    "JOURNAL_PHOTO_TOOL_SCOPES",
    "register_journal_photo_tools",
]

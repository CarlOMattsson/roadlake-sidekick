"""`/companion/v1/journal/photos`: a photo the owner adds from the phone, as a multipart form.

Added to the companion router with the Journal routes (`sidekick.api.companion_rooms`). It is the
phone's way into the same use case as the app-only `add_journal_photo` tool: the phone has the file,
not a base64 text, so the two files and the fields beside them arrive as the parts of one
`multipart/form-data` body:

- `POST /companion/v1/journal/photos` = `add_journal_photo`

Parts: `photo` and `thumbnail` (the files; the phone has already shrunk the photo to a long edge of
2048 px and at most 4 MiB and drawn the thumbnail, which also leaves the metadata out of both),
exactly one of `entry_id` and `journal_date`, and the optional fields the phone read from the file
before it shrank it: `taken_at`, `lat` and `lon` (together) with `place`, `camera`, `orientation`,
and `alt_text`. The server refuses a file that still carries metadata, and a photo is never sent to
memory. The route needs `Idempotency-Key`; the answer is the tool's structured content.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from sidekick.api.body_limits import MAX_PHOTO_UPLOAD_BODY_BYTES
from sidekick.api.companion import (
    MULTIPART_CONTENT,
    CompanionRouter,
    CompanionRouteSpec,
    Credential,
    IdempotencyKey,
    RequestBody,
    no_store_headers,
)
from sidekick.companion.operations import JOURNAL_PHOTO_ADD, operation_actor
from sidekick.composition import container_of
from sidekick.journal.domain.photo import MAX_ALT_TEXT, MAX_CAMERA, MAX_PLACE_NAME
from sidekick.shared.text_guard import NoImageData
from sidekick.structured.journal_photos import (
    PhotoLocationInput,
    add_journal_photo_structured,
)


class PhotoUploadForm(BaseModel):
    """The parts of the upload. Every field is one part of the form; a file is a `bytes` part."""

    model_config = ConfigDict(extra="forbid")

    photo: bytes
    thumbnail: bytes
    entry_id: UUID | None = None
    journal_date: date | None = None
    alt_text: Annotated[str, Field(max_length=MAX_ALT_TEXT), NoImageData] | None = None
    taken_at: datetime | None = None
    lat: Annotated[float, Field(ge=-90, le=90)] | None = None
    lon: Annotated[float, Field(ge=-180, le=180)] | None = None
    place: Annotated[str, Field(min_length=1, max_length=MAX_PLACE_NAME), NoImageData] | None = None
    camera: Annotated[str, Field(max_length=MAX_CAMERA), NoImageData] | None = None
    orientation: Annotated[int, Field(ge=1, le=8)] | None = None

    @model_validator(mode="after")
    def _one_target_and_a_whole_place(self) -> Self:
        if (self.entry_id is None) == (self.journal_date is None):
            raise ValueError("name exactly one of entry_id and journal_date")
        if (self.lat is None) != (self.lon is None):
            raise ValueError("send lat and lon together")
        if self.place is not None and self.lat is None:
            raise ValueError("a place name needs lat and lon")
        return self

    def location(self) -> PhotoLocationInput | None:
        if self.lat is None or self.lon is None:
            return None
        return PhotoLocationInput(lat=self.lat, lon=self.lon, name=self.place)


UPLOAD_BODY = RequestBody(
    PhotoUploadForm, MAX_PHOTO_UPLOAD_BODY_BYTES, content_type=MULTIPART_CONTENT
)


def add_journal_photo_routes(router: CompanionRouter) -> None:
    """Register the photo upload route on the companion router."""

    @router.register(
        CompanionRouteSpec("POST", "/journal/photos", JOURNAL_PHOTO_ADD.name, body=UPLOAD_BODY)
    )
    async def journal_photo_add(
        request: Request, credential: Credential, idempotency_key: IdempotencyKey
    ) -> JSONResponse:
        actor = operation_actor(credential, JOURNAL_PHOTO_ADD)
        form = await UPLOAD_BODY.read(request)
        container = container_of(request)
        structured = await run_in_threadpool(
            lambda: add_journal_photo_structured(
                container,
                actor,
                entry_id=form.entry_id,
                journal_date=form.journal_date,
                photo=form.photo,
                thumbnail=form.thumbnail,
                alt_text=form.alt_text,
                taken_at=form.taken_at,
                location=form.location(),
                camera=form.camera,
                orientation=form.orientation,
                idempotency_key=idempotency_key,
                correlation_id=request.scope.get("sidekick.correlation_id"),
            )
        )
        return JSONResponse(
            headers=dict(no_store_headers), content=structured.model_dump(mode="json")
        )

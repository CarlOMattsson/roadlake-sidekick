"""Journal photo records and structured results, shared by the MCP tools and the companion API.

The records name a photo's type, size, dimensions, caption and the fields the client sent beside
the image (`taken_at`, `location`, `camera`, `orientation`). They never carry a digest or the bytes;
the bytes come only from `get_journal_photo` as base64, and only to the app. Capture time is shown
in the owner's time zone: a value sent without an offset is read in that zone.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date, datetime, tzinfo
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from sidekick.journal.application.photos import PhotoUpload
from sidekick.journal.domain.photo import (
    MAX_ALT_TEXT,
    MAX_CAMERA,
    MAX_PHOTOS_PER_TARGET,
    MAX_PLACE_NAME,
    JournalPhoto,
    PhotoDetails,
    PhotoLocation,
    PhotoSize,
    PhotoSummary,
    PhotoTarget,
)
from sidekick.journal.domain.photo_format import (
    PHOTO_LIMITS,
    MediaType,
    PhotoRefusal,
    PhotoRefusedError,
)
from sidekick.lifecycle import RecordKind
from sidekick.shared.text_guard import NoImageData
from sidekick.shared.types import UNSET, Actor
from sidekick.structured.base import Output, PartialChanges, WithIgnoredNulls

if TYPE_CHECKING:
    from sidekick.composition import Container

# The longest base64 text of a photo or of its thumbnail: four characters for each three bytes.
MAX_PHOTO_BASE64 = (PHOTO_LIMITS.max_bytes + 2) // 3 * 4
MAX_THUMBNAIL_BASE64 = (128 * 1024 + 2) // 3 * 4

PhotoClear = Literal["alt_text", "taken_at", "location", "camera", "orientation"]
_EDITABLE = ("alt_text", "taken_at", "location", "camera", "orientation", "position")


class PhotoLocationInput(Output):
    """Where the photo was taken: degrees (WGS 84) and, when known, a place name."""

    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    name: Annotated[str, Field(min_length=1, max_length=MAX_PLACE_NAME), NoImageData] | None = None


class PhotoLocationRecord(Output):
    lat: float
    lon: float
    name: str | None


class PhotoChangesInput(PartialChanges):
    """update_journal_photo input: an omitted or null field stays; `clear` empties one."""

    fixed_fields = frozenset({"position"})

    alt_text: Annotated[str, Field(max_length=MAX_ALT_TEXT), NoImageData] | None = None
    taken_at: datetime | None = None
    location: PhotoLocationInput | None = None
    camera: Annotated[str, Field(max_length=MAX_CAMERA), NoImageData] | None = None
    orientation: Annotated[int, Field(ge=1, le=8)] | None = None
    position: Annotated[int, Field(ge=0, lt=MAX_PHOTOS_PER_TARGET)] | None = None


class PhotoAttachments(Output):
    """Photos on this record: how many, and their ids."""

    count: int = 0
    ids: list[UUID] = Field(default_factory=list[UUID])


class JournalPhotoRecord(Output):
    id: UUID
    # Exactly one is set: the entry the photo hangs on, or the day.
    entry_id: UUID | None
    journal_date: date | None
    media_type: MediaType
    byte_size: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(ge=1, le=4096)]
    height: Annotated[int, Field(ge=1, le=4096)]
    alt_text: Annotated[str, Field(max_length=MAX_ALT_TEXT)] | None
    alt_text_by: Literal["you", "claude"] | None
    # The time it was taken, in the owner's zone, and where, with what and how the file was turned,
    # as the client sent them. The owner can change or remove each of them.
    taken_at: datetime | None
    location: PhotoLocationRecord | None
    camera: Annotated[str, Field(max_length=MAX_CAMERA)] | None
    orientation: Annotated[int, Field(ge=1, le=8)] | None
    position: Annotated[int, Field(ge=0)]
    version: Annotated[int, Field(ge=1)]


class JournalPhotoResult(Output):
    photo: JournalPhotoRecord


class UpdatedJournalPhotoResult(JournalPhotoResult, WithIgnoredNulls):
    """update_journal_photo's reply: the photo and the nulls that were read as not sent."""


class JournalPhotoFileResult(Output):
    """One photo with the bytes of its thumbnail or of the photo itself, as base64."""

    photo: JournalPhotoRecord
    size: Literal["thumb", "photo"]
    data: Annotated[str, Field(max_length=MAX_PHOTO_BASE64)]


class JournalPhotoTrashResult(Output):
    """A photo that was moved to the trash or taken back; its version after the change."""

    id: UUID
    in_trash: bool
    version: Annotated[int, Field(ge=1)]


def attachments_record(summary: PhotoSummary | None) -> PhotoAttachments:
    if summary is None:
        return PhotoAttachments()
    return PhotoAttachments(count=summary.count, ids=list(summary.ids))


def photo_record(photo: JournalPhoto, zone: tzinfo) -> JournalPhotoRecord:
    where = photo.details.location
    taken = photo.details.taken_at
    return JournalPhotoRecord(
        id=photo.id,
        entry_id=photo.entry_id,
        journal_date=photo.journal_date,
        media_type=photo.media_type,
        byte_size=photo.byte_size,
        width=photo.width,
        height=photo.height,
        alt_text=photo.alt_text,
        alt_text_by=photo.alt_text_by,
        taken_at=taken.astimezone(zone) if taken else None,
        location=PhotoLocationRecord(lat=where.lat, lon=where.lon, name=where.name)
        if where
        else None,
        camera=photo.details.camera,
        orientation=photo.details.orientation,
        position=photo.position,
        version=photo.version,
    )


def _aware(value: datetime, zone: tzinfo) -> datetime:
    """A time without an offset is the owner's wall clock."""

    return value if value.tzinfo is not None else value.replace(tzinfo=zone)


def _location(value: PhotoLocationInput | None) -> PhotoLocation | None:
    return PhotoLocation(value.lat, value.lon, value.name) if value else None


def decode_photo_data(text: str) -> bytes:
    """The bytes of a base64 text, or a refusal that names no part of the text."""

    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise PhotoRefusedError(PhotoRefusal.MALFORMED) from None


def add_journal_photo_structured(
    container: Container,
    actor: Actor,
    *,
    entry_id: UUID | None,
    journal_date: date | None,
    photo: bytes,
    thumbnail: bytes,
    alt_text: str | None,
    taken_at: datetime | None,
    location: PhotoLocationInput | None,
    camera: str | None,
    orientation: int | None,
    idempotency_key: str,
    correlation_id: str | None,
) -> JournalPhotoResult:
    """Add one photo to an entry or a day; the structured content of `add_journal_photo`."""

    zone = container.settings.owner_zone
    stored = container.journal_photos.add_photo(
        actor,
        PhotoTarget(entry_id=entry_id, journal_date=journal_date),
        PhotoUpload(
            photo=photo,
            thumbnail=thumbnail,
            alt_text=alt_text,
            details=PhotoDetails(
                taken_at=_aware(taken_at, zone) if taken_at else None,
                location=_location(location),
                camera=camera,
                orientation=orientation,
            ),
        ),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return JournalPhotoResult(photo=photo_record(stored, zone))


def get_journal_photo_structured(
    container: Container, actor: Actor, photo_id: UUID, size: PhotoSize
) -> JournalPhotoFileResult:
    """One photo with its thumbnail or its full file: the content of `get_journal_photo`."""

    photo, data = container.journal_photos.read_file(actor, photo_id, size)
    return JournalPhotoFileResult(
        photo=photo_record(photo, container.settings.owner_zone),
        size=size,
        data=base64.b64encode(data).decode("ascii"),
    )


def update_journal_photo_structured(
    container: Container,
    actor: Actor,
    photo_id: UUID,
    changes: PhotoChangesInput,
    clear: list[PhotoClear] | None,
    *,
    expected_version: int,
    idempotency_key: str,
    correlation_id: str | None,
) -> UpdatedJournalPhotoResult:
    """Change a photo's fields; a cleared field is emptied, an omitted one stays."""

    changes.resolve(clear or ())
    sent = changes.model_fields_set
    zone = container.settings.owner_zone
    edits: dict[str, Any] = dict.fromkeys(_EDITABLE, UNSET)
    for name in sent:
        value = getattr(changes, name)
        if name == "taken_at" and value is not None:
            value = _aware(value, zone)
        elif name == "location":
            value = _location(value)
        edits[name] = value
    saved = container.journal_photos.update_photo(
        actor,
        photo_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        **edits,
    )
    return UpdatedJournalPhotoResult(
        photo=photo_record(saved, zone), ignored_nulls=changes.ignored_nulls
    )


def trash_journal_photo_structured(
    container: Container,
    actor: Actor,
    photo_id: UUID,
    *,
    version: int,
    idempotency_key: str,
    correlation_id: str | None,
) -> JournalPhotoTrashResult:
    """Move a photo to the trash; only the trash sweep erases it, so it can come back until then."""

    item = container.lifecycle.trash(
        actor,
        RecordKind.JOURNAL_ATTACHMENT,
        photo_id,
        version=version,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return JournalPhotoTrashResult(id=item.id, in_trash=True, version=item.version)


def restore_journal_photo_structured(
    container: Container,
    actor: Actor,
    photo_id: UUID,
    *,
    version: int,
    idempotency_key: str,
    correlation_id: str | None,
) -> JournalPhotoTrashResult:
    """Take a photo back from the trash."""

    item = container.lifecycle.restore(
        actor,
        RecordKind.JOURNAL_ATTACHMENT,
        photo_id,
        version=version,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return JournalPhotoTrashResult(id=item.id, in_trash=False, version=item.version)

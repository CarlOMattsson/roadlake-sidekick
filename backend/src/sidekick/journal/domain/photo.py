"""Journal photos beside their files: the fields kept with a photo and the rules for them.

A photo is a file (judged by `photo_format`, stored by `media_store`) and a row of fields. The
client reads capture time, place, camera and orientation from the file before it shrinks it and
sends them as fields; the stored file itself holds none of it. The owner may edit or remove every
field. None of them is ever sent to memory, and none is written to a log.

Nothing here knows a database, a file system or a framework.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Final, Literal
from uuid import UUID

from sidekick.journal.domain.photo_format import MediaType
from sidekick.shared.change_source import ChangeSource
from sidekick.shared.errors import FieldValidationError
from sidekick.shared.types import UNSET, UnsetType

#: Most photos on one entry or on one day.
MAX_PHOTOS_PER_TARGET: Final = 20
MAX_ALT_TEXT: Final = 500
MAX_CAMERA: Final = 80
MAX_PLACE_NAME: Final = 120
ORIENTATIONS: Final = range(1, 9)

PhotoSize = Literal["thumb", "photo"]

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_OWNER_KEY_LABEL = b"sidekick.journal-media.owner-key.v1"


class PhotoFieldError(FieldValidationError):
    """A photo field outside its bounds. The text names the field, never its value."""

    def __init__(self, field: str, rule: str) -> None:
        super().__init__([f"{field}: {rule}"])


def clean_text(value: str | None, field: str, maximum: int) -> str | None:
    """The text trimmed, or None when empty; control characters and a long text are refused."""

    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > maximum:
        raise PhotoFieldError(field, f"at most {maximum} characters")
    if _CONTROL.search(text):
        raise PhotoFieldError(field, "no control characters")
    return text


@dataclass(frozen=True, slots=True)
class PhotoLocation:
    """Where a photo was taken: degrees (WGS 84) and, when the owner knows it, a place name."""

    lat: float
    lon: float
    name: str | None = None

    def __post_init__(self) -> None:
        if not (math.isfinite(self.lat) and -90 <= self.lat <= 90):
            raise PhotoFieldError("location.lat", "between -90 and 90")
        if not (math.isfinite(self.lon) and -180 <= self.lon <= 180):
            raise PhotoFieldError("location.lon", "between -180 and 180")
        object.__setattr__(self, "name", clean_text(self.name, "location.name", MAX_PLACE_NAME))


@dataclass(frozen=True, slots=True)
class PhotoDetails:
    """The fields the client sends beside the image. Every one is optional."""

    taken_at: datetime | None = None
    location: PhotoLocation | None = None
    camera: str | None = None
    orientation: int | None = None

    def __post_init__(self) -> None:
        if self.taken_at is not None and self.taken_at.tzinfo is None:
            raise PhotoFieldError("taken_at", "needs a time zone")
        object.__setattr__(self, "camera", clean_text(self.camera, "camera", MAX_CAMERA))
        if self.orientation is not None and self.orientation not in ORIENTATIONS:
            raise PhotoFieldError("orientation", "between 1 and 8")


@dataclass(frozen=True, slots=True)
class PhotoTarget:
    """What a photo hangs on: one Journal entry, or one day. Never both and never neither."""

    entry_id: UUID | None = None
    journal_date: date | None = None

    def __post_init__(self) -> None:
        if (self.entry_id is None) == (self.journal_date is None):
            raise PhotoFieldError("target", "name exactly one of entry_id and journal_date")


@dataclass(frozen=True, slots=True)
class JournalPhoto:
    """One photo's row. The digests name its files and are never shown or logged."""

    id: UUID
    owner_id: UUID
    entry_id: UUID | None
    journal_date: date | None
    media_type: MediaType
    byte_size: int
    width: int
    height: int
    content_digest: str
    thumb_digest: str
    thumb_size: int
    alt_text: str | None
    alt_text_by: ChangeSource | None
    details: PhotoDetails
    position: int
    version: int
    created_at: datetime
    updated_at: datetime
    trashed_at: datetime | None = None


def edited_photo(
    photo: JournalPhoto,
    *,
    source: ChangeSource | None,
    alt_text: str | UnsetType | None = UNSET,
    taken_at: datetime | UnsetType | None = UNSET,
    location: PhotoLocation | UnsetType | None = UNSET,
    camera: str | UnsetType | None = UNSET,
    orientation: int | UnsetType | None = UNSET,
    position: int | UnsetType = UNSET,
) -> JournalPhoto:
    """The photo with the named fields changed; a field left out stays, `None` empties it.

    Alt text records who wrote it (`source`, the owner when no transport said). Nothing else about
    the photo changes: the files, their digests and the target are fixed for life.
    """

    changed = photo
    if not isinstance(alt_text, UnsetType):
        text = clean_text(alt_text, "alt_text", MAX_ALT_TEXT)
        changed = replace(
            changed, alt_text=text, alt_text_by=(source or "you") if text is not None else None
        )
    details = changed.details
    if not isinstance(taken_at, UnsetType):
        details = replace(details, taken_at=taken_at)
    if not isinstance(location, UnsetType):
        details = replace(details, location=location)
    if not isinstance(camera, UnsetType):
        details = replace(details, camera=camera)
    if not isinstance(orientation, UnsetType):
        details = replace(details, orientation=orientation)
    if details is not changed.details:
        # Built again, so the new values pass the same checks as the first ones.
        details = PhotoDetails(
            details.taken_at, details.location, details.camera, details.orientation
        )
        changed = replace(changed, details=details)
    if not isinstance(position, UnsetType):
        if position < 0:
            raise PhotoFieldError("position", "zero or more")
        changed = replace(changed, position=position)
    return changed


@dataclass(frozen=True, slots=True)
class PhotoSummary:
    """What a record says about the photos it carries: how many, and which."""

    count: int = 0
    ids: tuple[UUID, ...] = ()


def owner_media_key(secret: str, owner_id: UUID) -> str:
    """The directory name of one owner's photo files: an HMAC of the owner's id, never the id.

    The secret is the instance's own (`token_pepper`), mixed with a fixed label first so the same
    secret keeps no other use in common with this one. Nothing on the volume names the owner, and
    the name cannot be worked out without the secret.
    """

    derived = hmac.new(secret.encode(), _OWNER_KEY_LABEL, hashlib.sha256).digest()
    return hmac.new(derived, owner_id.bytes, hashlib.sha256).hexdigest()

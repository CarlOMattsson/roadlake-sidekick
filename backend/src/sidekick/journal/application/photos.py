"""Journal photos: add one, read it back, edit its fields, and say which a record carries.

A photo is a file and a row. The use case judges the bytes with the strict format gate (no image is
ever decoded here), stores the file and its thumbnail under the owner's key, and inserts the row in
one transaction with the replay record. A crash between the file and the row leaves a file no row
names, which the media sweep removes once it is old enough. Removal is the existing trash path: a
trashed photo is erased by the trash sweep (`sidekick.lifecycle`).

Nothing here sends anything to memory, and nothing logs a byte, a digest, a place or a caption: the
audit trail records the kind, the id and the outcome.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from sidekick.journal.domain.photo import (
    MAX_ALT_TEXT,
    MAX_PHOTOS_PER_TARGET,
    JournalPhoto,
    PhotoDetails,
    PhotoLocation,
    PhotoSize,
    PhotoSummary,
    PhotoTarget,
    clean_text,
    edited_photo,
)
from sidekick.journal.domain.photo_format import (
    PHOTO_LIMITS,
    THUMBNAIL_LIMITS,
    MediaType,
    PhotoRefusal,
    PhotoRefusedError,
    inspect_photo,
)
from sidekick.shared.change_source import current_change_source
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.types import (
    UNSET,
    Actor,
    AuditingStore,
    Clock,
    IdempotentStore,
    TransactionalStore,
    TxSession,
    UnsetType,
    new_uuid7,
)

PHOTO_RECORD_KIND = "journal_attachment"


class PhotoStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    """The persistence the photo use cases depend on."""

    def require_photo_target(
        self, session: TxSession, owner_id: UUID, target: PhotoTarget
    ) -> None: ...

    def count_photos(self, session: TxSession, owner_id: UUID, target: PhotoTarget) -> int: ...

    def next_photo_position(
        self, session: TxSession, owner_id: UUID, target: PhotoTarget
    ) -> int: ...

    def save_photo(self, session: TxSession, photo: JournalPhoto) -> None: ...

    def get_photo(self, session: TxSession, owner_id: UUID, photo_id: UUID) -> JournalPhoto: ...

    def update_photo(
        self,
        session: TxSession,
        owner_id: UUID,
        photo: JournalPhoto,
        *,
        expected_version: int,
        now: datetime,
    ) -> JournalPhoto: ...

    def list_photo_summaries(
        self, session: TxSession, owner_id: UUID, entry_ids: Sequence[UUID]
    ) -> dict[UUID, PhotoSummary]: ...

    def day_photo_summary(
        self, session: TxSession, owner_id: UUID, journal_date: date
    ) -> PhotoSummary: ...


@dataclass(frozen=True, slots=True)
class _StoredFiles:
    """What storing the two files of an upload produced: their type, size, dimensions, digests."""

    media_type: MediaType
    byte_size: int
    width: int
    height: int
    content_digest: str
    thumb_digest: str
    thumb_size: int


@dataclass(frozen=True, slots=True)
class PhotoUpload:
    """What the client sends for one photo: both files and the fields beside them."""

    photo: bytes
    thumbnail: bytes
    alt_text: str | None = None
    details: PhotoDetails = field(default_factory=PhotoDetails)


def _details_payload(details: PhotoDetails) -> dict[str, Any]:
    where = details.location
    return {
        "taken_at": details.taken_at.isoformat() if details.taken_at else None,
        "location": None if where is None else [where.lat, where.lon, where.name],
        "camera": details.camera,
        "orientation": details.orientation,
    }


class PhotoBytes(Protocol):
    """The bytes of an owner's photo files, by owner id; `OwnerPhotoFiles` is the adapter."""

    def put(self, owner_id: UUID, data: bytes) -> str: ...

    def read(self, owner_id: UUID, digest: str) -> bytes: ...


class JournalPhotoService:
    """The Journal's photo use cases. Every method checks the actor's scopes first."""

    def __init__(self, store: PhotoStore, files: PhotoBytes, clock: Clock) -> None:
        self.store = store
        self.files = files
        self.clock = clock

    def add_photo(
        self,
        actor: Actor,
        target: PhotoTarget,
        upload: PhotoUpload,
        *,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> JournalPhoto:
        """Store one photo on an entry or a day; a retry with the same key stores it once."""

        actor.require("journal:write")
        alt_text = clean_text(upload.alt_text, "alt_text", MAX_ALT_TEXT)
        info = inspect_photo(upload.photo, PHOTO_LIMITS)
        thumb = inspect_photo(upload.thumbnail, THUMBNAIL_LIMITS)
        if thumb.media_type != info.media_type:
            # Both files carry one type; the row names one, and a reader serves either as it.
            raise PhotoRefusedError(PhotoRefusal.UNSUPPORTED)
        # Before any byte is written: a target that is not the owner's leaves no file behind.
        self.store.transaction(
            lambda session: self.store.require_photo_target(session, actor.user_id, target)
        )
        stored = _StoredFiles(
            media_type=info.media_type,
            byte_size=info.byte_size,
            width=info.width,
            height=info.height,
            content_digest=self.files.put(actor.user_id, upload.photo),
            thumb_digest=self.files.put(actor.user_id, upload.thumbnail),
            thumb_size=thumb.byte_size,
        )
        payload: dict[str, Any] = {
            "entry_id": str(target.entry_id) if target.entry_id else None,
            "journal_date": target.journal_date.isoformat() if target.journal_date else None,
            "content": stored.content_digest,
            "thumb": stored.thumb_digest,
            "alt_text": alt_text,
            **_details_payload(upload.details),
        }

        def operation(session: TxSession) -> JournalPhoto:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="add_journal_photo",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._insert(
                    session, actor, target, upload.details, alt_text, stored, correlation_id
                ),
            )
            return self.store.get_photo(session, actor.user_id, UUID(result["photo_id"]))

        return self.store.transaction(operation)

    def _insert(
        self,
        session: TxSession,
        actor: Actor,
        target: PhotoTarget,
        details: PhotoDetails,
        alt_text: str | None,
        stored: _StoredFiles,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        self.store.require_photo_target(session, actor.user_id, target)
        if self.store.count_photos(session, actor.user_id, target) >= MAX_PHOTOS_PER_TARGET:
            raise ConflictError("this entry or day already has the most photos it can hold")
        now = self.clock.now()
        photo = JournalPhoto(
            id=new_uuid7(),
            owner_id=actor.user_id,
            entry_id=target.entry_id,
            journal_date=target.journal_date,
            media_type=stored.media_type,
            byte_size=stored.byte_size,
            width=stored.width,
            height=stored.height,
            content_digest=stored.content_digest,
            thumb_digest=stored.thumb_digest,
            thumb_size=stored.thumb_size,
            alt_text=alt_text,
            alt_text_by=(current_change_source() or "you") if alt_text else None,
            details=details,
            position=self.store.next_photo_position(session, actor.user_id, target),
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.store.save_photo(session, photo)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event=f"{PHOTO_RECORD_KIND}.added",
            outcome="success",
            target_type=PHOTO_RECORD_KIND,
            target_id=photo.id,
            correlation_id=correlation_id,
        )
        return {"photo_id": str(photo.id)}

    def get_photo(self, actor: Actor, photo_id: UUID) -> JournalPhoto:
        """One visible photo's row (not in the trash, nor on an entry that is)."""

        actor.require("journal:read")
        return self.store.transaction(
            lambda session: self.store.get_photo(session, actor.user_id, photo_id)
        )

    def read_file(
        self, actor: Actor, photo_id: UUID, size: PhotoSize
    ) -> tuple[JournalPhoto, bytes]:
        """The photo's row and the bytes of its thumbnail or of the photo itself."""

        photo = self.get_photo(actor, photo_id)
        digest = photo.thumb_digest if size == "thumb" else photo.content_digest
        return photo, self.files.read(actor.user_id, digest)

    def update_photo(
        self,
        actor: Actor,
        photo_id: UUID,
        *,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
        alt_text: str | UnsetType | None = UNSET,
        taken_at: datetime | UnsetType | None = UNSET,
        location: PhotoLocation | UnsetType | None = UNSET,
        camera: str | UnsetType | None = UNSET,
        orientation: int | UnsetType | None = UNSET,
        position: int | UnsetType = UNSET,
    ) -> JournalPhoto:
        """Change a photo's caption, place, time, camera, orientation or position.

        A field left out stays; `None` removes it. The place is the owner's to keep, change or
        remove, so it can be emptied like any other field.
        """

        actor.require("journal:read")
        actor.require("journal:write")
        changes = {
            "alt_text": alt_text,
            "taken_at": taken_at,
            "location": location,
            "camera": camera,
            "orientation": orientation,
            "position": position,
        }
        if all(isinstance(value, UnsetType) for value in changes.values()):
            raise ValidationError("name at least one field to change")
        payload: dict[str, Any] = {
            "photo_id": str(photo_id),
            "expected_version": expected_version,
            **{
                name: "unchanged" if isinstance(value, UnsetType) else _payload_value(value)
                for name, value in changes.items()
            },
        }

        def operation(session: TxSession) -> JournalPhoto:
            def execute() -> dict[str, Any]:
                current = self.store.get_photo(session, actor.user_id, photo_id)
                edited = edited_photo(
                    current,
                    source=current_change_source(),
                    alt_text=alt_text,
                    taken_at=taken_at,
                    location=location,
                    camera=camera,
                    orientation=orientation,
                    position=position,
                )
                saved = self.store.update_photo(
                    session,
                    actor.user_id,
                    edited,
                    expected_version=expected_version,
                    now=self.clock.now(),
                )
                self.store.append_audit(
                    session,
                    actor_id=actor.user_id,
                    event=f"{PHOTO_RECORD_KIND}.updated",
                    outcome="success",
                    target_type=PHOTO_RECORD_KIND,
                    target_id=saved.id,
                    correlation_id=correlation_id,
                )
                return {"photo_id": str(saved.id)}

            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="update_journal_photo",
                key=idempotency_key,
                payload=payload,
                execute=execute,
            )
            return self.store.get_photo(session, actor.user_id, UUID(result["photo_id"]))

        return self.store.transaction(operation)

    def summaries(self, actor: Actor, entry_ids: Sequence[UUID]) -> dict[UUID, PhotoSummary]:
        """The photos each entry carries; none without the read scope."""

        if "journal:read" not in actor.scopes or not entry_ids:
            return {}
        return self.store.transaction(
            lambda session: self.store.list_photo_summaries(session, actor.user_id, entry_ids)
        )

    def day_summary(self, actor: Actor, journal_date: date) -> PhotoSummary:
        """The photos that hang on the day itself, not on one of its entries."""

        if "journal:read" not in actor.scopes:
            return PhotoSummary()
        return self.store.transaction(
            lambda session: self.store.day_photo_summary(session, actor.user_id, journal_date)
        )


def _payload_value(value: object) -> object:
    if isinstance(value, PhotoLocation):
        return [value.lat, value.lon, value.name]
    if isinstance(value, datetime):
        return value.isoformat()
    return value

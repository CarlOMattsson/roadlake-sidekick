"""The owner-scoped rows of Journal photos. The files are not here; see `media_store`.

A photo is visible while neither it nor the entry it hangs on is in the trash. The operations are
static and owner-filtered; `SqlJournalStore` adds the transaction boundary.
"""

from collections.abc import Collection, Sequence
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from sidekick.journal.domain.photo import (
    JournalPhoto,
    PhotoDetails,
    PhotoLocation,
    PhotoSummary,
    PhotoTarget,
)
from sidekick.journal.domain.photo_format import MediaType
from sidekick.shared.change_source import ChangeSource
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.models import (
    JournalAttachmentRow,
    JournalEntryRow,
    JournalSourceRow,
)

_IN_ORDER = (
    JournalAttachmentRow.position,
    JournalAttachmentRow.created_at,
    JournalAttachmentRow.id,
)


def photo_from_row(row: JournalAttachmentRow) -> JournalPhoto:
    location = (
        PhotoLocation(row.location_lat, row.location_lon, row.location_name)
        if row.location_lat is not None and row.location_lon is not None
        else None
    )
    return JournalPhoto(
        id=row.id,
        owner_id=row.owner_id,
        entry_id=row.entry_id,
        journal_date=row.journal_date,
        media_type=cast("MediaType", row.media_type),  # the table's CHECK bounds it
        byte_size=row.byte_size,
        width=row.width,
        height=row.height,
        content_digest=row.content_digest,
        thumb_digest=row.thumb_digest,
        thumb_size=row.thumb_size,
        alt_text=row.alt_text,
        alt_text_by=cast("ChangeSource | None", row.alt_text_by),
        details=PhotoDetails(
            taken_at=row.taken_at,
            location=location,
            camera=row.camera,
            orientation=row.orientation,
        ),
        position=row.position,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        trashed_at=row.trashed_at,
    )


def _apply_details(row: JournalAttachmentRow, details: PhotoDetails) -> None:
    where = details.location
    row.taken_at = details.taken_at
    row.location_lat = where.lat if where else None
    row.location_lon = where.lon if where else None
    row.location_name = where.name if where else None
    row.camera = details.camera
    row.orientation = details.orientation


def _live_entry_ids(owner_id: UUID) -> Select[Any]:
    """The owner's entries that are not in the trash, and whose source is not either."""

    return (
        select(JournalEntryRow.id)
        .join(
            JournalSourceRow,
            (JournalSourceRow.id == JournalEntryRow.source_id)
            & (JournalSourceRow.owner_id == JournalEntryRow.owner_id),
        )
        .where(
            JournalEntryRow.owner_id == owner_id,
            JournalEntryRow.trashed_at.is_(None),
            JournalSourceRow.trashed_at.is_(None),
        )
    )


def _on_target[Query: Select[Any]](statement: Query, target: PhotoTarget) -> Query:
    if target.entry_id is not None:
        return statement.where(JournalAttachmentRow.entry_id == target.entry_id)
    return statement.where(JournalAttachmentRow.journal_date == target.journal_date)


class JournalPhotoStore:
    """Photo rows of one owner."""

    @staticmethod
    def require_photo_target(session: Session, owner_id: UUID, target: PhotoTarget) -> None:
        """Raise `NotFoundError` unless the target entry is the owner's own and not in the trash."""

        if target.entry_id is None:
            return
        found = session.scalar(
            _live_entry_ids(owner_id).where(JournalEntryRow.id == target.entry_id)
        )
        if found is None:
            raise NotFoundError("journal entry not found")

    @staticmethod
    def count_photos(session: Session, owner_id: UUID, target: PhotoTarget) -> int:
        """The photos on the target that are not in the trash."""

        statement = (
            select(func.count())
            .select_from(JournalAttachmentRow)
            .where(JournalAttachmentRow.owner_id == owner_id)
            .where(JournalAttachmentRow.trashed_at.is_(None))
        )
        return int(session.scalar(_on_target(statement, target)) or 0)

    @staticmethod
    def next_photo_position(session: Session, owner_id: UUID, target: PhotoTarget) -> int:
        statement = (
            select(func.max(JournalAttachmentRow.position))
            .select_from(JournalAttachmentRow)
            .where(JournalAttachmentRow.owner_id == owner_id)
        )
        highest = session.scalar(_on_target(statement, target))
        return 0 if highest is None else int(highest) + 1

    @staticmethod
    def save_photo(session: Session, photo: JournalPhoto) -> None:
        row = JournalAttachmentRow(
            id=photo.id,
            owner_id=photo.owner_id,
            entry_id=photo.entry_id,
            journal_date=photo.journal_date,
            media_type=photo.media_type,
            byte_size=photo.byte_size,
            width=photo.width,
            height=photo.height,
            content_digest=photo.content_digest,
            thumb_digest=photo.thumb_digest,
            thumb_size=photo.thumb_size,
            alt_text=photo.alt_text,
            alt_text_by=photo.alt_text_by,
            position=photo.position,
            version=photo.version,
            created_at=photo.created_at,
            updated_at=photo.updated_at,
        )
        _apply_details(row, photo.details)
        session.add(row)
        session.flush()

    @staticmethod
    def get_photo(session: Session, owner_id: UUID, photo_id: UUID) -> JournalPhoto:
        """One visible photo: itself not in the trash, and neither is the entry it hangs on."""

        row = session.scalar(
            select(JournalAttachmentRow).where(
                JournalAttachmentRow.id == photo_id,
                JournalAttachmentRow.owner_id == owner_id,
                JournalAttachmentRow.trashed_at.is_(None),
                or_(
                    JournalAttachmentRow.entry_id.is_(None),
                    JournalAttachmentRow.entry_id.in_(_live_entry_ids(owner_id)),
                ),
            )
        )
        if row is None:
            raise NotFoundError("photo not found")
        return photo_from_row(row)

    @staticmethod
    def update_photo(
        session: Session,
        owner_id: UUID,
        photo: JournalPhoto,
        *,
        expected_version: int,
        now: datetime,
    ) -> JournalPhoto:
        """Write the editable fields of `photo` over the stored row at `expected_version`."""

        row = session.scalar(
            select(JournalAttachmentRow)
            .where(
                JournalAttachmentRow.id == photo.id,
                JournalAttachmentRow.owner_id == owner_id,
                JournalAttachmentRow.trashed_at.is_(None),
            )
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("photo not found")
        if row.version != expected_version:
            raise ConflictError("stale photo version", reason="stale_version")
        row.alt_text = photo.alt_text
        row.alt_text_by = photo.alt_text_by
        row.position = photo.position
        _apply_details(row, photo.details)
        row.version = expected_version + 1
        row.updated_at = now
        session.flush()
        return photo_from_row(row)

    @staticmethod
    def list_photo_summaries(
        session: Session, owner_id: UUID, entry_ids: Sequence[UUID]
    ) -> dict[UUID, PhotoSummary]:
        """The photo count and ids of each entry that has any, in photo order."""

        if not entry_ids:
            return {}
        rows = session.execute(
            select(JournalAttachmentRow.entry_id, JournalAttachmentRow.id)
            .where(
                JournalAttachmentRow.owner_id == owner_id,
                JournalAttachmentRow.entry_id.in_(entry_ids),
                JournalAttachmentRow.trashed_at.is_(None),
            )
            .order_by(*_IN_ORDER)
        ).all()
        grouped: dict[UUID, list[UUID]] = {}
        for entry_id, photo_id in rows:
            if entry_id is not None:
                grouped.setdefault(entry_id, []).append(photo_id)
        return {
            entry_id: PhotoSummary(count=len(ids), ids=tuple(ids))
            for entry_id, ids in grouped.items()
        }

    @staticmethod
    def day_photo_summary(session: Session, owner_id: UUID, journal_date: date) -> PhotoSummary:
        ids = tuple(
            session.scalars(
                select(JournalAttachmentRow.id)
                .where(
                    JournalAttachmentRow.owner_id == owner_id,
                    JournalAttachmentRow.journal_date == journal_date,
                    JournalAttachmentRow.trashed_at.is_(None),
                )
                .order_by(*_IN_ORDER)
            )
        )
        return PhotoSummary(count=len(ids), ids=ids)

    @staticmethod
    def digests_in_use(session: Session, owner_id: UUID, digests: Collection[str]) -> set[str]:
        """Which of `digests` the owner's rows still name, as a photo file or as a thumbnail."""

        if not digests:
            return set()
        wanted = list(digests)
        full = session.scalars(
            select(JournalAttachmentRow.content_digest).where(
                JournalAttachmentRow.owner_id == owner_id,
                JournalAttachmentRow.content_digest.in_(wanted),
            )
        )
        thumbs = session.scalars(
            select(JournalAttachmentRow.thumb_digest).where(
                JournalAttachmentRow.owner_id == owner_id,
                JournalAttachmentRow.thumb_digest.in_(wanted),
            )
        )
        return {*full, *thumbs}

"""Journal photos end to end through the application service, the lifecycle and the file store.

Synthetic images only (`tests/support/photo_files.py`). The checks are what an owner relies on: a
photo is stored once, only its owner can reach it, the fields can be changed and removed, the
bytes and the fields stay out of the audit trail, the replay records, the logs and memory, and a
photo's files go when the photo is erased.
"""

import logging
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.composition import Container
from sidekick.journal.application.photos import PhotoUpload
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.photo import (
    MAX_PHOTOS_PER_TARGET,
    JournalPhoto,
    PhotoDetails,
    PhotoLocation,
    PhotoTarget,
)
from sidekick.journal.domain.photo_format import PhotoRefusal, PhotoRefusedError
from sidekick.journal.domain.source import SourceType
from sidekick.journal.infrastructure.media_store import MediaNotFoundError
from sidekick.lifecycle.application.empty_trash import empty_trash
from sidekick.lifecycle.domain import RecordKind
from sidekick.memory.domain import MemoryKind, canonical_document
from sidekick.memory.infrastructure.candidates import candidate_page
from sidekick.shared.errors import (
    ConflictError,
    IdempotencyKeyReusedError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from sidekick.shared.types import UNSET, Actor
from tests.db import database_factory
from tests.support import photo_files
from tests.support.settings import MEDIA_DIRECTORY, make_settings

WRITE = frozenset({"journal:read", "journal:write"})
READ = frozenset({"journal:read"})
DAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 9, tzinfo=UTC)
STOCKHOLM = timezone(timedelta(hours=1))
ALT = "Alt-text-hemlig-marker-71"
CAMERA = "Kamera-hemlig-marker-72"
PLACE = "Plats-hemlig-marker-73"
LAT, LON = 59.329312, 18.068611


def jpeg(width: int = 640, height: int = 480, **options: object) -> bytes:
    return photo_files.jpeg(width, height, **options)  # type: ignore[arg-type]


def thumb(width: int = 320, height: int = 240) -> bytes:
    return photo_files.jpeg(width, height)


class World:
    """Two owners on a clean database, one with an entry."""

    def __init__(self) -> None:
        self.factory: sessionmaker[Session] = database_factory()
        self.container: Container = create_container(make_settings(), self.factory)
        self.service = self.container.journal_photos
        self.owner = self.container.auth.provision_user("photo-owner", "Owner")
        self.other = self.container.auth.provision_user("photo-other", "Other")
        self.actor = Actor(self.owner, WRITE)
        self.reader = Actor(self.owner, READ)
        self.writer_only = Actor(self.owner, frozenset({"journal:write"}))
        self.other_actor = Actor(self.other, WRITE)
        self.entry = self.entry_of(self.actor, "photo-entry")

    def entry_of(self, actor: Actor, key: str) -> object:
        _, entry = self.container.journal_capture.write_entry(
            actor,
            source_type=SourceType.TRANSCRIPT_TEXT,
            journal_date=DAY,
            occurred_at=NOW,
            raw_text="Synthetic source text",
            language="sv",
            title="Synthetic entry",
            summary=None,
            key_points=(KeyPoint(KeyPointKind.FACT, "A synthetic fact."),),
            idempotency_key=key,
        )
        return entry

    def add(
        self,
        key: str,
        *,
        actor: Actor | None = None,
        target: PhotoTarget | None = None,
        photo: bytes | None = None,
        thumbnail: bytes | None = None,
        alt_text: str | None = None,
        details: PhotoDetails | None = None,
    ) -> JournalPhoto:
        return self.service.add_photo(
            actor or self.actor,
            target or PhotoTarget(entry_id=self.entry.id),  # type: ignore[attr-defined]
            PhotoUpload(
                photo=photo or jpeg(),
                thumbnail=thumbnail or thumb(),
                alt_text=alt_text,
                details=details or PhotoDetails(),
            ),
            idempotency_key=key,
        )

    def rows(self) -> int:
        with self.factory() as session:
            return int(
                session.scalar(text("SELECT count(*) FROM sidekick.journal_attachments")) or 0
            )

    def stored_text(self) -> str:
        """Everything the audit trail and the replay records hold, as one string."""

        with self.factory() as session:
            rows = session.execute(
                text(
                    "SELECT row_to_json(a)::text FROM sidekick.audit_events a "
                    "UNION ALL SELECT row_to_json(i)::text FROM sidekick.idempotency_operations i"
                )
            ).scalars()
            return "\n".join(rows)

    def files_of(self, owner_id: UUID) -> set[Path]:
        folder = MEDIA_DIRECTORY / self.service.files.key_of(owner_id)
        return {path for path in folder.rglob("*") if path.is_file()} if folder.exists() else set()


@pytest.fixture
def world() -> World:
    return World()


def full_details() -> PhotoDetails:
    return PhotoDetails(
        taken_at=datetime(2026, 7, 4, 15, 30, tzinfo=STOCKHOLM),
        location=PhotoLocation(LAT, LON, PLACE),
        camera=CAMERA,
        orientation=6,
    )


@pytest.mark.integration
def test_a_photo_is_stored_with_its_fields_and_read_back_as_the_same_bytes(world: World) -> None:
    photo = jpeg()
    small = thumb()
    added = world.add("add-1", photo=photo, thumbnail=small, alt_text=ALT, details=full_details())

    assert (added.media_type, added.width, added.height, added.version) == (
        "image/jpeg",
        640,
        480,
        1,
    )
    assert added.entry_id == world.entry.id  # type: ignore[attr-defined]
    assert added.journal_date is None
    assert (added.alt_text, added.alt_text_by) == (ALT, "you")
    assert added.details == full_details()
    shown, full = world.service.read_file(world.actor, added.id, "photo")
    _, little = world.service.read_file(world.actor, added.id, "thumb")
    assert (full, little) == (photo, small)
    assert shown.details.location == PhotoLocation(LAT, LON, PLACE)
    assert world.service.get_photo(world.reader, added.id).id == added.id


@pytest.mark.integration
def test_the_files_sit_under_a_directory_named_by_an_hmac_and_not_by_the_owner(
    world: World,
) -> None:
    added = world.add("add-dir")

    key = world.service.files.key_of(world.owner)
    assert len(key) == 64 and str(world.owner) not in key and world.owner.hex not in key
    names = {path.name for path in world.files_of(world.owner)}
    assert names == {added.content_digest, added.thumb_digest}
    assert world.files_of(world.other) == set()


@pytest.mark.integration
def test_a_photo_can_hang_on_a_day_and_the_day_and_entry_summaries_count_it(world: World) -> None:
    on_day = world.add("add-day", target=PhotoTarget(journal_date=DAY))
    on_entry = world.add("add-entry")

    day = world.service.day_summary(world.actor, DAY)
    assert (day.count, day.ids) == (1, (on_day.id,))
    entry_id = world.entry.id  # type: ignore[attr-defined]
    summaries = world.service.summaries(world.actor, [entry_id])
    assert (summaries[entry_id].count, summaries[entry_id].ids) == (1, (on_entry.id,))
    assert world.service.day_summary(world.writer_only, DAY).count == 0
    assert world.service.summaries(world.writer_only, [entry_id]) == {}
    assert world.service.day_summary(world.other_actor, DAY).count == 0


@pytest.mark.integration
def test_a_retry_with_the_same_key_stores_one_photo_and_a_changed_retry_is_refused(
    world: World,
) -> None:
    first = world.add("retry-1", alt_text=ALT)
    again = world.add("retry-1", alt_text=ALT)

    assert again.id == first.id
    assert world.rows() == 1
    with pytest.raises(IdempotencyKeyReusedError):
        world.add("retry-1", alt_text="Another caption")
    assert world.rows() == 1


@pytest.mark.integration
def test_the_format_gate_refuses_a_file_with_metadata_and_stores_nothing(world: World) -> None:
    with pytest.raises(PhotoRefusedError) as caught:
        world.add("gps", photo=photo_files.gps_jpeg())
    assert caught.value.refusal is PhotoRefusal.CARRIES_METADATA
    with pytest.raises(PhotoRefusedError):
        world.add("junk", photo=b"not an image at all")
    with pytest.raises(PhotoRefusedError):
        world.add(
            "gps-thumb",
            thumbnail=photo_files.jpeg(
                320,
                240,
                headers=(photo_files.JFIF, photo_files.segment(0xE1, photo_files.GPS_EXIF)),
            ),
        )
    with pytest.raises(PhotoRefusedError):
        world.add("types", thumbnail=photo_files.lossy_webp(320, 240))
    assert world.rows() == 0
    assert world.files_of(world.owner) == set()


@pytest.mark.integration
def test_an_oversized_photo_and_an_oversized_thumbnail_are_refused(world: World) -> None:
    with pytest.raises(PhotoRefusedError):
        world.add("wide", photo=jpeg(4000, 3000))
    with pytest.raises(PhotoRefusedError):
        world.add("big-thumb", thumbnail=jpeg(1000, 800))
    assert world.rows() == 0


@pytest.mark.integration
def test_a_target_that_is_not_the_owners_gives_not_found_and_a_scope_gap_gives_denied(
    world: World,
) -> None:
    with pytest.raises(NotFoundError):
        world.add("foreign", actor=world.other_actor)
    with pytest.raises(NotFoundError):
        world.add("missing", target=PhotoTarget(entry_id=uuid4()))
    with pytest.raises(PermissionDeniedError):
        world.add("reader", actor=world.reader)
    assert world.rows() == 0
    assert world.files_of(world.other) == set() and world.files_of(world.owner) == set()


@pytest.mark.integration
def test_the_most_photos_on_one_entry_is_enforced(world: World) -> None:
    for number in range(MAX_PHOTOS_PER_TARGET):
        world.add(f"many-{number}")
    with pytest.raises(ConflictError):
        world.add("many-over")
    assert world.rows() == MAX_PHOTOS_PER_TARGET


@pytest.mark.integration
def test_only_the_owner_with_the_read_scope_reaches_a_photo_or_its_bytes(world: World) -> None:
    added = world.add("owner-only")

    with pytest.raises(NotFoundError):
        world.service.get_photo(world.other_actor, added.id)
    with pytest.raises(NotFoundError):
        world.service.read_file(world.other_actor, added.id, "photo")
    with pytest.raises(PermissionDeniedError):
        world.service.get_photo(world.writer_only, added.id)
    with pytest.raises(PermissionDeniedError):
        world.service.read_file(world.writer_only, added.id, "thumb")
    with pytest.raises(NotFoundError):
        world.service.get_photo(world.actor, uuid4())


@pytest.mark.integration
def test_a_missing_or_changed_file_is_not_served(world: World) -> None:
    added = world.add("tamper")
    (path,) = [p for p in world.files_of(world.owner) if p.name == added.content_digest]
    path.chmod(0o600)
    path.write_bytes(jpeg(641, 480))

    with pytest.raises(MediaNotFoundError):
        world.service.read_file(world.actor, added.id, "photo")
    path.unlink()
    with pytest.raises(MediaNotFoundError):
        world.service.read_file(world.actor, added.id, "photo")


@pytest.mark.integration
def test_a_field_is_changed_and_the_place_is_moved_and_then_removed(world: World) -> None:
    added = world.add("edit-add", alt_text=ALT, details=full_details())

    moved = world.service.update_photo(
        world.actor,
        added.id,
        expected_version=1,
        idempotency_key="edit-1",
        location=PhotoLocation(10.5, 20.5, "Somewhere"),
        alt_text="A new caption",
    )
    assert moved.version == 2
    assert moved.details.location == PhotoLocation(10.5, 20.5, "Somewhere")
    assert moved.details.camera == CAMERA and moved.details.orientation == 6
    assert moved.alt_text == "A new caption"

    bare = world.service.update_photo(
        world.actor,
        added.id,
        expected_version=2,
        idempotency_key="edit-2",
        location=None,
        taken_at=None,
        camera=None,
        orientation=None,
        alt_text=None,
    )
    assert bare.version == 3
    assert bare.details == PhotoDetails()
    assert (bare.alt_text, bare.alt_text_by) == (None, None)
    # The place is gone from the row itself, not only from the answer.
    with world.factory() as session:
        row = session.execute(
            text(
                "SELECT location_lat, location_lon, location_name, camera, taken_at, orientation "
                "FROM sidekick.journal_attachments"
            )
        ).one()
    assert tuple(row) == (None,) * 6


@pytest.mark.integration
def test_an_edit_needs_the_current_version_a_field_and_both_journal_scopes(world: World) -> None:
    added = world.add("edit-guard")

    with pytest.raises(ConflictError):
        world.service.update_photo(
            world.actor, added.id, expected_version=7, idempotency_key="g-1", camera="Old"
        )
    with pytest.raises(ValidationError):
        world.service.update_photo(world.actor, added.id, expected_version=1, idempotency_key="g-2")
    with pytest.raises(PermissionDeniedError):
        world.service.update_photo(
            world.reader, added.id, expected_version=1, idempotency_key="g-3", camera="Old"
        )
    with pytest.raises(PermissionDeniedError):
        world.service.update_photo(
            world.writer_only, added.id, expected_version=1, idempotency_key="g-4", camera="Old"
        )
    with pytest.raises(NotFoundError):
        world.service.update_photo(
            world.other_actor, added.id, expected_version=1, idempotency_key="g-5", camera="Old"
        )
    with pytest.raises(ValidationError):
        world.service.update_photo(
            world.actor, added.id, expected_version=1, idempotency_key="g-6", orientation=11
        )
    unchanged = world.service.get_photo(world.actor, added.id)
    assert unchanged.version == 1 and unchanged.details == PhotoDetails()


@pytest.mark.integration
def test_an_edit_retried_with_its_key_is_applied_once(world: World) -> None:
    added = world.add("edit-retry")

    first = world.service.update_photo(
        world.actor, added.id, expected_version=1, idempotency_key="r-1", camera="Pixel"
    )
    again = world.service.update_photo(
        world.actor, added.id, expected_version=1, idempotency_key="r-1", camera="Pixel"
    )

    assert (first.version, again.version) == (2, 2)
    with pytest.raises(IdempotencyKeyReusedError):
        world.service.update_photo(
            world.actor, added.id, expected_version=1, idempotency_key="r-1", camera="Other"
        )


@pytest.mark.integration
def test_a_photo_in_the_trash_or_on_a_trashed_entry_is_not_shown(world: World) -> None:
    kept = world.add("trash-kept")
    gone = world.add("trash-gone")
    entry_id = world.entry.id  # type: ignore[attr-defined]

    world.container.lifecycle.trash(
        world.actor, RecordKind.JOURNAL_ATTACHMENT, gone.id, version=1, idempotency_key="t-1"
    )
    with pytest.raises(NotFoundError):
        world.service.get_photo(world.actor, gone.id)
    assert world.service.summaries(world.actor, [entry_id])[entry_id].ids == (kept.id,)

    world.container.lifecycle.trash(
        world.actor,
        RecordKind.JOURNAL_ENTRY,
        entry_id,
        version=world.entry.version,  # type: ignore[attr-defined]
        idempotency_key="t-2",
    )
    with pytest.raises(NotFoundError):
        world.service.get_photo(world.actor, kept.id)
    with pytest.raises(NotFoundError):
        world.service.read_file(world.actor, kept.id, "photo")
    with pytest.raises(NotFoundError):
        world.add("on-trashed")


@pytest.mark.integration
def test_erasing_a_photo_removes_its_files_unless_a_row_still_names_them(world: World) -> None:
    same = jpeg(700, 500)
    first = world.add("erase-1", photo=same)
    second = world.add("erase-2", photo=same)
    assert first.content_digest == second.content_digest
    assert len(world.files_of(world.owner)) == 2  # one photo file, one thumbnail

    for photo, number in ((first, 1), (second, 2)):
        world.container.lifecycle.trash(
            world.actor,
            RecordKind.JOURNAL_ATTACHMENT,
            photo.id,
            version=1,
            idempotency_key=f"erase-trash-{number}",
        )
    world.container.lifecycle.permanently_remove(
        world.actor,
        RecordKind.JOURNAL_ATTACHMENT,
        first.id,
        version=2,
        idempotency_key="erase-remove-1",
    )
    # The second photo still names both files, so nothing is removed yet.
    assert len(world.files_of(world.owner)) == 2

    world.container.lifecycle.permanently_remove(
        world.actor,
        RecordKind.JOURNAL_ATTACHMENT,
        second.id,
        version=2,
        idempotency_key="erase-remove-2",
    )
    assert world.files_of(world.owner) == set()
    assert world.rows() == 0


@pytest.mark.integration
def test_emptying_the_trash_erases_the_photos_of_a_trashed_entry_and_their_files(
    world: World,
) -> None:
    entry_id = world.entry.id  # type: ignore[attr-defined]
    world.add("sweep-1")
    world.add("sweep-2", photo=jpeg(650, 480))
    other_entry = world.entry_of(world.actor, "photo-entry-2")
    live = world.add("sweep-live", target=PhotoTarget(entry_id=other_entry.id))  # type: ignore[attr-defined]
    world.container.lifecycle.trash(
        world.actor,
        RecordKind.JOURNAL_ENTRY,
        entry_id,
        version=world.entry.version,  # type: ignore[attr-defined]
        idempotency_key="sweep-entry",
    )

    result = empty_trash(world.container.lifecycle, remove=True, correlation_id="sweep")

    assert result.removed.get(RecordKind.JOURNAL_ATTACHMENT) == 2
    assert world.rows() == 1
    assert {path.name for path in world.files_of(world.owner)} == {
        live.content_digest,
        live.thumb_digest,
    }


@pytest.mark.integration
def test_one_owners_erase_never_touches_the_files_of_another(world: World) -> None:
    mine = world.add("shared-mine", photo=jpeg(660, 480))
    other_entry = world.entry_of(world.other_actor, "photo-entry-other")
    theirs = world.add(
        "shared-theirs",
        actor=world.other_actor,
        target=PhotoTarget(entry_id=other_entry.id),  # type: ignore[attr-defined]
        photo=jpeg(660, 480),
    )
    assert mine.content_digest == theirs.content_digest

    world.container.lifecycle.trash(
        world.actor, RecordKind.JOURNAL_ATTACHMENT, mine.id, version=1, idempotency_key="o-1"
    )
    world.container.lifecycle.permanently_remove(
        world.actor, RecordKind.JOURNAL_ATTACHMENT, mine.id, version=2, idempotency_key="o-2"
    )

    assert world.files_of(world.owner) == set()
    assert len(world.files_of(world.other)) == 2
    assert world.service.read_file(world.other_actor, theirs.id, "photo")[1] == jpeg(660, 480)


@pytest.mark.integration
def test_no_field_reaches_the_audit_trail_the_replay_records_or_the_logs(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        added = world.add("redact-add", alt_text=ALT, details=full_details())
        world.service.update_photo(
            world.actor,
            added.id,
            expected_version=1,
            idempotency_key="redact-edit",
            camera=CAMERA + "-2",
            location=PhotoLocation(LAT, LON, PLACE + "-2"),
        )
        world.service.read_file(world.actor, added.id, "photo")
        with pytest.raises(PhotoRefusedError):
            world.add("redact-bad", alt_text=ALT, photo=photo_files.gps_jpeg())

    stored = world.stored_text()
    logged = "\n".join(record.getMessage() for record in caplog.records)
    logged += "\n".join(str(getattr(record, "__dict__", "")) for record in caplog.records)
    for secret in (ALT, CAMERA, PLACE, "59.3293", "18.0686", added.content_digest):
        assert secret not in stored, secret
        assert secret not in logged, secret
    assert "journal_attachment.added" in stored and "journal_attachment.updated" in stored


@pytest.mark.integration
def test_a_photo_and_its_fields_never_reach_the_memory_documents_of_its_entry(
    world: World,
) -> None:
    world.add("memory-1", alt_text=ALT, details=full_details())
    with world.factory() as session:
        pages = candidate_page(session, world.owner, MemoryKind.JOURNAL_ENTRY, owner_timezone=UTC)
    assert len(pages) == 1
    document = canonical_document(pages[0].record)
    rendered = repr(pages[0].record) + repr(document)
    for secret in (ALT, CAMERA, PLACE, "59.32", "image/jpeg", "attachment", "photo"):
        assert secret not in rendered, secret


@pytest.mark.integration
def test_update_with_the_unset_marker_changes_nothing_and_asks_for_a_field(world: World) -> None:
    added = world.add("unset")
    with pytest.raises(ValidationError):
        world.service.update_photo(
            world.actor,
            added.id,
            expected_version=1,
            idempotency_key="unset-1",
            alt_text=UNSET,
        )

"""A Journal photo goes through the trash like other records, and can be erased from it.

Unlike a Journal entry, a photo may be erased permanently, so the removal use case and the trash
sweep reach it; the entry it hangs on stays. A photo is not on the model-facing trash tools, it is
not in the change feed, it never reaches memory, and its alt text never reaches the audit trail,
the replay records or the logs.
"""

import logging
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.composition import Container
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.lifecycle.application.empty_trash import empty_trash
from sidekick.lifecycle.domain import RecordKind
from sidekick.shared.errors import ConflictError, NotFoundError, PermissionDeniedError
from sidekick.shared.persistence.models import JournalAttachmentRow, JournalEntryRow
from sidekick.shared.types import Actor, new_uuid7
from sidekick.structured.trash import TRASHABLE_KINDS, list_trash_structured
from tests.db import database_factory
from tests.support.settings import make_settings

READ = frozenset({"journal:read"})
WRITE = frozenset({"journal:read", "journal:write"})
ALT_TEXT = "Secret alt text about the owner's grandmother"
NOW = datetime(2026, 11, 22, 9, tzinfo=UTC)


class World:
    """One owner with an entry, and a second owner, on a clean database."""

    def __init__(self) -> None:
        self.factory: sessionmaker[Session] = database_factory()
        self.container: Container = create_container(make_settings(), self.factory)
        self.owner = self.container.auth.provision_user("photo-owner", "Owner")
        self.other = self.container.auth.provision_user("photo-other", "Other")
        self.actor = Actor(self.owner, WRITE)
        self.other_actor = Actor(self.other, WRITE)
        _, self.entry = self.container.journal_capture.write_entry(
            self.actor,
            source_type=SourceType.TRANSCRIPT_TEXT,
            journal_date=date(2026, 11, 22),
            occurred_at=NOW,
            raw_text="Synthetic source text",
            language="sv",
            title="Synthetic entry",
            summary=None,
            key_points=(KeyPoint(KeyPointKind.FACT, "A synthetic fact."),),
            idempotency_key="photo-entry",
        )

    def add_photo(self, *, alt_text: str | None = ALT_TEXT, day: bool = False) -> UUID:
        photo_id = new_uuid7()
        with self.factory.begin() as session:
            session.add(
                JournalAttachmentRow(
                    id=photo_id,
                    owner_id=self.owner,
                    entry_id=None if day else self.entry.id,
                    journal_date=date(2026, 11, 22) if day else None,
                    media_type="image/jpeg",
                    byte_size=1000,
                    width=800,
                    height=600,
                    content_digest="a" * 64,
                    thumb_digest="b" * 64,
                    thumb_size=900,
                    alt_text=alt_text,
                    alt_text_by="you" if alt_text else None,
                    position=0,
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        return photo_id

    def trash(self, photo_id: UUID, key: str, *, version: int = 1) -> None:
        self.container.lifecycle.trash(
            self.actor,
            RecordKind.JOURNAL_ATTACHMENT,
            photo_id,
            version=version,
            idempotency_key=key,
        )

    def photo_ids(self) -> set[UUID]:
        with self.factory() as session:
            return set(session.scalars(text("SELECT id FROM sidekick.journal_attachments")))

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


@pytest.fixture
def world() -> World:
    return World()


@pytest.mark.integration
def test_a_photo_is_listed_restored_and_trashed_again_with_its_alt_text_as_label(
    world: World,
) -> None:
    lifecycle = world.container.lifecycle
    photo_id = world.add_photo()
    world.trash(photo_id, "photo-trash-1")

    listed = lifecycle.list_trash(world.actor, kind=RecordKind.JOURNAL_ATTACHMENT).items
    assert [(item.kind, item.id, item.label, item.version) for item in listed] == [
        (RecordKind.JOURNAL_ATTACHMENT, photo_id, ALT_TEXT, 2)
    ]
    assert listed[0].trashed_at is not None

    restored = lifecycle.restore(
        world.actor,
        RecordKind.JOURNAL_ATTACHMENT,
        photo_id,
        version=2,
        idempotency_key="photo-restore-1",
    )
    assert restored.trashed_at is None
    assert lifecycle.list_trash(world.actor, kind=RecordKind.JOURNAL_ATTACHMENT).items == []
    world.trash(photo_id, "photo-trash-2", version=3)


@pytest.mark.integration
def test_a_photo_without_alt_text_has_a_plain_label(world: World) -> None:
    photo_id = world.add_photo(alt_text=None, day=True)
    world.trash(photo_id, "photo-trash-plain")

    (item,) = world.container.lifecycle.list_trash(
        world.actor, kind=RecordKind.JOURNAL_ATTACHMENT
    ).items

    assert item.label == "photo"


@pytest.mark.integration
def test_trashing_and_erasing_a_photo_needs_the_journal_scopes_and_the_owner(
    world: World,
) -> None:
    lifecycle = world.container.lifecycle
    photo_id = world.add_photo()
    reader = Actor(world.owner, READ)
    key = "photo-denied"

    with pytest.raises(PermissionDeniedError):
        lifecycle.trash(
            reader, RecordKind.JOURNAL_ATTACHMENT, photo_id, version=1, idempotency_key=key
        )
    with pytest.raises(PermissionDeniedError):
        lifecycle.list_trash(
            Actor(world.owner, frozenset({"tasks:read"})), kind=RecordKind.JOURNAL_ATTACHMENT
        )
    with pytest.raises(NotFoundError):
        lifecycle.trash(
            world.other_actor,
            RecordKind.JOURNAL_ATTACHMENT,
            photo_id,
            version=1,
            idempotency_key=key,
        )
    world.trash(photo_id, "photo-trash-owner")
    with pytest.raises(PermissionDeniedError):
        lifecycle.permanently_remove(
            reader, RecordKind.JOURNAL_ATTACHMENT, photo_id, version=2, idempotency_key=key
        )
    with pytest.raises(NotFoundError):
        lifecycle.permanently_remove(
            world.other_actor,
            RecordKind.JOURNAL_ATTACHMENT,
            photo_id,
            version=2,
            idempotency_key="photo-other-remove",
        )
    assert lifecycle.list_trash(world.other_actor, kind=RecordKind.JOURNAL_ATTACHMENT).items == []
    assert world.photo_ids() == {photo_id}


@pytest.mark.integration
def test_only_a_trashed_photo_at_its_current_version_can_be_erased(world: World) -> None:
    lifecycle = world.container.lifecycle
    photo_id = world.add_photo()

    with pytest.raises(Exception, match="only a trashed record"):
        lifecycle.permanently_remove(
            world.actor,
            RecordKind.JOURNAL_ATTACHMENT,
            photo_id,
            version=1,
            idempotency_key="photo-remove-live",
        )
    world.trash(photo_id, "photo-trash-stale")
    with pytest.raises(ConflictError):
        lifecycle.permanently_remove(
            world.actor,
            RecordKind.JOURNAL_ATTACHMENT,
            photo_id,
            version=1,
            idempotency_key="photo-remove-stale",
        )
    assert world.photo_ids() == {photo_id}

    lifecycle.permanently_remove(
        world.actor,
        RecordKind.JOURNAL_ATTACHMENT,
        photo_id,
        version=2,
        idempotency_key="photo-remove-ok",
        correlation_id="photo-remove-correlation",
    )

    assert world.photo_ids() == set()
    with world.factory() as session:
        assert session.get(JournalEntryRow, world.entry.id) is not None


@pytest.mark.integration
def test_the_sweep_erases_trashed_photos_and_keeps_the_entry_and_live_photos(
    world: World,
) -> None:
    lifecycle = world.container.lifecycle
    live = world.add_photo()
    trashed = world.add_photo(day=True)
    world.trash(trashed, "photo-sweep-trash")
    # The runtime holds no DELETE on entries, so a trashed entry is kept, and its live photo too.
    lifecycle.trash(
        world.actor,
        RecordKind.JOURNAL_ENTRY,
        world.entry.id,
        version=world.entry.version,
        idempotency_key="photo-sweep-entry",
    )

    dry = empty_trash(lifecycle, remove=False)
    assert dict(dry.matched) == {RecordKind.JOURNAL_ENTRY: 1, RecordKind.JOURNAL_ATTACHMENT: 1}
    assert world.photo_ids() == {live, trashed}

    result = empty_trash(lifecycle, remove=True, correlation_id="photo-sweep")

    assert dict(result.removed) == {RecordKind.JOURNAL_ATTACHMENT: 1}
    assert dict(result.kept) == {RecordKind.JOURNAL_ENTRY: 1}
    assert world.photo_ids() == {live}
    with world.factory() as session:
        assert session.get(JournalEntryRow, world.entry.id) is not None


@pytest.mark.integration
def test_a_photo_is_not_on_the_model_trash_surface_or_in_the_change_feed(world: World) -> None:
    photo_id = world.add_photo()
    world.trash(photo_id, "photo-surface-trash")

    assert RecordKind.JOURNAL_ATTACHMENT not in TRASHABLE_KINDS
    listed = list_trash_structured(world.container, world.actor)
    assert photo_id not in {item.id for item in listed.items}
    assert all(item.kind != "journal_attachment" for item in listed.items)
    narrowed = list_trash_structured(
        world.container, world.actor, within=frozenset({RecordKind.JOURNAL_ATTACHMENT})
    )
    assert narrowed.items == []
    changes = world.container.lifecycle.list_recent_changes(world.actor, limit=20)
    assert all(change.kind != "journal_attachment" for change in changes)
    assert photo_id not in {change.id for change in changes}


@pytest.mark.integration
def test_the_alt_text_reaches_neither_the_audit_trail_nor_the_replay_nor_the_logs(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    lifecycle = world.container.lifecycle
    photo_id = world.add_photo()
    with caplog.at_level(logging.DEBUG):
        world.trash(photo_id, "photo-redact-trash")
        lifecycle.restore(
            world.actor,
            RecordKind.JOURNAL_ATTACHMENT,
            photo_id,
            version=2,
            idempotency_key="photo-redact-restore",
        )
        world.trash(photo_id, "photo-redact-trash-again", version=3)
        lifecycle.permanently_remove(
            world.actor,
            RecordKind.JOURNAL_ATTACHMENT,
            photo_id,
            version=4,
            idempotency_key="photo-redact-remove",
            correlation_id="photo-redact-correlation",
        )

    stored = world.stored_text()
    assert "journal_attachment.permanently_removed" in stored
    assert ALT_TEXT not in stored
    assert "grandmother" not in stored
    assert ALT_TEXT not in caplog.text
    assert "grandmother" not in caplog.text

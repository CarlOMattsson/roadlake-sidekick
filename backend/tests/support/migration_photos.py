"""Rows and probes the photo migration tests share: an owner, an entry and one valid photo."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from tests.support.migration_baseline import _admin_url

OWNER = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
SOURCE = "00000000-0000-4000-8000-0000000000a1"
ENTRY = "00000000-0000-4000-8000-0000000000e1"
PHOTO = "00000000-0000-4000-8000-0000000000b1"
IDS: dict[str, object] = {
    "owner": OWNER,
    "other": OTHER,
    "source": SOURCE,
    "entry": ENTRY,
    "photo": PHOTO,
}
ROWS = (
    "INSERT INTO sidekick.users (id, username, display_name, created_at) "
    "VALUES (:owner, 'kept', 'Kept', now()), (:other, 'other', 'Other', now())",
    "INSERT INTO sidekick.journal_sources "
    "(id, owner_id, source_type, journal_date, raw_text, content_fingerprint, created_at) "
    "VALUES (:source, :owner, 'manual_text', current_date, 'Words', repeat('a', 64), now())",
    "INSERT INTO sidekick.journal_entries "
    "(id, owner_id, source_id, journal_date, title, key_points, version, created_at, updated_at) "
    "VALUES (:entry, :owner, :source, current_date, 'Day', '[]'::jsonb, 1, now(), now())",
)
# A valid photo row on the entry; the tests change one field at a time.
PHOTO_COLUMNS = (
    "id, owner_id, entry_id, journal_date, media_type, byte_size, width, height, content_digest, "
    "thumb_digest, thumb_size, alt_text, alt_text_by, taken_at, position, version, created_at, "
    "updated_at"
)
PHOTO_VALUES = {
    "id": ":photo",
    "owner_id": ":owner",
    "entry_id": ":entry",
    "journal_date": "NULL",
    "media_type": "'image/jpeg'",
    "byte_size": "1000",
    "width": "800",
    "height": "600",
    "content_digest": "repeat('a', 64)",
    "thumb_digest": "repeat('b', 64)",
    "thumb_size": "900",
    "alt_text": "NULL",
    "alt_text_by": "NULL",
    "taken_at": "NULL",
    "position": "0",
    "version": "1",
    "created_at": "now()",
    "updated_at": "now()",
}


def _insert_photo(**changes: str) -> str:
    values = {**PHOTO_VALUES, **changes}
    names = [name.strip() for name in PHOTO_COLUMNS.split(",")]
    # Only constants and the test's own SQL literals go in, never a value from outside.
    return (
        f"INSERT INTO sidekick.journal_attachments ({PHOTO_COLUMNS}) "  # noqa: S608
        f"VALUES ({', '.join(values[name] for name in names)})"
    )


def _scalar(sql: str) -> object:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return connection.scalar(text(sql))
    finally:
        engine.dispose()

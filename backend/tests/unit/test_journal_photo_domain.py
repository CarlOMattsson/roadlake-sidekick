"""The rules for a Journal photo's fields and its owner key, without a database or a framework."""

import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from sidekick.journal.domain.photo import (
    MAX_ALT_TEXT,
    MAX_CAMERA,
    MAX_PLACE_NAME,
    JournalPhoto,
    PhotoDetails,
    PhotoFieldError,
    PhotoLocation,
    PhotoTarget,
    clean_text,
    edited_photo,
    owner_media_key,
)
from sidekick.shared.errors import FieldValidationError

NOW = datetime(2026, 11, 22, 9, tzinfo=UTC)
OWNER = UUID("0192f0e0-1234-7abc-8def-0123456789ab")
OTHER = UUID("0192f0e0-1234-7abc-8def-0123456789ac")


def photo(**fields: object) -> JournalPhoto:
    base = JournalPhoto(
        id=OTHER,
        owner_id=OWNER,
        entry_id=OTHER,
        journal_date=None,
        media_type="image/jpeg",
        byte_size=1000,
        width=800,
        height=600,
        content_digest="a" * 64,
        thumb_digest="b" * 64,
        thumb_size=900,
        alt_text=None,
        alt_text_by=None,
        details=PhotoDetails(),
        position=0,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    return replace(base, **fields)  # type: ignore[arg-type]


def test_a_field_error_is_a_validation_error_that_names_the_field_and_not_the_value() -> None:
    with pytest.raises(FieldValidationError) as caught:
        PhotoLocation(95.0, 18.0)
    assert "location.lat" in str(caught.value) and "95" not in str(caught.value)


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (-90.1, 0),
        (90.1, 0),
        (0, -180.1),
        (0, 180.1),
        (float("nan"), 0),
        (0, float("inf")),
    ],
)
def test_a_place_outside_the_globe_is_refused(lat: float, lon: float) -> None:
    with pytest.raises(PhotoFieldError):
        PhotoLocation(lat, lon)


def test_the_edges_of_the_globe_and_a_trimmed_place_name_are_accepted() -> None:
    place = PhotoLocation(-90, 180, "  Södermalm  ")
    assert (place.lat, place.lon, place.name) == (-90, 180, "Södermalm")
    assert PhotoLocation(0, 0, "   ").name is None


def test_text_fields_are_trimmed_bounded_and_free_of_control_characters() -> None:
    assert clean_text("  ", "alt_text", MAX_ALT_TEXT) is None
    assert clean_text(None, "alt_text", MAX_ALT_TEXT) is None
    assert clean_text(" hej ", "alt_text", MAX_ALT_TEXT) == "hej"
    with pytest.raises(PhotoFieldError):
        clean_text("x" * (MAX_ALT_TEXT + 1), "alt_text", MAX_ALT_TEXT)
    with pytest.raises(PhotoFieldError):
        clean_text("a\x00b", "alt_text", MAX_ALT_TEXT)
    with pytest.raises(PhotoFieldError):
        PhotoDetails(camera="c" * (MAX_CAMERA + 1))
    with pytest.raises(PhotoFieldError):
        PhotoLocation(0, 0, "p" * (MAX_PLACE_NAME + 1))


def test_a_capture_time_needs_a_zone_and_an_orientation_is_one_to_eight() -> None:
    with pytest.raises(PhotoFieldError):
        PhotoDetails(taken_at=datetime(2026, 7, 1, 12))
    PhotoDetails(taken_at=datetime(2026, 7, 1, 12, tzinfo=timezone(timedelta(hours=2))))
    for bad in (0, 9, -1):
        with pytest.raises(PhotoFieldError):
            PhotoDetails(orientation=bad)
    assert PhotoDetails(orientation=8).orientation == 8


def test_a_photo_hangs_on_exactly_one_of_an_entry_and_a_day() -> None:
    assert PhotoTarget(entry_id=OWNER).journal_date is None
    assert PhotoTarget(journal_date=date(2026, 11, 22)).entry_id is None
    with pytest.raises(PhotoFieldError):
        PhotoTarget()
    with pytest.raises(PhotoFieldError):
        PhotoTarget(entry_id=OWNER, journal_date=date(2026, 11, 22))


def test_an_edit_changes_only_the_named_fields_and_keeps_the_files() -> None:
    start = photo(
        alt_text="Old",
        alt_text_by="claude",
        details=PhotoDetails(
            taken_at=NOW, location=PhotoLocation(59.3, 18.0, "Home"), camera="Pixel", orientation=6
        ),
    )

    renamed = edited_photo(start, source=None, alt_text="New")
    assert (renamed.alt_text, renamed.alt_text_by) == ("New", "you")
    assert renamed.details == start.details
    assert (renamed.content_digest, renamed.thumb_digest) == ("a" * 64, "b" * 64)

    by_claude = edited_photo(start, source="claude", alt_text="Claude's words")
    assert by_claude.alt_text_by == "claude"


def test_an_edit_can_change_and_remove_the_place_and_every_other_field() -> None:
    start = photo(
        details=PhotoDetails(
            taken_at=NOW, location=PhotoLocation(59.3, 18.0, "Home"), camera="Pixel", orientation=6
        )
    )

    moved = edited_photo(start, source=None, location=PhotoLocation(1.0, 2.0))
    assert moved.details.location == PhotoLocation(1.0, 2.0)
    assert moved.details.camera == "Pixel"

    bare = edited_photo(
        start, source=None, taken_at=None, location=None, camera=None, orientation=None
    )
    assert bare.details == PhotoDetails()

    emptied = edited_photo(
        replace(start, alt_text="Words", alt_text_by="you"), source=None, alt_text=None
    )
    assert (emptied.alt_text, emptied.alt_text_by) == (None, None)


def test_an_edit_is_held_to_the_same_bounds_as_a_new_photo() -> None:
    start = photo()
    with pytest.raises(PhotoFieldError):
        edited_photo(start, source=None, orientation=12)
    with pytest.raises(PhotoFieldError):
        edited_photo(start, source=None, camera="c" * (MAX_CAMERA + 1))
    with pytest.raises(PhotoFieldError):
        edited_photo(start, source=None, position=-1)
    assert edited_photo(start, source=None, position=3).position == 3


def test_the_owner_key_is_a_hex_digest_of_the_secret_and_the_id_and_never_the_id() -> None:
    key = owner_media_key("a-secret-of-the-instance", OWNER)
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert OWNER.hex not in key and str(OWNER) not in key
    assert key == owner_media_key("a-secret-of-the-instance", OWNER)
    assert key != owner_media_key("a-secret-of-the-instance", OTHER)
    assert key != owner_media_key("another-secret", OWNER)

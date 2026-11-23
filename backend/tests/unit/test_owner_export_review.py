"""Repetition in the owner export (from format 11): the three collections, the ids a restore
rewrites, the answer keys it leaves as written, and the refusal of a card that names the wrong
source."""

from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID

import pytest

from sidekick.owner_export.catalogue import (
    COLLECTIONS_ADDED_IN_FORMAT_11,
    EXPORT_FORMAT_VERSION,
    EXPORT_SOURCES,
    SOURCES_BY_NAME,
    ExportRefused,
    source_fields,
)
from sidekick.owner_export.cli import build_parser
from sidekick.owner_export.document import (
    build_export_document,
    export_checksum,
    json_safe,
    verify_export,
)
from sidekick.owner_export.restore_plan import build_restore_plan, verify_restorable
from sidekick.owner_export.restore_remap import (
    remapped_restore_rows,
    restore_id,
    restore_source_order,
)
from tests.support.older_export_formats import as_format_9, as_format_10

OWNER_ID = UUID("00000000-0000-7000-8000-000000000001")
TARGET_ID = UUID("00000000-0000-7000-8000-0000000000aa")
CONTACT_ID = UUID("00000000-0000-7000-8000-000000000021")
FACT_ID = UUID("00000000-0000-7000-8000-000000000022")
CARD_ID = UUID("00000000-0000-7000-8000-000000000023")
FACT_CARD_ID = UUID("00000000-0000-7000-8000-000000000024")
LOG_ID = UUID("00000000-0000-7000-8000-000000000025")
STAMP = "2026-11-23T09:00:00+00:00"
# An answer key that looks like an id: a restore must keep it exactly as written.
CLIENT_KEY = "00000000-0000-4000-8000-0000000000f1"


def _empty() -> dict[str, list[dict[str, object]]]:
    return {source.name: [] for source in EXPORT_SOURCES}


def _contact() -> dict[str, object]:
    row = {field: None for field in _fields("contacts")}
    return {
        **row,
        "id": str(CONTACT_ID),
        "owner_id": str(OWNER_ID),
        "display_name": "Anna Svensson",
        "display_name_key": "anna svensson",
        "archived": False,
        "version": 1,
        "created_at": STAMP,
        "updated_at": STAMP,
    }


def _fields(name: str) -> tuple[str, ...]:
    return source_fields(SOURCES_BY_NAME[name])


def _settings() -> dict[str, object]:
    return {
        "owner_id": str(OWNER_ID),
        "enabled": True,
        "include_contacts": True,
        "include_library": False,
        "new_per_day": 5,
        "max_reviews_per_day": 100,
        "push_enabled": True,
        "push_local_time": "07:30:00",
        "desired_retention": "0.85",
        "version": 2,
        "created_at": STAMP,
        "updated_at": STAMP,
    }


def _card(card_id: UUID = CARD_ID, **overrides: object) -> dict[str, object]:
    return {
        "id": str(card_id),
        "owner_id": str(OWNER_ID),
        "source_kind": "contact_face",
        "contact_id": str(CONTACT_ID),
        "library_fact_id": None,
        "fsrs_state": "learning",
        "step": 0,
        "stability": 2.5,
        "difficulty": 5.1,
        "due_at": STAMP,
        "last_review_at": STAMP,
        "reps": 1,
        "lapses": 0,
        "introduced_on": "2026-11-23",
        "suspended_at": None,
        "retired_at": None,
        "scheduler_version": "fsrs-6.3.3/r0.85/s10m/v1",
        "version": 2,
        "created_at": STAMP,
        "updated_at": STAMP,
        **overrides,
    }


def _log() -> dict[str, object]:
    return {
        "id": str(LOG_ID),
        "owner_id": str(OWNER_ID),
        "card_id": str(CARD_ID),
        "rating": 3,
        "reviewed_at": STAMP,
        "received_at": STAMP,
        "client_review_id": CLIENT_KEY,
        "channel": "companion",
        "duration_ms": 1500,
        "clock_adjusted": False,
    }


def _reseal(document: dict[str, Any]) -> dict[str, Any]:
    document["manifest"] = {"collection_counts": document["manifest"]["collection_counts"]}
    document["manifest"]["sha256"] = export_checksum(document)
    return document


def _document(**cards: object) -> dict[str, Any]:
    collections = _empty()
    collections["contacts"] = [_contact()]
    collections["review_settings"] = [_settings()]
    collections["review_cards"] = [_card(**cards)]
    collections["review_log"] = [_log()]
    return build_export_document(
        OWNER_ID, collections, exported_at=datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    )


def test_the_export_carries_the_three_repetition_collections_that_format_11_added() -> None:
    assert EXPORT_FORMAT_VERSION == 12
    assert {"review_settings", "review_cards", "review_log"} == COLLECTIONS_ADDED_IN_FORMAT_11
    assert set(SOURCES_BY_NAME) >= COLLECTIONS_ADDED_IN_FORMAT_11

    document = _document()

    assert document["format_version"] == 12
    assert verify_export(document).collection_counts["review_cards"] == 1
    verify_restorable(document)


def test_the_cards_come_after_their_contact_and_the_answers_after_their_card() -> None:
    order = [source.name for source in restore_source_order(_document()["collections"])]

    assert order.index("contacts") < order.index("review_cards") < order.index("review_log")


def test_a_restore_rewrites_the_card_and_answer_ids_and_leaves_the_answer_key_as_written() -> None:
    rows = remapped_restore_rows(_document(), TARGET_ID)

    card, log = rows["review_cards"][0], rows["review_log"][0]
    assert card["id"] == restore_id(CARD_ID, TARGET_ID, "review_cards")
    assert card["contact_id"] == restore_id(CONTACT_ID, TARGET_ID, "contacts")
    assert card["owner_id"] == TARGET_ID
    assert log["card_id"] == card["id"]
    assert log["id"] == restore_id(LOG_ID, TARGET_ID, "review_log")
    assert log["client_review_id"] == CLIENT_KEY
    assert isinstance(log["client_review_id"], str)
    assert rows["review_settings"][0]["owner_id"] == TARGET_ID
    assert rows["review_settings"][0]["push_local_time"] == time(7, 30)


def test_a_card_keeps_its_schedule_through_a_restore() -> None:
    document = _document()

    card = remapped_restore_rows(document, TARGET_ID)["review_cards"][0]

    original = document["collections"]["review_cards"][0]
    for field in ("fsrs_state", "step", "stability", "difficulty", "reps", "lapses"):
        assert card[field] == original[field]
    assert card["due_at"] == datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
    assert card["scheduler_version"] == original["scheduler_version"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"contact_id": None},
        {"library_fact_id": str(FACT_ID)},
        {"source_kind": "library_fact"},
        {"source_kind": "contact_photo"},
    ],
)
def test_a_card_that_names_the_wrong_source_is_refused_by_position_only(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ExportRefused, match=r"review_cards\[0\]") as refused:
        build_restore_plan(_document(**overrides), TARGET_ID)

    assert "Anna" not in str(refused.value)


def test_a_library_fact_card_names_its_fact_and_not_a_contact() -> None:
    collections = _empty()
    collections["review_cards"] = [
        _card(
            FACT_CARD_ID,
            source_kind="library_fact",
            contact_id=None,
            library_fact_id=str(FACT_ID),
        )
    ]
    document = build_export_document(
        OWNER_ID, collections, exported_at=datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    )

    assert build_restore_plan(document, TARGET_ID).status == "ready"


def test_the_plan_counts_the_references_it_rewrites_and_holds_no_card_text() -> None:
    plan = build_restore_plan(_document(), TARGET_ID)

    assert plan.status == "ready"
    names = {collection.name for collection in plan.collections}
    assert names >= COLLECTIONS_ADDED_IN_FORMAT_11
    assert "Anna" not in str(plan.as_dict())


def test_the_formats_before_have_no_repetition_collections_and_restore_without_them() -> None:
    """Format 10 is the photo format and format 9 the one before photos; both are still read."""

    for older, version in ((as_format_10(_document()), 10), (as_format_9(_document()), 9)):
        assert older["format_version"] == version
        assert not COLLECTIONS_ADDED_IN_FORMAT_11 & set(older["collections"])
        verify_export(older)
        assert build_restore_plan(older, TARGET_ID).status == "ready"
        rows = remapped_restore_rows(older, TARGET_ID)
        assert all(rows[name] == [] for name in COLLECTIONS_ADDED_IN_FORMAT_11)
    assert EXPORT_FORMAT_VERSION == 12


@pytest.mark.parametrize("name", sorted(COLLECTIONS_ADDED_IN_FORMAT_11))
def test_a_current_export_must_carry_every_repetition_collection(name: str) -> None:
    document = _document()
    del document["collections"][name]
    del document["manifest"]["collection_counts"][name]

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(_reseal(document))


@pytest.mark.parametrize("name", sorted(COLLECTIONS_ADDED_IN_FORMAT_11))
def test_an_older_export_cannot_carry_a_repetition_collection(name: str) -> None:
    older = as_format_9(_document())
    older["collections"][name] = []
    older["manifest"]["collection_counts"][name] = 0

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(_reseal(older))


def test_a_row_of_another_owner_in_a_repetition_collection_is_refused() -> None:
    document = _document()
    document["collections"]["review_log"][0]["owner_id"] = str(TARGET_ID)

    with pytest.raises(ExportRefused, match="crosses the owner boundary"):
        verify_export(_reseal(document))


def test_a_time_of_day_is_written_as_text() -> None:
    assert json_safe(time(7, 30)) == "07:30:00"


def test_the_restore_command_takes_a_refold_flag_that_is_off_by_default() -> None:
    base = [
        "restore",
        "export.json",
        "--apply",
        "--target-owner-id",
        str(TARGET_ID),
        "--plan-checksum",
        "abc",
    ]
    parser = build_parser()

    assert parser.parse_args(base).refold is False
    assert parser.parse_args([*base, "--refold"]).refold is True

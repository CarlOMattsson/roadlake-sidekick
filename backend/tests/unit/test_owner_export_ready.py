"""Ready conversations in the owner export (from format 12): the collection, the ids a restore
rewrites, the refusal of a cadence nobody can read, and the older formats that have none. The day
marks are transient and are not part of the export."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from sidekick.owner_export.catalogue import (
    COLLECTIONS_ADDED_IN_FORMAT_12,
    EXPORT_FORMAT_VERSION,
    EXPORT_SOURCES,
    SOURCES_BY_NAME,
    ExportRefused,
)
from sidekick.owner_export.document import build_export_document, export_checksum, verify_export
from sidekick.owner_export.restore_plan import build_restore_plan, verify_restorable
from sidekick.owner_export.restore_remap import remapped_restore_rows
from tests.support.older_export_formats import as_format_9, as_format_10, as_format_11
from tests.support.ready_rows import DAILY_AT_18

OWNER_ID = UUID("00000000-0000-7000-8000-000000000001")
TARGET_ID = UUID("00000000-0000-7000-8000-0000000000aa")
CONVERSATION_ID = UUID("00000000-0000-7000-8000-000000000031")
STAMP = "2026-11-23T09:00:00+00:00"
TITLE = "Evening review of the day"


def _conversation(**overrides: object) -> dict[str, object]:
    return {
        "id": str(CONVERSATION_ID),
        "owner_id": str(OWNER_ID),
        "title": TITLE,
        "kind": "evening_review",
        "instruction": "One question at a time.",
        "instruction_written_by": "you",
        "instruction_edited_by_model": False,
        "ingredients": ["overdue", "waiting"],
        "cadence": DAILY_AT_18,
        "state": "active",
        "version": 3,
        "created_at": STAMP,
        "updated_at": STAMP,
        **overrides,
    }


def _reseal(document: dict[str, Any]) -> dict[str, Any]:
    document["manifest"] = {"collection_counts": document["manifest"]["collection_counts"]}
    document["manifest"]["sha256"] = export_checksum(document)
    return document


def _document(**changes: object) -> dict[str, Any]:
    collections: dict[str, list[dict[str, object]]] = {s.name: [] for s in EXPORT_SOURCES}
    collections["ready_conversations"] = [_conversation(**changes)]
    return build_export_document(
        OWNER_ID, collections, exported_at=datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    )


def test_the_export_carries_the_conversations_of_format_12_and_not_their_day_marks() -> None:
    assert EXPORT_FORMAT_VERSION == 12
    assert {"ready_conversations"} == COLLECTIONS_ADDED_IN_FORMAT_12
    assert "ready_conversation_days" not in SOURCES_BY_NAME

    document = _document()

    assert document["format_version"] == 12
    assert verify_export(document).collection_counts["ready_conversations"] == 1
    verify_restorable(document)


def test_a_restore_rewrites_the_conversation_id_and_the_owner_and_keeps_the_rest() -> None:
    rows = remapped_restore_rows(_document(), TARGET_ID)["ready_conversations"]

    [row] = rows
    assert row["id"] != CONVERSATION_ID
    assert row["owner_id"] == TARGET_ID
    assert (row["title"], row["ingredients"], row["version"]) == (TITLE, ["overdue", "waiting"], 3)
    assert row["cadence"] == DAILY_AT_18


def test_the_plan_counts_the_conversation_and_holds_none_of_its_text() -> None:
    plan = build_restore_plan(_document(), TARGET_ID)

    assert plan.status == "ready"
    assert {c.name: c.row_count for c in plan.collections}["ready_conversations"] == 1
    assert TITLE not in str(plan.as_dict())
    assert "One question" not in str(plan.as_dict())


@pytest.mark.parametrize(
    "cadence",
    [
        {"frequency": "daily"},
        {**DAILY_AT_18, "local_time": "25:99"},
        {**DAILY_AT_18, "frequency": "hourly"},
        {**DAILY_AT_18, "unknown": 1},
        {},
    ],
)
def test_a_cadence_nobody_can_read_is_refused_by_position_and_never_by_content(
    cadence: dict[str, object],
) -> None:
    document = _reseal(_document(cadence=cadence, title="SECRET-TITLE"))

    with pytest.raises(ExportRefused, match=r"ready_conversations\[0\]") as refused:
        build_restore_plan(document, TARGET_ID)

    assert "SECRET-TITLE" not in str(refused.value)


def test_the_formats_before_have_no_conversations_and_restore_without_them() -> None:
    for older, version in (
        (as_format_11(_document()), 11),
        (as_format_10(_document()), 10),
        (as_format_9(_document()), 9),
    ):
        assert older["format_version"] == version
        assert not COLLECTIONS_ADDED_IN_FORMAT_12 & set(older["collections"])
        verify_export(older)
        assert build_restore_plan(older, TARGET_ID).status == "ready"
        assert remapped_restore_rows(older, TARGET_ID)["ready_conversations"] == []


def test_a_current_export_must_carry_the_collection() -> None:
    document = _document()
    del document["collections"]["ready_conversations"]
    del document["manifest"]["collection_counts"]["ready_conversations"]

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(_reseal(document))


def test_an_older_export_cannot_carry_the_collection() -> None:
    older = as_format_11(_document())
    older["collections"]["ready_conversations"] = []
    older["manifest"]["collection_counts"]["ready_conversations"] = 0

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(_reseal(older))


def test_a_conversation_of_another_owner_is_refused() -> None:
    document = _document(owner_id=str(TARGET_ID))

    with pytest.raises(ExportRefused, match="crosses the owner boundary"):
        verify_export(_reseal(document))


@pytest.mark.parametrize(
    "fields",
    [
        {"instruction_written_by": None},
        {"instruction_written_by": "robot"},
        {"instruction_edited_by_model": None},
        {"instruction": None, "instruction_written_by": "you"},
        {"instruction": None, "instruction_written_by": None, "instruction_edited_by_model": True},
    ],
)
def test_an_instruction_that_does_not_say_who_wrote_it_is_refused_by_position_only(
    fields: dict[str, object],
) -> None:
    document = _reseal(_document(title="SECRET-TITLE", **fields))

    with pytest.raises(ExportRefused, match=r"ready_conversations\[0\]") as refused:
        build_restore_plan(document, TARGET_ID)

    assert "SECRET-TITLE" not in str(refused.value)


def test_a_restore_keeps_who_wrote_the_instruction() -> None:
    document = _document(instruction_written_by="claude", instruction_edited_by_model=True)

    [row] = remapped_restore_rows(document, TARGET_ID)["ready_conversations"]

    assert (row["instruction_written_by"], row["instruction_edited_by_model"]) == ("claude", True)

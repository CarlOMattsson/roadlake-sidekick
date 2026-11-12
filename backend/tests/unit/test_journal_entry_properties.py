"""Property 6: entry lifecycle preserves provenance and deterministic order."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sidekick.journal.domain.entry import (
    JournalEntry,
    KeyPoint,
    KeyPointKind,
    archive_entry,
    entry_order_key,
    restore_entry,
    update_entry,
)

OWNER_ID = UUID("018af000-0000-7000-8000-000000000001")
BASE = datetime(2026, 7, 21, 8, tzinfo=UTC)


def _entry(
    number: int,
    *,
    occurred_at: datetime | None = None,
    source_recorded_at: datetime | None = None,
    created_at: datetime | None = None,
) -> JournalEntry:
    return JournalEntry(
        id=UUID(f"01920000-0000-7000-8000-{number:012d}"),
        owner_id=OWNER_ID,
        source_id=UUID(f"01920000-0000-7001-8000-{number:012d}"),
        journal_date=date(2026, 7, 21),
        occurred_at=occurred_at,
        source_recorded_at=source_recorded_at,
        title=f"Anteckning {number}",
        summary=None,
        key_points=(KeyPoint(KeyPointKind.FACT, "Syntetisk uppgift"),),
        version=1,
        created_at=created_at or BASE,
        updated_at=created_at or BASE,
        archived_at=None,
    )


# Journal property 6:
# Entry lifecycle preserves provenance and deterministic order
@given(st.permutations([0, 1, 2, 3]))
@settings(max_examples=100)
def test_multiple_entries_use_occurrence_recorded_created_then_id_order(
    permutation: list[int],
) -> None:
    entries = [
        _entry(1, occurred_at=BASE + timedelta(hours=3), created_at=BASE),
        _entry(2, source_recorded_at=BASE + timedelta(hours=2), created_at=BASE),
        _entry(3, created_at=BASE + timedelta(hours=1)),
        _entry(4, created_at=BASE + timedelta(hours=1)),
    ]
    shuffled = [entries[index] for index in permutation]
    ordered = sorted(shuffled, key=entry_order_key)
    assert [entry.id for entry in ordered] == [
        entries[2].id,
        entries[3].id,
        entries[1].id,
        entries[0].id,
    ]
    assert len({entry.journal_date for entry in ordered}) == 1


@given(title=st.text(min_size=1, max_size=200).filter(lambda value: bool(value.strip())))
@settings(max_examples=100)
def test_update_preserves_source_and_date_and_advances_version_once(title: str) -> None:
    entry = _entry(10)
    updated = update_entry(
        entry,
        expected_version=1,
        title=title,
        summary="Uppdaterad sammanfattning",
        key_points=(KeyPoint(KeyPointKind.REFLECTION, "Ny reflektion"),),
        changed_at=BASE + timedelta(days=1),
    )
    assert updated.source_id == entry.source_id
    assert updated.journal_date == entry.journal_date
    assert updated.version == 2
    assert updated.title == title.strip()
    with pytest.raises(ValueError, match="stale"):
        update_entry(
            updated,
            expected_version=1,
            title="Stale",
            summary=None,
            key_points=(),
            changed_at=BASE + timedelta(days=2),
        )


def test_archive_and_restore_are_reversible_versioned_transitions() -> None:
    entry = _entry(20)
    archived = archive_entry(entry, expected_version=1, changed_at=BASE + timedelta(hours=1))
    assert archived.archived_at == BASE + timedelta(hours=1)
    assert archived.version == 2
    restored = restore_entry(archived, expected_version=2, changed_at=BASE + timedelta(hours=2))
    assert restored.archived_at is None
    assert restored.version == 3
    assert restored.source_id == entry.source_id
    assert restored.journal_date == entry.journal_date

    with pytest.raises(ValueError):
        archive_entry(archived, expected_version=2, changed_at=BASE + timedelta(hours=3))
    with pytest.raises(ValueError):
        restore_entry(entry, expected_version=1, changed_at=BASE + timedelta(hours=3))


def test_key_points_are_closed_bounded_values() -> None:
    assert KeyPoint(KeyPointKind.QUESTION, "Vad är nästa steg?").kind is KeyPointKind.QUESTION
    with pytest.raises(ValueError):
        KeyPoint(KeyPointKind.FACT, "")
    with pytest.raises(ValueError):
        KeyPoint(KeyPointKind.FACT, "x" * 2001)

from datetime import date
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sidekick.journal.domain.entry import JournalEntry, KeyPoint, KeyPointKind
from sidekick.journal.domain.summary import (
    SummaryContent,
    SummaryProposal,
    changed_entry_count,
    entry_fingerprint,
    validate_content_references,
)

OWNER = UUID("018af000-0000-7000-8000-000000000001")
SOURCE = UUID("01910000-0000-7000-8000-000000000001")


def make_entry(entry_id: UUID, version: int, *, archived: bool = False) -> JournalEntry:
    from datetime import UTC, datetime

    now = datetime(2026, 7, 21, 9, 0, tzinfo=UTC)
    return JournalEntry(
        id=entry_id,
        owner_id=OWNER,
        source_id=SOURCE,
        journal_date=now.date(),
        occurred_at=now,
        source_recorded_at=now,
        title="Anteckning",
        summary=None,
        key_points=(KeyPoint(KeyPointKind.FACT, "Fakta"),),
        version=version,
        created_at=now,
        updated_at=now,
        archived_at=now if archived else None,
    )


@given(st.lists(st.integers(min_value=1, max_value=5), min_size=0, max_size=8))
def test_entry_fingerprint_is_deterministic_and_hex(versions: list[int]) -> None:
    entries = [
        make_entry(UUID(int=0x19100000000070008000000000000010 + index), version)
        for index, version in enumerate(versions)
    ]
    assert entry_fingerprint(entries) == entry_fingerprint(list(reversed(entries)))
    assert len(entry_fingerprint(entries)) == 64


@given(st.dictionaries(st.uuids(), st.integers(min_value=1, max_value=5), max_size=8))
def test_changed_entry_count_counts_id_union_once(stored: dict[UUID, int]) -> None:
    current = dict(stored)
    if stored:
        first = next(iter(stored))
        current[first] = stored[first] + 1
    added = UUID("01910000-0000-7000-8000-000000000099")
    current[added] = 1
    assert changed_entry_count(stored, current) == (1 if not stored else 2)


@given(st.lists(st.integers(min_value=1, max_value=5), min_size=1, max_size=8))
def test_entry_fingerprint_uses_only_active_id_version_map(versions: list[int]) -> None:
    entries = [
        make_entry(UUID(int=0x19100000000070008000000000000040 + index), version)
        for index, version in enumerate(versions)
    ]
    archived = make_entry(UUID("01910000-0000-7000-8000-000000000099"), 99, archived=True)

    assert entry_fingerprint([*entries, archived]) == entry_fingerprint(entries)
    assert entry_fingerprint(entries) != entry_fingerprint(
        [*entries[:-1], make_entry(entries[-1].id, entries[-1].version + 1)]
    )


@given(st.dictionaries(st.uuids(), st.integers(min_value=1, max_value=5), max_size=8))
def test_changed_entry_count_counts_removed_and_version_changed_ids_once(
    stored: dict[UUID, int],
) -> None:
    current = dict(stored)
    removed = next(iter(stored), UUID("01910000-0000-7000-8000-000000000098"))
    current.pop(removed, None)
    changed = next(iter(current), UUID("01910000-0000-7000-8000-000000000097"))
    if changed in current:
        current[changed] += 1
    added = UUID("01910000-0000-7000-8000-000000000096")
    current[added] = 1

    expected = (1 if removed in stored else 0) + (1 if changed in stored else 0) + 1
    assert changed_entry_count(stored, current) == expected


def test_summary_proposal_acceptance_is_explicit_and_rejects_reuse() -> None:
    entry_id = UUID("01910000-0000-7000-8000-000000000003")
    proposal = SummaryProposal(
        id=UUID("01910000-0000-7000-8000-000000000005"),
        owner_id=OWNER,
        journal_date=date(2026, 7, 21),
        state="pending_review",
        entry_fingerprint="a" * 64,
        content=SummaryContent(
            overview="Ett förslag.",
            overview_entry_ids=[entry_id],
            themes=[],
            important_events=[],
            decisions=[],
            commitments=[],
            open_questions=[],
            unresolved_items=[],
            contradictions=[],
        ),
        version=1,
    )

    accepted = proposal.accept()
    assert accepted.state == "accepted"
    assert accepted.version == 2
    with pytest.raises(ValueError, match="no longer pending"):
        accepted.accept()
    rejected = proposal.reject()
    assert rejected.state == "rejected"
    with pytest.raises(ValueError, match="no longer pending"):
        rejected.reject()


def test_summary_content_references_are_guarded_to_current_active_ids() -> None:
    entry_id = UUID("01910000-0000-7000-8000-000000000003")
    content = SummaryContent(
        overview="Dagens översikt.",
        overview_entry_ids=[entry_id],
        themes=[],
        important_events=[],
        decisions=[],
        commitments=[],
        open_questions=[],
        unresolved_items=[],
        contradictions=[],
    )
    validate_content_references(content, {entry_id})
    with pytest.raises(ValueError, match="outside the active day"):
        validate_content_references(content, set())

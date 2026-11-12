"""Property 1: source validity and immutable provenance."""

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sidekick.journal.domain.source import (
    JournalSource,
    SourceType,
    content_fingerprint,
    replacement_source,
    validate_raw_text,
)

AWARE_TIMES = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31, 23, 59, 59),
    timezones=st.sampled_from([UTC, timezone(timedelta(hours=2))]),
)
VALID_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")), min_size=1, max_size=500
).filter(lambda value: bool(value.strip()))


def _source(
    *,
    source_id: UUID | None = None,
    owner_id: UUID | None = None,
    raw_text: str = "En syntetisk svensk journalanteckning.",
    replaces_source_id: UUID | None = None,
) -> JournalSource:
    return JournalSource(
        id=source_id or uuid4(),
        owner_id=owner_id or uuid4(),
        source_type=SourceType.MANUAL_TEXT,
        journal_date=date(2026, 7, 21),
        occurred_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
        source_recorded_at=datetime(2026, 7, 24, 8, tzinfo=UTC),
        raw_text=raw_text,
        language="sv",
        replaces_source_id=replaces_source_id,
        created_at=datetime(2026, 7, 24, 10, tzinfo=UTC),
    )


# Journal property 1: Source validity and immutable provenance
@given(raw_text=VALID_TEXT, occurred_at=AWARE_TIMES, recorded_at=AWARE_TIMES)
@settings(max_examples=100)
def test_valid_source_has_deterministic_fingerprint_and_aware_times(
    raw_text: str, occurred_at: datetime, recorded_at: datetime
) -> None:
    validate_raw_text(raw_text)
    source = JournalSource(
        id=uuid4(),
        owner_id=uuid4(),
        source_type=SourceType.TRANSCRIPT_TEXT,
        journal_date=date(2026, 7, 21),
        occurred_at=occurred_at,
        source_recorded_at=recorded_at,
        raw_text=raw_text,
        language="sv-SE",
        replaces_source_id=None,
        created_at=datetime.now(UTC),
    )
    assert len(source.content_fingerprint) == 64
    assert source.content_fingerprint == content_fingerprint(
        source_type=source.source_type,
        journal_date=source.journal_date,
        occurred_at=occurred_at,
        source_recorded_at=recorded_at,
        raw_text=raw_text,
        language="sv-SE",
        replaces_source_id=None,
    )


@pytest.mark.parametrize("raw_text", ["", "   ", "text\x00med nul", "x" * 100_001])
def test_source_text_bounds_fail_closed(raw_text: str) -> None:
    with pytest.raises(ValueError):
        _source(raw_text=raw_text)


@pytest.mark.parametrize("field", ["occurred_at", "source_recorded_at", "created_at"])
def test_naive_source_timestamps_are_rejected(field: str) -> None:
    values = {
        "id": uuid4(),
        "owner_id": uuid4(),
        "source_type": SourceType.MANUAL_TEXT,
        "journal_date": date(2026, 7, 21),
        "occurred_at": datetime(2026, 7, 21, 9, tzinfo=UTC),
        "source_recorded_at": datetime(2026, 7, 24, 8, tzinfo=UTC),
        "raw_text": "Syntetisk text",
        "language": "sv",
        "replaces_source_id": None,
        "created_at": datetime(2026, 7, 24, 10, tzinfo=UTC),
    }
    values[field] = datetime(2026, 7, 21, 9)
    with pytest.raises(ValueError, match="timezone-aware"):
        JournalSource(**values)


@given(replacement_text=VALID_TEXT)
@settings(max_examples=100)
def test_replacement_is_distinct_and_preserves_prior_provenance(replacement_text: str) -> None:
    original = _source()
    before = original
    replacement = replacement_source(
        original,
        source_id=uuid4(),
        raw_text=replacement_text,
        created_at=datetime(2026, 7, 25, 10, tzinfo=UTC),
    )

    assert replacement.id != original.id
    assert replacement.owner_id == original.owner_id
    assert replacement.replaces_source_id == original.id
    assert original == before
    with pytest.raises(FrozenInstanceError):
        original.raw_text = "försök till ändring"  # type: ignore[misc]


def test_replacement_rejects_same_id_or_cross_owner() -> None:
    original = _source()
    with pytest.raises(ValueError):
        replacement_source(
            original,
            source_id=original.id,
            raw_text="Rättelse",
            created_at=datetime.now(UTC),
        )
    with pytest.raises(ValueError):
        replacement_source(
            original,
            source_id=uuid4(),
            raw_text="Rättelse",
            created_at=datetime.now(UTC),
            owner_id=uuid4(),
        )

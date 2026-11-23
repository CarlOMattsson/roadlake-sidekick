"""The values of repetition refuse what the tables refuse, so a bad value never reaches them."""

from dataclasses import replace
from datetime import UTC, datetime, time
from uuid import uuid4

import pytest

from sidekick.review.domain.cards import (
    Answer,
    AnswerChannel,
    CardSource,
    FoldReport,
    default_settings,
    new_card,
)
from sidekick.review.domain.scheduling import NEW_CARD, Grade, ReviewConfig

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
OWNER = uuid4()


def test_the_defaults_are_off_ten_new_cards_and_ninety_percent() -> None:
    settings = default_settings(OWNER, NOW)

    assert (settings.enabled, settings.include_contacts, settings.include_library) == (
        False,
        True,
        True,
    )
    assert (settings.new_per_day, settings.max_reviews_per_day) == (10, 200)
    assert (settings.push_enabled, settings.push_local_time) == (True, time(18, 0))
    assert settings.config == ReviewConfig(0.90)


@pytest.mark.parametrize(
    "change",
    [
        {"new_per_day": -1},
        {"new_per_day": 51},
        {"max_reviews_per_day": 9},
        {"max_reviews_per_day": 1001},
        {"desired_retention": 0.79},
        {"desired_retention": 0.98},
    ],
)
def test_settings_outside_the_ranges_of_the_table_are_refused(change: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="between"):
        replace(default_settings(OWNER, NOW), **change)


@pytest.mark.parametrize(
    "change", [{"new_per_day": 0}, {"new_per_day": 50}, {"max_reviews_per_day": 10}]
)
def test_the_ends_of_the_ranges_are_allowed(change: dict[str, int]) -> None:
    assert replace(default_settings(OWNER, NOW), **change)


def test_a_new_card_for_a_contact_names_the_contact_and_has_never_been_answered() -> None:
    contact = uuid4()

    card = new_card(uuid4(), OWNER, CardSource.CONTACT_FACE, contact, ReviewConfig(), NOW)

    assert (card.contact_id, card.library_fact_id, card.source_id) == (contact, None, contact)
    assert card.state == NEW_CARD
    assert card.introduced_on is None
    assert card.scheduler_version == ReviewConfig().scheduler_version
    assert card.schedulable().in_play


def test_a_new_card_for_a_fact_names_the_fact() -> None:
    fact = uuid4()

    card = new_card(uuid4(), OWNER, CardSource.LIBRARY_FACT, fact, ReviewConfig(), NOW)

    assert (card.contact_id, card.library_fact_id, card.source_id) == (None, fact, fact)


@pytest.mark.parametrize(
    "keys",
    [
        {"contact_id": None, "library_fact_id": None},
        {"contact_id": uuid4(), "library_fact_id": uuid4()},
        {"contact_id": None, "library_fact_id": uuid4()},
    ],
)
def test_a_contact_card_names_exactly_a_contact(keys: dict[str, object]) -> None:
    card = new_card(uuid4(), OWNER, CardSource.CONTACT_FACE, uuid4(), ReviewConfig(), NOW)

    with pytest.raises(ValueError, match="exactly the source"):
        replace(card, **keys)


def test_a_suspended_or_retired_card_is_not_in_play_and_a_card_of_the_other_kind_must_match() -> (
    None
):
    card = new_card(uuid4(), OWNER, CardSource.CONTACT_FACE, uuid4(), ReviewConfig(), NOW)

    assert not replace(card, suspended_at=NOW).schedulable().in_play
    assert not replace(card, retired_at=NOW).schedulable().in_play
    with pytest.raises(ValueError, match="exactly the source"):
        replace(card, source_kind=CardSource.LIBRARY_FACT)


def _answer(**overrides: object) -> Answer:
    return replace(
        Answer(
            entry_id=uuid4(),
            grade=Grade.GOOD,
            reviewed_at=NOW,
            received_at=NOW,
            client_review_id="phone-1",
            channel=AnswerChannel.COMPANION,
            introduced_on=NOW.date(),
        ),
        **overrides,
    )


def test_an_answer_becomes_the_log_entry_the_fold_reads() -> None:
    answer = _answer()

    assert (answer.entry.entry_id, answer.entry.grade, answer.entry.reviewed_at) == (
        answer.entry_id,
        Grade.GOOD,
        NOW,
    )


@pytest.mark.parametrize("change", [{"client_review_id": ""}, {"client_review_id": "x" * 65}])
def test_an_answer_key_must_be_one_to_sixty_four_characters(change: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="client_review_id"):
        _answer(**change)


@pytest.mark.parametrize("duration", [-1, 600_001])
def test_an_answer_duration_is_bounded(duration: int) -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        _answer(duration_ms=duration)


def test_a_fold_report_is_consistent_only_without_mismatches() -> None:
    assert FoldReport(checked=3, mismatched=0, stale=1).consistent
    assert not FoldReport(checked=3, mismatched=1, stale=0).consistent

"""The schedule of a card is a fold of its log: golden values, late grades, the day's cards."""

import importlib.metadata
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sidekick.review.domain import scheduling
from sidekick.review.domain.scheduling import (
    NEW_CARD,
    CardState,
    DaySelection,
    Grade,
    LogEntry,
    Phase,
    ReviewConfig,
    SchedulableCard,
    apply_review,
    can_extend,
    fold,
    select_day,
    start_of_next_day,
)

CONFIG = ReviewConfig()
T0 = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)
A, G = Grade.AGAIN, Grade.GOOD


def entry(number: int, grade: Grade, offset: timedelta) -> LogEntry:
    return LogEntry(UUID(int=number), grade, T0 + offset)


def log(*steps: tuple[Grade, timedelta]) -> list[LogEntry]:
    return [entry(number, grade, offset) for number, (grade, offset) in enumerate(steps, start=1)]


# Values produced by py-fsrs 6.3.3 itself (its Scheduler, same settings, fuzzing off), copied
# here so that a library upgrade that changes the schedule fails this test, not silently.
# Each row: grade, offset from T0, phase after, stability, difficulty, due offset from T0.
GOLDEN = {
    "good_every_time": [
        (G, 0 * MINUTE, Phase.REVIEW, 2.3065, 2.118103970459016, 2 * DAY),
        (G, 10 * MINUTE, Phase.REVIEW, 2.3065, 2.111214235785395, 2 * DAY + 10 * MINUTE),
        (G, DAY, Phase.REVIEW, 2.3065, 2.1043313908464483, 3 * DAY),
        (G, 5 * DAY, Phase.REVIEW, 16.198771694744682, 2.0974554287524403, 21 * DAY),
    ],
    "lapse_and_recover": [
        (G, 0 * MINUTE, Phase.REVIEW, 2.3065, 2.118103970459016, 2 * DAY),
        (G, 10 * MINUTE, Phase.REVIEW, 2.3065, 2.111214235785395, 2 * DAY + 10 * MINUTE),
        (A, DAY, Phase.RELEARNING, 0.7750839828558984, 7.392238132342694, DAY + 10 * MINUTE),
        (
            G,
            DAY + 10 * MINUTE,
            Phase.REVIEW,
            0.8281648000472626,
            7.38007426350719,
            2 * DAY + 10 * MINUTE,
        ),
        (G, 3 * DAY, Phase.REVIEW, 2.729633329301031, 7.3679225585405215, 6 * DAY),
    ],
    "again_while_learning": [
        (A, 0 * MINUTE, Phase.LEARNING, 0.212, 6.4133, 10 * MINUTE),
        (A, 10 * MINUTE, Phase.LEARNING, 0.08335671711031604, 8.806304468856837, 20 * MINUTE),
        (G, 20 * MINUTE, Phase.REVIEW, 0.10314065007785231, 8.792726533684817, DAY + 20 * MINUTE),
        (G, 30 * MINUTE, Phase.REVIEW, 0.12584423732556518, 8.77916217644797, DAY + 30 * MINUTE),
    ],
}


@pytest.mark.parametrize("name", list(GOLDEN))
def test_the_wrapper_reproduces_the_libraries_own_schedule(name: str) -> None:
    state = NEW_CARD
    for number, (grade, offset, phase, stability, difficulty, due) in enumerate(GOLDEN[name], 1):
        state = apply_review(state, entry(number, grade, offset), CONFIG)
        assert state.phase is phase
        assert state.stability == pytest.approx(stability, rel=1e-12)
        assert state.difficulty == pytest.approx(difficulty, rel=1e-12)
        assert state.due_at == T0 + due
        assert state.last_review_at == T0 + offset
        assert state.reps == number


def test_a_lapse_is_counted_only_when_a_known_card_is_forgotten() -> None:
    steps = [(a, b) for a, b, *_ in GOLDEN["again_while_learning"]]
    assert fold(log(*steps), CONFIG).lapses == 0
    steps = [(a, b) for a, b, *_ in GOLDEN["lapse_and_recover"]]
    assert fold(log(*steps), CONFIG).lapses == 1


def test_the_library_version_is_the_one_the_rules_name() -> None:
    assert importlib.metadata.version("fsrs") == scheduling.FSRS_VERSION
    assert CONFIG.scheduler_version == "fsrs-6.3.3/r0.90/s10m/v1"
    assert ReviewConfig(0.85).scheduler_version == "fsrs-6.3.3/r0.85/s10m/v1"


@pytest.mark.parametrize("retention", [0.79, 0.98, 1.0, 0.0])
def test_a_retention_outside_the_owners_range_is_refused(retention: float) -> None:
    with pytest.raises(ValueError, match="desired_retention"):
        ReviewConfig(retention)


def test_a_higher_retention_schedules_sooner() -> None:
    entries = log((G, 0 * MINUTE), (G, DAY), (G, 4 * DAY))
    assert fold(entries, ReviewConfig(0.95)).due_at < fold(entries, ReviewConfig(0.85)).due_at


def test_the_fold_needs_no_clock_and_no_random_source(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> float:
        raise AssertionError("the fold must not draw a random number")

    monkeypatch.setattr("fsrs.scheduler.random", forbidden)
    entries = log(
        (G, 0 * MINUTE), (G, 10 * MINUTE), (G, 3 * DAY), (A, 9 * DAY), (G, 9 * DAY + MINUTE)
    )

    first = fold(entries, CONFIG)

    assert fold(entries, CONFIG) == first
    assert first.due_at is not None
    assert first.due_at.tzinfo is not None


def test_an_entry_in_another_time_zone_folds_like_the_same_moment_in_utc() -> None:
    plus_two = ZoneInfo("Europe/Stockholm")
    moved = LogEntry(UUID(int=1), G, T0.astimezone(plus_two))
    assert fold([moved], CONFIG) == fold([entry(1, G, timedelta(0))], CONFIG)


def test_a_time_without_a_zone_is_refused() -> None:
    with pytest.raises(ValueError, match="time zone"):
        LogEntry(UUID(int=1), G, datetime(2026, 3, 2, 8, 0))


def test_an_empty_log_is_a_new_card() -> None:
    assert fold([], CONFIG) == NEW_CARD
    assert NEW_CARD.phase is Phase.NEW
    assert NEW_CARD.due_at is None


def test_an_answer_before_the_last_one_cannot_extend_a_state() -> None:
    state = apply_review(NEW_CARD, entry(1, G, DAY), CONFIG)
    late = entry(2, G, 0 * MINUTE)

    assert not can_extend(state, late)
    assert not can_extend(state, entry(3, G, DAY))
    assert can_extend(state, entry(4, G, DAY + MINUTE))
    assert can_extend(NEW_CARD, late)
    with pytest.raises(ValueError, match="refold"):
        apply_review(state, late, CONFIG)


def test_a_late_grade_gives_what_an_online_review_would_have() -> None:
    online = log((G, 0 * MINUTE), (G, DAY), (A, 4 * DAY), (G, 4 * DAY + 10 * MINUTE))
    cached = fold(online[:2] + online[3:], CONFIG)  # the phone had not yet sent the third answer

    assert not can_extend(cached, online[2])
    assert fold(online, CONFIG) != cached
    assert fold(online[:2] + online[3:] + [online[2]], CONFIG) == fold(online, CONFIG)


def base_state(first_answer: LogEntry) -> CardState:
    return apply_review(NEW_CARD, first_answer, CONFIG)


def test_answers_at_the_same_moment_fold_by_id() -> None:
    first, second = entry(1, A, DAY), entry(2, G, DAY)
    base = entry(3, G, 0 * MINUTE)

    in_id_order = apply_review(apply_review(base_state(base), first, CONFIG), second, CONFIG)
    in_other_order = apply_review(apply_review(base_state(base), second, CONFIG), first, CONFIG)

    assert fold([second, first, base], CONFIG) == fold([base, first, second], CONFIG) == in_id_order
    assert in_other_order != in_id_order


_offsets = st.one_of(
    st.integers(min_value=0, max_value=3).map(lambda n: timedelta(seconds=n)),
    st.integers(min_value=0, max_value=40 * 24 * 60).map(lambda n: timedelta(minutes=n)),
)
_answers = st.lists(st.tuples(st.sampled_from(Grade), _offsets), min_size=1, max_size=12).flatmap(
    lambda steps: st.permutations(
        [entry(number, grade, offset) for number, (grade, offset) in enumerate(steps, start=1)]
    )
)


@given(arrival=_answers)
@settings(max_examples=300, deadline=None)
def test_folding_one_answer_at_a_time_equals_folding_the_whole_log(arrival: list[LogEntry]) -> None:
    """Answers reach the server in any order; the stored state must equal a fold of the log."""

    state = NEW_CARD
    seen: list[LogEntry] = []
    for item in arrival:
        seen.append(item)
        state = apply_review(state, item, CONFIG) if can_extend(state, item) else fold(seen, CONFIG)
        assert state == fold(seen, CONFIG)

    assert state == fold(sorted(arrival, key=lambda e: (e.reviewed_at, e.entry_id)), CONFIG)
    assert state == fold(reversed(arrival), CONFIG)


# --- the day's cards ---

ZONE = ZoneInfo("Europe/Stockholm")
NOW = datetime(2026, 3, 2, 10, 0, tzinfo=ZONE)


def card(number: int, *, due: timedelta | None, created: int = 0, **flags: bool) -> SchedulableCard:
    state = (
        NEW_CARD
        if due is None
        else CardState(Phase.REVIEW, None, 3.0, 5.0, NOW + due, NOW - DAY, reps=2)
    )
    return SchedulableCard(UUID(int=number), state, T0 + timedelta(minutes=created), **flags)


def pick(cards: list[SchedulableCard], **limits: int) -> DaySelection:
    settings_ = {
        "new_per_day": 10,
        "max_reviews_per_day": 200,
        "answered_today": 0,
        "introduced_today": 0,
    } | limits
    return select_day(cards, now=NOW, zone=ZONE, **settings_)


def test_tomorrow_starts_at_the_owners_midnight() -> None:
    assert start_of_next_day(NOW, ZONE) == datetime(2026, 3, 3, 0, 0, tzinfo=ZONE)
    assert start_of_next_day(NOW, ZONE) == datetime(2026, 3, 2, 23, 0, tzinfo=UTC)
    spring = datetime(2026, 3, 28, 12, 0, tzinfo=ZONE)  # the day before the clocks go forward
    assert start_of_next_day(spring, ZONE) == datetime(2026, 3, 28, 23, 0, tzinfo=UTC)
    assert start_of_next_day(datetime(2026, 3, 29, 12, 0, tzinfo=ZONE), ZONE) == datetime(
        2026, 3, 29, 22, 0, tzinfo=UTC
    )


def test_cards_due_before_tomorrow_come_first_by_due_time_and_later_ones_wait() -> None:
    cards = [
        card(1, due=timedelta(hours=5)),
        card(2, due=-3 * DAY),
        card(3, due=timedelta(hours=13, minutes=59)),  # 23:59 local: still today
        card(4, due=timedelta(hours=14)),  # midnight: tomorrow
        card(5, due=-DAY),
    ]

    assert pick(cards).due == (UUID(int=2), UUID(int=5), UUID(int=1), UUID(int=3))


def test_suspended_and_retired_cards_are_never_chosen() -> None:
    cards = [
        card(1, due=-DAY, suspended=True),
        card(2, due=-DAY, retired=True),
        card(3, due=None, suspended=True),
        card(4, due=None, retired=True),
        card(5, due=-DAY),
        card(6, due=None),
    ]

    chosen = pick(cards)

    assert chosen.due == (UUID(int=5),)
    assert chosen.new == (UUID(int=6),)


def test_new_cards_come_in_stable_order_and_stop_at_the_days_limit() -> None:
    cards = [
        card(9, due=None, created=1),
        card(3, due=None, created=2),
        card(7, due=None, created=1),
    ]

    assert pick(cards).new == (UUID(int=7), UUID(int=9), UUID(int=3))
    assert pick(cards, new_per_day=2).new == (UUID(int=7), UUID(int=9))
    assert pick(cards, new_per_day=2, introduced_today=1).new == (UUID(int=7),)
    assert pick(cards, new_per_day=2, introduced_today=5).new == ()


def test_todays_answers_use_up_the_review_limit() -> None:
    cards = [card(number, due=-number * DAY) for number in range(1, 6)]

    assert len(pick(cards, max_reviews_per_day=10, answered_today=7).due) == 3
    assert pick(cards, max_reviews_per_day=10, answered_today=10).due == ()
    assert pick(cards, max_reviews_per_day=10, answered_today=12).due == ()
    assert pick(cards, max_reviews_per_day=2).due == (UUID(int=5), UUID(int=4))

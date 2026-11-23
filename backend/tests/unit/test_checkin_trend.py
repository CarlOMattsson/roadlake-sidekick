"""The owner's series and the coarse summary: windows, direction, and what is left out."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from sidekick.checkins.domain.instruments import OWN_V1
from sidekick.checkins.domain.trend import (
    SERIES_MAX_RESPONSES,
    Direction,
    Response,
    own_series,
    summarise,
)

DAY0 = date(2026, 1, 5)
TODAY = date(2026, 12, 1)


def _response(
    index: int,
    answers: Mapping[str, int],
    *,
    version: int = 1,
    instrument: str = "own",
    on: date | None = None,
) -> Response:
    answered_on = on or DAY0 + timedelta(days=7 * index)
    return Response(
        instrument_id=instrument,
        instrument_version=version,
        answered_on=answered_on,
        answered_at=datetime(answered_on.year, answered_on.month, answered_on.day, 9, tzinfo=UTC),
        answers=answers,
    )


def _moods(values: list[int]) -> list[Response]:
    return [_response(index, {"mood": value}) for index, value in enumerate(values)]


def _mood(responses: list[Response]) -> tuple[float | None, float | None, Direction | None]:
    summary = next(item for item in summarise(OWN_V1, responses).questions if item.key == "mood")
    return summary.recent_mean, summary.previous_mean, summary.direction


def test_nothing_answered_gives_an_empty_summary() -> None:
    summary = summarise(OWN_V1, [])
    assert summary.responses_count == 0
    assert summary.last_answered_on is None
    assert [item.key for item in summary.questions] == ["energy", "mood", "sleep", "stress"]
    assert all(item.direction is None and item.recent_mean is None for item in summary.questions)


def test_with_no_earlier_window_there_is_a_mean_but_no_direction() -> None:
    assert _mood(_moods([2, 3, 4])) == (3.0, None, None)


def test_the_recent_four_are_compared_with_the_four_before() -> None:
    recent, previous, direction = _mood(_moods([1, 1, 1, 1, 4, 4, 4, 4]))
    assert (recent, previous, direction) == (4.0, 1.0, Direction.HIGHER)
    assert _mood(_moods([5, 5, 5, 5, 2, 3, 2, 3])) == (2.5, 5.0, Direction.LOWER)


def test_answers_older_than_two_windows_do_not_count() -> None:
    recent, previous, _ = _mood(_moods([5, 5, 5, 1, 1, 1, 1, 3, 3, 3, 3]))
    assert (recent, previous) == (3.0, 1.0)


def test_a_change_of_half_a_point_is_similar_and_more_is_not() -> None:
    assert _mood(_moods([3, 3, 3, 3, 3, 3, 3, 4]))[2] is Direction.SIMILAR  # 3.25 vs 3.0
    assert _mood(_moods([3, 3, 3, 3, 3, 3, 4, 4]))[2] is Direction.SIMILAR  # 3.5 vs 3.0
    assert _mood(_moods([3, 3, 3, 3, 3, 4, 4, 4]))[2] is Direction.HIGHER  # 3.75 vs 3.0
    assert _mood(_moods([3, 3, 3, 3, 3, 2, 2, 3]))[2] is Direction.SIMILAR  # 2.5 vs 3.0
    assert _mood(_moods([3, 3, 3, 3, 2, 2, 2, 3]))[2] is Direction.LOWER  # 2.25 vs 3.0


def test_a_shorter_earlier_window_still_gives_a_direction() -> None:
    # Seven answers: the recent four against the three before them (mean 10/3, shown as 3.33).
    assert _mood(_moods([3, 3, 4, 5, 5, 5, 5])) == (5.0, 3.33, Direction.HIGHER)


def test_the_means_are_rounded_to_two_places() -> None:
    recent, _, _ = _mood(_moods([1, 1, 2]))
    assert recent == 1.33


def test_order_comes_from_the_date_and_then_the_time_not_from_the_list() -> None:
    shuffled = list(reversed(_moods([1, 1, 1, 1, 4, 4, 4, 4])))
    assert _mood(shuffled) == (4.0, 1.0, Direction.HIGHER)
    early = _response(0, {"mood": 1}, on=DAY0)
    late = Response(
        instrument_id="own",
        instrument_version=1,
        answered_on=DAY0,
        answered_at=datetime(DAY0.year, DAY0.month, DAY0.day, 20, tzinfo=UTC),
        answers={"mood": 5},
    )
    assert _mood([late, early])[0] == 3.0
    assert own_series(OWN_V1, [late, early], DAY0)["mood"] == ((DAY0, 1), (DAY0, 5))


def test_a_skipped_question_leaves_a_gap_and_does_not_shorten_the_window() -> None:
    responses = [_response(index, {"mood": 3, "sleep": 2}) for index in range(4)]
    responses += [_response(index, {"mood": 3}) for index in range(4, 8)]
    sleep = next(item for item in summarise(OWN_V1, responses).questions if item.key == "sleep")
    assert (sleep.recent_mean, sleep.previous_mean) == (2.0, None)
    assert summarise(OWN_V1, responses).responses_count == 8


def test_other_versions_and_instruments_are_not_mixed_in() -> None:
    responses = _moods([1, 1, 1, 1, 4, 4, 4, 4])
    responses += [_response(20, {"mood": 5}, version=2), _response(21, {"mood": 5}, instrument="x")]
    summary = summarise(OWN_V1, responses)
    assert summary.responses_count == 8
    assert _mood(responses) == (4.0, 1.0, Direction.HIGHER)
    assert own_series(OWN_V1, responses, TODAY)["mood"][-1][1] == 4


def test_the_summary_holds_only_means_directions_a_count_and_the_last_day() -> None:
    summary = summarise(OWN_V1, _moods([1, 2, 3, 4, 5, 4, 3, 2, 1]))
    assert set(summary.__slots__) == {
        "instrument_id",
        "instrument_version",
        "responses_count",
        "last_answered_on",
        "questions",
    }
    assert set(summary.questions[0].__slots__) == {
        "key",
        "recent_mean",
        "previous_mean",
        "direction",
    }
    assert summary.last_answered_on == DAY0 + timedelta(days=7 * 8)


def test_the_series_is_as_answered_oldest_first_per_question() -> None:
    responses = [
        _response(0, {"mood": 2, "sleep": 4}),
        _response(1, {"mood": 3}),
        _response(2, {"mood": 1, "sleep": 5}),
    ]
    series = own_series(OWN_V1, responses, DAY0 + timedelta(days=30))
    assert series["mood"] == (
        (DAY0, 2),
        (DAY0 + timedelta(days=7), 3),
        (DAY0 + timedelta(days=14), 1),
    )
    assert series["sleep"] == ((DAY0, 4), (DAY0 + timedelta(days=14), 5))
    assert series["energy"] == ()
    assert list(series) == ["energy", "mood", "sleep", "stress"]


def test_the_series_stops_at_the_last_twenty_six_responses() -> None:
    responses = _moods([1 + index % 5 for index in range(40)])
    series = own_series(OWN_V1, responses, DAY0 + timedelta(days=7 * 40))
    # Forty weekly answers reach back 280 days, within a year, so the count is what limits it.
    assert len(series["mood"]) == SERIES_MAX_RESPONSES
    assert series["mood"][-1][0] == DAY0 + timedelta(days=7 * 39)


def test_the_series_stops_at_a_year_when_that_is_fewer() -> None:
    responses = _moods([3] * 20)  # weekly from DAY0
    today = DAY0 + timedelta(days=7 * 19)
    assert len(own_series(OWN_V1, responses, today)["mood"]) == 20
    late = today + timedelta(days=365 - 7 * 19 + 7 * 10)
    kept = own_series(OWN_V1, responses, late)["mood"]
    assert 0 < len(kept) < 20
    assert all(day > late - timedelta(days=365) for day, _ in kept)


@given(
    st.lists(st.integers(min_value=1, max_value=5), max_size=30),
    st.lists(st.integers(min_value=1, max_value=5), max_size=30),
)
def test_means_stay_within_the_scale_and_direction_needs_both_windows(
    first: list[int], second: list[int]
) -> None:
    recent, previous, direction = _mood(_moods(first + second))
    for mean in (recent, previous):
        assert mean is None or 1 <= mean <= 5
    assert (direction is None) == (recent is None or previous is None)

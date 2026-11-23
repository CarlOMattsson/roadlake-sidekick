"""What the owner sees as change over time, and the coarse summary Claude may be given.

Both are computed on read from the owner's answers; nothing here is stored. Nothing names a value
good or bad, and there is no overall number: a series is shown as it is, and a summary says only
whether the recent mean is higher, lower or similar to the one before it.

Only responses made with the exact instrument (id and version) are used, so answers to a changed
wording are never mixed with older ones.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from fractions import Fraction
from typing import Final

from sidekick.checkins.domain.instruments import Instrument

SERIES_MAX_RESPONSES: Final = 26
SERIES_MAX_DAYS: Final = 365
"""The owner's chart covers the last 26 responses or the last year, whichever is fewer."""
SUMMARY_WINDOW: Final = 4
"""The summary compares the mean of up to this many recent answers with the mean of the same
number before them."""
SIMILAR_BAND: Final = Fraction(1, 2)
"""A change of at most this much between the two means is reported as similar."""


@dataclass(frozen=True, slots=True)
class Response:
    """One submitted check-in as the trend sees it."""

    instrument_id: str
    instrument_version: int
    answered_on: date
    answered_at: datetime
    """Breaks ties between two check-ins on the same day."""
    answers: Mapping[str, int]


class Direction(StrEnum):
    HIGHER = "higher"
    LOWER = "lower"
    SIMILAR = "similar"


@dataclass(frozen=True, slots=True)
class QuestionSummary:
    key: str
    recent_mean: float | None
    previous_mean: float | None
    direction: Direction | None
    """None until there are answers both in the recent window and before it."""


@dataclass(frozen=True, slots=True)
class CheckinSummary:
    instrument_id: str
    instrument_version: int
    responses_count: int
    last_answered_on: date | None
    questions: tuple[QuestionSummary, ...]


def _of_instrument(instrument: Instrument, responses: Iterable[Response]) -> list[Response]:
    """The responses made with exactly this instrument, oldest first."""

    own = [
        item
        for item in responses
        if item.instrument_id == instrument.id and item.instrument_version == instrument.version
    ]
    return sorted(own, key=lambda item: (item.answered_on, item.answered_at))


def own_series(
    instrument: Instrument, responses: Iterable[Response], today: date
) -> dict[str, tuple[tuple[date, int], ...]]:
    """Per question, the `(day, value)` points of the owner's chart, oldest first, as given."""

    since = today - timedelta(days=SERIES_MAX_DAYS)
    recent = [item for item in _of_instrument(instrument, responses) if item.answered_on > since]
    window = recent[-SERIES_MAX_RESPONSES:]
    return {
        question.key: tuple(
            (item.answered_on, item.answers[question.key])
            for item in window
            if question.key in item.answers
        )
        for question in instrument.questions
    }


def _mean(values: list[int]) -> Fraction | None:
    return Fraction(sum(values), len(values)) if values else None


def _direction(recent: Fraction | None, previous: Fraction | None) -> Direction | None:
    if recent is None or previous is None:
        return None
    change = recent - previous
    if abs(change) <= SIMILAR_BAND:
        return Direction.SIMILAR
    return Direction.HIGHER if change > 0 else Direction.LOWER


def _rounded(value: Fraction | None) -> float | None:
    return None if value is None else float(round(value, 2))


def _question_summary(key: str, ordered: list[Response]) -> QuestionSummary:
    """The windows count the answers to this question, so a skipped question leaves a gap
    instead of shortening the window of the others."""

    values = [item.answers[key] for item in ordered if key in item.answers]
    recent = _mean(values[-SUMMARY_WINDOW:])
    previous = _mean(values[-2 * SUMMARY_WINDOW : -SUMMARY_WINDOW])
    return QuestionSummary(
        key=key,
        recent_mean=_rounded(recent),
        previous_mean=_rounded(previous),
        direction=_direction(recent, previous),
    )


def summarise(instrument: Instrument, responses: Iterable[Response]) -> CheckinSummary:
    """The coarse summary: per question two means and a direction, and no dates besides the last
    one. Which other fields to hand to Claude is the caller's decision, not made here."""

    ordered = _of_instrument(instrument, responses)
    return CheckinSummary(
        instrument_id=instrument.id,
        instrument_version=instrument.version,
        responses_count=len(ordered),
        last_answered_on=ordered[-1].answered_on if ordered else None,
        questions=tuple(_question_summary(item.key, ordered) for item in instrument.questions),
    )

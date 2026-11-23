"""The questions the owner can be asked, in code, and the check that an answer fits them.

An instrument is a closed, versioned set of questions. Stored answers are keyed by
`(instrument id, instrument version, question key)`, so a changed wording or a different set of
questions is a new version (or a new instrument) and never a reinterpretation of old rows: keep
every old version in `CATALOGUE`.

The wording is written for Sidekick and is not taken from any published questionnaire. The
instrument says of itself that it is not validated; that text is shown wherever it is asked.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sidekick.shared.errors.core import ValidationError
from sidekick.shared.locale import LocalizedText

DEFAULT_INSTRUMENT_ID: Final = "own"
KEY_LENGTH_LIMIT: Final = 24
"""Longest instrument id and question key the tables hold (`varchar(24)`)."""


@dataclass(frozen=True, slots=True)
class Anchors:
    """What the two ends of a scale mean, in words."""

    low: LocalizedText
    high: LocalizedText


@dataclass(frozen=True, slots=True)
class Question:
    key: str
    name: LocalizedText
    """A short name for a list or a line in a chart."""
    text: LocalizedText
    anchors: Anchors
    minimum: int = 1
    maximum: int = 5


@dataclass(frozen=True, slots=True)
class Instrument:
    id: str
    version: int
    questions: tuple[Question, ...]
    validated: bool
    """True only for an instrument with published evidence; the own questions are not."""
    disclaimer: LocalizedText
    """Shown with the questions: what the answers are and are not."""

    def question(self, key: str) -> Question | None:
        return next((item for item in self.questions if item.key == key), None)


OWN_V1: Final = Instrument(
    id=DEFAULT_INSTRUMENT_ID,
    version=1,
    validated=False,
    disclaimer={
        "sv": "Egna frågor, inte ett validerat formulär och ingen diagnos.",
        "en": "Own questions, not a validated form and not a diagnosis.",
    },
    questions=(
        Question(
            key="energy",
            name={"sv": "Energi", "en": "Energy"},
            text={
                "sv": "Hur har din energi varit den senaste veckan?",
                "en": "How has your energy been this past week?",
            },
            anchors=Anchors(
                low={"sv": "Mycket låg", "en": "Very low"},
                high={"sv": "Mycket hög", "en": "Very high"},
            ),
        ),
        Question(
            key="mood",
            name={"sv": "Humör", "en": "Mood"},
            text={
                "sv": "Hur har ditt humör varit den senaste veckan?",
                "en": "How has your mood been this past week?",
            },
            anchors=Anchors(
                low={"sv": "Mycket lågt", "en": "Very low"},
                high={"sv": "Mycket gott", "en": "Very good"},
            ),
        ),
        Question(
            key="sleep",
            name={"sv": "Sömn", "en": "Sleep"},
            text={
                "sv": "Hur har du sovit den senaste veckan?",
                "en": "How have you slept this past week?",
            },
            anchors=Anchors(
                low={"sv": "Mycket dåligt", "en": "Very badly"},
                high={"sv": "Mycket bra", "en": "Very well"},
            ),
        ),
        Question(
            key="stress",
            name={"sv": "Stress", "en": "Stress"},
            text={
                "sv": "Hur mycket stress har du känt den senaste veckan?",
                "en": "How much stress have you felt this past week?",
            },
            anchors=Anchors(
                low={"sv": "Knappt någon", "en": "Hardly any"},
                high={"sv": "Mycket", "en": "A lot"},
            ),
        ),
    ),
)

CATALOGUE: Final[tuple[Instrument, ...]] = (OWN_V1,)
"""Every instrument version ever offered. A version is never edited or removed once answered."""


def find_instrument(instrument_id: str, version: int | None = None) -> Instrument | None:
    """The instrument of that id and version, or the newest version when `version` is None."""

    versions = [item for item in CATALOGUE if item.id == instrument_id]
    if version is not None:
        versions = [item for item in versions if item.version == version]
    return max(versions, key=lambda item: item.version, default=None)


class AnswerProblem(StrEnum):
    """Why an answer set was refused. Closed, and never carries a key or a value."""

    NO_ANSWERS = "no_answers"
    UNKNOWN_QUESTION = "unknown_question"
    NOT_AN_INTEGER = "not_an_integer"
    OUT_OF_RANGE = "out_of_range"


class InvalidAnswerError(ValidationError):
    """An answer set that does not fit the instrument. The text is the problem code alone: a
    value or a question key would put health data into a log line."""

    code = "invalid_answer"
    safe_title = "Invalid answer"

    def __init__(self, problem: AnswerProblem) -> None:
        super().__init__(problem.value)
        self.problem = problem


def _whole_number(value: object) -> int | None:
    """`value` when it is an integer (a bool is not one), else None."""

    return value if isinstance(value, int) and not isinstance(value, bool) else None


def validate_answers(instrument: Instrument, answers: Mapping[str, object]) -> dict[str, int]:
    """The answers as integers in question order, or `InvalidAnswerError`.

    A check-in may skip questions, but must answer at least one. Total over string keys: any
    values either give a result or this error, never another exception.
    """

    if not answers:
        raise InvalidAnswerError(AnswerProblem.NO_ANSWERS)
    for key in answers:
        if instrument.question(key) is None:
            raise InvalidAnswerError(AnswerProblem.UNKNOWN_QUESTION)
    checked: dict[str, int] = {}
    for question in instrument.questions:
        if question.key not in answers:
            continue
        value = _whole_number(answers[question.key])
        if value is None:
            raise InvalidAnswerError(AnswerProblem.NOT_AN_INTEGER)
        if not question.minimum <= value <= question.maximum:
            raise InvalidAnswerError(AnswerProblem.OUT_OF_RANGE)
        checked[question.key] = value
    return checked

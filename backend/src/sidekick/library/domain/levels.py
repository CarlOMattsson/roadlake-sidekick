"""Levels of knowing, question attempts, answer options and the shape of a question set.

The owner raises a level by answering questions; nothing else does. A level never goes down.
These functions only decide from the attempts they are given: reading and writing them is the
store's job, and who may answer is decided where the answer arrives.
"""

import hashlib
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sidekick.library.domain.errors import LibraryRefusedError
from sidekick.work.domain.ai_spec import clean_text

OVERVIEW_COUNT = 3
FULL_MIN = 5
FULL_MAX = 12
OPTIONS_MIN = 3
OPTIONS_MAX = 4
MAX_PROMPT_CHARS = 300
MAX_OPTION_CHARS = 200
MAX_EXPLANATION_CHARS = 300
MAX_FACTS = 20
MAX_FACT_PROMPT_CHARS = 200
MAX_FACT_ANSWER_CHARS = 300


class Level(StrEnum):
    SAVED = "saved"
    RECOGNISED = "recognised"
    UNDERSTOOD = "understood"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK = {Level.SAVED: 0, Level.RECOGNISED: 1, Level.UNDERSTOOD: 2}


class SetKind(StrEnum):
    OVERVIEW = "overview"
    FULL = "full"


@dataclass(frozen=True)
class Attempt:
    """One answer to one question. Only whether it was right matters for the level."""

    question_id: UUID
    correct: bool


@dataclass(frozen=True)
class LevelState:
    """A source's level and when each level was first reached (set if and only if reached)."""

    level: Level = Level.SAVED
    recognised_at: datetime | None = None
    understood_at: datetime | None = None

    def __post_init__(self) -> None:
        if (self.recognised_at is not None) != (self.level.rank >= Level.RECOGNISED.rank):
            raise LibraryRefusedError("level_timestamps_inconsistent")
        if (self.understood_at is not None) != (self.level.rank >= Level.UNDERSTOOD.rank):
            raise LibraryRefusedError("level_timestamps_inconsistent")


def reached_level(
    *, overview: Sequence[UUID], full: Sequence[UUID], attempts: Iterable[Attempt]
) -> Level:
    """The level the attempts earn for these two question sets, ignoring the level held now.

    * `recognised`: the overview set is exactly three questions and each has a correct attempt.
      A wrong answer is answered again, so only a correct attempt counts and none is scored.
    * `understood`: recognised, and the full set is five to twelve questions with a correct
      attempt each. A source without a full set cannot be understood yet.

    Attempts at questions outside the two sets are ignored.
    """

    answered_right = {attempt.question_id for attempt in attempts if attempt.correct}
    if not _complete(overview, answered_right, OVERVIEW_COUNT, OVERVIEW_COUNT):
        return Level.SAVED
    if not _complete(full, answered_right, FULL_MIN, FULL_MAX):
        return Level.RECOGNISED
    return Level.UNDERSTOOD


def _complete(
    questions: Sequence[UUID], answered_right: set[UUID], minimum: int, maximum: int
) -> bool:
    distinct = set(questions)
    return (
        len(distinct) == len(questions)
        and minimum <= len(questions) <= maximum
        and distinct <= answered_right
    )


def full_set_missing(full: Sequence[UUID]) -> bool:
    """True when the source has no usable full set ("Frågor saknas" and Claude may add one)."""

    return not FULL_MIN <= len(set(full)) == len(full) <= FULL_MAX


def advance(state: LevelState, reached: Level, now: datetime) -> LevelState:
    """`state` with the level `reached` applied: never lower, each timestamp set once."""

    level = reached if reached.rank > state.level.rank else state.level
    recognised_at = state.recognised_at
    if recognised_at is None and level.rank >= Level.RECOGNISED.rank:
        recognised_at = now
    understood_at = state.understood_at
    if understood_at is None and level.rank >= Level.UNDERSTOOD.rank:
        understood_at = now
    return LevelState(level, recognised_at, understood_at)


# --- answering ---------------------------------------------------------------------------------


def grade_answer(chosen_index: int, correct_index: int, option_count: int) -> bool:
    """Whether the option stored at `chosen_index` is the right one; the index must exist."""

    if not OPTIONS_MIN <= option_count <= OPTIONS_MAX:
        raise LibraryRefusedError("option_count_invalid")
    if type(chosen_index) is not int or not 0 <= chosen_index < option_count:
        raise LibraryRefusedError("option_out_of_range")
    return chosen_index == correct_index


def option_order(question_id: UUID, attempt_count: int, option_count: int) -> tuple[int, ...]:
    """The stored option indexes in the order they are shown at this attempt.

    Deterministic from the question and the number of attempts so far, so a reload shows the
    same order. A fixed shuffle per question is turned one place for every attempt, so two
    attempts in a row never show the same order and, over `option_count` attempts, every option
    has stood in every place. The client sends back the stored index it was given.
    """

    if not OPTIONS_MIN <= option_count <= OPTIONS_MAX:
        raise LibraryRefusedError("option_count_invalid")
    if type(attempt_count) is not int or attempt_count < 0:
        raise LibraryRefusedError("attempt_count_invalid")
    base = _shuffled(question_id, option_count)
    turn = attempt_count % option_count
    return base[turn:] + base[:turn]


def _shuffled(question_id: UUID, size: int) -> tuple[int, ...]:
    digest = hashlib.sha256(b"sidekick.library.options.v1" + question_id.bytes).digest()
    order = list(range(size))
    for index in range(size - 1, 0, -1):
        other = digest[index] % (index + 1)
        order[index], order[other] = order[other], order[index]
    return tuple(order)


# --- the shape of what Claude writes -----------------------------------------------------------


@dataclass(frozen=True)
class QuestionDraft:
    prompt: str
    options: tuple[str, ...]
    correct_index: int
    explanation: str | None = None


@dataclass(frozen=True)
class FactDraft:
    prompt: str
    answer: str


def validate_question_set(
    kind: SetKind, drafts: Sequence[QuestionDraft]
) -> tuple[QuestionDraft, ...]:
    """The set with its text cleaned, or a refusal: 3 overview questions, 5 to 12 full ones."""

    minimum, maximum = (
        (OVERVIEW_COUNT, OVERVIEW_COUNT) if kind is SetKind.OVERVIEW else (FULL_MIN, FULL_MAX)
    )
    if not minimum <= len(drafts) <= maximum:
        raise LibraryRefusedError("question_count_invalid")
    cleaned = tuple(_clean_question(draft) for draft in drafts)
    if len({_match(draft.prompt) for draft in cleaned}) != len(cleaned):
        raise LibraryRefusedError("question_duplicated")
    return cleaned


def _clean_question(draft: QuestionDraft) -> QuestionDraft:
    prompt = _line(draft.prompt, MAX_PROMPT_CHARS, "prompt_invalid")
    options = tuple(_line(option, MAX_OPTION_CHARS, "option_invalid") for option in draft.options)
    if not OPTIONS_MIN <= len(options) <= OPTIONS_MAX:
        raise LibraryRefusedError("option_count_invalid")
    if len({_match(option) for option in options}) != len(options):
        raise LibraryRefusedError("option_duplicated")
    if type(draft.correct_index) is not int or not 0 <= draft.correct_index < len(options):
        raise LibraryRefusedError("correct_index_invalid")
    explanation = (
        None
        if draft.explanation is None
        else _line(draft.explanation, MAX_EXPLANATION_CHARS, "explanation_invalid")
    )
    return QuestionDraft(prompt, options, draft.correct_index, explanation)


def validate_facts(drafts: Sequence[FactDraft], *, already: int = 0) -> tuple[FactDraft, ...]:
    """The facts with their text cleaned; at most twenty per source, `already` of them kept."""

    if already < 0 or already + len(drafts) > MAX_FACTS:
        raise LibraryRefusedError("fact_count_invalid")
    return tuple(
        FactDraft(
            _line(draft.prompt, MAX_FACT_PROMPT_CHARS, "fact_invalid"),
            _line(draft.answer, MAX_FACT_ANSWER_CHARS, "fact_invalid"),
        )
        for draft in drafts
    )


def _line(value: str, limit: int, refusal: str) -> str:
    text = " ".join(clean_text(value).split())
    if not text or len(text) > limit:
        raise LibraryRefusedError(refusal)
    return text


def _match(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()

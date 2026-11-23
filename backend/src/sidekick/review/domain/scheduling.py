"""The schedule of a card is a deterministic fold of its review log, and the day's card selection.

The log only grows and is the authority; a card's stored state is a cache of folding it. Entries
are folded in `(reviewed_at, id)` order, so a grade that reaches the server late (answered offline
on a phone) lands at its true place and the refold gives what an online review would have given.
Fuzzing is off and nothing here reads a clock or a random source, so the same log always folds to
the same state. `ReviewConfig.scheduler_version` names the rules that made a state; a state made
under another version is refolded from the log.

This module is the only one that imports `fsrs` (py-fsrs, FSRS-6). The rest of the code deals in
`CardState`, `LogEntry` and `Grade`.
"""

import functools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, tzinfo
from enum import IntEnum, StrEnum
from uuid import UUID

from fsrs import Card, Rating, Scheduler, State

FSRS_VERSION = "6.3.3"
DEFAULT_RETENTION = 0.90
MIN_RETENTION = 0.80
MAX_RETENTION = 0.97
LEARNING_STEP = timedelta(minutes=10)
MAXIMUM_INTERVAL_DAYS = 3650
RULES_REVISION = 1
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Grade(IntEnum):
    """How the owner answered. The log stores the number; version 1 writes AGAIN and GOOD."""

    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class Phase(StrEnum):
    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


@dataclass(frozen=True, slots=True)
class ReviewConfig:
    """What the owner may tune; the other FSRS settings are fixed (see the constants above)."""

    desired_retention: float = DEFAULT_RETENTION

    def __post_init__(self) -> None:
        if not MIN_RETENTION <= self.desired_retention <= MAX_RETENTION:
            raise ValueError("desired_retention must be between 0.80 and 0.97")

    @property
    def scheduler_version(self) -> str:
        minutes = int(LEARNING_STEP.total_seconds() // 60)
        return f"fsrs-{FSRS_VERSION}/r{self.desired_retention:.2f}/s{minutes}m/v{RULES_REVISION}"


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One answer. `entry_id` breaks ties between answers given at the same moment."""

    entry_id: UUID
    grade: Grade
    reviewed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "reviewed_at", _utc(self.reviewed_at))


@dataclass(frozen=True, slots=True)
class CardState:
    """Where a card stands; the all-default value is a card that has never been answered."""

    phase: Phase = Phase.NEW
    step: int | None = None
    stability: float | None = None
    difficulty: float | None = None
    due_at: datetime | None = None
    last_review_at: datetime | None = None
    reps: int = 0
    lapses: int = 0


NEW_CARD = CardState()

_TO_FSRS = {
    Phase.LEARNING: State.Learning,
    Phase.REVIEW: State.Review,
    Phase.RELEARNING: State.Relearning,
}
_FROM_FSRS = {fsrs_state: phase for phase, fsrs_state in _TO_FSRS.items()}


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("a time must carry a time zone")
    return moment.astimezone(UTC)


@functools.cache
def _scheduler(config: ReviewConfig) -> Scheduler:
    return Scheduler(
        desired_retention=config.desired_retention,
        learning_steps=(LEARNING_STEP,),
        relearning_steps=(LEARNING_STEP,),
        maximum_interval=MAXIMUM_INTERVAL_DAYS,
        enable_fuzzing=False,
    )


def _library_card(state: CardState) -> Card:
    """The library's card for a state. Built with every field set: its defaults read the clock."""

    if state.phase is Phase.NEW:
        return Card(card_id=0, state=State.Learning, step=0, due=_EPOCH)
    if state.due_at is None:
        raise ValueError("an answered card has a due time")
    return Card(
        card_id=0,
        state=_TO_FSRS[state.phase],
        step=state.step,
        stability=state.stability,
        difficulty=state.difficulty,
        due=state.due_at,
        last_review=state.last_review_at,
    )


def can_extend(state: CardState, entry: LogEntry) -> bool:
    """True when `entry` comes strictly after everything folded into `state`.

    Only then may `apply_review` extend a stored state; any other entry (a late offline grade, or
    one at the same moment as the last) needs `fold` over the whole log.
    """

    return state.last_review_at is None or entry.reviewed_at > state.last_review_at


def apply_review(state: CardState, entry: LogEntry, config: ReviewConfig) -> CardState:
    """The state after one more answer at or after the state's last answer."""

    if state.last_review_at is not None and entry.reviewed_at < state.last_review_at:
        raise ValueError("an earlier answer needs a refold of the whole log")
    card, _ = _scheduler(config).review_card(
        _library_card(state), Rating(entry.grade), entry.reviewed_at
    )
    lapsed = state.phase is Phase.REVIEW and entry.grade is Grade.AGAIN
    return CardState(
        phase=_FROM_FSRS[card.state],
        step=card.step,
        stability=card.stability,
        difficulty=card.difficulty,
        due_at=card.due,
        last_review_at=card.last_review,
        reps=state.reps + 1,
        lapses=state.lapses + int(lapsed),
    )


def fold(entries: Iterable[LogEntry], config: ReviewConfig) -> CardState:
    """The state of a card from its whole log, whatever order the entries arrive in."""

    state = NEW_CARD
    for entry in sorted(entries, key=lambda e: (e.reviewed_at, e.entry_id)):
        state = apply_review(state, entry, config)
    return state


@dataclass(frozen=True, slots=True)
class SchedulableCard:
    """What the selection needs to know about a card."""

    card_id: UUID
    state: CardState
    created_at: datetime
    suspended: bool = False
    retired: bool = False

    @property
    def in_play(self) -> bool:
        return not (self.suspended or self.retired)


@dataclass(frozen=True, slots=True)
class DaySelection:
    """The cards of today: due ones by due time, new ones in stable order."""

    due: tuple[UUID, ...]
    new: tuple[UUID, ...]


def start_of_next_day(now: datetime, zone: tzinfo) -> datetime:
    """The first moment of tomorrow in the owner's zone, as UTC."""

    tomorrow = _utc(now).astimezone(zone).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=zone).astimezone(UTC)


def select_day(
    cards: Sequence[SchedulableCard],
    *,
    now: datetime,
    zone: tzinfo,
    new_per_day: int,
    max_reviews_per_day: int,
    answered_today: int,
    introduced_today: int,
) -> DaySelection:
    """Which cards are up today.

    Due: answered cards whose due time is before tomorrow starts, by due time, at most the day's
    review limit less today's answers. New: never-answered cards by `(created_at, id)`, at most
    `new_per_day` less the cards first answered today. A suspended or retired card is never chosen.
    Choosing writes nothing; `introduced_today` is what the first answer recorded.
    """

    cutoff = start_of_next_day(now, zone)
    due = sorted(
        (
            (card.state.due_at, card.card_id)
            for card in cards
            if card.in_play
            and card.state.phase is not Phase.NEW
            and card.state.due_at is not None
            and card.state.due_at < cutoff
        ),
    )
    fresh = sorted(
        (_utc(card.created_at), card.card_id)
        for card in cards
        if card.in_play and card.state.phase is Phase.NEW
    )
    review_room = max(0, max_reviews_per_day - answered_today)
    new_room = max(0, new_per_day - introduced_today)
    return DaySelection(
        due=tuple(card_id for _, card_id in due[:review_room]),
        new=tuple(card_id for _, card_id in fresh[:new_room]),
    )

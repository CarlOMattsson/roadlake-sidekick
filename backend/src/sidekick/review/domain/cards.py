"""The values of repetition the store keeps: settings, cards and answers.

A card holds a schedule that is only a cache of folding its answers (`scheduling.fold`). It holds
no copy of what it asks about; the front and back are read from the source when shown.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from enum import StrEnum
from typing import cast
from uuid import UUID

from sidekick.review.domain.scheduling import (
    NEW_CARD,
    CardState,
    Grade,
    LogEntry,
    ReviewConfig,
    SchedulableCard,
)

DEFAULT_NEW_PER_DAY = 10
DEFAULT_MAX_REVIEWS_PER_DAY = 200
DEFAULT_PUSH_TIME = time(18, 0)
NEW_PER_DAY_RANGE = (0, 50)
MAX_REVIEWS_PER_DAY_RANGE = (10, 1000)
MAX_DURATION_MS = 600_000


class CardSource(StrEnum):
    """What a card asks about. A second kind of card for a contact is a new value, never a
    different reading of an existing one."""

    CONTACT_FACE = "contact_face"
    LIBRARY_FACT = "library_fact"


class AnswerChannel(StrEnum):
    APP = "app"
    COMPANION = "companion"


class AnswerOutcome(StrEnum):
    """What recording an answer did: it was written, or the same answer had been written before."""

    OK = "ok"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class ReviewSettings:
    """The owner's choices. Repetition is off until the owner turns it on."""

    owner_id: UUID
    enabled: bool
    include_contacts: bool
    include_library: bool
    new_per_day: int
    max_reviews_per_day: int
    push_enabled: bool
    push_local_time: time
    desired_retention: float
    version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not NEW_PER_DAY_RANGE[0] <= self.new_per_day <= NEW_PER_DAY_RANGE[1]:
            raise ValueError("new_per_day must be between 0 and 50")
        low, high = MAX_REVIEWS_PER_DAY_RANGE
        if not low <= self.max_reviews_per_day <= high:
            raise ValueError("max_reviews_per_day must be between 10 and 1000")
        ReviewConfig(self.desired_retention)

    @property
    def config(self) -> ReviewConfig:
        return ReviewConfig(self.desired_retention)


def default_settings(owner_id: UUID, now: datetime) -> ReviewSettings:
    """What an owner who never touched the settings has; nothing is stored until a change."""

    return ReviewSettings(
        owner_id=owner_id,
        enabled=False,
        include_contacts=True,
        include_library=True,
        new_per_day=DEFAULT_NEW_PER_DAY,
        max_reviews_per_day=DEFAULT_MAX_REVIEWS_PER_DAY,
        push_enabled=True,
        push_local_time=DEFAULT_PUSH_TIME,
        desired_retention=0.90,
        version=1,
        created_at=now,
        updated_at=now,
    )


@dataclass(frozen=True, slots=True)
class ReviewCard:
    """One thing to remember and where its schedule stands.

    Exactly the key that matches `source_kind` is set. A card the source no longer supports is
    retired and comes back with its history if the source returns.
    """

    id: UUID
    owner_id: UUID
    source_kind: CardSource
    contact_id: UUID | None
    library_fact_id: UUID | None
    state: CardState
    introduced_on: date | None
    suspended_at: datetime | None
    retired_at: datetime | None
    scheduler_version: str
    version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        matches = (
            self.contact_id is not None and self.library_fact_id is None
            if self.source_kind is CardSource.CONTACT_FACE
            else self.library_fact_id is not None and self.contact_id is None
        )
        if not matches:
            raise ValueError("a card names exactly the source that matches its kind")

    @property
    def source_id(self) -> UUID:
        """The key of the source, whichever kind it is (the constructor guarantees one is set)."""

        return cast(UUID, self.contact_id or self.library_fact_id)

    def schedulable(self) -> SchedulableCard:
        return SchedulableCard(
            card_id=self.id,
            state=self.state,
            created_at=self.created_at,
            suspended=self.suspended_at is not None,
            retired=self.retired_at is not None,
        )


def new_card(
    card_id: UUID,
    owner_id: UUID,
    source_kind: CardSource,
    source_id: UUID,
    config: ReviewConfig,
    now: datetime,
) -> ReviewCard:
    """A card nobody has answered yet."""

    contact = source_kind is CardSource.CONTACT_FACE
    return ReviewCard(
        id=card_id,
        owner_id=owner_id,
        source_kind=source_kind,
        contact_id=source_id if contact else None,
        library_fact_id=None if contact else source_id,
        state=NEW_CARD,
        introduced_on=None,
        suspended_at=None,
        retired_at=None,
        scheduler_version=config.scheduler_version,
        version=1,
        created_at=now,
        updated_at=now,
    )


@dataclass(frozen=True, slots=True)
class Answer:
    """One answer to write. `reviewed_at` is the owner's moment, already clamped by the caller;
    `client_review_id` is what makes a replay a no-op; `introduced_on` is the owner-zone day of the
    answer, kept on the card by its first answer."""

    entry_id: UUID
    grade: Grade
    reviewed_at: datetime
    received_at: datetime
    client_review_id: str
    channel: AnswerChannel
    introduced_on: date
    duration_ms: int | None = None
    clock_adjusted: bool = False

    def __post_init__(self) -> None:
        if not 1 <= len(self.client_review_id) <= 64:
            raise ValueError("client_review_id is 1 to 64 characters")
        if self.duration_ms is not None and not 0 <= self.duration_ms <= MAX_DURATION_MS:
            raise ValueError("duration_ms is 0 to 600000")

    @property
    def entry(self) -> LogEntry:
        return LogEntry(entry_id=self.entry_id, grade=self.grade, reviewed_at=self.reviewed_at)


@dataclass(frozen=True, slots=True)
class AnswerResult:
    outcome: AnswerOutcome
    card: ReviewCard


@dataclass(frozen=True, slots=True)
class FoldReport:
    """What folding every log of an owner again found. Counts only, never a card or a name.

    `stale` cards were scheduled under other rules than the current ones and are left out of the
    comparison; they are refolded on next touch or by the admin command.
    """

    checked: int
    mismatched: int
    stale: int

    @property
    def consistent(self) -> bool:
        return self.mismatched == 0


def with_state(
    card: ReviewCard, state: CardState, config: ReviewConfig, now: datetime
) -> ReviewCard:
    """The card after its schedule was recomputed under `config`."""

    return replace(
        card,
        state=state,
        scheduler_version=config.scheduler_version,
        version=card.version + 1,
        updated_at=now,
    )

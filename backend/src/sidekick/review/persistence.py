"""The repetition tables, read and written owner-filtered.

Every statement names the owner, and a row of another owner answers as not found, so no id reveals
whether a row exists. The log is written once and never changed or deleted: the application role
has no UPDATE or DELETE on `review_log`, and this store has no operation that would try. A card's
schedule is a cache of folding its log; `record_answer` extends it when the answer is the newest
and folds the whole log otherwise, with the card row locked. Nothing here logs a card or a name.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sidekick.review.domain.cards import (
    Answer,
    AnswerOutcome,
    AnswerResult,
    CardSource,
    FoldReport,
    ReviewCard,
    ReviewSettings,
    new_card,
    with_state,
)
from sidekick.review.domain.scheduling import (
    CardState,
    Grade,
    LogEntry,
    Phase,
    ReviewConfig,
    apply_review,
    can_extend,
    fold,
)
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.models import ReviewCardRow, ReviewLogRow, ReviewSettingsRow
from sidekick.shared.types import new_uuid7, validate_limit

MAX_LIST_ROWS = 25_000
"""The most cards one list read returns; an owner's deck is never larger (the design's cap)."""

_CONTACT_UNIQUE = "uq_review_cards_contact"
_FACT_UNIQUE = "uq_review_cards_library_fact"
_CONTACT_FK = "fk_review_cards_contact_owner"
_LOG_UNIQUE = "uq_review_log_card_client_review"


def _settings_from_row(row: ReviewSettingsRow) -> ReviewSettings:
    return ReviewSettings(
        owner_id=row.owner_id,
        enabled=row.enabled,
        include_contacts=row.include_contacts,
        include_library=row.include_library,
        new_per_day=row.new_per_day,
        max_reviews_per_day=row.max_reviews_per_day,
        push_enabled=row.push_enabled,
        push_local_time=row.push_local_time,
        desired_retention=float(row.desired_retention),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply_settings(row: ReviewSettingsRow, settings: ReviewSettings) -> None:
    row.enabled = settings.enabled
    row.include_contacts = settings.include_contacts
    row.include_library = settings.include_library
    row.new_per_day = settings.new_per_day
    row.max_reviews_per_day = settings.max_reviews_per_day
    row.push_enabled = settings.push_enabled
    row.push_local_time = settings.push_local_time
    row.desired_retention = Decimal(f"{settings.desired_retention:.2f}")
    row.version = settings.version
    row.updated_at = settings.updated_at


def _state_from_row(row: ReviewCardRow) -> CardState:
    return CardState(
        phase=Phase(row.fsrs_state),
        step=row.step,
        stability=row.stability,
        difficulty=row.difficulty,
        due_at=row.due_at,
        last_review_at=row.last_review_at,
        reps=row.reps,
        lapses=row.lapses,
    )


def _apply_state(row: ReviewCardRow, state: CardState) -> None:
    row.fsrs_state = state.phase.value
    row.step = state.step
    row.stability = state.stability
    row.difficulty = state.difficulty
    row.due_at = state.due_at
    row.last_review_at = state.last_review_at
    row.reps = state.reps
    row.lapses = state.lapses


def card_from_row(row: ReviewCardRow) -> ReviewCard:
    return ReviewCard(
        id=row.id,
        owner_id=row.owner_id,
        source_kind=CardSource(row.source_kind),
        contact_id=row.contact_id,
        library_fact_id=row.library_fact_id,
        state=_state_from_row(row),
        introduced_on=row.introduced_on,
        suspended_at=row.suspended_at,
        retired_at=row.retired_at,
        scheduler_version=row.scheduler_version,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _entry_from_row(row: ReviewLogRow) -> LogEntry:
    return LogEntry(entry_id=row.id, grade=Grade(row.rating), reviewed_at=row.reviewed_at)


def _constraint(error: IntegrityError) -> str | None:
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


def _locked_card_row(session: Session, owner_id: UUID, card_id: UUID) -> ReviewCardRow:
    row = session.scalar(
        select(ReviewCardRow)
        .where(ReviewCardRow.id == card_id, ReviewCardRow.owner_id == owner_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFoundError("card not found")
    return row


def _card_row_for_source(
    session: Session, owner_id: UUID, source_kind: CardSource, source_id: UUID
) -> ReviewCardRow | None:
    column = (
        ReviewCardRow.contact_id
        if source_kind is CardSource.CONTACT_FACE
        else ReviewCardRow.library_fact_id
    )
    return session.scalar(
        select(ReviewCardRow).where(ReviewCardRow.owner_id == owner_id, column == source_id)
    )


def _log_entries(session: Session, owner_id: UUID, card_id: UUID) -> list[LogEntry]:
    rows = session.scalars(
        select(ReviewLogRow)
        .where(ReviewLogRow.owner_id == owner_id, ReviewLogRow.card_id == card_id)
        .order_by(ReviewLogRow.reviewed_at, ReviewLogRow.id)
    )
    return [_entry_from_row(row) for row in rows]


def _log_row(owner_id: UUID, card_id: UUID, answer: Answer) -> ReviewLogRow:
    return ReviewLogRow(
        id=answer.entry_id,
        owner_id=owner_id,
        card_id=card_id,
        rating=int(answer.grade),
        reviewed_at=answer.reviewed_at,
        received_at=answer.received_at,
        client_review_id=answer.client_review_id,
        channel=answer.channel.value,
        duration_ms=answer.duration_ms,
        clock_adjusted=answer.clock_adjusted,
    )


def _write_answer(session: Session, owner_id: UUID, card_id: UUID, answer: Answer) -> bool:
    """Write the log row; False when this card already holds an answer with the same key."""

    try:
        with session.begin_nested():
            session.add(_log_row(owner_id, card_id, answer))
            session.flush()
    except IntegrityError as error:
        if _constraint(error) == _LOG_UNIQUE:
            return False
        raise
    return True


def _scheduled_state(
    session: Session, card: ReviewCard, entry: LogEntry, config: ReviewConfig
) -> CardState:
    """The state after `entry`: the cached one extended when the answer is the newest and the
    rules did not change, otherwise the fold of the whole log (which already holds the entry)."""

    if card.scheduler_version == config.scheduler_version and can_extend(card.state, entry):
        return apply_review(card.state, entry, config)
    return fold(_log_entries(session, card.owner_id, card.id), config)


class ReviewStore:
    """Settings, cards and the log of answers.

    The operations are static and owner-filtered; a store that adds the transaction boundary
    (`StoreBase`) is built on them.
    """

    @staticmethod
    def get_settings(session: Session, owner_id: UUID) -> ReviewSettings | None:
        """The owner's settings, or None when they never changed any (the defaults apply)."""

        row = session.get(ReviewSettingsRow, owner_id)
        return None if row is None else _settings_from_row(row)

    @staticmethod
    def save_settings(
        session: Session, settings: ReviewSettings, expected_version: int | None = None
    ) -> None:
        """Insert the settings, or update them when the stored version is `expected_version`."""

        row = session.scalar(
            select(ReviewSettingsRow)
            .where(ReviewSettingsRow.owner_id == settings.owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            row = ReviewSettingsRow(owner_id=settings.owner_id, created_at=settings.created_at)
            _apply_settings(row, settings)
            session.add(row)
            return
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale review settings version", reason="stale_version")
        _apply_settings(row, settings)

    @staticmethod
    def get_card(
        session: Session, owner_id: UUID, card_id: UUID, *, lock: bool = False
    ) -> ReviewCard:
        statement = select(ReviewCardRow).where(
            ReviewCardRow.id == card_id, ReviewCardRow.owner_id == owner_id
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        row = session.scalar(statement)
        if row is None:
            raise NotFoundError("card not found")
        return card_from_row(row)

    @staticmethod
    def card_for_source(
        session: Session, owner_id: UUID, source_kind: CardSource, source_id: UUID
    ) -> ReviewCard | None:
        row = _card_row_for_source(session, owner_id, source_kind, source_id)
        return None if row is None else card_from_row(row)

    @staticmethod
    def list_cards(
        session: Session,
        owner_id: UUID,
        *,
        in_play_only: bool = False,
        limit: int = MAX_LIST_ROWS,
        offset: int = 0,
    ) -> list[ReviewCard]:
        """The owner's cards in stable order; `in_play_only` leaves out suspended and retired."""

        statement = select(ReviewCardRow).where(ReviewCardRow.owner_id == owner_id)
        if in_play_only:
            statement = statement.where(
                ReviewCardRow.suspended_at.is_(None), ReviewCardRow.retired_at.is_(None)
            )
        rows = session.scalars(
            statement.order_by(ReviewCardRow.created_at, ReviewCardRow.id)
            .offset(offset)
            .limit(validate_limit(limit, maximum=MAX_LIST_ROWS))
        )
        return [card_from_row(row) for row in rows]

    @staticmethod
    def ensure_card(
        session: Session,
        owner_id: UUID,
        source_kind: CardSource,
        source_id: UUID,
        config: ReviewConfig,
        now: datetime,
    ) -> tuple[ReviewCard, bool]:
        """The card of a source, made when it has none. The flag says whether it was made.

        A source that is not the owner's (another owner's contact, or none) answers as not found.
        """

        existing = _card_row_for_source(session, owner_id, source_kind, source_id)
        if existing is not None:
            return card_from_row(existing), False
        card = new_card(new_uuid7(), owner_id, source_kind, source_id, config, now)
        try:
            with session.begin_nested():
                session.add(_card_row(card))
                session.flush()
        except IntegrityError as error:
            return _after_failed_card_insert(session, error, card)
        return card, True

    @staticmethod
    def set_suspended(
        session: Session, owner_id: UUID, card_id: UUID, suspended: bool, now: datetime
    ) -> ReviewCard:
        """Hide a card from the day's selection, or show it again. No change writes nothing."""

        row = _locked_card_row(session, owner_id, card_id)
        if (row.suspended_at is not None) != suspended:
            row.suspended_at = now if suspended else None
            _touch(row, now)
        return card_from_row(row)

    @staticmethod
    def set_retired(
        session: Session, owner_id: UUID, card_id: UUID, retired: bool, now: datetime
    ) -> ReviewCard:
        """Retire a card whose source is gone, or bring it back with its history."""

        row = _locked_card_row(session, owner_id, card_id)
        if (row.retired_at is not None) != retired:
            row.retired_at = now if retired else None
            _touch(row, now)
        return card_from_row(row)

    @staticmethod
    def log_entries(session: Session, owner_id: UUID, card_id: UUID) -> list[LogEntry]:
        """The answers of a card in fold order: by `(reviewed_at, id)`."""

        ReviewStore.get_card(session, owner_id, card_id)
        return _log_entries(session, owner_id, card_id)

    @staticmethod
    def count_answers(session: Session, owner_id: UUID, since: datetime, until: datetime) -> int:
        """How many answers fall in `[since, until)`: the day's answers when the bounds are the
        owner's day."""

        return (
            session.scalar(
                select(func.count())
                .select_from(ReviewLogRow)
                .where(
                    ReviewLogRow.owner_id == owner_id,
                    ReviewLogRow.reviewed_at >= since,
                    ReviewLogRow.reviewed_at < until,
                )
            )
            or 0
        )

    @staticmethod
    def count_introduced(session: Session, owner_id: UUID, day: date) -> int:
        """How many cards were first answered on `day`."""

        return (
            session.scalar(
                select(func.count())
                .select_from(ReviewCardRow)
                .where(ReviewCardRow.owner_id == owner_id, ReviewCardRow.introduced_on == day)
            )
            or 0
        )

    @staticmethod
    def record_answer(
        session: Session,
        owner_id: UUID,
        card_id: UUID,
        answer: Answer,
        config: ReviewConfig,
        now: datetime,
    ) -> AnswerResult:
        """Append the answer and bring the card's schedule up to date, in this transaction.

        The card row is locked first. An answer whose key the card already holds writes nothing and
        answers `duplicate`. The caller has applied the clock rules to `reviewed_at`.
        """

        row = _locked_card_row(session, owner_id, card_id)
        if not _write_answer(session, owner_id, card_id, answer):
            return AnswerResult(AnswerOutcome.DUPLICATE, card_from_row(row))
        state = _scheduled_state(session, card_from_row(row), answer.entry, config)
        _apply_state(row, state)
        row.scheduler_version = config.scheduler_version
        if row.introduced_on is None:
            row.introduced_on = answer.introduced_on
        _touch(row, now)
        return AnswerResult(AnswerOutcome.OK, card_from_row(row))

    @staticmethod
    def refold_card(
        session: Session, owner_id: UUID, card_id: UUID, config: ReviewConfig, now: datetime
    ) -> ReviewCard:
        """Recompute the card's schedule from its whole log under `config` and store it."""

        row = _locked_card_row(session, owner_id, card_id)
        card = card_from_row(row)
        state = fold(_log_entries(session, owner_id, card_id), config)
        if state != card.state or card.scheduler_version != config.scheduler_version:
            refolded = with_state(card, state, config, now)
            _apply_state(row, refolded.state)
            row.scheduler_version = refolded.scheduler_version
            _touch(row, now)
        return card_from_row(row)

    @staticmethod
    def verify_cards(session: Session, owner_id: UUID, config: ReviewConfig) -> FoldReport:
        """Fold every card's log and compare it with the schedule the card holds. Writes nothing.

        A card whose answers do not fold to its stored schedule (a log that was cut or changed, or
        a schedule that was) counts as mismatched. A card scheduled under other rules is stale.
        """

        entries = _owner_entries(session, owner_id)
        checked = mismatched = stale = 0
        for row in session.scalars(select(ReviewCardRow).where(ReviewCardRow.owner_id == owner_id)):
            if row.scheduler_version != config.scheduler_version:
                stale += 1
                continue
            checked += 1
            if fold(entries.get(row.id, ()), config) != _state_from_row(row):
                mismatched += 1
        return FoldReport(checked=checked, mismatched=mismatched, stale=stale)


def _owner_entries(session: Session, owner_id: UUID) -> Mapping[UUID, Sequence[LogEntry]]:
    entries: defaultdict[UUID, list[LogEntry]] = defaultdict(list)
    for row in session.scalars(select(ReviewLogRow).where(ReviewLogRow.owner_id == owner_id)):
        entries[row.card_id].append(_entry_from_row(row))
    return entries


def _touch(row: ReviewCardRow, now: datetime) -> None:
    row.version += 1
    row.updated_at = now


def _card_row(card: ReviewCard) -> ReviewCardRow:
    row = ReviewCardRow(
        id=card.id,
        owner_id=card.owner_id,
        source_kind=card.source_kind.value,
        contact_id=card.contact_id,
        library_fact_id=card.library_fact_id,
        introduced_on=card.introduced_on,
        suspended_at=card.suspended_at,
        retired_at=card.retired_at,
        scheduler_version=card.scheduler_version,
        version=card.version,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )
    _apply_state(row, card.state)
    return row


def _after_failed_card_insert(
    session: Session, error: IntegrityError, card: ReviewCard
) -> tuple[ReviewCard, bool]:
    """A card that was made at the same moment is returned; a source that is not the owner's is
    not found; any other failure is raised."""

    name = _constraint(error)
    if name in {_CONTACT_UNIQUE, _FACT_UNIQUE}:
        row = _card_row_for_source(session, card.owner_id, card.source_kind, card.source_id)
        if row is not None:
            return card_from_row(row), False
    if name == _CONTACT_FK:
        raise NotFoundError("card source not found") from None
    raise error


__all__ = [
    "MAX_LIST_ROWS",
    "ReviewStore",
    "card_from_row",
]

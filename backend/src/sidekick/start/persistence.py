"""Ready conversations and their days, read and written owner-filtered.

Every statement names the owner, and a row of another owner answers as not found, so no id reveals
whether a row exists. The application role has no DELETE on `ready_conversations` (a conversation
is paused or archived) and this store has no operation that would try; it deletes only day rows
older than the retention. `title` and `instruction` are the owner's text; nothing here logs them.
"""

from collections.abc import Collection
from datetime import date
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.automations.domain.spec import Cadence
from sidekick.shared.change_source import ChangeSource
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.persistence.models import ReadyConversationDayRow, ReadyConversationRow
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import validate_limit
from sidekick.start.domain.ready import (
    DayState,
    Ingredient,
    ReadyConversation,
    ReadyDay,
    ReadyKind,
    ReadyState,
)

MAX_LIST_ROWS = 50
"""The most conversations one list read returns."""

_PRIMARY_KEY = "ready_conversations_pkey"


def conversation_from_row(row: ReadyConversationRow) -> ReadyConversation:
    return ReadyConversation(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        kind=ReadyKind(row.kind),
        instruction=row.instruction,
        instruction_written_by=cast("ChangeSource | None", row.instruction_written_by),
        instruction_edited_by_model=row.instruction_edited_by_model,
        ingredients=tuple(Ingredient(item) for item in row.ingredients),
        cadence=Cadence.model_validate(row.cadence),
        state=ReadyState(row.state),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply(row: ReadyConversationRow, conversation: ReadyConversation) -> None:
    row.title = conversation.title
    row.kind = conversation.kind.value
    row.instruction = conversation.instruction
    row.instruction_written_by = conversation.instruction_written_by
    row.instruction_edited_by_model = conversation.instruction_edited_by_model
    row.ingredients = [item.value for item in conversation.ingredients]
    row.cadence = conversation.cadence.model_dump(mode="json")
    row.state = conversation.state.value
    row.version = conversation.version
    row.updated_at = conversation.updated_at


def day_from_row(row: ReadyConversationDayRow) -> ReadyDay:
    return ReadyDay(
        conversation_id=row.conversation_id,
        day=row.day,
        state=DayState(row.state),
        changed_at=row.changed_at,
        version=row.version,
    )


class ReadyStore:
    """Ready conversations and their days.

    The operations are static and owner-filtered; `SqlReadyStore` adds the transaction boundary,
    idempotency and audit of `StoreBase`.
    """

    @staticmethod
    def get_conversation(
        session: Session, owner_id: UUID, conversation_id: UUID, *, lock: bool = False
    ) -> ReadyConversation:
        statement = select(ReadyConversationRow).where(
            ReadyConversationRow.id == conversation_id, ReadyConversationRow.owner_id == owner_id
        )
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise NotFoundError("ready conversation not found")
        return conversation_from_row(row)

    @staticmethod
    def list_conversations(
        session: Session,
        owner_id: UUID,
        *,
        states: Collection[ReadyState] | None = None,
        limit: int = MAX_LIST_ROWS,
    ) -> list[ReadyConversation]:
        statement = select(ReadyConversationRow).where(ReadyConversationRow.owner_id == owner_id)
        if states is not None:
            statement = statement.where(
                ReadyConversationRow.state.in_([item.value for item in states])
            )
        rows = session.scalars(
            statement.order_by(ReadyConversationRow.created_at, ReadyConversationRow.id).limit(
                validate_limit(limit, maximum=MAX_LIST_ROWS)
            )
        )
        return [conversation_from_row(row) for row in rows]

    @staticmethod
    def count_open_conversations(session: Session, owner_id: UUID) -> int:
        """Active and paused conversations: what the owner's cap counts."""

        return (
            session.scalar(
                select(func.count())
                .select_from(ReadyConversationRow)
                .where(
                    ReadyConversationRow.owner_id == owner_id,
                    ReadyConversationRow.state.in_(
                        [ReadyState.ACTIVE.value, ReadyState.PAUSED.value]
                    ),
                )
            )
            or 0
        )

    @staticmethod
    def save_conversation(
        session: Session, conversation: ReadyConversation, expected_version: int | None = None
    ) -> None:
        """Insert the conversation, or update it when the stored version is `expected_version`."""

        row = session.scalar(
            select(ReadyConversationRow)
            .where(
                ReadyConversationRow.id == conversation.id,
                ReadyConversationRow.owner_id == conversation.owner_id,
            )
            .with_for_update()
        )
        if row is None:
            row = ReadyConversationRow(
                id=conversation.id,
                owner_id=conversation.owner_id,
                created_at=conversation.created_at,
            )
            _apply(row, conversation)
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError as error:
                diag = getattr(error.orig, "diag", None)
                if getattr(diag, "constraint_name", None) == _PRIMARY_KEY:
                    # An id another owner holds answers as a missing row, like any lookup.
                    raise NotFoundError("ready conversation not found") from None
                raise
            return
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale ready conversation version", reason="stale_version")
        _apply(row, conversation)

    @staticmethod
    def get_days(session: Session, owner_id: UUID, day: date) -> dict[UUID, ReadyDay]:
        """The day rows of every conversation of the owner for one day, by conversation."""

        rows = session.scalars(
            select(ReadyConversationDayRow).where(
                ReadyConversationDayRow.owner_id == owner_id, ReadyConversationDayRow.day == day
            )
        )
        return {row.conversation_id: day_from_row(row) for row in rows}

    @staticmethod
    def get_day(
        session: Session, owner_id: UUID, conversation_id: UUID, day: date
    ) -> ReadyDay | None:
        row = session.scalar(
            select(ReadyConversationDayRow).where(
                ReadyConversationDayRow.owner_id == owner_id,
                ReadyConversationDayRow.conversation_id == conversation_id,
                ReadyConversationDayRow.day == day,
            )
        )
        return None if row is None else day_from_row(row)

    @staticmethod
    def save_day(session: Session, owner_id: UUID, value: ReadyDay) -> None:
        """Insert the day row, or move its state. The caller holds the conversation's lock."""

        row = session.scalar(
            select(ReadyConversationDayRow).where(
                ReadyConversationDayRow.owner_id == owner_id,
                ReadyConversationDayRow.conversation_id == value.conversation_id,
                ReadyConversationDayRow.day == value.day,
            )
        )
        if row is None:
            session.add(
                ReadyConversationDayRow(
                    conversation_id=value.conversation_id,
                    day=value.day,
                    owner_id=owner_id,
                    state=value.state.value,
                    changed_at=value.changed_at,
                    version=value.version,
                )
            )
            session.flush()
            return
        row.state = value.state.value
        row.changed_at = value.changed_at
        row.version = value.version

    @staticmethod
    def prune_days(session: Session, owner_id: UUID, before: date) -> int:
        """Delete the owner's day rows older than `before`; returns how many went."""

        outcome = session.execute(
            delete(ReadyConversationDayRow).where(
                ReadyConversationDayRow.owner_id == owner_id,
                ReadyConversationDayRow.day < before,
            )
        )
        return int(getattr(outcome, "rowcount", 0) or 0)


class SqlReadyStore(ReadyStore, StoreBase):
    """The ready conversation operations with the transaction, idempotency and audit of
    `StoreBase`."""

    def __init__(
        self, session_factory: sessionmaker[Session], telemetry: TelemetryPort | None = None
    ) -> None:
        super().__init__(session_factory, telemetry)

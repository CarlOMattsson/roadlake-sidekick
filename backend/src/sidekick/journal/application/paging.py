"""Cursor and range checks shared by the Journal list and day reads."""

from datetime import date
from uuid import UUID

from sidekick.journal.application.models import MAX_JOURNAL_RANGE_DAYS
from sidekick.journal.domain.entry import ENTRY_PAGE_KEY, JournalEntry, entry_page_key
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import Actor, CursorCodec, KeyValue


def decode_cursor(
    codec: CursorCodec, actor_id: UUID, cursor: str | None, query_key: str
) -> tuple[KeyValue, ...] | None:
    try:
        return codec.decode_keyset(actor_id, cursor, query_key, kinds=ENTRY_PAGE_KEY)
    except ValueError as error:
        raise ValidationError("invalid pagination cursor") from error


def entry_cursor(codec: CursorCodec, actor: Actor, last: JournalEntry, query_key: str) -> str:
    """Keyset cursor after the last entry served: it does not shift when entries come and go."""

    return codec.encode_keyset(actor.user_id, entry_page_key(last), query_key)


def validate_list_bounds(start_date: date, end_date: date, limit: int) -> None:
    if end_date < start_date:
        raise ValidationError("end_date cannot precede start_date")
    if (end_date - start_date).days >= MAX_JOURNAL_RANGE_DAYS:
        raise ValidationError("journal range must span at most 366 inclusive days")
    if not 1 <= limit <= 100:
        raise ValidationError("limit must be between 1 and 100")


def journal_list_cursor_key(start_date: date, end_date: date, include_archived: bool) -> str:
    return (
        "journal:entries:v1:"
        f"from={start_date.isoformat()}:to={end_date.isoformat()}:"
        f"archived={str(include_archived).lower()}"
    )


def journal_day_cursor_key(journal_date: date, include_archived: bool) -> str:
    return (
        f"journal:day:v1:date={journal_date.isoformat()}:archived={str(include_archived).lower()}"
    )

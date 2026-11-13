"""Framework-independent Journal entry ordering and lifecycle rules."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal, cast
from uuid import UUID

from sidekick.shared.errors import InvalidInputError

from .source import require_aware


class KeyPointKind(StrEnum):
    FACT = "fact"
    REFLECTION = "reflection"
    DECISION = "decision"
    COMMITMENT = "commitment"
    QUESTION = "question"


@dataclass(frozen=True, slots=True)
class KeyPoint:
    kind: KeyPointKind
    text: str

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.kind), KeyPointKind):
            raise InvalidInputError("unsupported key point kind")
        if (
            not isinstance(cast(object, self.text), str)
            or not self.text.strip()
            or len(self.text) > 2_000
        ):
            raise InvalidInputError("key point text must contain 1 to 2000 nonblank characters")
        object.__setattr__(self, "text", self.text.strip())


@dataclass(frozen=True, slots=True)
class JournalEntry:
    id: UUID
    owner_id: UUID
    source_id: UUID
    journal_date: date
    occurred_at: datetime | None
    source_recorded_at: datetime | None
    title: str
    summary: str | None
    key_points: tuple[KeyPoint, ...]
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    def __post_init__(self) -> None:
        require_aware(self.occurred_at, "occurred_at")
        require_aware(self.source_recorded_at, "source_recorded_at")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        require_aware(self.archived_at, "archived_at")
        if (
            not isinstance(cast(object, self.title), str)
            or not self.title.strip()
            or len(self.title) > 200
        ):
            raise InvalidInputError("title must contain 1 to 200 nonblank characters")
        if self.summary is not None and len(self.summary) > 10_000:
            raise InvalidInputError("summary must contain at most 10000 characters")
        if len(self.key_points) > 50 or not all(
            isinstance(cast(object, point), KeyPoint) for point in self.key_points
        ):
            raise InvalidInputError("key_points must contain at most 50 KeyPoint values")
        if self.version < 1:
            raise InvalidInputError("version must be positive")
        if self.updated_at < self.created_at:
            raise InvalidInputError("updated_at cannot precede created_at")
        if self.archived_at is not None and self.archived_at < self.created_at:
            raise InvalidInputError("archived_at cannot precede created_at")
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "key_points", tuple(self.key_points))


@dataclass(frozen=True, slots=True)
class EntryHead:
    """What the day's ordering and fingerprint need of an entry: no title, text or key points."""

    id: UUID
    version: int
    occurred_at: datetime | None
    source_recorded_at: datetime | None
    created_at: datetime
    archived_at: datetime | None = None


def entry_order_key(entry: JournalEntry | EntryHead) -> tuple[datetime, int, int]:
    """Order by occurrence, recorded, creation fallback, then stable identifier."""

    if entry.occurred_at is not None:
        effective_at, fallback_rank = entry.occurred_at, 0
    elif entry.source_recorded_at is not None:
        effective_at, fallback_rank = entry.source_recorded_at, 1
    else:
        effective_at, fallback_rank = entry.created_at, 2
    return effective_at.astimezone(UTC), fallback_rank, entry.id.int


JournalOrder = Literal["asc", "desc"]
"""Direction of a journal list: day order, or its exact reverse for the timed entries."""

NO_OCCURRENCE = datetime(9999, 12, 31, tzinfo=UTC)
NO_OCCURRENCE_DESC = datetime(1, 1, 1, tzinfo=UTC)


def no_occurrence(order: JournalOrder) -> datetime:
    """Stands for "no time at all" in the page key: such an entry sorts after every dated one.

    The stand-in is the latest instant when ascending and the earliest when descending, so an
    entry without a time is last in both directions.
    """

    return NO_OCCURRENCE_DESC if order == "desc" else NO_OCCURRENCE


ENTRY_PAGE_KEY = (datetime, int, datetime, UUID)
"""Kinds of `entry_page_key`: (effective time, fallback rank, created_at, id)."""


def entry_page_key(
    entry: JournalEntry, order: JournalOrder = "asc"
) -> tuple[datetime, int, datetime, UUID]:
    """The sort position of an entry in a journal list; the next page starts strictly after it.

    Mirrors the persistence ORDER BY: occurrence, else recorded time, else last; then creation
    time and the id as unique tiebreak. It does not move when entries are added or removed.
    """

    if entry.occurred_at is not None:
        effective_at, rank = entry.occurred_at, 0
    elif entry.source_recorded_at is not None:
        effective_at, rank = entry.source_recorded_at, 1
    else:
        effective_at, rank = no_occurrence(order), 2
    return effective_at, rank, entry.created_at, entry.id


def _require_transition(entry: JournalEntry, expected_version: int, changed_at: datetime) -> None:
    require_aware(changed_at, "changed_at")
    if expected_version != entry.version:
        raise InvalidInputError("stale entry version")
    if changed_at < entry.updated_at:
        raise InvalidInputError("changed_at cannot precede the current update time")


def update_entry(
    entry: JournalEntry,
    *,
    expected_version: int,
    title: str,
    summary: str | None,
    key_points: tuple[KeyPoint, ...],
    changed_at: datetime,
) -> JournalEntry:
    """Update mutable content while preserving source and authoritative date."""

    _require_transition(entry, expected_version, changed_at)
    if entry.archived_at is not None:
        raise InvalidInputError("an archived entry must be restored before update")
    return replace(
        entry,
        title=title,
        summary=summary,
        key_points=tuple(key_points),
        version=entry.version + 1,
        updated_at=changed_at,
    )


def relink_entry(
    entry: JournalEntry, *, expected_version: int, changed_at: datetime
) -> JournalEntry:
    """Version an entry whose relations changed; its content stays as it is."""

    _require_transition(entry, expected_version, changed_at)
    if entry.archived_at is not None:
        raise InvalidInputError("an archived entry must be restored before update")
    return replace(entry, version=entry.version + 1, updated_at=changed_at)


def append_to_entry(
    entry: JournalEntry,
    *,
    expected_version: int,
    title: str | None,
    summary: str | None,
    append_key_points: tuple[KeyPoint, ...],
    source_id: UUID | None,
    changed_at: datetime,
) -> JournalEntry:
    """Add key points after the existing ones and optionally move to a replacement source.

    A `None` title or summary keeps the current one. `source_id` is the id of a source that
    replaces the entry's current source (the existing replacement model keeps the old row as
    provenance); `None` keeps the current source.
    """

    _require_transition(entry, expected_version, changed_at)
    if entry.archived_at is not None:
        raise InvalidInputError("an archived entry must be restored before update")
    return replace(
        entry,
        title=entry.title if title is None else title,
        summary=entry.summary if summary is None else summary,
        key_points=entry.key_points + tuple(append_key_points),
        source_id=entry.source_id if source_id is None else source_id,
        version=entry.version + 1,
        updated_at=changed_at,
    )


def archive_entry(
    entry: JournalEntry,
    *,
    expected_version: int,
    changed_at: datetime,
) -> JournalEntry:
    _require_transition(entry, expected_version, changed_at)
    if entry.archived_at is not None:
        raise InvalidInputError("entry is already archived")
    return replace(
        entry,
        archived_at=changed_at,
        version=entry.version + 1,
        updated_at=changed_at,
    )


def restore_entry(
    entry: JournalEntry,
    *,
    expected_version: int,
    changed_at: datetime,
) -> JournalEntry:
    _require_transition(entry, expected_version, changed_at)
    if entry.archived_at is None:
        raise InvalidInputError("entry is not archived")
    return replace(
        entry,
        archived_at=None,
        version=entry.version + 1,
        updated_at=changed_at,
    )

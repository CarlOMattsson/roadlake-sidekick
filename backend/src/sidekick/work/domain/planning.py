"""Framework-free Work planning vocabulary: cadence, estimates, waiting, and tags.

Every rule here is a pure function of stored values and an explicit `now`. Nothing
in this module writes, schedules, or reacts to a passing timestamp: earliest start,
follow-up, and review cadence are read by derivation only.
"""

import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.shared.types import UNSET, UnsetType

MAX_ESTIMATED_MINUTES = 12_000
"""One working month. An estimate above this is a plan, not an estimate."""

ESTIMATE_PRESETS: tuple[int, ...] = (5, 15, 30, 60, 120, 240)
"""Approximate interface shortcuts. Storage is always whole minutes."""

MAX_TAGS_PER_RECORD = 10
MAX_TAG_LABEL_LENGTH = 40
MAX_TAG_SLUG_LENGTH = 60
MAX_TAG_FILTER_VALUES = 5
MAX_DEFINITION_OF_DONE_LENGTH = 2_000
MAX_STEP_INSTRUCTION_LENGTH = 2_000
MAX_ACTION_NOTE_LENGTH = 500


@dataclass(frozen=True, slots=True)
class EstimateTotals:
    """A server-computed estimate summary for one explicitly bounded Task set."""

    scope: str
    task_count: int
    estimated_minutes_total: int
    overdue_minutes: int
    unestimated_count: int
    calculated_at: datetime

    def to_data(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "task_count": self.task_count,
            "estimated_minutes_total": self.estimated_minutes_total,
            "overdue_minutes": self.overdue_minutes,
            "unestimated_count": self.unestimated_count,
            "calculated_at": self.calculated_at,
        }


TAG_MATCH_MODES = frozenset({"any", "all"})


class Cadence(StrEnum):
    """Declared rhythm, shared by Domain review cadence and Process run cadence."""

    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

    @property
    def interval(self) -> timedelta:
        """Fixed documented interval, so derivation needs no calendar library."""

        return timedelta(days=_CADENCE_DAYS[self])


_CADENCE_DAYS: dict[Cadence, int] = {
    Cadence.DAILY: 1,
    Cadence.WEEKLY: 7,
    Cadence.BIWEEKLY: 14,
    Cadence.MONTHLY: 30,
    Cadence.QUARTERLY: 90,
    Cadence.YEARLY: 365,
}


def parse_cadence(value: str | Cadence | None) -> Cadence | None:
    if value is None or isinstance(value, Cadence):
        return value
    try:
        return Cadence(value)
    except ValueError as error:
        raise ValidationError("unsupported cadence value") from error


def validate_estimated_minutes(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValidationError("estimate must be whole minutes")
    if value <= 0 or value > MAX_ESTIMATED_MINUTES:
        raise ValidationError(f"estimate must be between 1 and {MAX_ESTIMATED_MINUTES} minutes")
    return value


def is_actionable_now(earliest_start: datetime | None, now: datetime) -> bool:
    """True when nothing schedules the record for later."""

    return earliest_start is None or earliest_start <= now


def is_review_due(
    *,
    review_cadence: Cadence | None,
    last_reviewed_at: datetime | None,
    archived: bool,
    now: datetime,
) -> bool:
    """A Domain with a declared cadence whose review interval has elapsed.

    No cadence means no reason. A missing last review counts as due, so the first
    review is not silently skipped. Archived records never demand attention.
    """

    if review_cadence is None or archived:
        return False
    if last_reviewed_at is None:
        return True
    return last_reviewed_at + review_cadence.interval <= now


def normalize_tag_slug(value: str) -> str:
    """Lowercase, NFC-normalize, trim, and collapse internal whitespace to `-`."""

    normalized = unicodedata.normalize("NFC", value).strip().casefold()
    slug = "-".join(part for part in normalized.split() if part)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    if not slug:
        raise ValidationError("tag must contain at least one visible character")
    if len(slug) > MAX_TAG_SLUG_LENGTH:
        raise ValidationError(f"tag is longer than {MAX_TAG_SLUG_LENGTH} characters")
    return slug


def validate_tag_label(value: str) -> str:
    label = unicodedata.normalize("NFC", value).strip()
    if not label:
        raise ValidationError("tag label must contain at least one visible character")
    if len(label) > MAX_TAG_LABEL_LENGTH:
        raise ValidationError(f"tag label must be at most {MAX_TAG_LABEL_LENGTH} characters")
    return label


def normalize_tag_selection(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Normalize an intended tag set for one record: deduplicated and bounded."""

    slugs: list[str] = []
    for value in values:
        slug = normalize_tag_slug(value)
        if slug not in slugs:
            slugs.append(slug)
    if len(slugs) > MAX_TAGS_PER_RECORD:
        raise ValidationError(f"at most {MAX_TAGS_PER_RECORD} tags per record")
    return tuple(slugs)


def normalize_tag_filter(
    values: list[str] | tuple[str, ...] | None, match: str = "any"
) -> tuple[tuple[str, ...], str]:
    """Normalize a bounded projection tag filter and its explicit match mode."""

    if match not in TAG_MATCH_MODES:
        raise ValidationError("invalid tag match mode")
    if not values:
        return (), match
    slugs: list[str] = []
    for value in values:
        slug = normalize_tag_slug(value)
        if slug not in slugs:
            slugs.append(slug)
    if len(slugs) > MAX_TAG_FILTER_VALUES:
        raise ValidationError(f"at most {MAX_TAG_FILTER_VALUES} tags per query")
    return tuple(slugs), match


def matches_tag_filter(
    record_slugs: tuple[str, ...] | frozenset[str],
    wanted: tuple[str, ...],
    match: str,
) -> bool:
    if not wanted:
        return True
    present = frozenset(record_slugs)
    if match == "all":
        return set(wanted) <= present
    return any(slug in present for slug in wanted)


def validate_waiting(
    *,
    waiting_since: datetime | None,
    follow_up_at: datetime | None,
    waiting_on_contact_id: UUID | None,
) -> None:
    """Follow-up time and waiting Contact exist only while the Task is waiting."""

    if waiting_since is None and (follow_up_at is not None or waiting_on_contact_id is not None):
        raise ValidationError("follow-up time and waiting contact require a waiting state")


def is_waiting(*, waiting_since: datetime | None, completed: bool) -> bool:
    return waiting_since is not None and not completed


def is_follow_up_due(
    *, waiting_since: datetime | None, follow_up_at: datetime | None, completed: bool, now: datetime
) -> bool:
    if not is_waiting(waiting_since=waiting_since, completed=completed):
        return False
    return follow_up_at is not None and follow_up_at <= now


@dataclass(frozen=True, slots=True)
class WorkTag:
    """One owner-scoped vocabulary entry: normalized `slug`, owner-written `label`."""

    id: UUID
    owner_id: UUID
    slug: str
    label: str
    created_at: datetime
    updated_at: datetime
    version: int = 1
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", validate_tag_label(self.label))
        object.__setattr__(self, "slug", normalize_tag_slug(self.slug))
        if self.version < 1:
            raise ValidationError("tag version must be positive")

    @property
    def archived(self) -> bool:
        return self.archived_at is not None

    def rename(self, *, now: datetime, label: str) -> "WorkTag":
        """Change the visible label and its matching slug in one step."""

        next_label = validate_tag_label(label)
        return replace(
            self,
            label=next_label,
            slug=normalize_tag_slug(next_label),
            updated_at=now,
            version=self.version + 1,
        )

    def archive(self, *, now: datetime) -> "WorkTag":
        if self.archived_at is not None:
            return self
        return replace(self, archived_at=now, updated_at=now, version=self.version + 1)

    def restore(self, *, now: datetime) -> "WorkTag":
        if self.archived_at is None:
            return self
        return replace(self, archived_at=None, updated_at=now, version=self.version + 1)

    def update(
        self, *, now: datetime, label: str | UnsetType = UNSET
    ) -> "WorkTag":  # pragma: no cover - convenience wrapper
        if label is UNSET:
            raise ValidationError("at least one tag change is required")
        return self.rename(now=now, label=label)

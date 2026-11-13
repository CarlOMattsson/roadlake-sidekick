"""Commands and queries of the Work context use cases."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Any, get_args
from uuid import UUID

from sidekick.shared.cadence import Cadence
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import UNSET, UnsetType, validate_limit
from sidekick.tasks.domain.planning import validate_estimated_minutes
from sidekick.work.domain import DomainStatus, ProcessStatus
from sidekick.work.domain.planning import normalize_tag_filter
from sidekick.work.listing import (
    AgendaGroup,
    WorkActionable,
    WorkArchive,
    WorkAttention,
    WorkEstimate,
    WorkGroup,
    WorkKind,
    WorkSort,
    WorkTagMatch,
    WorkWaiting,
)


@dataclass(frozen=True, slots=True)
class UpdateContextCommand:
    """Mutable Domain/Process fields. `tags` is the record's intended tag set."""

    name: str | UnsetType = UNSET
    description: str | None | UnsetType = UNSET
    status: DomainStatus | ProcessStatus | UnsetType = UNSET
    domain_id: UUID | UnsetType = UNSET
    review_cadence: Cadence | None | UnsetType = UNSET
    last_reviewed_at: datetime | None | UnsetType = UNSET
    cadence: Cadence | None | UnsetType = UNSET
    accent: str | None | UnsetType = UNSET
    tags: tuple[str, ...] | UnsetType = UNSET

    def changes(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "name": self.name,
                "description": self.description,
                "status": self.status,
                "domain_id": self.domain_id,
                "review_cadence": self.review_cadence,
                "last_reviewed_at": self.last_reviewed_at,
                "cadence": self.cadence,
                "accent": self.accent,
                "tags": self.tags,
            }.items()
            if value is not UNSET
        }

    def entity_changes(self, kind: str) -> dict[str, Any]:
        """Only the fields that exist for this kind; tags are applied separately."""

        allowed = {
            "domain": {
                "name",
                "description",
                "status",
                "review_cadence",
                "last_reviewed_at",
                "accent",
            },
            "process": {"name", "description", "status", "domain_id", "cadence"},
        }[kind]
        changes = self.changes()
        unsupported = set(changes) - allowed - {"tags"}
        if unsupported:
            raise ValidationError(f"unsupported {kind} planning field")
        return {key: value for key, value in changes.items() if key in allowed}


def _require(value: str, vocabulary: object, message: str) -> None:
    """Reject a filter value outside its closed vocabulary (callers may pass any string)."""

    if value not in get_args(vocabulary):
        raise ValidationError(message)


@dataclass(frozen=True, slots=True)
class WorkQuery:
    """Closed, bounded projection inputs shared by Work read models."""

    q: str | None = None
    status: str | None = None
    priority: str | None = None
    due_from: datetime | None = None
    due_to: datetime | None = None
    attention: WorkAttention = "all"
    archive: WorkArchive = "active"
    kind: WorkKind = "all"
    sort: WorkSort = "updated_desc"
    group: WorkGroup = "none"
    limit: int = 100
    cursor: str | None = None
    tags: tuple[str, ...] = ()
    """Bounded, deduplicated tag slugs. Empty means no tag filter."""
    tag_match: WorkTagMatch = "any"
    actionable: WorkActionable = "all"
    waiting: WorkWaiting = "all"
    estimate: WorkEstimate = "all"
    project_id: UUID | None = None
    """Only Tasks of this Project; Projects and other kinds never match. None means no filter."""
    max_minutes: int | None = None
    """Only records estimated at this many minutes or fewer; unestimated records never match."""
    include_undated: bool = False
    """Agenda only: also list open, actionable Tasks without a due date (grouped as upcoming)."""

    def validate(self) -> "WorkQuery":
        validate_limit(
            self.limit,
            maximum=100,
            message="Work page size must be between 1 and 100",
            error=ValidationError,
        )
        _require(self.attention, WorkAttention, "invalid Work attention filter")
        _require(self.archive, WorkArchive, "invalid Work archive filter")
        _require(self.kind, WorkKind, "invalid Work kind filter")
        _require(self.sort, WorkSort, "invalid Work sort")
        _require(self.group, WorkGroup, "invalid Work grouping")
        if self.q is not None and len(self.q) > 200:
            raise ValidationError("Work text query is too long")
        _require(self.actionable, WorkActionable, "invalid Work actionable filter")
        _require(self.waiting, WorkWaiting, "invalid Work waiting filter")
        _require(self.estimate, WorkEstimate, "invalid Work estimate filter")
        if self.max_minutes is not None:
            validate_estimated_minutes(self.max_minutes)
        normalize_tag_filter(list(self.tags), self.tag_match)
        return self

    def normalized_tags(self) -> tuple[tuple[str, ...], str]:
        return normalize_tag_filter(list(self.tags), self.tag_match)

    def key(self) -> str:
        tags, tag_match = self.normalized_tags()
        return json.dumps(
            {
                "q": self.q,
                "status": self.status,
                "priority": self.priority,
                "due_from": self.due_from.isoformat() if self.due_from else None,
                "due_to": self.due_to.isoformat() if self.due_to else None,
                "attention": self.attention,
                "archive": self.archive,
                "kind": self.kind,
                "sort": self.sort,
                "group": self.group,
                "limit": self.limit,
                "tags": list(tags),
                "tag_match": tag_match,
                "actionable": self.actionable,
                "waiting": self.waiting,
                "estimate": self.estimate,
                "project_id": str(self.project_id) if self.project_id else None,
                "max_minutes": self.max_minutes,
                "include_undated": self.include_undated,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkRow:
    """One Work record as a list, agenda, Today or board row.

    Every kind carries every field, so one filter reads all kinds the same way; the defaults are
    what a kind without the field shows. `project_title` is only set on a Task that belongs to a
    Project. `agenda_group` is only set by the agenda and Today. Times stay aware datetimes and
    ids stay UUIDs: `to_data` is the one place a row becomes a plain mapping, for the transports.
    """

    kind: str
    id: UUID
    parent_id: UUID | None
    title: str
    status: str
    version: int
    priority: str | None = None
    due_at: datetime | None = None
    attention_requested: bool = False
    archived: bool = False
    agenda_group: AgendaGroup | None = None
    domain_id: UUID | None = None
    process_id: UUID | None = None
    project_id: UUID | None = None
    project_title: str | None = None
    domain_accent: str | None = None
    task_id: UUID | None = None
    earliest_start: datetime | None = None
    actionable_now: bool = True
    estimated_minutes: int | None = None
    waiting: bool = False
    waiting_since: datetime | None = None
    follow_up_at: datetime | None = None
    waiting_on_contact_id: UUID | None = None
    follow_up_due: bool = False
    blocked_reminder_due: bool = False
    blocked_reminder_cadence: str | None = None
    blocked_reminder_snoozed_until: datetime | None = None
    recurrence: Mapping[str, object] | None = None
    last_completed_at: datetime | None = None
    review_due: bool = False
    review_cadence: str | None = None
    cadence: str | None = None
    tags: tuple[str, ...] = ()

    def to_data(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True, slots=True, kw_only=True)
class HierarchyNode:
    """One node of the Work hierarchy: a Domain, a Process or a Project.

    `accent` is the Domain's colour and stays None on the other kinds. `to_data` is the one place
    a node becomes a plain mapping, for the transports.
    """

    kind: str
    id: UUID
    parent_id: UUID | None
    title: str
    status: str
    version: int
    accent: str | None = None

    def to_data(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class WorkToday:
    """Arbetes Idag: one page of the overdue and today agenda groups, and the whole selection's
    counts. `day` is the owner's calendar day at `calculated_at`."""

    items: list[WorkRow]
    next_cursor: str | None
    total: int
    overdue_total: int
    today_total: int
    day: date
    calculated_at: datetime

"""The automation report: what the owner's automations did in a window, as counts and a few cards.

The window is `(since, until]`. By default it starts where the owner last marked the report as
seen; before the first time it covers the last week. Everything here is a plain value: counts, ids,
closed codes and two pieces of text, the title of an automation (the owner's own) and the summary a
run wrote about itself (written by an AI, untrusted). Nothing a run read or proposed is in a report,
so a renderer has no instruction to pass on, and the summary is the only text it must label.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import islice
from uuid import UUID

from sidekick.automations.domain.automation import ReportCursor
from sidekick.automations.domain.spec import AutomationState, ModelTier
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import validate_limit

FIRST_LOOK_DAYS = 7
"""How far back the report reaches before the owner has marked it as seen once."""
MAX_WINDOW = timedelta(days=366)
MAX_HIGHLIGHTS = 10
DEFAULT_HIGHLIGHTS = 5
MAX_REPORT_AUTOMATIONS = 50
"""Rows listed in one report; the totals always cover every automation."""


class WindowBasis(StrEnum):
    LAST_SEEN = "last_seen"
    FIRST_LOOK = "first_look"
    GIVEN = "given"


@dataclass(frozen=True, slots=True)
class ReportWindow:
    since: datetime
    until: datetime
    basis: WindowBasis


def resolve_window(
    *, since: datetime | None, cursor: ReportCursor | None, now: datetime
) -> ReportWindow:
    """The window to report: from `since`, else from the last time seen, up to `now`."""

    if since is not None:
        if since.tzinfo is None:
            raise ValidationError("since needs a time zone")
        if since >= now:
            raise ValidationError("since must be in the past")
        if now - since > MAX_WINDOW:
            raise ValidationError("since reaches back more than a year")
        return ReportWindow(since, now, WindowBasis.GIVEN)
    if cursor is None:
        return ReportWindow(now - timedelta(days=FIRST_LOOK_DAYS), now, WindowBasis.FIRST_LOOK)
    since = max(min(cursor.seen_until, now), now - MAX_WINDOW)
    return ReportWindow(since, now, WindowBasis.LAST_SEEN)


def next_cursor(
    current: ReportCursor | None, *, owner_id: UUID, seen_until: datetime, now: datetime
) -> ReportCursor:
    """The cursor after the owner has seen the report up to `seen_until`.

    It never moves backwards and never into the future: a report cannot have been seen before it
    was made.
    """

    if seen_until.tzinfo is None:
        raise ValidationError("seen_until needs a time zone")
    if seen_until > now:
        raise ValidationError("seen_until is in the future")
    if current is not None and seen_until < current.seen_until:
        raise ValidationError("seen_until is before the time already marked as seen")
    return ReportCursor(
        owner_id=owner_id,
        seen_until=seen_until,
        version=current.version + 1 if current else 1,
        updated_at=now,
    )


@dataclass(frozen=True, slots=True)
class ReportRow:
    """One automation's activity in the window."""

    automation_id: UUID
    title: str
    state: AutomationState
    model_tier: ModelTier
    runs: int
    ok_runs: int
    failed_runs: int
    suggestions_created: int
    applied: int
    dismissed: int
    flagged: int
    auto_applied: int
    pending: int
    """Suggestions that wait for a decision now, whenever they were made."""
    cost_microusd: int


@dataclass(frozen=True, slots=True)
class ReportTotals:
    automations: int
    runs: int
    ok_runs: int
    failed_runs: int
    suggestions_created: int
    applied: int
    dismissed: int
    flagged: int
    auto_applied: int
    pending: int
    cost_microusd: int


def totals_of(rows: Iterable[ReportRow]) -> ReportTotals:
    items = list(rows)
    return ReportTotals(
        automations=len(items),
        runs=sum(row.runs for row in items),
        ok_runs=sum(row.ok_runs for row in items),
        failed_runs=sum(row.failed_runs for row in items),
        suggestions_created=sum(row.suggestions_created for row in items),
        applied=sum(row.applied for row in items),
        dismissed=sum(row.dismissed for row in items),
        flagged=sum(row.flagged for row in items),
        auto_applied=sum(row.auto_applied for row in items),
        pending=sum(row.pending for row in items),
        cost_microusd=sum(row.cost_microusd for row in items),
    )


def ranked(rows: Iterable[ReportRow]) -> list[ReportRow]:
    """What needs a look first: failures, then what waits, then the busiest, then by title."""

    return sorted(
        rows,
        key=lambda row: (-row.failed_runs, -row.pending, -row.runs, row.title.casefold()),
    )


class HighlightKind(StrEnum):
    """Why a card is in the report, in the order it is worth a look."""

    RUN_FAILED = "run_failed"
    SUGGESTION_FLAGGED = "suggestion_flagged"
    SUGGESTION_AUTO_APPLIED = "suggestion_auto_applied"


_PRIORITY = {kind: place for place, kind in enumerate(HighlightKind)}


@dataclass(frozen=True, slots=True)
class Highlight:
    """One thing worth a look. It names a run or a suggestion by id and carries closed codes."""

    kind: HighlightKind
    automation_id: UUID
    automation_title: str
    at: datetime
    run_id: UUID | None = None
    suggestion_id: UUID | None = None
    effect: str | None = None
    outcome: str | None = None
    """A run's outcome code."""
    flags: tuple[str, ...] = ()
    verdict: str | None = None
    summary: str | None = None
    """The summary a failed run wrote about itself: written by an AI, untrusted."""


def select_highlights(candidates: Iterable[Highlight], limit: int) -> list[Highlight]:
    """The first `limit`: failed runs, then flagged cards, then auto-applied ones, newest first."""

    validate_limit(limit, maximum=MAX_HIGHLIGHTS)
    ordered = sorted(candidates, key=lambda item: (_PRIORITY[item.kind], -item.at.timestamp()))
    return list(islice(ordered, limit))


@dataclass(frozen=True, slots=True)
class AutomationReport:
    window: ReportWindow
    rows: Sequence[ReportRow]
    omitted_automations: int
    totals: ReportTotals
    highlights: Sequence[Highlight]
    version: int
    """The version of the report cursor the window was read against; 0 before the first mark."""

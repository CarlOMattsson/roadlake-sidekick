"""The report's pure rules: which window it covers, how the mark moves, what is ranked first.

No database and no framework: a window and a mark are plain values and a clock is a datetime.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from sidekick.automations.domain.automation import ReportCursor
from sidekick.automations.domain.report import (
    FIRST_LOOK_DAYS,
    MAX_HIGHLIGHTS,
    MAX_WINDOW,
    Highlight,
    HighlightKind,
    ReportRow,
    WindowBasis,
    next_cursor,
    ranked,
    resolve_window,
    select_highlights,
    totals_of,
)
from sidekick.automations.domain.spec import AutomationState, ModelTier
from sidekick.shared.errors import InvalidInputError, ValidationError

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
OWNER = UUID("00000000-0000-7000-8000-000000000001")


def _cursor(seen: datetime, version: int = 1) -> ReportCursor:
    return ReportCursor(OWNER, seen, version, seen)


def _row(title: str = "Mail", **counts: int) -> ReportRow:
    values = {
        "runs": 0,
        "ok_runs": 0,
        "failed_runs": 0,
        "suggestions_created": 0,
        "applied": 0,
        "dismissed": 0,
        "flagged": 0,
        "auto_applied": 0,
        "pending": 0,
        "cost_microusd": 0,
        **counts,
    }
    return ReportRow(uuid4(), title, AutomationState.ACTIVE, ModelTier.STANDARD, **values)


def _highlight(kind: HighlightKind, at: datetime) -> Highlight:
    return Highlight(kind, uuid4(), "Mail", at)


def test_the_window_starts_where_the_owner_last_looked() -> None:
    seen = NOW - timedelta(hours=5)

    window = resolve_window(since=None, cursor=_cursor(seen), now=NOW)

    assert (window.since, window.until, window.basis) == (seen, NOW, WindowBasis.LAST_SEEN)


def test_before_the_first_look_the_window_covers_the_last_week() -> None:
    window = resolve_window(since=None, cursor=None, now=NOW)

    assert window.since == NOW - timedelta(days=FIRST_LOOK_DAYS)
    assert window.basis is WindowBasis.FIRST_LOOK


def test_a_given_time_wins_over_the_mark() -> None:
    since = NOW - timedelta(days=2)

    window = resolve_window(since=since, cursor=_cursor(NOW - timedelta(hours=1)), now=NOW)

    assert (window.since, window.basis) == (since, WindowBasis.GIVEN)


@pytest.mark.parametrize(
    "since",
    [
        datetime(2026, 11, 20, 9, 0),  # no time zone
        NOW,  # not in the past
        NOW + timedelta(hours=1),
        NOW - MAX_WINDOW - timedelta(seconds=1),
    ],
)
def test_a_given_time_that_makes_no_window_is_refused(since: datetime) -> None:
    with pytest.raises(ValidationError):
        resolve_window(since=since, cursor=None, now=NOW)


def test_a_mark_in_the_future_never_starts_a_window_after_now() -> None:
    window = resolve_window(since=None, cursor=_cursor(NOW + timedelta(hours=1)), now=NOW)

    assert window.since == NOW


def test_a_mark_older_than_a_year_does_not_widen_the_window_beyond_it() -> None:
    window = resolve_window(since=None, cursor=_cursor(NOW - timedelta(days=900)), now=NOW)

    assert (window.since, window.basis) == (NOW - MAX_WINDOW, WindowBasis.LAST_SEEN)


def test_the_first_mark_makes_version_one_and_each_next_one_raises_it() -> None:
    first = next_cursor(None, owner_id=OWNER, seen_until=NOW - timedelta(hours=1), now=NOW)
    second = next_cursor(first, owner_id=OWNER, seen_until=NOW, now=NOW)

    assert (first.version, second.version) == (1, 2)
    assert second.seen_until == NOW
    assert second.updated_at == NOW


def test_the_mark_can_stay_where_it_is_but_never_move_back_or_into_the_future() -> None:
    current = _cursor(NOW - timedelta(hours=2))

    same = next_cursor(current, owner_id=OWNER, seen_until=current.seen_until, now=NOW)
    assert same.seen_until == current.seen_until

    with pytest.raises(ValidationError):
        next_cursor(current, owner_id=OWNER, seen_until=NOW - timedelta(hours=3), now=NOW)
    with pytest.raises(ValidationError):
        next_cursor(current, owner_id=OWNER, seen_until=NOW + timedelta(seconds=1), now=NOW)
    with pytest.raises(ValidationError):
        next_cursor(None, owner_id=OWNER, seen_until=datetime(2026, 11, 23, 8, 0), now=NOW)


def test_failures_come_first_then_what_waits_then_the_busiest() -> None:
    quiet = _row("Quiet", runs=1)
    busy = _row("Busy", runs=9)
    waiting = _row("Waiting", runs=1, pending=4)
    failing = _row("Failing", runs=1, failed_runs=1)

    assert [row.title for row in ranked([quiet, busy, waiting, failing])] == [
        "Failing",
        "Waiting",
        "Busy",
        "Quiet",
    ]


def test_the_totals_cover_every_row() -> None:
    totals = totals_of(
        [
            _row(runs=2, ok_runs=1, failed_runs=1, pending=3, cost_microusd=1_500),
            _row(runs=1, ok_runs=1, flagged=2, auto_applied=1, cost_microusd=500),
        ]
    )

    assert (totals.automations, totals.runs, totals.ok_runs, totals.failed_runs) == (2, 3, 2, 1)
    assert (totals.pending, totals.flagged, totals.auto_applied) == (3, 2, 1)
    assert totals.cost_microusd == 2_000


def test_highlights_rank_by_kind_then_newest_first_and_stop_at_the_limit() -> None:
    old_failure = _highlight(HighlightKind.RUN_FAILED, NOW - timedelta(hours=9))
    new_failure = _highlight(HighlightKind.RUN_FAILED, NOW - timedelta(hours=1))
    flagged = _highlight(HighlightKind.SUGGESTION_FLAGGED, NOW)
    automatic = _highlight(HighlightKind.SUGGESTION_AUTO_APPLIED, NOW)

    chosen = select_highlights([automatic, flagged, old_failure, new_failure], 3)

    assert chosen == [new_failure, old_failure, flagged]


@pytest.mark.parametrize("limit", [0, MAX_HIGHLIGHTS + 1])
def test_a_limit_outside_the_range_is_refused(limit: int) -> None:
    with pytest.raises(InvalidInputError):
        select_highlights([], limit)

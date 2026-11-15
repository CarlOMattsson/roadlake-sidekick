"""The review buckets: which open Tasks a review brings up, why, and at which boundaries."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from sidekick.tasks.domain import Priority, Task, TaskStatus
from sidekick.tasks.domain.review import (
    BUCKET_ORDER,
    LONG_OVERDUE_AFTER,
    REVIEW_INTERVAL,
    ReviewBucket,
    ReviewFinding,
    is_review_due,
    review_finding,
)

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
RECENT = NOW - timedelta(days=1)


def _task(**changes: Any) -> Task:
    task = Task(
        id=UUID(int=1),
        owner_id=UUID(int=2),
        project_id=None,
        title="Rensa förrådet",
        description=None,
        status=TaskStatus.TODO,
        priority=Priority.NORMAL,
        due_at=None,
        completed_at=None,
        created_at=RECENT,
        updated_at=RECENT,
    )
    return replace(task, **changes)


def _finding(task: Task, steps_done: int = 0, steps_total: int = 0) -> ReviewFinding:
    return review_finding(task, steps_done=steps_done, steps_total=steps_total, now=NOW)


def test_the_buckets_are_served_in_the_planned_order() -> None:
    assert [bucket.value for bucket in BUCKET_ORDER] == [
        "likely_done",
        "long_overdue",
        "follow_up_due",
        "overdue",
        "other",
    ]
    assert ReviewFinding(ReviewBucket.LIKELY_DONE).rank < ReviewFinding(ReviewBucket.OTHER).rank


def test_all_steps_done_is_likely_done_before_any_other_reason() -> None:
    overdue = _task(due_at=NOW - timedelta(days=40), updated_at=NOW - timedelta(days=90))

    assert _finding(overdue, steps_done=3, steps_total=3) == ReviewFinding(ReviewBucket.LIKELY_DONE)
    # Some Steps left, or no Steps at all, is not "likely done".
    assert _finding(overdue, steps_done=2, steps_total=3).bucket is ReviewBucket.LONG_OVERDUE
    assert _finding(overdue).bucket is ReviewBucket.LONG_OVERDUE


@pytest.mark.parametrize(
    ("age", "bucket"),
    [
        (LONG_OVERDUE_AFTER + timedelta(seconds=1), ReviewBucket.LONG_OVERDUE),
        # Exactly 14 days is still "overdue": long overdue is *more* than 14 days.
        (LONG_OVERDUE_AFTER, ReviewBucket.OVERDUE),
        (timedelta(seconds=1), ReviewBucket.OVERDUE),
        # Due right now has not passed yet.
        (timedelta(0), ReviewBucket.OTHER),
        (-timedelta(days=3), ReviewBucket.OTHER),
    ],
)
def test_overdue_and_long_overdue_split_at_fourteen_days(
    age: timedelta, bucket: ReviewBucket
) -> None:
    due = NOW - age
    finding = _finding(_task(due_at=due))

    assert finding.bucket is bucket
    if bucket in (ReviewBucket.LONG_OVERDUE, ReviewBucket.OVERDUE):
        assert finding.since == due


def test_a_passed_follow_up_ranks_after_long_overdue_and_before_overdue() -> None:
    follow_up = NOW - timedelta(days=2)
    waiting = _task(waiting_since=NOW - timedelta(days=10), follow_up_at=follow_up)

    assert _finding(waiting) == ReviewFinding(ReviewBucket.FOLLOW_UP_DUE, follow_up)
    assert _finding(replace(waiting, due_at=NOW - timedelta(days=3))).bucket is (
        ReviewBucket.FOLLOW_UP_DUE
    )
    assert _finding(replace(waiting, due_at=NOW - timedelta(days=30))).bucket is (
        ReviewBucket.LONG_OVERDUE
    )
    # A follow-up still ahead is not due; one reached right now is.
    assert _finding(replace(waiting, follow_up_at=NOW + timedelta(hours=1))).bucket is (
        ReviewBucket.OTHER
    )
    assert _finding(replace(waiting, follow_up_at=NOW)).bucket is ReviewBucket.FOLLOW_UP_DUE


def test_an_old_task_without_any_other_reason_is_other_never_stale() -> None:
    old = NOW - timedelta(days=400)

    assert _finding(_task(updated_at=old, created_at=old)) == ReviewFinding(ReviewBucket.OTHER)
    future = _task(updated_at=old, created_at=old, due_at=NOW + timedelta(days=30))
    assert _finding(future) == ReviewFinding(ReviewBucket.OTHER)
    assert "stale" not in {bucket.value for bucket in ReviewBucket}


def test_only_open_unarchived_tasks_not_reviewed_this_week_are_due() -> None:
    assert is_review_due(_task(), now=NOW)
    for status in (TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED):
        assert is_review_due(_task(status=status), now=NOW)
    done = _task(status=TaskStatus.COMPLETED, completed_at=RECENT)
    assert not is_review_due(done, now=NOW)
    assert not is_review_due(_task(archived_at=RECENT), now=NOW)
    assert not is_review_due(
        _task(last_reviewed_at=NOW - REVIEW_INTERVAL + timedelta(seconds=1)), now=NOW
    )
    assert is_review_due(_task(last_reviewed_at=NOW - REVIEW_INTERVAL), now=NOW)

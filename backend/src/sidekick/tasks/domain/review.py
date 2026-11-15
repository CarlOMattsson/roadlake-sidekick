"""Which open Tasks a review of many Tasks should bring up, and why.

Pure functions of stored values and an explicit `now`. A Task is due for review while it is open
and has not been reviewed in the last `REVIEW_INTERVAL`. A due Task falls into at most one bucket;
the buckets are ranked so the quickest decisions come first. Nothing here reads or writes storage.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NamedTuple

from .task import Task, TaskStatus

REVIEW_INTERVAL = timedelta(days=7)
"""A Task reviewed more recently than this is left out of the queue."""

LONG_OVERDUE_AFTER = timedelta(days=14)
"""A Task whose due date passed more than this long ago is long overdue, not just overdue."""

OPEN_STATUSES = frozenset({TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED})


class ReviewBucket(StrEnum):
    """Why a Task is in the review queue, in the order the queue serves them."""

    LIKELY_DONE = "likely_done"
    """Every Step is done but the Task is still open."""
    LONG_OVERDUE = "long_overdue"
    FOLLOW_UP_DUE = "follow_up_due"
    """Waiting on someone, and the follow-up day has passed."""
    OVERDUE = "overdue"
    OTHER = "other"
    """In none of the buckets above, however old; only a review of every open Task brings it up,
    last. Age alone is never a reason."""


BUCKET_ORDER: tuple[ReviewBucket, ...] = tuple(ReviewBucket)
"""Queue order: the position of a bucket here is its rank."""


class ReviewDecision(StrEnum):
    """What the owner decided about one reviewed Task. Every decision marks the Task reviewed."""

    KEEP = "keep"
    """Nothing changes; the Task leaves the queue for `REVIEW_INTERVAL`."""
    DONE = "done"
    MOVE = "move"
    """A new due date, or none."""
    WAITING = "waiting"
    """Waiting on someone, with an optional follow-up time."""
    FLAG = "flag"
    """Look at it later: sets `attention_requested`."""
    ARCHIVE = "archive"
    """No longer relevant: archived, hidden but never deleted."""
    AMBITION = "ambition"
    """Keep it in view as an ambition: undated, never reviewed or reminded of again."""


class ReviewCandidate(NamedTuple):
    """An open Task that may be due for review, with its live Step counts."""

    task: Task
    steps_done: int
    steps_total: int


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    """The bucket of one Task and the instant its reason is measured from.

    `since` is the due date (overdue buckets), the follow-up time (`follow_up_due`), and None for
    `likely_done` and `other`.
    """

    bucket: ReviewBucket
    since: datetime | None = None

    @property
    def rank(self) -> int:
        return BUCKET_ORDER.index(self.bucket)


def is_review_due(task: Task, *, now: datetime) -> bool:
    """Open, not archived, not an ambition, and not reviewed within `REVIEW_INTERVAL` of `now`."""

    if (
        task.status not in OPEN_STATUSES
        or task.archived_at is not None
        or task.ambition_since is not None
    ):
        return False
    return task.last_reviewed_at is None or task.last_reviewed_at <= now - REVIEW_INTERVAL


def review_finding(
    task: Task, *, steps_done: int, steps_total: int, now: datetime
) -> ReviewFinding:
    """The first bucket `task` matches, in `BUCKET_ORDER`; `OTHER` when it matches none.

    The caller decides whether the Task is due for review at all (`is_review_due`). Archived Steps
    are not counted by the caller, so a Task with only archived Steps has none here.
    """

    if steps_total > 0 and steps_done == steps_total:
        return ReviewFinding(ReviewBucket.LIKELY_DONE)
    due_at = task.due_at
    if due_at is not None and due_at < now - LONG_OVERDUE_AFTER:
        return ReviewFinding(ReviewBucket.LONG_OVERDUE, due_at)
    if task.follow_up_due(now=now):
        return ReviewFinding(ReviewBucket.FOLLOW_UP_DUE, task.follow_up_at)
    if due_at is not None and due_at < now:
        return ReviewFinding(ReviewBucket.OVERDUE, due_at)
    return ReviewFinding(ReviewBucket.OTHER)

"""The review queue: the open Tasks a review of many Tasks should bring up, in a fixed order.

The queue is derived on every read, never stored: an open Task is in it while it has not been
reviewed in the last `REVIEW_INTERVAL`, and its bucket comes from `review_finding`. Pages follow a
keyset over (bucket rank, Domain, Project, due date, id), so a Task that leaves the queue while
the owner pages (reviewed, completed, archived) moves nothing else.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from sidekick.shared.types import Actor, KeyValue, TxSession, paginate, validate_limit
from sidekick.tasks.application.service import TaskService
from sidekick.tasks.domain import Task
from sidekick.tasks.domain.review import (
    BUCKET_ORDER,
    REVIEW_INTERVAL,
    ReviewBucket,
    ReviewFinding,
    review_finding,
)

type ReviewScope = Literal["suggested", "all"]
"""`suggested` leaves out the Tasks in no bucket (`other`); `all` brings every due Task."""

DEFAULT_REVIEW_PAGE = 10
MAX_REVIEW_PAGE = 25
MAX_REVIEW_CANDIDATES = 2000
"""Most open Tasks one read considers; far above what a person reviews, it bounds the read."""

_POSITION_KINDS = (int, UUID, UUID, datetime, UUID)
_POSITION_NULLABLE = (False, True, True, True, False)


@dataclass(frozen=True, slots=True)
class ReviewQueueItem:
    """One Task of the queue, why it is there, and its context by name when that may be read."""

    task: Task
    finding: ReviewFinding
    project_title: str | None
    domain_name: str | None


@dataclass(frozen=True, slots=True)
class ReviewQueuePage:
    items: tuple[ReviewQueueItem, ...]
    next_cursor: str | None
    remaining_total: int
    """Every Task in the queue now, before and after this page."""
    bucket_counts: dict[ReviewBucket, int]
    """How many of `remaining_total` are in each bucket; buckets with none are left out."""


def _position(task: Task, finding: ReviewFinding) -> tuple[KeyValue, ...]:
    return (finding.rank, task.derived_domain_id, task.project_id, task.due_at, task.id)


def _order(position: tuple[KeyValue, ...]) -> tuple[object, ...]:
    """A sortable form of a position: within a bucket, grouped by Domain then Project (Tasks
    without one last), then the earliest due date first (undated last), then the id."""

    rank, domain_id, project_id, due_at, task_id = position
    return (
        rank,
        domain_id is None,
        str(domain_id or ""),
        project_id is None,
        str(project_id or ""),
        due_at is None,
        cast(datetime, due_at).timestamp() if due_at is not None else 0.0,
        str(task_id),
    )


class TaskReviewService:
    def __init__(self, tasks: TaskService) -> None:
        self.tasks = tasks
        self.store = tasks.store
        self.cursor_codec = tasks.cursor_codec

    def queue(
        self,
        actor: Actor,
        *,
        scope: ReviewScope = "suggested",
        limit: int = DEFAULT_REVIEW_PAGE,
        cursor: str | None = None,
    ) -> ReviewQueuePage:
        """One page of the queue. Project and Domain names need `projects:read` as well."""

        actor.require("tasks:read")
        validate_limit(limit, maximum=MAX_REVIEW_PAGE)
        query_key = f"review-queue:v1:scope={scope}"  # gitleaks:allow
        after = self.cursor_codec.decode_keyset(
            actor.user_id,
            cursor,
            query_key,
            kinds=_POSITION_KINDS,
            nullable=_POSITION_NULLABLE,
        )

        def read(session: TxSession) -> ReviewQueuePage:
            # The Task service's clock, so the queue and the writes agree on `now`.
            now = self.tasks.clock.now()
            candidates = self.store.list_review_candidates(
                session,
                actor.user_id,
                reviewed_before=now - REVIEW_INTERVAL,
                limit=MAX_REVIEW_CANDIDATES,
            )
            tasks = self.tasks.with_derived_domains(
                session, actor, [candidate.task for candidate in candidates]
            )
            findings = [
                review_finding(
                    task,
                    steps_done=candidate.steps_done,
                    steps_total=candidate.steps_total,
                    now=now,
                )
                for task, candidate in zip(tasks, candidates, strict=True)
            ]
            queue = sorted(
                (
                    (task, finding)
                    for task, finding in zip(tasks, findings, strict=True)
                    if scope == "all" or finding.bucket is not ReviewBucket.OTHER
                ),
                key=lambda pair: _order(_position(*pair)),
            )
            start = _order(after) if after is not None else None
            rest = [pair for pair in queue if start is None or _order(_position(*pair)) > start]
            page, next_cursor = paginate(
                rest,
                limit,
                lambda last: self.cursor_codec.encode_keyset(
                    actor.user_id, _position(*last), query_key
                ),
            )
            counts = Counter(finding.bucket for _, finding in queue)
            return ReviewQueuePage(
                items=tuple(self._named(session, actor, page)),
                next_cursor=next_cursor,
                remaining_total=len(queue),
                bucket_counts={bucket: counts[bucket] for bucket in BUCKET_ORDER if counts[bucket]},
            )

        return self.store.transaction(read)

    def _named(
        self, session: TxSession, actor: Actor, pairs: list[tuple[Task, ReviewFinding]]
    ) -> list[ReviewQueueItem]:
        """The pairs as queue items, with Project titles and Domain names for `projects:read`."""

        titles: dict[UUID, str] = {}
        names: dict[UUID, str] = {}
        if "projects:read" in actor.scopes:
            project_ids = tuple({t.project_id for t, _ in pairs if t.project_id is not None})
            domain_ids = tuple(
                {t.derived_domain_id for t, _ in pairs if t.derived_domain_id is not None}
            )
            titles = self.store.project_titles(session, actor.user_id, project_ids)
            names = self.store.domain_names(session, actor.user_id, domain_ids)
        return [
            ReviewQueueItem(
                task=task,
                finding=finding,
                project_title=titles.get(task.project_id) if task.project_id else None,
                domain_name=(names.get(task.derived_domain_id) if task.derived_domain_id else None),
            )
            for task, finding in pairs
        ]

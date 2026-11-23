"""Going through many Tasks with the owner, for voice first: the queue and the decisions.

`get_review_queue` reads `TaskReviewService.queue`: the open Tasks not reviewed this week, the
quickest decisions first, with a server-derived reason per Task. `review_tasks` saves 1 to 20
decisions the owner has confirmed (`TaskBulkService.review`), atomically and retry-safe, and
answers with what each Task was before, so an undo is the opposite ordinary write.

`get_review_queue` opens the Sidekick app's review card. Its text is written to be read out, so
line 1 has no ids, ISO times or card note; the rows after it carry the id and version for the next
call.

`REVIEW_GUIDE` is how Claude runs the walk-through. It is written once and used twice: as part of
the `get_review_queue` description and in the `review_tasks_walkthrough` prompt.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from typing import Annotated, Literal, Self
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field, model_validator

from sidekick.mcp.annotations import READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.reschedule import RescheduleWhen, day_in_words, target_day
from sidekick.mcp.results import output_schema, result, spoken_names
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import card_row, count_phrase, spoken_date
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.base import Output
from sidekick.structured.work_records import end_of_day_due_at
from sidekick.tasks.application.models import (
    MAX_REVIEW_DECISIONS,
    ReviewDecisionItem,
    ReviewedTask,
)
from sidekick.tasks.application.review import (
    DEFAULT_REVIEW_PAGE,
    MAX_REVIEW_PAGE,
    ReviewQueueItem,
    ReviewQueuePage,
)
from sidekick.tasks.domain.review import ReviewBucket, ReviewDecision

REVIEW_GUIDE = (
    "Guide: open with the count and the plan in one sentence; offer klar, behåll, flytta, "
    "väntar, flagga, arkivera, hoppa. Start with likely_done and long_overdue. Say title and "
    "reason in at most 12 words, no ids or ISO dates. Say each decision back first; behåll is "
    "keep, never kvar. Done or archive only on the user's word; say probably done only for "
    "likely_done. Three or more alike: confirm at most three tasks at a time, with count and "
    "target. Save with review_tasks after 5 decisions, at a group's end and before any pause. "
    "After about 30 tasks suggest a break. Stop: save, say how many remain. Undo: reverse the "
    "last save with previous."
)
QUEUE_DESCRIPTION = (
    "Use this when the user wants to go through or clean up many tasks at once. Returns open "
    "tasks not reviewed in 7 days, quickest decisions first: likely_done, long_overdue, "
    "follow_up_due, overdue; scope=all adds the rest, last. Rows carry id, version and a "
    "spoken reason; line 1 is what to say. Skipping writes nothing: page on with next_cursor. "
    f"{REVIEW_GUIDE}"
)
WALKTHROUGH_PROMPT = """\
Go through my open tasks with me{time}.

1. Call get_review_queue with scope "{scope}" and follow its guide.
2. Show up to 10 rows, numbered, with the reason. I answer in one line, for example \
"1, 3, 5 done, 2 next week"; save that in one review_tasks call.
3. Never mark done or archive a task I have not said so about. Keep going until the queue is \
empty or I say stop.

{guide}
"""

ReviewBucketName = Literal["likely_done", "long_overdue", "follow_up_due", "overdue", "other"]

_BUCKET_WORDS: dict[ReviewBucket, str] = {
    ReviewBucket.LIKELY_DONE: "likely done",
    ReviewBucket.LONG_OVERDUE: "long overdue",
    ReviewBucket.FOLLOW_UP_DUE: "follow-up due",
    ReviewBucket.OVERDUE: "overdue",
    ReviewBucket.OTHER: "other",
}


class ReviewQueueRecord(Output):
    """One Task to review; `reason` is the bucket in words, for saying out loud."""

    id: UUID
    version: int
    title: str
    status: str
    bucket: ReviewBucketName
    reason: str
    due_at: datetime | None = None
    follow_up_at: datetime | None = None
    project_id: UUID | None = None
    project_title: str | None = None
    """Needs projects:read, like domain_name."""
    domain_id: UUID | None = None
    domain_name: str | None = None


class ReviewQueueOutput(Output):
    tasks: list[ReviewQueueRecord]
    scope: Literal["suggested", "all"]
    """The scope the page was read with; a next page is read with the same scope and next_cursor."""
    remaining_total: int
    """Every Task in the queue now, this page included; skipped Tasks stay in it."""
    bucket_counts: dict[str, int]
    next_cursor: str | None = None


def _span(days: int) -> str:
    """A number of days in words a listener can hold: days, then weeks, then months."""

    if days < 14:
        return count_phrase(days, "day", "days")
    if days < 60:
        return count_phrase(days // 7, "week", "weeks")
    return count_phrase(days // 30, "month", "months")


def _reason(item: ReviewQueueItem, today: date, zone: tzinfo) -> str:
    """Why the Task is in the queue, in at most a few words, with no ISO date."""

    since = item.finding.since
    days = (today - since.astimezone(zone).date()).days if since is not None else 0
    match item.finding.bucket:
        case ReviewBucket.LIKELY_DONE:
            return "all steps done"
        case ReviewBucket.LONG_OVERDUE | ReviewBucket.OVERDUE:
            return f"overdue {_span(days)}" if days > 0 else "due earlier today"
        case ReviewBucket.FOLLOW_UP_DUE:
            return f"follow-up due {_span(days)} ago" if days > 0 else "follow-up due today"
        case ReviewBucket.OTHER:
            due = item.task.due_at
            if due is None:
                return "no due date"
            return f"due {spoken_date(due.astimezone(zone).date(), today)}"


def _record(item: ReviewQueueItem, today: date, zone: tzinfo) -> ReviewQueueRecord:
    task = item.task
    return ReviewQueueRecord(
        id=task.id,
        version=task.version,
        title=task.title,
        status=task.status.value,
        bucket=item.finding.bucket.value,
        reason=_reason(item, today, zone),
        due_at=task.due_at,
        follow_up_at=task.follow_up_at,
        project_id=task.project_id,
        project_title=item.project_title,
        domain_id=task.derived_domain_id,
        domain_name=item.domain_name,
    )


def queue_sentence(page: ReviewQueuePage) -> str:
    """Line 1: how many Tasks are left and how many of them are in each bucket."""

    if page.remaining_total == 0:
        return "Nothing left to review."
    parts = [
        f"{count} {_BUCKET_WORDS[bucket]}"
        for bucket, count in page.bucket_counts.items()
        if bucket is not ReviewBucket.OTHER
    ]
    head = f"{page.remaining_total} to review"
    return f"{head}: {', '.join(parts)}." if parts else f"{head}."


def queue_text(page: ReviewQueuePage, records: list[ReviewQueueRecord]) -> str:
    """The sentence, then one row per Task: id and version, title, reason, Project or Domain."""

    lines = [queue_sentence(page)]
    for record in records:
        lines.append(
            card_row(
                f"{record.id} v{record.version}",
                record.title,
                record.reason,
                record.project_title or record.domain_name,
            )
        )
    if page.next_cursor is not None:
        lines.append(f"More: next_cursor {page.next_cursor}.")
    return "\n".join(lines)


ReviewDecisionName = Literal["keep", "done", "move", "waiting", "flag", "archive", "ambition"]
FollowUpWhen = Literal["tomorrow", "next_week"] | date


class ReviewDecisionInput(Output):
    """One confirmed decision: `when` belongs to `move` only, `follow_up` to `waiting`."""

    task_id: UUID
    expected_version: Annotated[int, Field(ge=1)]
    decision: ReviewDecisionName
    when: RescheduleWhen | None = None
    follow_up: FollowUpWhen | None = None

    @model_validator(mode="after")
    def _fits_the_decision(self) -> Self:
        if (self.decision == "move") != (self.when is not None):
            raise ValueError("when is required for move and allowed for no other decision")
        if self.follow_up is not None and self.decision != "waiting":
            raise ValueError("follow_up is only allowed with waiting")
        return self


class ReviewPreviousRecord(Output):
    """The Task before the decision: send these back with update_task or reschedule_tasks to undo
    (status, due date, waiting and follow-up, the flag, a recurring Task's last completion)."""

    status: str
    due_at: datetime | None
    waiting_since: datetime | None
    follow_up_at: datetime | None
    attention_requested: bool
    last_completed_at: datetime | None
    archived_at: datetime | None


class ReviewedTaskRecord(Output):
    id: UUID
    version: int
    decision: ReviewDecisionName
    status: str
    due_at: datetime | None
    archived: bool
    previous: ReviewPreviousRecord


class ReviewTasksOutput(Output):
    count: int
    tasks: list[ReviewedTaskRecord]


_DECISION_WORDS: dict[ReviewDecision, str] = {
    ReviewDecision.DONE: "done",
    ReviewDecision.KEEP: "kept",
    ReviewDecision.MOVE: "moved",
    ReviewDecision.WAITING: "waiting",
    ReviewDecision.FLAG: "flagged",
    ReviewDecision.ARCHIVE: "archived",
    ReviewDecision.AMBITION: "kept as ambitions",
}


def review_sentence(
    reviewed: list[ReviewedTask], whens: dict[UUID, date | None], today: date
) -> str:
    """Line 1: each decision with the Tasks it applied to, by title, in the order of the words."""

    parts: list[str] = []
    for decision, word in _DECISION_WORDS.items():
        titles = [entry.task.title for entry in reviewed if entry.decision is decision]
        if not titles:
            continue
        names = spoken_names(titles, len(titles))
        if decision is ReviewDecision.MOVE:
            targets = {whens[entry.task.id] for entry in reviewed if entry.decision is decision}
            if len(targets) == 1:
                (target,) = targets
                where = (
                    "with no due date" if target is None else f"to {day_in_words(target, today)}"
                )
                parts.append(f"{names} moved {where}")
                continue
        if decision is ReviewDecision.AMBITION:
            parts.append(f"{names} kept as {'an ambition' if len(titles) == 1 else 'ambitions'}")
            continue
        parts.append(f"{names} {word}")
    return f"Saved {count_phrase(len(reviewed), 'decision', 'decisions')}: {'; '.join(parts)}."


def _reviewed_record(entry: ReviewedTask) -> ReviewedTaskRecord:
    task = entry.task
    return ReviewedTaskRecord(
        id=task.id,
        version=task.version,
        decision=entry.decision.value,
        status=task.status.value,
        due_at=task.due_at,
        archived=task.archived_at is not None,
        previous=ReviewPreviousRecord.model_validate(entry.previous),
    )


def register_review_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register `get_review_queue` (it opens the app's review card), `review_tasks` (no card) and
    the walk-through prompt."""

    @mcp.prompt(
        name="review_tasks_walkthrough",
        description="Go through the owner's open tasks together, by text, a few at a time.",
    )
    def review_tasks_walkthrough(
        minutes: Annotated[int | None, Field(ge=1, le=240)] = None,
        scope: Literal["suggested", "all"] = "suggested",
    ) -> str:
        time = "" if minutes is None else f"; I have about {minutes} minutes, so stop then"
        return WALKTHROUGH_PROMPT.format(time=time, scope=scope, guide=REVIEW_GUIDE)

    @mcp.tool(
        name="get_review_queue",
        description=QUEUE_DESCRIPTION,
        output_schema=output_schema(ReviewQueueOutput),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_review_queue")
    def get_review_queue(
        scope: Literal["suggested", "all"] = "suggested",
        limit: Annotated[int, Field(ge=1, le=MAX_REVIEW_PAGE)] = DEFAULT_REVIEW_PAGE,
        cursor: Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        zone = ctx.container.settings.owner_zone
        page = ctx.container.task_review.queue(actor, scope=scope, limit=limit, cursor=cursor)
        today = ctx.container.tasks.clock.now().astimezone(zone).date()
        records = [_record(item, today, zone) for item in page.items]
        structured = ReviewQueueOutput(
            tasks=records,
            scope=scope,
            remaining_total=page.remaining_total,
            bucket_counts={bucket.value: count for bucket, count in page.bucket_counts.items()},
            next_cursor=page.next_cursor,
        ).model_dump(mode="json")
        return result(structured, queue_text(page, records))

    @mcp.tool(
        name="review_tasks",
        description=(
            "Save 1 to 20 confirmed decisions on get_review_queue rows: keep, done, move "
            "(when: tomorrow, next_week, a date or clear), waiting (optional follow_up), flag, "
            "archive (undo with restore_task) or ambition (kept in view, undated, never "
            "reminded; for what the user wants someday). Each marks the task reviewed. In voice, "
            "confirm at most three tasks per mass change. Items need task_id and "
            "expected_version; a stale version fails the call. Retry-safe with the same key. "
            "previous undoes a change via update_task or reschedule_tasks."
        ),
        output_schema=output_schema(ReviewTasksOutput),
        annotations=WRITE,
    )
    @ctx.instrument("review_tasks")
    def review_tasks(
        items: Annotated[
            list[ReviewDecisionInput], Field(min_length=1, max_length=MAX_REVIEW_DECISIONS)
        ],
        idempotency_key: IdempotencyKey,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        zone = ctx.container.settings.owner_zone
        today = ctx.container.tasks.clock.now().astimezone(zone).date()
        whens = {
            item.task_id: target_day(item.when, today) for item in items if item.when is not None
        }
        decisions = [
            ReviewDecisionItem(
                task_id=item.task_id,
                expected_version=item.expected_version,
                decision=ReviewDecision(item.decision),
                due_day=whens.get(item.task_id),
                follow_up_at=end_of_day_due_at(
                    target_day(item.follow_up, today) if item.follow_up is not None else None,
                    zone,
                ),
            )
            for item in items
        ]
        reviewed = ctx.container.task_bulk.review(
            actor,
            decisions,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        records = [_reviewed_record(entry) for entry in reviewed]
        structured = ReviewTasksOutput(count=len(records), tasks=records).model_dump(mode="json")
        lines = [review_sentence(reviewed, whens, today)]
        for record in records:
            lines.append(f"{record.id} version {record.version}, {record.decision}")
        return result(structured, "\n".join(lines))

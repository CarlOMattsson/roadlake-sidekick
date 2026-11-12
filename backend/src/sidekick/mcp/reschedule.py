"""Morning triage: move 1 to 20 Tasks' due dates in one atomic call, for voice and cards.

`reschedule_tasks` calls the same Task update as `update_task` (`TaskBulkService.reschedule` runs
`TaskService.update_in_session` for each item in one transaction), so validation, versions,
status history and the activity ledger are shared. A bare date, "tomorrow" and "next_week" all
become 23:59 in the owner's zone through `end_of_day_due_at`, the helper create_task and
update_task use. "next_week" is the Monday of next week, counted from the owner's calendar day.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field

from sidekick.mcp.annotations import WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result, spoken_names
from sidekick.mcp.text import spoken_date
from sidekick.mcp.tool_context import ToolContext
from sidekick.structured.base import Output
from sidekick.structured.work_records import end_of_day_due_at
from sidekick.tasks.application.models import MAX_RESCHEDULE_TASKS, RescheduleTaskItem

RescheduleWhen = Literal["tomorrow", "next_week", "clear"] | date


class RescheduleInput(Output):
    """One Task to move; `when` is a relative day, `clear` (no due date), or a bare YYYY-MM-DD."""

    task_id: UUID
    expected_version: Annotated[int, Field(ge=1)]
    when: RescheduleWhen


class RescheduledTaskRecord(Output):
    id: UUID
    version: int
    due_at: datetime | None


class RescheduleOutput(Output):
    count: int
    tasks: list[RescheduledTaskRecord]


def _target_day(when: RescheduleWhen, today: date) -> date | None:
    """The calendar day that `when` names, or None for `clear`."""

    if when == "tomorrow":
        return today + timedelta(days=1)
    if when == "next_week":
        # weekday() is 0 on Monday; a Monday gives the following Monday, never today.
        return today + timedelta(days=7 - today.weekday())
    if when == "clear":
        return None
    return when


_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _day_in_words(day: date, today: date) -> str:
    """A day for voice: "tomorrow", or the weekday and date, such as "Monday 2 November"."""

    if day == today + timedelta(days=1):
        return "tomorrow"
    return f"{_WEEKDAYS[day.weekday()]} {spoken_date(day, today)}"


def _summary(titles: list[str], targets: set[date | None], today: date) -> str:
    """Line 1: which tasks moved and where, in words, with no ids or ISO times."""

    names = spoken_names(titles, len(titles))
    if len(targets) != 1:
        return f"Rescheduled {names}."
    (target,) = targets
    if target is None:
        return f"Cleared the due date on {names}."
    return f"Moved {names} to {_day_in_words(target, today)}."


def register_reschedule_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register `reschedule_tasks`; it opens no app card."""

    @mcp.tool(
        name="reschedule_tasks",
        description=(
            "Use this when the user wants to move 1 to 20 tasks at once, for example to tomorrow, "
            "next week (Monday), a given date, or to clear the due date. Each item needs task_id "
            "and expected_version from a recent read. The whole call fails if any version is "
            "stale, so re-read and retry. New due dates are 23:59 in the owner's zone. Retry-safe "
            "with the same idempotency key. Relative days (tomorrow, next_week) are recomputed on "
            "every call, so a retry after midnight with the same key conflicts."
        ),
        output_schema=output_schema(RescheduleOutput),
        annotations=WRITE,
    )
    @ctx.instrument("reschedule_tasks")
    def reschedule_tasks(
        items: Annotated[
            list[RescheduleInput], Field(min_length=1, max_length=MAX_RESCHEDULE_TASKS)
        ],
        idempotency_key: IdempotencyKey,
    ) -> Any:
        actor = ctx.actor_provider()
        zone = ctx.container.settings.owner_zone
        today = ctx.container.tasks.clock.now().astimezone(zone).date()
        commands = [
            RescheduleTaskItem(
                task_id=item.task_id,
                expected_version=item.expected_version,
                due_at=end_of_day_due_at(_target_day(item.when, today), zone),
            )
            for item in items
        ]
        tasks = ctx.container.task_bulk.reschedule(
            actor,
            commands,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        records = [
            RescheduledTaskRecord(id=task.id, version=task.version, due_at=task.due_at)
            for task in tasks
        ]
        structured = RescheduleOutput(count=len(records), tasks=records).model_dump(mode="json")
        targets = {_target_day(item.when, today) for item in items}
        lines = [_summary([task.title for task in tasks], targets, today)]
        for record in records:
            due = record.due_at.isoformat() if record.due_at else "none"
            lines.append(f"{record.id} version {record.version}, due {due}")
        return result(structured, "\n".join(lines))

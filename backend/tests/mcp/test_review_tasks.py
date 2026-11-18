"""review_tasks: save 1 to 20 confirmed review decisions in one atomic, retry-safe call.

Every decision marks the Task reviewed, so it leaves the review queue. A stale version rejects the
whole call. The reply keeps what each Task was before, so an undo is the opposite ordinary write.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.mcp.instrument import instrument_mcp
from sidekick.mcp.review import register_review_tools
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import Actor
from sidekick.tasks.application.models import MAX_REVIEW_DECISIONS, ReviewDecisionItem
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.tasks.domain.review import ReviewDecision
from tests.db import database_factory
from tests.support.settings import make_settings

ZONE = ZoneInfo("Europe/Stockholm")
# Sunday 15 November 2026, so next_week is tomorrow, Monday 16 November.
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=ZONE)
LONG_AGO = NOW - timedelta(days=90)
SCOPES = frozenset({"tasks:read", "tasks:write", "projects:read"})


class MovableClock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


def _setup(username: str = "review-writer") -> tuple[Container, Actor, MovableClock]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(username, "Review Writer")
    clock = MovableClock(LONG_AGO)
    container.tasks.clock = clock
    return container, Actor(owner, SCOPES), clock


def _server(container: Container, actor: Actor) -> FastMCP:
    mcp = FastMCP("review-tasks-test")
    register_review_tools(
        mcp, ToolContext(container, lambda: actor, lambda name: instrument_mcp(container, name))
    )
    return mcp


def _task(container: Container, actor: Actor, title: str, **fields: Any) -> Task:
    return container.tasks.create(
        actor, title=title, idempotency_key=f"review-{uuid4().hex}", **fields
    )


def _item(task: Task, decision: str, **extra: Any) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "expected_version": task.version,
        "decision": decision,
        **extra,
    }


async def _review(client: Client[Any], items: list[dict[str, Any]], key: str) -> Any:
    return await client.call_tool(
        "review_tasks", {"items": items, "idempotency_key": key}, raise_on_error=False
    )


def _lines(result: Any) -> list[str]:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text.splitlines()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_each_decision_is_applied_marks_the_task_reviewed_and_keeps_what_it_was() -> None:
    container, actor, clock = _setup()
    old_due = NOW - timedelta(days=20)
    keep = _task(container, actor, "Behåll mig")
    done = _task(container, actor, "Redan gjord", due_at=old_due)
    move = _task(container, actor, "Flytta mig", due_at=old_due)
    wait = _task(container, actor, "Vänta på Sara")
    flag = _task(container, actor, "Titta senare")
    drop = _task(container, actor, "Inte aktuell")
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        saved = await _review(
            client,
            [
                _item(keep, "keep"),
                _item(done, "done"),
                _item(move, "move", when="next_week"),
                _item(wait, "waiting", follow_up="tomorrow"),
                _item(flag, "flag"),
                _item(drop, "archive"),
            ],
            "review-all-1",
        )

    assert not saved.is_error, saved.structured_content
    content = saved.structured_content
    assert content["count"] == 6
    records = {row["id"]: row for row in content["tasks"]}
    for task in (keep, done, move, wait, flag, drop):
        assert records[str(task.id)]["version"] == task.version + 1
    assert records[str(done.id)]["status"] == "completed"
    assert records[str(done.id)]["previous"]["status"] == "todo"
    assert datetime.fromisoformat(records[str(done.id)]["previous"]["due_at"]) == old_due
    # The moved Task had a time of day (12:00), which it keeps on the new day.
    assert datetime.fromisoformat(records[str(move.id)]["due_at"]) == datetime(
        2026, 11, 16, 12, 0, tzinfo=ZONE
    )
    assert records[str(drop.id)]["archived"] is True
    assert records[str(drop.id)]["previous"]["archived_at"] is None
    assert records[str(flag.id)]["previous"]["attention_requested"] is False
    assert records[str(keep.id)]["previous"]["status"] == "todo"

    flagged = container.tasks.get(actor, flag.id)
    assert flagged.attention_requested and flagged.last_reviewed_at == NOW
    waiting = container.tasks.get(actor, wait.id)
    assert waiting.waiting_since == NOW
    assert waiting.follow_up_at == datetime(2026, 11, 16, 23, 59, tzinfo=ZONE)
    kept = container.tasks.get(actor, keep.id)
    # Keep changes nothing but the review time and the version.
    assert kept.last_reviewed_at == NOW and kept.updated_at == keep.updated_at
    assert container.tasks.get(actor, move.id).last_reviewed_at == NOW

    lines = _lines(saved)
    assert lines[0] == (
        "Saved 6 decisions: Redan gjord done; Behåll mig kept; Flytta mig moved to tomorrow; "
        "Vänta på Sara waiting; Titta senare flagged; Inte aktuell archived."
    )
    assert lines[1] == f"{keep.id} version {keep.version + 1}, keep"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_reviewed_task_leaves_the_queue_until_a_week_has_passed() -> None:
    container, actor, clock = _setup()
    first = _task(container, actor, "Gammal ett")
    second = _task(container, actor, "Gammal två")
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        await _review(client, [_item(first, "keep")], "review-queue-1")
        queue = await client.call_tool("get_review_queue", {"scope": "all"})
        clock.at = NOW + timedelta(days=7)
        later = await client.call_tool("get_review_queue", {"scope": "all"})

    assert [row["id"] for row in queue.structured_content["tasks"]] == [str(second.id)]
    assert {row["id"] for row in later.structured_content["tasks"]} == {
        str(first.id),
        str(second.id),
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_version_rolls_back_every_decision_of_the_call() -> None:
    container, actor, clock = _setup()
    fresh = _task(container, actor, "Färsk")
    kept = _task(container, actor, "Behållen")
    stale = _task(container, actor, "Inaktuell")
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        rejected = await _review(
            client,
            [
                _item(fresh, "done"),
                _item(kept, "keep"),
                {**_item(stale, "flag"), "expected_version": stale.version + 3},
            ],
            "review-stale-1",
        )

    assert rejected.is_error
    assert rejected.structured_content["code"] == "conflict"
    assert rejected.structured_content["reason"] == "stale_version"
    for task in (fresh, kept, stale):
        stored = container.tasks.get(actor, task.id)
        assert stored.version == task.version
        assert stored.last_reviewed_at is None
        assert stored.status is TaskStatus.TODO
        assert not stored.attention_requested


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_same_key_replays_the_committed_answer_and_other_data_conflicts() -> None:
    container, actor, clock = _setup()
    task = _task(container, actor, "Retry-säker", due_at=NOW - timedelta(days=3))
    clock.at = NOW
    items = [_item(task, "move", when="clear")]

    async with Client(_server(container, actor)) as client:
        first = await _review(client, items, "review-retry-1")
        replayed = await _review(client, items, "review-retry-1")
        conflicting = await _review(client, [_item(task, "keep")], "review-retry-1")

    assert not first.is_error, first.structured_content
    assert replayed.structured_content == first.structured_content
    assert _lines(replayed)[0] == "Saved 1 decision: Retry-säker moved with no due date."
    # The replay still reports the due date the Task had before the first call.
    assert first.structured_content["tasks"][0]["previous"]["due_at"] is not None
    assert container.tasks.get(actor, task.id).version == task.version + 1
    assert conflicting.is_error
    assert conflicting.structured_content["code"] == "conflict"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_done_on_a_recurring_task_reopens_it_and_previous_holds_the_undo() -> None:
    container, actor, clock = _setup()
    due = NOW - timedelta(days=2)
    task = _task(
        container, actor, "Vattna blommorna", due_at=due, recurrence={"frequency": "weekly"}
    )
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        saved = await _review(client, [_item(task, "done")], "review-recurring-1")

    assert not saved.is_error, saved.structured_content
    record = saved.structured_content["tasks"][0]
    assert record["status"] == "todo"
    assert datetime.fromisoformat(record["due_at"]) > NOW
    assert record["previous"]["last_completed_at"] is None
    assert datetime.fromisoformat(record["previous"]["due_at"]) == due
    stored = container.tasks.get(actor, task.id)
    assert stored.last_completed_at == NOW and stored.last_reviewed_at == NOW
    assert record["version"] == stored.version


@pytest.mark.asyncio
@pytest.mark.integration
async def test_without_tasks_write_or_for_another_owner_nothing_changes() -> None:
    container, actor, clock = _setup()
    task = _task(container, actor, "Skyddad")
    stranger = Actor(container.auth.provision_user("review-stranger-w", "Stranger"), SCOPES)
    clock.at = NOW

    async with Client(
        _server(container, Actor(actor.user_id, frozenset({"tasks:read"})))
    ) as client:
        denied = await _review(client, [_item(task, "done")], "review-denied-1")
    async with Client(_server(container, stranger)) as client:
        foreign = await _review(client, [_item(task, "done")], "review-foreign-1")

    assert denied.is_error and denied.structured_content["code"] == "forbidden"
    assert foreign.is_error and foreign.structured_content["code"] == "not_found"
    stored = container.tasks.get(actor, task.id)
    assert stored.version == task.version and stored.last_reviewed_at is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_changes_get_their_own_entry_and_unchanged_tasks_share_one_summary() -> None:
    container, actor, clock = _setup()
    first = _task(container, actor, "Behåll ett")
    second = _task(container, actor, "Behåll två")
    done = _task(container, actor, "Gjord nu")
    drop = _task(container, actor, "Arkivera nu")
    clock.at = NOW
    seen = {entry.id for entry in container.activity.list_activity(actor, limit=100).items}

    async with Client(_server(container, actor)) as client:
        saved = await _review(
            client,
            [
                _item(first, "keep"),
                _item(done, "done"),
                _item(second, "keep"),
                _item(drop, "archive"),
            ],
            "review-ledger-1",
        )

    assert not saved.is_error, saved.structured_content
    entries = [
        entry
        for entry in container.activity.list_activity(actor, limit=100).items
        if entry.id not in seen
    ]
    by_operation = {entry.operation: entry for entry in entries}
    assert sorted(by_operation) == ["archive_task", "review_tasks", "update_task"]
    assert len(entries) == 3
    summary = by_operation["review_tasks"]
    assert summary.aggregate_id == first.id
    assert summary.evidence == {"task_ids": [str(first.id), str(second.id)]}
    assert summary.summary == "Reviewed without changes (2): Behåll ett, Behåll två"
    assert by_operation["update_task"].aggregate_id == done.id
    assert by_operation["update_task"].category == "task_status_change"
    assert by_operation["archive_task"].aggregate_id == drop.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_logs_and_errors_carry_no_task_titles(caplog: pytest.LogCaptureFixture) -> None:
    container, actor, clock = _setup()
    task = _task(container, actor, "Hemlig granskningstitel")
    clock.at = NOW
    caplog.set_level(logging.DEBUG)

    async with Client(_server(container, actor)) as client:
        saved = await _review(client, [_item(task, "flag")], "review-redact-1")
        stale = await _review(client, [_item(task, "keep")], "review-redact-2")

    assert not saved.is_error
    assert stale.is_error
    assert "Hemlig granskningstitel" not in caplog.text
    assert "review-redact" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_inputs_that_do_not_fit_their_decision_are_refused_before_any_write() -> None:
    container, actor, clock = _setup()
    task = _task(container, actor, "Orörd")
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        for items in (
            [_item(task, "move")],
            [_item(task, "keep", when="tomorrow")],
            [_item(task, "done", follow_up="tomorrow")],
            [_item(task, "keep"), _item(task, "done")],
            [_item(task, "keep") for _ in range(MAX_REVIEW_DECISIONS + 1)],
            [],
        ):
            with pytest.raises(ToolError):
                await client.call_tool(
                    "review_tasks", {"items": items, "idempotency_key": f"bad-{uuid4().hex}"}
                )

    assert container.tasks.get(actor, task.id).version == task.version


@pytest.mark.integration
def test_the_service_refuses_too_many_and_repeated_tasks_for_any_caller() -> None:
    container, actor, _ = _setup()
    task = _task(container, actor, "Tjänsten")
    item = ReviewDecisionItem(task.id, task.version, ReviewDecision.KEEP)

    with pytest.raises(ValidationError):
        container.task_bulk.review(actor, [item, item], idempotency_key="service-repeat-1")
    with pytest.raises(ValidationError):
        container.task_bulk.review(
            actor, [item] * (MAX_REVIEW_DECISIONS + 1), idempotency_key="service-many-1"
        )
    assert container.tasks.get(actor, task.id).version == task.version

"""Ambitions: Tasks the owner keeps in view without ever being due, reviewed or reminded of.

An ambition is a Task with `ambition_since` set. It has no due date, start, waiting, flag, repeat
or reminder, so it is never late and nothing nudges about it; the review queue and the agenda
(and so the day brief, the phone's Idag and its push summary) leave it and its Steps out.
`update_task` makes a Task an ambition and back, `list_tasks(ambitions=true)` lists them, and a
review can keep a Task as one. No answer words it as late, missed or not started.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client, FastMCP
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.mcp.instrument import instrument_mcp
from sidekick.mcp.review import register_review_tools
from sidekick.mcp.task_tools import register_task_tools
from sidekick.mcp.tool_context import ToolContext
from sidekick.mcp.work_view_tools import register_work_view_tools
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import Actor
from sidekick.tasks.application.models import ReviewDecisionItem, UpdateTaskCommand
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.tasks.domain.review import ReviewDecision
from sidekick.work.application.models import WorkQuery
from tests.db import database_factory
from tests.support.settings import make_settings

ZONE = ZoneInfo("Europe/Stockholm")
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=ZONE)
SCOPES = frozenset({"tasks:read", "tasks:write", "projects:read"})
GUILT = re.compile(r"overdue|late|missed|not (yet )?started|behind|stale", re.IGNORECASE)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


def _setup() -> tuple[Container, Actor, FixedClock]:
    container = create_container(make_settings(), database_factory())
    actor = Actor(container.auth.provision_user("ambition-owner", "Ambition Owner"), SCOPES)
    clock = FixedClock(NOW - timedelta(days=40))
    container.tasks.clock = clock
    container.work_lists.clock = clock
    return container, actor, clock


def _server(container: Container, actor: Actor) -> FastMCP:
    mcp = FastMCP("ambitions-test")
    ctx = ToolContext(container, lambda: actor, lambda name: instrument_mcp(container, name))
    register_task_tools(mcp, ctx)
    register_review_tools(mcp, ctx)
    register_work_view_tools(mcp, ctx)
    return mcp


def _task(container: Container, actor: Actor, title: str, **fields: Any) -> Task:
    return container.tasks.create(
        actor, title=title, idempotency_key=f"ambition-{uuid4().hex}", **fields
    )


def _text(result: Any) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def _make_ambition(client: Client[Any], task: Task, value: bool = True) -> Any:
    return await client.call_tool(
        "update_task",
        {
            "task_id": str(task.id),
            "version": task.version,
            "idempotency_key": f"ambition-{uuid4().hex}",
            "changes": {"ambition": value},
        },
        raise_on_error=False,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_overdue_waiting_flagged_task_becomes_an_ambition_and_back() -> None:
    container, actor, clock = _setup()
    task = _task(container, actor, "Lära mig spela piano", due_at=NOW - timedelta(days=30))
    task = container.tasks.update(
        actor,
        task.id,
        version=task.version,
        idempotency_key=f"ambition-{uuid4().hex}",
        command=UpdateTaskCommand(
            waiting_since=NOW - timedelta(days=35),
            follow_up_at=NOW - timedelta(days=2),
            attention_requested=True,
            not_before=NOW - timedelta(days=39),
        ),
    )
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        made = await _make_ambition(client, task)
        stored = container.tasks.get(actor, task.id)
        again = await _make_ambition(client, stored, value=False)

    assert not made.is_error, made.structured_content
    assert stored.ambition_since == NOW
    assert stored.scheduled_fields() == frozenset()
    assert stored.version == task.version + 1
    assert not again.is_error, again.structured_content
    back = container.tasks.get(actor, task.id)
    assert back.ambition_since is None and back.due_at is None
    assert back.version == task.version + 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_tasks_lists_the_ambitions_apart_in_plain_words() -> None:
    container, actor, clock = _setup()
    dream = _task(container, actor, "Segla runt Gotland")
    _task(container, actor, "Betala elräkningen", due_at=NOW - timedelta(days=3))
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        await _make_ambition(client, dream)
        none_yet = await client.call_tool("list_tasks", {"ambitions": True, "status": "blocked"})
        ambitions = await client.call_tool("list_tasks", {"ambitions": True})
        tasks = await client.call_tool("list_tasks", {})

    assert [row["id"] for row in ambitions.structured_content["tasks"]] == [str(dream.id)]
    assert str(dream.id) not in {row["id"] for row in tasks.structured_content["tasks"]}
    assert _text(ambitions).splitlines()[0].startswith("You have 1 ambition")
    assert _text(none_yet).splitlines()[0] == "No ambitions noted."
    assert not GUILT.search(_text(ambitions)) and not GUILT.search(_text(none_yet))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_ambition_is_never_in_the_review_queue_nor_the_agenda_nor_are_its_steps() -> None:
    container, actor, clock = _setup()
    dream = _task(container, actor, "Skriva en bok", due_at=NOW - timedelta(days=20))
    clock.at = NOW
    async with Client(_server(container, actor)) as client:
        await _make_ambition(client, dream)
    container.steps.create_step(
        actor,
        dream.id,
        title="Första kapitlet",
        due_at=NOW - timedelta(days=1),
        idempotency_key=f"ambition-{uuid4().hex}",
    )
    ordinary = _task(container, actor, "Odaterad vanlig")

    async with Client(_server(container, actor)) as client:
        queue = await client.call_tool("get_review_queue", {"scope": "all"})
    agenda = container.work_lists.work_agenda_page(
        actor, WorkQuery(sort="due_asc", include_undated=True, limit=50).validate()
    )
    today = container.work_lists.work_today_page(actor, limit=50)

    assert str(dream.id) not in {row["id"] for row in queue.structured_content["tasks"]}
    listed = {row.id for row in agenda.items}
    assert ordinary.id in listed
    assert not any(row.id == dream.id or row.title == "Första kapitlet" for row in agenda.items)
    assert today.total == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_ambition_cannot_be_dated_and_a_repeating_task_cannot_become_one() -> None:
    container, actor, clock = _setup()
    dream = _task(container, actor, "Springa ett maraton")
    weekly = _task(
        container,
        actor,
        "Vattna",
        due_at=NOW + timedelta(days=1),
        recurrence={"frequency": "weekly"},
    )
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        await _make_ambition(client, dream)
        stored = container.tasks.get(actor, dream.id)
        dated = await client.call_tool(
            "update_task",
            {
                "task_id": str(dream.id),
                "version": stored.version,
                "idempotency_key": f"ambition-{uuid4().hex}",
                "changes": {"due_at": "2026-12-01"},
            },
            raise_on_error=False,
        )
        both = await client.call_tool(
            "update_task",
            {
                "task_id": str(dream.id),
                "version": stored.version,
                "idempotency_key": f"ambition-{uuid4().hex}",
                "changes": {"ambition": True, "due_at": "2026-12-01"},
            },
            raise_on_error=False,
        )
        repeating = await _make_ambition(client, weekly)

    for refused in (dated, repeating):
        assert refused.is_error
        assert refused.structured_content["code"] == "validation_error"
        assert not GUILT.search(_text(refused))
    assert both.is_error
    assert both.structured_content["code"] == "validation_error"
    assert container.tasks.get(actor, dream.id).version == stored.version
    assert container.tasks.get(actor, weekly.id).ambition_since is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_review_keeps_a_long_overdue_task_as_an_ambition_with_the_undo_values() -> None:
    container, actor, clock = _setup()
    due = NOW - timedelta(days=30)
    task = _task(container, actor, "Bygga en båt", due_at=due)
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        saved = await client.call_tool(
            "review_tasks",
            {
                "items": [
                    {
                        "task_id": str(task.id),
                        "expected_version": task.version,
                        "decision": "ambition",
                    }
                ],
                "idempotency_key": "review-ambition-1",
            },
        )

    record = saved.structured_content["tasks"][0]
    assert record["decision"] == "ambition"
    assert record["due_at"] is None
    assert datetime.fromisoformat(record["previous"]["due_at"]) == due
    stored = container.tasks.get(actor, task.id)
    assert stored.ambition_since == NOW and stored.last_reviewed_at == NOW
    assert _text(saved).splitlines()[0] == "Saved 1 decision: Bygga en båt kept as an ambition."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_ambition_becomes_a_dated_task_in_one_call() -> None:
    container, actor, clock = _setup()
    dream = _task(container, actor, "Lära mig måla")
    clock.at = NOW
    due = NOW + timedelta(days=10)

    async with Client(_server(container, actor)) as client:
        await _make_ambition(client, dream)
        stored = container.tasks.get(actor, dream.id)
        result = await client.call_tool(
            "update_task",
            {
                "task_id": str(dream.id),
                "version": stored.version,
                "idempotency_key": f"ambition-{uuid4().hex}",
                "changes": {"ambition": False, "due_at": due.isoformat()},
            },
            raise_on_error=False,
        )

    assert not result.is_error, result.structured_content
    back = container.tasks.get(actor, dream.id)
    assert back.ambition_since is None
    assert back.due_at == due
    assert back.version == stored.version + 1


@pytest.mark.integration
def test_an_ambition_can_be_flagged_in_the_same_command_that_makes_it_a_task() -> None:
    container, actor, clock = _setup()
    dream = _task(container, actor, "Lära mig måla")
    clock.at = NOW
    made = container.tasks.update(
        actor,
        dream.id,
        version=dream.version,
        idempotency_key=f"ambition-{uuid4().hex}",
        command=UpdateTaskCommand(ambition=True),
    )

    with pytest.raises(ValidationError):
        container.tasks.update(
            actor,
            dream.id,
            version=made.version,
            idempotency_key=f"ambition-{uuid4().hex}",
            command=UpdateTaskCommand(ambition=True, attention_requested=True),
        )
    flagged = container.tasks.update(
        actor,
        dream.id,
        version=made.version,
        idempotency_key=f"ambition-{uuid4().hex}",
        command=UpdateTaskCommand(ambition=False, attention_requested=True),
    )

    assert flagged.ambition_since is None and flagged.attention_requested
    assert flagged.version == made.version + 1


@pytest.mark.integration
def test_a_review_that_cannot_keep_one_task_as_an_ambition_refuses_the_whole_call() -> None:
    container, actor, clock = _setup()
    open_task = _task(container, actor, "Öppen uppgift")
    done = _task(container, actor, "Hemlig klar titel")
    clock.at = NOW
    done = container.tasks.update(
        actor,
        done.id,
        version=done.version,
        idempotency_key=f"ambition-{uuid4().hex}",
        command=UpdateTaskCommand(status=TaskStatus.COMPLETED),
    )

    with pytest.raises(ValidationError) as refused:
        container.task_bulk.review(
            actor,
            [
                ReviewDecisionItem(open_task.id, open_task.version, ReviewDecision.AMBITION),
                ReviewDecisionItem(done.id, done.version, ReviewDecision.AMBITION),
            ],
            idempotency_key=f"ambition-{uuid4().hex}",
        )

    assert refused.value.reason == "not_an_ambition"
    assert f"review item 1 (task {done.id})" in str(refused.value)
    assert "Hemlig" not in str(refused.value)
    stored = container.tasks.get(actor, open_task.id)
    assert stored.ambition_since is None and stored.version == open_task.version


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_completed_ambition_is_no_longer_listed_as_an_ambition() -> None:
    container, actor, clock = _setup()
    dream = _task(container, actor, "Segla runt Gotland")
    kept = _task(container, actor, "Lära mig måla")
    clock.at = NOW

    async with Client(_server(container, actor)) as client:
        await _make_ambition(client, dream)
        await _make_ambition(client, kept)
        stored = container.tasks.get(actor, dream.id)
        container.tasks.update(
            actor,
            dream.id,
            version=stored.version,
            idempotency_key=f"ambition-{uuid4().hex}",
            command=UpdateTaskCommand(status=TaskStatus.COMPLETED),
        )
        ambitions = await client.call_tool("list_tasks", {"ambitions": True})
        completed = await client.call_tool("list_tasks", {"status": "completed"})

    assert [row["id"] for row in ambitions.structured_content["tasks"]] == [str(kept.id)]
    assert [row["id"] for row in completed.structured_content["tasks"]] == [str(dream.id)]

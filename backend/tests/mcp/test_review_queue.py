"""get_review_queue: the open Tasks a review brings up, quickest decisions first, for voice.

The clock is fixed through the Task service, so Tasks can be created "long ago" and then read at
`NOW`. Line 1 of the text is the spoken sentence: no id, no ISO time and no card note.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.mcp.instrument import instrument_mcp
from sidekick.mcp.review import register_review_tools
from sidekick.mcp.text import CARD_NOTE
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.types import Actor
from sidekick.tasks.application.models import NewTaskItem, UpdateTaskCommand
from sidekick.tasks.application.review import MAX_REVIEW_PAGE
from sidekick.tasks.domain import Priority, Task
from tests.db import database_factory
from tests.support.settings import make_settings

ZONE = ZoneInfo("Europe/Stockholm")
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=ZONE)
LONG_AGO = NOW - timedelta(days=90)
SCOPES = frozenset({"tasks:read", "tasks:write", "projects:read", "projects:write"})


class MovableClock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


def _setup(username: str = "review-owner") -> tuple[Container, Actor, MovableClock]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(username, "Review Owner")
    clock = MovableClock(LONG_AGO)
    container.tasks.clock = clock
    return container, Actor(owner, SCOPES), clock


def _server(container: Container, actor: Actor) -> FastMCP:
    mcp = FastMCP("review-queue-test")
    register_review_tools(
        mcp, ToolContext(container, lambda: actor, lambda name: instrument_mcp(container, name))
    )
    return mcp


def _task(container: Container, actor: Actor, title: str, **fields: Any) -> Task:
    return container.tasks.create(
        actor, title=title, idempotency_key=f"review-{uuid4().hex}", **fields
    )


async def _queue(client: Client[Any], **arguments: Any) -> Any:
    return await client.call_tool("get_review_queue", arguments, raise_on_error=False)


def _lines(result: Any) -> list[str]:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text.splitlines()


def _ids(result: Any) -> list[str]:
    return [row["id"] for row in result.structured_content["tasks"]]


def _seed_buckets(container: Container, actor: Actor, clock: MovableClock) -> dict[str, Task]:
    """One Task per bucket, created 90 days before `NOW`; the clock is left at `NOW`."""

    batch = container.task_bulk.create_batch(
        actor,
        [NewTaskItem("Alla steg klara", None, Priority.NORMAL, (), ("Ett", "Två"))],
        idempotency_key=f"review-batch-{uuid4().hex}",
    )
    done_task = batch.tasks[0]
    for step in done_task.steps:
        container.steps.complete_step(
            actor,
            UUID(step["id"]),
            version=step["version"],
            idempotency_key=f"review-step-{uuid4().hex}",
        )
    tasks = {
        "likely_done": container.tasks.get(actor, done_task.task.id),
        "long_overdue": _task(container, actor, "Länge försenad", due_at=NOW - timedelta(days=35)),
        "overdue": _task(container, actor, "Lite försenad", due_at=NOW - timedelta(days=3)),
        "old_other": _task(container, actor, "Gammal och odaterad"),
    }
    waiting = _task(container, actor, "Väntar på svar")
    tasks["follow_up_due"] = container.tasks.update(
        actor,
        waiting.id,
        version=waiting.version,
        idempotency_key=f"review-wait-{uuid4().hex}",
        command=_waiting(NOW - timedelta(days=2)),
    )
    clock.at = NOW
    tasks["other"] = _task(container, actor, "Helt ny", due_at=NOW + timedelta(days=5))
    return tasks


def _waiting(follow_up: datetime) -> UpdateTaskCommand:
    return UpdateTaskCommand(waiting_since=LONG_AGO, follow_up_at=follow_up)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_queue_serves_the_buckets_in_order_with_a_spoken_first_line() -> None:
    container, actor, clock = _setup()
    tasks = _seed_buckets(container, actor, clock)

    async with Client(_server(container, actor)) as client:
        queue = await _queue(client)

    assert not queue.is_error, queue.structured_content
    content = queue.structured_content
    assert [row["bucket"] for row in content["tasks"]] == [
        "likely_done",
        "long_overdue",
        "follow_up_due",
        "overdue",
    ]
    assert _ids(queue) == [
        str(tasks[name].id) for name in ("likely_done", "long_overdue", "follow_up_due", "overdue")
    ]
    assert content["remaining_total"] == 4
    assert content["bucket_counts"] == {
        "likely_done": 1,
        "long_overdue": 1,
        "follow_up_due": 1,
        "overdue": 1,
    }
    assert [row["reason"] for row in content["tasks"]] == [
        "all steps done",
        "overdue 5 weeks",
        "follow-up due 2 days ago",
        "overdue 3 days",
    ]
    lines = _lines(queue)
    assert lines[0] == ("4 to review: 1 likely done, 1 long overdue, 1 follow-up due, 1 overdue.")
    # Line 1 is read aloud: no id, no ISO time; the reply opens no card, so no card note.
    assert not re.search(r"[0-9a-f]{8}-|\d{4}-\d{2}-\d{2}", lines[0])
    assert CARD_NOTE not in "\n".join(lines)
    assert lines[1].startswith(f"- {tasks['likely_done'].id} v")
    assert "Alla steg klara" in lines[1] and "all steps done" in lines[1]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_scope_all_adds_the_tasks_in_no_bucket_last() -> None:
    container, actor, clock = _setup()
    tasks = _seed_buckets(container, actor, clock)

    async with Client(_server(container, actor)) as client:
        queue = await _queue(client, scope="all")

    content = queue.structured_content
    assert content["remaining_total"] == 6
    # Old ordinary Tasks are "other", last, with a neutral reason: nothing is called stale.
    last_two = content["tasks"][-2:]
    assert [row["id"] for row in last_two] == [str(tasks["other"].id), str(tasks["old_other"].id)]
    assert [row["bucket"] for row in last_two] == ["other", "other"]
    assert [row["reason"] for row in last_two] == ["due 20 November", "no due date"]
    assert content["bucket_counts"]["other"] == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_completed_tasks_and_tasks_in_no_bucket_are_not_suggested() -> None:
    container, actor, clock = _setup()
    late = _task(container, actor, "Försenad", due_at=NOW - timedelta(days=3))
    _task(container, actor, "Gammal")
    done = _task(container, actor, "Klar", due_at=NOW - timedelta(days=3))
    clock.at = NOW
    _task(container, actor, "Alldeles ny")
    container.tasks.complete(
        actor, done.id, version=done.version, idempotency_key=f"review-{uuid4().hex}"
    )

    async with Client(_server(container, actor)) as client:
        queue = await _queue(client)

    assert _ids(queue) == [str(late.id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_page_is_bounded_and_paging_is_stable_while_tasks_leave_the_queue() -> None:
    container, actor, clock = _setup()
    tasks = [
        _task(container, actor, f"Försenad {number:02d}", due_at=NOW - timedelta(days=30 + number))
        for number in range(30)
    ]
    clock.at = NOW
    # Earliest due date first inside one bucket and context.
    expected = [str(task.id) for task in reversed(tasks)]

    async with Client(_server(container, actor)) as client:
        with pytest.raises(ToolError):
            await client.call_tool("get_review_queue", {"limit": MAX_REVIEW_PAGE + 1})
        first = await _queue(client, limit=MAX_REVIEW_PAGE)
        assert len(first.structured_content["tasks"]) == MAX_REVIEW_PAGE
        small = await _queue(client, limit=4)
        assert _ids(small) == expected[:4]
        # Two Tasks of the first page and one of the next leave the queue (completed elsewhere).
        for task_id in (expected[0], expected[2], expected[5]):
            task = container.tasks.get(actor, UUID(task_id))
            container.tasks.complete(
                actor, task.id, version=task.version, idempotency_key=f"review-{uuid4().hex}"
            )
        cursor = small.structured_content["next_cursor"]
        second = await _queue(client, limit=4, cursor=cursor)
        assert second.structured_content["remaining_total"] == 27
        seen = _ids(small)
        while cursor is not None:
            page = await _queue(client, limit=4, cursor=cursor)
            seen.extend(_ids(page))
            cursor = page.structured_content["next_cursor"]

    assert _ids(second) == [expected[4], *expected[6:9]]
    assert seen == [task_id for task_id in expected if task_id != expected[5]]
    assert len(seen) == len(set(seen))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_cursor_of_another_scope_or_owner_is_refused() -> None:
    container, actor, clock = _setup()
    for number in range(3):
        _task(container, actor, f"Försenad {number}", due_at=NOW - timedelta(days=3))
    clock.at = NOW
    other = Actor(container.auth.provision_user("review-other", "Other"), SCOPES)

    async with Client(_server(container, actor)) as client:
        page = await _queue(client, limit=1)
        cursor = page.structured_content["next_cursor"]
        wrong_scope = await _queue(client, limit=1, cursor=cursor, scope="all")
    async with Client(_server(container, other)) as client:
        wrong_owner = await _queue(client, limit=1, cursor=cursor)

    for refused in (wrong_scope, wrong_owner):
        assert refused.is_error
        assert refused.structured_content["code"] == "validation_error"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_owners_tasks_never_appear_and_tasks_read_is_required() -> None:
    container, actor, clock = _setup()
    _task(container, actor, "Ägarens uppgift")
    other_owner = container.auth.provision_user("review-stranger", "Stranger")
    stranger = Actor(other_owner, SCOPES)
    clock.at = NOW

    async with Client(_server(container, stranger)) as client:
        empty = await _queue(client)
    async with Client(
        _server(container, Actor(actor.user_id, frozenset({"tasks:write"})))
    ) as client:
        denied = await _queue(client)

    assert empty.structured_content["tasks"] == []
    assert empty.structured_content["remaining_total"] == 0
    assert _lines(empty)[0] == "Nothing left to review."
    assert denied.is_error
    assert denied.structured_content["code"] == "forbidden"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_context_names_need_projects_read_and_no_title_reaches_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    container, actor, clock = _setup()
    domain = container.contexts.create_domain(
        actor, name="Huset", description=None, idempotency_key=f"review-{uuid4().hex}"
    )
    project = container.projects.create(
        actor, title="Altanen", domain_id=domain.id, idempotency_key=f"review-{uuid4().hex}"
    )
    task = _task(
        container, actor, "Hemlig altantitel", project_id=project.id, due_at=NOW - timedelta(days=3)
    )
    clock.at = NOW
    caplog.set_level(logging.DEBUG)

    async with Client(_server(container, actor)) as client:
        named = await _queue(client)
    async with Client(
        _server(container, Actor(actor.user_id, frozenset({"tasks:read"})))
    ) as client:
        unnamed = await _queue(client)

    row = named.structured_content["tasks"][0]
    assert row["id"] == str(task.id)
    assert (row["project_title"], row["domain_name"]) == ("Altanen", "Huset")
    assert row["domain_id"] == str(domain.id)
    assert "Altanen" in _lines(named)[1]
    bare = unnamed.structured_content["tasks"][0]
    assert bare["project_title"] is None and bare["domain_name"] is None
    assert "Altanen" not in "\n".join(_lines(unnamed)) and "Huset" not in str(unnamed.content)
    assert "Hemlig altantitel" not in caplog.text
    assert "Altanen" not in caplog.text

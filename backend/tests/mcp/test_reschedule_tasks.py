"""reschedule_tasks: move 1 to 20 Task due dates in one atomic, retry-safe call.

Each item carries its own `when` ("tomorrow", "next_week", "clear" or a bare date). The new due
date is 23:59 in `Settings.owner_zone`. A stale version rejects the whole call and nothing moves.
The clock is fixed through the Task service, so the owner's calendar day is deterministic.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.mcp.instrument import instrument_mcp
from sidekick.mcp.reschedule import MAX_RESCHEDULE_TASKS, register_reschedule_tools
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import Actor
from sidekick.tasks.application.models import RescheduleTaskItem
from sidekick.tasks.domain import Task
from tests.db import database_factory
from tests.support.settings import make_settings

OWNER_ZONE = ZoneInfo("Europe/Stockholm")
THURSDAY_NOON = datetime(2026, 10, 29, 12, 0, tzinfo=OWNER_ZONE)
MONDAY_NOON = datetime(2026, 11, 2, 12, 0, tzinfo=OWNER_ZONE)
SCOPES = frozenset({"tasks:read", "tasks:write"})


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _setup(
    now: datetime = THURSDAY_NOON, scopes: frozenset[str] = SCOPES
) -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("reschedule-owner", "Reschedule Owner")
    container.tasks.clock = FixedClock(now)
    return container, Actor(owner, scopes)


def _server(container: Container, actor: Actor) -> FastMCP:
    mcp = FastMCP("reschedule-test")
    register_reschedule_tools(
        mcp, ToolContext(container, lambda: actor, lambda name: instrument_mcp(container, name))
    )
    return mcp


def _make_task(
    container: Container, actor: Actor, title: str, due_at: datetime | None = None
) -> Task:
    return container.tasks.create(
        actor, title=title, idempotency_key=f"reschedule-{uuid4().hex}", due_at=due_at
    )


async def _reschedule(client: Client[Any], items: list[dict[str, Any]], key: str) -> Any:
    return await client.call_tool(
        "reschedule_tasks",
        {"items": items, "idempotency_key": key},
        raise_on_error=False,
    )


def _item(task: Task, when: str, version: int | None = None) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "expected_version": task.version if version is None else version,
        "when": when,
    }


def _text_lines(result: Any) -> list[str]:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text.splitlines()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tomorrow_sets_2359_the_next_day_and_reports_each_new_version() -> None:
    container, actor = _setup()
    first = _make_task(
        container, actor, "Betala räkningen", datetime(2026, 10, 27, 9, 0, tzinfo=OWNER_ZONE)
    )
    second = _make_task(container, actor, "Ring Sara")

    async with Client(_server(container, actor)) as client:
        moved = await _reschedule(
            client, [_item(first, "tomorrow"), _item(second, "tomorrow")], "triage-tomorrow-1"
        )

    assert not moved.is_error, moved.structured_content
    assert moved.structured_content is not None
    assert moved.structured_content["count"] == 2
    expected = datetime(2026, 10, 30, 23, 59, tzinfo=OWNER_ZONE)
    for record, task in zip(moved.structured_content["tasks"], [first, second], strict=True):
        assert record["id"] == str(task.id)
        assert record["version"] == task.version + 1
        assert datetime.fromisoformat(record["due_at"]) == expected
    lines = _text_lines(moved)
    assert lines[0] == "Moved Betala räkningen and Ring Sara to tomorrow."
    assert len(lines) == 3
    assert f"{first.id} version {first.version + 1}" in lines[1]
    assert f"{second.id} version {second.version + 1}" in lines[2]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("now", "expected_day"),
    [
        # Thursday 2026-10-29: the Monday of next week is 2026-11-02.
        (THURSDAY_NOON, datetime(2026, 11, 2, 23, 59, tzinfo=OWNER_ZONE)),
        # On a Monday, next week is the Monday after, never today.
        (MONDAY_NOON, datetime(2026, 11, 9, 23, 59, tzinfo=OWNER_ZONE)),
    ],
)
async def test_next_week_is_the_monday_after_the_owner_day(
    now: datetime, expected_day: datetime
) -> None:
    container, actor = _setup(now)
    task = _make_task(container, actor, "Städa garaget")

    async with Client(_server(container, actor)) as client:
        moved = await _reschedule(client, [_item(task, "next_week")], "triage-next-week-1")

    assert not moved.is_error, moved.structured_content
    assert moved.structured_content is not None
    record = moved.structured_content["tasks"][0]
    assert datetime.fromisoformat(record["due_at"]) == expected_day
    assert _text_lines(moved)[0] == f"Moved Städa garaget to Monday {expected_day.day} November."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_clear_removes_the_due_date() -> None:
    container, actor = _setup()
    task = _make_task(
        container, actor, "Utan brådska", datetime(2026, 10, 25, 23, 59, tzinfo=OWNER_ZONE)
    )

    async with Client(_server(container, actor)) as client:
        cleared = await _reschedule(client, [_item(task, "clear")], "triage-clear-1")

    assert not cleared.is_error, cleared.structured_content
    assert cleared.structured_content is not None
    record = cleared.structured_content["tasks"][0]
    assert record["due_at"] is None
    assert record["version"] == task.version + 1
    assert _text_lines(cleared)[0] == "Cleared the due date on Utan brådska."
    stored = container.tasks.get(actor, task.id)
    assert stored.due_at is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bare_date_means_end_of_that_day_and_mixed_whens_use_a_neutral_summary() -> None:
    container, actor = _setup()
    dated = _make_task(container, actor, "Lämna in deklarationen")
    tomorrow = _make_task(container, actor, "Hämta paketet")

    async with Client(_server(container, actor)) as client:
        moved = await _reschedule(
            client,
            [_item(dated, "2026-11-05"), _item(tomorrow, "tomorrow")],
            "triage-mixed-1",
        )

    assert not moved.is_error, moved.structured_content
    assert moved.structured_content is not None
    dated_record, tomorrow_record = moved.structured_content["tasks"]
    assert datetime.fromisoformat(dated_record["due_at"]) == datetime(
        2026, 11, 5, 23, 59, tzinfo=OWNER_ZONE
    )
    assert datetime.fromisoformat(tomorrow_record["due_at"]) == datetime(
        2026, 10, 30, 23, 59, tzinfo=OWNER_ZONE
    )
    assert _text_lines(moved)[0] == "Rescheduled Lämna in deklarationen and Hämta paketet."

    single = _make_task(container, actor, "Ett datum")
    async with Client(_server(container, actor)) as client:
        dated_only = await _reschedule(client, [_item(single, "2026-11-06")], "triage-date-1")
    assert _text_lines(dated_only)[0] == "Moved Ett datum to Friday 6 November."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_version_rolls_back_the_whole_batch() -> None:
    container, actor = _setup()
    fresh = _make_task(
        container, actor, "Korrekt version", datetime(2026, 10, 27, 9, 0, tzinfo=OWNER_ZONE)
    )
    stale = _make_task(container, actor, "Inaktuell version")
    before = container.tasks.get(actor, fresh.id)

    async with Client(_server(container, actor)) as client:
        rejected = await _reschedule(
            client,
            [_item(fresh, "tomorrow"), _item(stale, "tomorrow", version=stale.version + 5)],
            "triage-stale-1",
        )

    assert rejected.is_error
    assert rejected.structured_content is not None
    assert rejected.structured_content["code"] == "conflict"
    assert rejected.structured_content["reason"] == "stale_version"
    after = container.tasks.get(actor, fresh.id)
    assert after.version == before.version
    assert after.due_at == before.due_at
    assert container.tasks.get(actor, stale.id).version == stale.version


@pytest.mark.asyncio
@pytest.mark.integration
async def test_twenty_items_are_accepted_and_twenty_one_are_rejected_before_any_write() -> None:
    container, actor = _setup()
    tasks = [
        _make_task(container, actor, f"Post {number}") for number in range(MAX_RESCHEDULE_TASKS)
    ]

    async with Client(_server(container, actor)) as client:
        too_many = [
            {"task_id": str(uuid4()), "expected_version": 1, "when": "tomorrow"}
            for _ in range(MAX_RESCHEDULE_TASKS + 1)
        ]
        with pytest.raises(ToolError):
            await client.call_tool(
                "reschedule_tasks",
                {"items": too_many, "idempotency_key": "triage-too-many-1"},
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "reschedule_tasks",
                {"items": [], "idempotency_key": "triage-empty-1"},
            )

        moved = await _reschedule(
            client, [_item(task, "tomorrow") for task in tasks], "triage-twenty-1"
        )

    assert not moved.is_error, moved.structured_content
    assert moved.structured_content is not None
    assert moved.structured_content["count"] == MAX_RESCHEDULE_TASKS
    assert _text_lines(moved)[0] == "Moved Post 0, Post 1, Post 2 and 17 more to tomorrow."


@pytest.mark.integration
def test_the_service_refuses_twenty_one_items_without_writing_any_task() -> None:
    # The MCP schema is one guard; the service must refuse the same batch for any other caller.
    container, actor = _setup()
    tasks = [
        _make_task(container, actor, f"Servicepost {number}")
        for number in range(MAX_RESCHEDULE_TASKS)
    ]
    items = [
        RescheduleTaskItem(task_id=task.id, expected_version=task.version, due_at=None)
        for task in tasks
    ]
    items.append(RescheduleTaskItem(task_id=uuid4(), expected_version=1, due_at=None))

    with pytest.raises(ValidationError):
        container.task_bulk.reschedule(actor, items, idempotency_key="service-too-many-1")

    assert [container.tasks.get(actor, task.id).version for task in tasks] == [
        task.version for task in tasks
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_same_idempotency_key_returns_the_committed_result_without_a_new_version() -> (
    None
):
    container, actor = _setup()
    task = _make_task(
        container, actor, "Retry-säker", datetime(2026, 10, 27, 9, 0, tzinfo=OWNER_ZONE)
    )
    items = [_item(task, "tomorrow")]

    async with Client(_server(container, actor)) as client:
        first = await _reschedule(client, items, "triage-retry-1")
        replayed = await _reschedule(client, items, "triage-retry-1")
        conflicting = await _reschedule(client, [_item(task, "clear")], "triage-retry-1")

    assert not first.is_error, first.structured_content
    assert not replayed.is_error, replayed.structured_content
    assert replayed.structured_content == first.structured_content
    assert container.tasks.get(actor, task.id).version == task.version + 1
    assert conflicting.is_error
    assert conflicting.structured_content is not None
    assert conflicting.structured_content["code"] == "conflict"
    assert container.tasks.get(actor, task.id).due_at == datetime(
        2026, 10, 30, 23, 59, tzinfo=OWNER_ZONE
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_without_tasks_write_the_call_is_forbidden_and_nothing_moves() -> None:
    container, owner_actor = _setup()
    task = _make_task(
        container, owner_actor, "Skyddad", datetime(2026, 10, 27, 9, 0, tzinfo=OWNER_ZONE)
    )
    reader = Actor(owner_actor.user_id, frozenset({"tasks:read"}))

    async with Client(_server(container, reader)) as client:
        denied = await _reschedule(client, [_item(task, "tomorrow")], "triage-denied-1")

    assert denied.is_error
    assert denied.structured_content is not None
    assert denied.structured_content["code"] == "forbidden"
    assert container.tasks.get(owner_actor, task.id).version == task.version

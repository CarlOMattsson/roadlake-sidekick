"""A bare due date means end of that day: 23:59 in the owner's zone, never 00:00.

Datetimes with an offset are stored as the caller sent them. create_task and update_task share
one helper (end_of_day_due_at), so both tools behave the same way.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from sidekick.structured.work_records import TaskChanges, end_of_day_due_at
from tests.db import database_factory
from tests.support.settings import make_settings

STOCKHOLM = ZoneInfo("Europe/Stockholm")
SCOPES = frozenset({"projects:read", "tasks:read", "tasks:write"})


def _task(structured: dict[str, Any] | None) -> dict[str, Any]:
    assert structured is not None
    task: dict[str, Any] = structured["task"]
    return task


def test_bare_date_becomes_2359_in_the_owner_zone() -> None:
    due = end_of_day_due_at(date(2026, 11, 2), STOCKHOLM)

    assert due == datetime(2026, 11, 2, 23, 59, tzinfo=STOCKHOLM)
    assert due is not None
    assert due.tzinfo is not None
    assert due.utcoffset() == timedelta(hours=1)  # CET after the October switch


def test_bare_date_uses_the_zone_it_is_given() -> None:
    new_york = ZoneInfo("America/New_York")

    due = end_of_day_due_at(date(2026, 11, 2), new_york)

    assert due == datetime(2026, 11, 2, 23, 59, tzinfo=new_york)


def test_datetime_with_offset_is_unchanged() -> None:
    sent = datetime(2026, 11, 2, 9, 30, tzinfo=timezone(timedelta(hours=2)))

    due = end_of_day_due_at(sent, STOCKHOLM)

    assert due == sent
    assert due is not None
    assert due.utcoffset() == timedelta(hours=2)


def test_null_stays_null() -> None:
    assert end_of_day_due_at(None, STOCKHOLM) is None


def test_task_changes_reads_a_bare_date_then_the_helper_gives_end_of_day() -> None:
    changes = TaskChanges.model_validate({"due_at": "2026-11-02"})
    patch = changes.model_dump(exclude_unset=True)

    assert end_of_day_due_at(patch["due_at"], STOCKHOLM) == datetime(
        2026, 11, 2, 23, 59, tzinfo=STOCKHOLM
    )


def test_task_changes_reads_a_bare_date_from_json() -> None:
    changes = TaskChanges.model_validate_json('{"due_at": "2026-11-02"}')

    assert end_of_day_due_at(changes.due_at, STOCKHOLM) == datetime(
        2026, 11, 2, 23, 59, tzinfo=STOCKHOLM
    )


def test_task_changes_keeps_a_datetime_with_offset() -> None:
    changes = TaskChanges.model_validate({"due_at": "2026-11-02T09:30:00+02:00"})

    assert changes.due_at == datetime(2026, 11, 2, 9, 30, tzinfo=timezone(timedelta(hours=2)))
    assert isinstance(changes.due_at, datetime)
    assert changes.due_at.utcoffset() == timedelta(hours=2)


@pytest.mark.parametrize("bad", ["nope", "2026-13-40", "2026-W44-1", "02-11-2026"])
def test_invalid_due_at_is_rejected_as_before(bad: str) -> None:
    with pytest.raises(ValidationError):
        TaskChanges.model_validate({"due_at": bad})


@pytest.mark.asyncio
async def test_create_task_rejects_an_invalid_due_at() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)

    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_task",
                {"title": "bad date", "idempotency_key": "due-invalid-0001", "due_at": "nope"},
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_and_update_task_store_a_bare_date_as_end_of_day() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, SCOPES)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    expected = datetime(2026, 11, 2, 23, 59, tzinfo=STOCKHOLM)

    async with Client(server) as client:
        created = await client.call_tool(
            "create_task",
            {
                "title": "bare date",
                "idempotency_key": "due-bare-create-0001",
                "due_at": "2026-11-02",
            },
        )
        task = _task(created.structured_content)
        assert datetime.fromisoformat(task["due_at"]) == expected

        updated = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "due-bare-update-0001",
                "changes": {"due_at": "2026-11-05"},
            },
        )
    assert datetime.fromisoformat(_task(updated.structured_content)["due_at"]) == datetime(
        2026, 11, 5, 23, 59, tzinfo=STOCKHOLM
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_task_keeps_a_datetime_with_offset() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, SCOPES)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    sent = datetime(2026, 11, 2, 9, 30, tzinfo=timezone(timedelta(hours=2)))

    async with Client(server) as client:
        created = await client.call_tool(
            "create_task",
            {
                "title": "offset date",
                "idempotency_key": "due-offset-create-0001",
                "due_at": "2026-11-02T09:30:00+02:00",
            },
        )

    assert datetime.fromisoformat(_task(created.structured_content)["due_at"]) == sent

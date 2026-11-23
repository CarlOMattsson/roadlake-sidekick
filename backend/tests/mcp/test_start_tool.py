"""get_start: the Start view in one call, scope-aware, bounded and safe when a part fails.

The clock is fixed so the owner's day in `Settings.owner_zone` is deterministic. Titles, names and
the secret in a failing source's message must never reach a log or the spoken line.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.automation_rows import insert_automation, insert_run, insert_suggestion
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401  (the `all_logs` fixture)
    _Collector,
)
from tests.support.settings import make_settings

ZONE = ZoneInfo("Europe/Stockholm")
TODAY = "2026-11-23"
NOON = datetime(2026, 11, 23, 12, 0, tzinfo=ZONE)
WRITER = frozenset(
    {"tasks:read", "tasks:write", "contacts:read", "contacts:write", "projects:read"}
)
EVERYTHING = WRITER | {"automation:read", "start:read"}
SECRET = "the-secret-in-the-failing-source"


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _setup(**settings: Any) -> tuple[Container, UUID]:
    container = create_container(make_settings().model_copy(update=settings), database_factory())
    owner = container.auth.provision_user("start-owner", "Start Owner")
    container.work_lists.clock = FixedClock(NOON)
    return container, owner


def _server(container: Container, actor: Actor) -> Any:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _data(result: Any) -> dict[str, Any]:
    assert result.structured_content is not None
    return result.structured_content


def _text(result: Any) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def _task(client: Client, title: str, due_at: str, key: str) -> dict[str, Any]:
    created = await client.call_tool(
        "create_task", {"title": title, "due_at": due_at, "idempotency_key": f"start-{key}"}
    )
    return _data(created)["task"]


async def _wait_on(client: Client, task: dict[str, Any], contact_id: str, since: str) -> None:
    await client.call_tool(
        "update_task",
        {
            "task_id": task["id"],
            "version": task["version"],
            "idempotency_key": f"start-wait-{task['id']}",
            "changes": {"waiting_since": since, "waiting_on_contact_id": contact_id},
        },
    )


async def _seed(container: Container, owner: UUID) -> None:
    """Two tasks on the day, one overdue, one waiting nine days on a contact, three suggestions."""

    async with Client(_server(container, Actor(owner, WRITER))) as client:
        await _task(client, "Overdue invoice", "2026-11-20T09:00:00+01:00", "overdue")
        await _task(client, "Call the printer", "2026-11-23T18:00:00+01:00", "today")
        waiting = await _task(client, "Await the quote", "2026-12-20T09:00:00+01:00", "waiting")
        contact = await client.call_tool(
            "create_contact", {"display_name": "Erik Holm", "idempotency_key": "start-erik"}
        )
        await _wait_on(
            client, waiting, _data(contact)["contact"]["id"], "2026-11-14T09:00:00+01:00"
        )
    with container.session_factory.begin() as session:
        connection = session.connection()
        automation = insert_automation(connection, str(owner), title="Morning mail")
        run = insert_run(connection, str(owner), automation, state="done")
        for _ in range(3):
            insert_suggestion(connection, str(owner), automation, run)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_empty_day_has_a_day_and_no_part() -> None:
    container, owner = _setup()
    async with Client(_server(container, Actor(owner, EVERYTHING))) as client:
        start = await client.call_tool("get_start", {})

    assert _data(start) == {"day": TODAY}
    assert _text(start) == "Inget att visa på startvyn."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_parts_show_the_owners_day_in_bounded_rows() -> None:
    container, owner = _setup()
    await _seed(container, owner)
    async with Client(_server(container, Actor(owner, EVERYTHING))) as client:
        start = await client.call_tool("get_start", {})

    data = _data(start)
    assert data["day"] == TODAY
    assert (data["today"]["overdue_count"], data["today"]["today_count"]) == (1, 1)
    assert [row["title"] for row in data["today"]["items"]] == [
        "Overdue invoice",
        "Call the printer",
    ]
    waiting = data["waiting"]
    assert waiting["total"] == 1
    assert (waiting["items"][0]["contact_name"], waiting["items"][0]["days"]) == ("Erik Holm", 9)
    assert data["suggestions"] == {"pending_count": 3, "automation_count": 1}
    assert data["more"] == {"contacts": 1}
    assert data["insight"] == {
        "code": "waiting_long",
        "written_by": "system",
        "text": "Du har väntat på Erik Holm i 9 dagar.",
    }
    assert "unavailable" not in data
    assert "owner_id" not in str(data)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_spoken_line_holds_counts_only() -> None:
    container, owner = _setup()
    await _seed(container, owner)
    async with Client(_server(container, Actor(owner, EVERYTHING))) as client:
        start = await client.call_tool("get_start", {})

    assert _text(start) == "2 idag · 3 förslag · 1 väntar"
    for private in ("Overdue invoice", "Call the printer", "Await the quote", "Holm", "Morning"):
        assert private not in _text(start)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_spoken_line_follows_the_app_language() -> None:
    container, owner = _setup(mcp_app_locale="en")
    await _seed(container, owner)
    async with Client(_server(container, Actor(owner, EVERYTHING))) as client:
        start = await client.call_tool("get_start", {})

    assert _text(start) == "2 today · 3 suggestions · 1 waiting"
    assert _data(start)["insight"]["text"] == "You have been waiting for Erik Holm for 9 days."


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("scopes", "present", "absent"),
    [
        (frozenset(), set(), {"today", "waiting", "suggestions", "more", "insight"}),
        (frozenset({"tasks:read"}), {"today", "waiting"}, {"suggestions", "more", "insight"}),
        (frozenset({"automation:read"}), {"suggestions"}, {"today", "waiting", "more", "insight"}),
        (frozenset({"contacts:read"}), {"more"}, {"today", "waiting", "suggestions"}),
        (
            frozenset({"start:read", "start:write", "journal:read"}),
            set(),
            {"today", "waiting", "suggestions", "more"},
        ),
    ],
)
async def test_a_part_is_left_out_without_the_read_scope_of_what_it_shows(
    scopes: frozenset[str], present: set[str], absent: set[str]
) -> None:
    container, owner = _setup()
    await _seed(container, owner)
    async with Client(_server(container, Actor(owner, scopes))) as client:
        start = await client.call_tool("get_start", {})

    data = _data(start)
    assert not start.is_error
    assert present <= set(data)
    assert not absent & set(data)
    assert "Holm" not in str(data) or "contacts:read" in scopes


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_waiting_task_names_no_contact_without_the_contacts_scope() -> None:
    container, owner = _setup()
    await _seed(container, owner)
    async with Client(_server(container, Actor(owner, frozenset({"tasks:read"})))) as client:
        start = await client.call_tool("get_start", {})

    row = _data(start)["waiting"]["items"][0]
    assert row["contact_name"] is None
    assert "Holm" not in str(_data(start))
    assert "insight" not in _data(start)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_room_that_is_off_takes_its_part_away_even_with_the_scope() -> None:
    container, owner = _setup()
    await _seed(container, owner)
    work_only = replace(
        container, settings=container.settings.model_copy(update={"enabled_rooms": "work"})
    )
    async with Client(_server(work_only, Actor(owner, EVERYTHING))) as client:
        start = await client.call_tool("get_start", {})

    data = _data(start)
    assert "today" in data
    assert "more" not in data
    assert "Holm" not in str(data)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_owners_records_are_never_part_of_the_view() -> None:
    container, owner = _setup()
    await _seed(container, owner)
    other = container.auth.provision_user("start-other", "Other Owner")
    async with Client(_server(container, Actor(other, EVERYTHING))) as client:
        start = await client.call_tool("get_start", {})

    assert _data(start) == {"day": TODAY}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_failing_part_is_named_the_rest_stands_and_the_log_holds_no_content(
    all_logs: _Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, owner = _setup()
    await _seed(container, owner)

    def broken(actor: Actor) -> object:
        raise RuntimeError(f"{SECRET} Erik Holm Overdue invoice")

    monkeypatch.setattr(container.automation_activity, "pending", broken)
    async with Client(_server(container, Actor(owner, EVERYTHING))) as client:
        start = await client.call_tool("get_start", {})

    data = _data(start)
    assert not start.is_error
    assert data["unavailable"] == [{"part": "suggestions", "error": "unavailable"}]
    assert "suggestions" not in data
    assert data["today"]["today_count"] == 1
    assert data["waiting"]["total"] == 1
    failure = next(
        record for record in all_logs.records if record.getMessage() == "start_part_unavailable"
    )
    assert failure.__dict__["error_type"] == "RuntimeError"
    assert failure.__dict__["operation"] == "get_start.suggestions"
    assert failure.__dict__["correlation_id"]
    assert failure.exc_info is None
    rendered = all_logs.rendered()
    for private in (SECRET, "Holm", "Overdue invoice", "Call the printer", "Morning mail"):
        assert private not in rendered
    assert SECRET not in str(data) + _text(start)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_view_changes_nothing() -> None:
    container, owner = _setup()
    await _seed(container, owner)
    async with Client(_server(container, Actor(owner, EVERYTHING))) as client:
        first = await client.call_tool("get_start", {})
        second = await client.call_tool("get_start", {})
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert _data(first) == _data(second)
    annotations = tools["get_start"].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_project_title_is_shown_only_to_a_caller_who_may_read_projects() -> None:
    container, owner = _setup()
    async with Client(_server(container, Actor(owner, EVERYTHING | {"projects:write"}))) as client:
        domain = _data(
            await client.call_tool(
                "create_domain", {"name": "Home", "idempotency_key": "proj-title-dom"}
            )
        )["domain"]
        project = _data(
            await client.call_tool(
                "create_project",
                {
                    "domain_id": domain["id"],
                    "title": "Secret garden",
                    "idempotency_key": "proj-title-prj",
                },
            )
        )["project"]
        await client.call_tool(
            "create_task",
            {
                "title": "Water the beds",
                "due_at": "2026-11-23T18:00:00+01:00",
                "project_id": project["id"],
                "idempotency_key": "proj-title-task",
            },
        )

    async with Client(_server(container, Actor(owner, EVERYTHING))) as client:
        allowed = _data(await client.call_tool("get_start", {}))
    async with Client(_server(container, Actor(owner, frozenset({"tasks:read"})))) as client:
        denied = _data(await client.call_tool("get_start", {}))

    assert allowed["today"]["items"][0]["project_title"] == "Secret garden"
    assert denied["today"]["items"][0]["title"] == "Water the beds"
    assert denied["today"]["items"][0]["project_title"] is None
    assert "Secret garden" not in str(denied)

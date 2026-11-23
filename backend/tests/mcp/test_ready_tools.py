"""The ready conversation tools through a real FastMCP client and a real database.

The owner's Claude drafts a conversation, the Start view offers it from its local time, starting
it composes the summary from the owner's records when it is called, and a skip (or its undo) moves
one day. The clock is fixed so the owner's day in `Settings.owner_zone` is deterministic. Titles,
instructions and the secret in a failing source must never reach a log, an audit row or a replay
record.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.automations.domain.spec import Cadence
from sidekick.shared.types import Actor
from sidekick.start.domain.ready import ReadyChange
from sidekick.structured.ready_records import UNVERIFIED_NOTICE, VERIFIED_NOTICE
from tests.db import database_factory
from tests.mcp.harness import SwitchableServer
from tests.support.app_origin import origin_for
from tests.support.automation_rows import insert_automation, insert_run, insert_suggestion
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401  (the `all_logs` fixture)
    _Collector,
)
from tests.support.settings import make_settings

ZONE = ZoneInfo("Europe/Stockholm")
TODAY = "2026-11-23"
NOON = datetime(2026, 11, 23, 12, 0, tzinfo=ZONE)
EVENING = datetime(2026, 11, 23, 19, 0, tzinfo=ZONE)
TITLE = "SENTINEL-TITLE evening review"
INSTRUCTION = "SENTINEL-INSTRUCTION go through my day, one question at a time"
SECRET = "the-secret-in-the-failing-source"
CADENCE = {"frequency": "daily", "local_time": "18:00"}
EVERY_INGREDIENT = [
    "tasks_done_today",
    "tasks_due_today",
    "tasks_due_tomorrow",
    "overdue",
    "waiting",
    "suggestions",
    "journal_today",
    "review",
    "automation_report",
    "shopping_open",
]
READ_SCOPES = (
    "tasks:read",
    "contacts:read",
    "projects:read",
    "journal:read",
    "shopping:read",
    "automation:read",
)
WRITE_SCOPES = (
    "tasks:write",
    "journal:write",
    "shopping:write",
    "contacts:write",
    "projects:write",
)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


@dataclass(frozen=True, slots=True)
class World:
    container: Container
    server: SwitchableServer
    clock: FixedClock
    owner_id: Any
    claude: Actor  # reads and writes ready conversations, nothing else
    everything: Actor  # also reads every room an ingredient comes from
    seeder: Actor  # writes the records the ingredients read
    stranger: Actor


def _world() -> World:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("ready-owner", "Ready Owner")
    other = container.auth.provision_user("ready-other", "Ready Other")
    clock = FixedClock(NOON)
    for service in (container.ready_conversations, container.work_lists, container.tasks):
        service.clock = clock

    def actor(*scopes: str, user: Any = owner) -> Actor:
        return Actor(user, frozenset(scopes))

    claude = actor("start:read", "start:write")
    return World(
        container,
        SwitchableServer.build(container, claude),
        clock,
        owner,
        claude=claude,
        everything=actor("start:read", "start:write", *READ_SCOPES),
        seeder=actor(*READ_SCOPES, *WRITE_SCOPES),
        stranger=actor("start:read", "start:write", *READ_SCOPES, user=other),
    )


_WRITES = {
    "save_ready_conversation",
    "start_ready_conversation",
    "skip_ready_conversation",
    "create_task",
    "create_domain",
    "create_project",
    "complete_task",
    "update_task",
    "create_contact",
    "create_journal_source",
    "create_manual_journal_entry",
    "create_shopping_list",
    "add_shopping_items",
    "set_shopping_item_purchased",
}


async def _call(world: World, actor: Actor, name: str, /, **arguments: Any) -> CallToolResult:
    if "idempotency_key" not in arguments and name in _WRITES:
        arguments["idempotency_key"] = f"ready-{uuid4().hex}"
    async with world.server.client(actor) as client:
        return await client.call_tool(name, arguments, meta=origin_for(name), raise_on_error=False)


async def _ok(world: World, actor: Actor, name: str, /, **arguments: Any) -> dict[str, Any]:
    result = await _call(world, actor, name, **arguments)
    assert not result.is_error, result.structured_content
    assert result.structured_content is not None
    return result.structured_content


def _all_text(result: CallToolResult) -> str:
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join([*texts, json.dumps(result.structured_content)])


def _code(result: CallToolResult) -> str:
    assert result.is_error and result.structured_content is not None
    return str(result.structured_content["code"])


async def _save(world: World, **changes: Any) -> dict[str, Any]:
    fields = {"title": TITLE, "instruction": INSTRUCTION, "cadence": CADENCE, **changes}
    saved = await _ok(world, world.claude, "save_ready_conversation", changes=fields)
    return saved["conversation"]


async def _seed(world: World) -> None:
    """One overdue task, one due tomorrow, one waiting on a contact, one done today, a diary entry,
    a shopping list with one open item and three pending suggestions."""

    seeder = world.seeder
    await _ok(
        world, seeder, "create_task", title="Overdue invoice", due_at="2026-11-20T09:00:00+01:00"
    )
    await _ok(
        world, seeder, "create_task", title="Call the printer", due_at="2026-11-24T10:00:00+01:00"
    )
    domain = await _ok(world, seeder, "create_domain", name="Home")
    project = await _ok(
        world, seeder, "create_project", title="House", domain_id=domain["domain"]["id"]
    )
    await _ok(
        world,
        seeder,
        "create_task",
        title="Book the painter",
        due_at="2026-11-23T21:00:00+01:00",
        project_id=project["project"]["id"],
    )
    waiting = (await _ok(world, seeder, "create_task", title="Await the quote"))["task"]
    contact = await _ok(world, seeder, "create_contact", display_name="Erik Holm")
    await _ok(
        world,
        seeder,
        "update_task",
        task_id=waiting["id"],
        version=waiting["version"],
        changes={
            "waiting_since": "2026-11-14T09:00:00+01:00",
            "waiting_on_contact_id": contact["contact"]["id"],
        },
    )
    done = (await _ok(world, seeder, "create_task", title="Send the report"))["task"]
    await _ok(world, seeder, "complete_task", task_id=done["id"], version=done["version"])
    source = await _ok(
        world,
        seeder,
        "create_journal_source",
        source_type="manual_text",
        journal_date=TODAY,
        occurred_at=f"{TODAY}T09:00:00+01:00",
        source_recorded_at=f"{TODAY}T09:05:00+01:00",
        raw_text="En kort dagboksanteckning.",
        language="sv",
    )
    await _ok(
        world,
        seeder,
        "create_manual_journal_entry",
        source_id=source["source"]["id"],
        title="Dagens post",
        summary="Kort sammanfattning.",
        key_points=[],
        project_ids=[],
        task_ids=[],
        contact_ids=[],
    )
    shopping = await _ok(world, seeder, "create_shopping_list", name="Veckohandel")
    added = await _ok(
        world,
        seeder,
        "add_shopping_items",
        list_id=shopping["shopping_list"]["id"],
        items=[{"client_ref": "a", "name": "Mjolk"}, {"client_ref": "b", "name": "Brod"}],
    )
    milk = added["items"][0]["item"]
    await _ok(
        world,
        seeder,
        "set_shopping_item_purchased",
        item_id=milk["id"],
        purchased=True,
        version=milk["version"],
    )
    with world.container.session_factory.begin() as session:
        connection = session.connection()
        automation = insert_automation(connection, str(world.owner_id), title="Morning mail")
        run = insert_run(connection, str(world.owner_id), automation, state="done")
        for _ in range(3):
            insert_suggestion(connection, str(world.owner_id), automation, run)


def _blocks(started: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {block["ingredient"]: block for block in started["blocks"]}


def _count(world: World, table: str, **where: Any) -> int:
    clause = " AND ".join(f"{column} = :{column}" for column in where) or "true"
    with world.container.session_factory.begin() as session:
        return int(
            session.execute(
                text(f"SELECT count(*) FROM sidekick.{table} WHERE {clause}"),  # noqa: S608
                where,
            ).scalar_one()
        )


# --- the schedule ----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_draft_is_listed_and_ready_only_from_its_time_on_a_cadence_day() -> None:
    world = _world()
    saved = await _save(world, kind="evening_review", ingredients=["overdue", "waiting"])

    assert (saved["state"], saved["version"], saved["ready"]) == ("active", 1, False)
    assert saved["ingredients"] == ["overdue", "waiting"]
    assert saved["cadence"]["local_time"] == "18:00"
    assert saved["day"] == TODAY

    listed = await _ok(world, world.claude, "list_ready_conversations")
    assert [item["id"] for item in listed["items"]] == [saved["id"]]
    assert listed["items"][0]["ready"] is False

    world.clock.current = EVENING
    listed = await _ok(world, world.claude, "list_ready_conversations")
    assert listed["items"][0]["ready"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_shows_a_ready_conversation_and_drops_it_once_started() -> None:
    world = _world()
    saved = await _save(world)
    world.clock.current = EVENING

    before = await _ok(world, world.claude, "get_start")
    assert before["ready"] == {
        "items": [
            {
                "id": saved["id"],
                "title": TITLE,
                "kind": "custom",
                "local_time": "18:00",
                "version": 1,
            }
        ]
    }
    await _ok(world, world.claude, "start_ready_conversation", conversation_id=saved["id"])
    after = await _ok(world, world.claude, "get_start")

    assert "ready" not in after


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_start_view_shows_at_most_two_and_the_spoken_line_counts_them() -> None:
    world = _world()
    for number in range(3):
        await _save(
            world, title=f"Review {number}", cadence={**CADENCE, "local_time": f"1{number}:00"}
        )
    world.clock.current = EVENING

    start = await _call(world, world.claude, "get_start")

    assert start.structured_content is not None
    assert [row["title"] for row in start.structured_content["ready"]["items"]] == [
        "Review 0",
        "Review 1",
    ]
    assert isinstance(start.content[0], TextContent)
    assert start.content[0].text == "2 samtal redo"
    assert "Review" not in start.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_part_needs_start_read_and_a_paused_conversation_is_not_offered() -> None:
    world = _world()
    saved = await _save(world)
    world.clock.current = EVENING
    seeder_only = await _ok(world, world.seeder, "get_start")
    assert "ready" not in seeder_only

    await _ok(
        world,
        world.claude,
        "save_ready_conversation",
        conversation_id=saved["id"],
        expected_version=1,
        changes={"paused": True},
    )

    assert "ready" not in await _ok(world, world.claude, "get_start")
    paused = await _ok(world, world.claude, "list_ready_conversations")
    assert paused["items"][0]["state"] == "paused"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_change_needs_its_version_and_the_instruction_is_emptied_only_by_clear() -> None:
    world = _world()
    saved = await _save(world)
    key = {"conversation_id": saved["id"]}

    missing = await _call(
        world, world.claude, "save_ready_conversation", changes={"title": "X"}, **key
    )
    stale = await _call(
        world,
        world.claude,
        "save_ready_conversation",
        expected_version=7,
        changes={"title": "X"},
        **key,
    )
    assert _code(missing) == "validation_error"
    assert _code(stale) == "conflict"
    assert (
        stale.structured_content is not None
        and stale.structured_content["reason"] == "stale_version"
    )

    sent_null = await _ok(
        world,
        world.claude,
        "save_ready_conversation",
        expected_version=1,
        changes={"title": "Renamed", "instruction": None},
        **key,
    )
    assert sent_null["conversation"]["instruction"] == INSTRUCTION
    assert sent_null["ignored_nulls"] == ["instruction"]
    cleared = await _ok(
        world,
        world.claude,
        "save_ready_conversation",
        expected_version=2,
        changes={},
        clear=["instruction"],
        **key,
    )
    assert cleared["conversation"]["instruction"] is None
    assert cleared["conversation"]["version"] == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_archived_conversation_is_restored_before_it_changes_and_the_cap_holds() -> None:
    world = _world()
    saved = await _save(world)
    key = {"conversation_id": saved["id"]}
    archived = await _ok(
        world,
        world.claude,
        "save_ready_conversation",
        expected_version=1,
        changes={"archived": True},
        **key,
    )
    assert archived["conversation"]["state"] == "archived"
    refused = await _call(
        world,
        world.claude,
        "save_ready_conversation",
        expected_version=2,
        changes={"title": "Again"},
        **key,
    )
    assert _code(refused) == "validation_error"
    listed = await _ok(world, world.claude, "list_ready_conversations")
    assert listed["items"] == []
    only_archived = await _ok(world, world.claude, "list_ready_conversations", state="archived")
    assert [item["id"] for item in only_archived["items"]] == [saved["id"]]

    for number in range(20):
        await _save(world, title=f"Open {number}")
    over = await _call(
        world, world.claude, "save_ready_conversation", changes={"title": "21", "cadence": CADENCE}
    )
    assert _code(over) == "validation_error"
    # An archived one counts only once it is restored, and then the cap holds.
    restore = await _call(
        world,
        world.claude,
        "save_ready_conversation",
        expected_version=2,
        changes={"archived": False},
        **key,
    )
    assert _code(restore) == "validation_error"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_new_conversation_needs_a_title_and_a_cadence_and_the_text_is_cleaned() -> None:
    world = _world()

    for changes in ({"cadence": CADENCE}, {"title": "No cadence"}):
        result = await _call(world, world.claude, "save_ready_conversation", changes=changes)
        assert _code(result) == "validation_error"
    bad_cadence = await _call(
        world,
        world.claude,
        "save_ready_conversation",
        changes={"title": "T", "cadence": {"frequency": "hourly", "local_time": "25:00"}},
    )
    assert bad_cadence.is_error
    saved = await _save(world, instruction="<script>alert(1)</script>​  say it ")
    assert "<script" not in saved["instruction"]
    assert saved["instruction"].endswith("say it")


# --- starting and skipping a day --------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_composes_every_ingredient_the_session_may_read_and_marks_the_day() -> None:
    world = _world()
    await _seed(world)
    saved = await _save(world, ingredients=EVERY_INGREDIENT)
    world.clock.current = EVENING

    started = await _ok(
        world, world.everything, "start_ready_conversation", conversation_id=saved["id"]
    )

    blocks = _blocks(started)
    assert started["conversation"]["instruction"] == INSTRUCTION
    assert started["conversation"]["day_state"] == "started"
    assert started["conversation"]["ready"] is False
    assert (blocks["overdue"]["count"], blocks["overdue"]["lines"]) == (1, ["Overdue invoice"])
    assert blocks["tasks_due_today"]["lines"] == ["Book the painter (House)"]
    assert blocks["tasks_due_tomorrow"]["lines"] == ["Call the printer"]
    assert blocks["waiting"]["lines"] == ["Await the quote"]
    assert blocks["tasks_done_today"]["lines"] == ["Send the report"]
    assert blocks["journal_today"]["count"] == 1
    assert blocks["journal_today"]["lines"] == ["Dagens post: Kort sammanfattning."]
    assert (blocks["shopping_open"]["count"], blocks["shopping_open"]["lines"]) == (
        1,
        ["Veckohandel: 1"],
    )
    assert (blocks["suggestions"]["count"], blocks["suggestions"]["details"]) == (
        3,
        {"automations": 1},
    )
    # No review track and no look at the report yet: those two compose nothing.
    assert set(blocks) == set(EVERY_INGREDIENT) - {"review", "automation_report"}
    assert started["unavailable"] is None
    assert len(json.dumps(started["blocks"]).encode()) <= 8 * 1024
    assert _count(world, "ready_conversation_days", state="started") == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_ingredient_the_session_cannot_read_is_left_out_without_an_error() -> None:
    world = _world()
    await _seed(world)
    saved = await _save(world, ingredients=EVERY_INGREDIENT)
    tasks_only = Actor(world.owner_id, frozenset({"start:read", "start:write", "tasks:read"}))

    started = await _ok(world, tasks_only, "start_ready_conversation", conversation_id=saved["id"])

    assert set(_blocks(started)) == {
        "overdue",
        "tasks_due_today",
        "tasks_due_tomorrow",
        "waiting",
    }
    # Without `projects:read` the Project's title stays out of the line.
    assert _blocks(started)["tasks_due_today"]["lines"] == ["Book the painter"]
    assert started["unavailable"] is None
    nothing = Actor(world.owner_id, frozenset({"start:read", "start:write"}))
    bare = await _ok(world, nothing, "start_ready_conversation", conversation_id=saved["id"])
    assert bare["blocks"] == []
    assert bare["conversation"]["instruction"] == INSTRUCTION


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_failing_source_is_named_and_the_others_stand_and_nothing_secret_is_logged(
    all_logs: _Collector,
) -> None:
    world = _world()
    await _seed(world)
    saved = await _save(world, ingredients=["overdue", "suggestions", "waiting"])

    class Failing:
        def pending(self, actor: Actor) -> Any:
            raise RuntimeError(SECRET)

    sources = world.container.ready_conversations.sources
    object.__setattr__(sources, "automations", Failing())

    started = await _call(
        world, world.everything, "start_ready_conversation", conversation_id=saved["id"]
    )

    assert not started.is_error
    assert started.structured_content is not None
    data = started.structured_content
    assert data["unavailable"] == ["suggestions"]
    assert set(_blocks(data)) == {"overdue", "waiting"}
    assert SECRET not in all_logs.rendered()
    assert SECRET not in _all_text(started)
    assert "ready_ingredient_unavailable" in all_logs.rendered()
    assert "RuntimeError" in all_logs.rendered()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_starting_twice_the_same_day_marks_it_once_and_a_new_key_composes_again() -> None:
    world = _world()
    await _seed(world)
    saved = await _save(world, ingredients=["overdue"])
    key = f"ready-{uuid4().hex}"
    arguments = {"conversation_id": saved["id"]}

    first = await _ok(
        world, world.everything, "start_ready_conversation", idempotency_key=key, **arguments
    )
    again = await _ok(
        world, world.everything, "start_ready_conversation", idempotency_key=key, **arguments
    )
    other_key = await _ok(world, world.everything, "start_ready_conversation", **arguments)

    for result in (first, again, other_key):
        assert result["conversation"]["day_state"] == "started"
        assert _blocks(result)["overdue"]["count"] == 1
    assert _count(world, "ready_conversation_days") == 1
    started = [row for row in _audit_events(world) if row == "ready_conversation.started"]
    assert len(started) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_skipped_day_is_not_offered_and_the_undo_offers_it_again() -> None:
    world = _world()
    saved = await _save(world)
    world.clock.current = EVENING
    key = {"conversation_id": saved["id"]}

    skipped = await _ok(world, world.claude, "skip_ready_conversation", **key)
    assert (skipped["conversation"]["day_state"], skipped["conversation"]["ready"]) == (
        "skipped",
        False,
    )
    assert "ready" not in await _ok(world, world.claude, "get_start")
    # The schedule stays: tomorrow is ready as usual.
    tomorrow = await _ok(world, world.claude, "skip_ready_conversation", undo=True, **key)
    assert (tomorrow["conversation"]["day_state"], tomorrow["conversation"]["ready"]) == (
        "open",
        True,
    )
    assert "ready" in await _ok(world, world.claude, "get_start")
    again = await _ok(world, world.claude, "skip_ready_conversation", undo=True, **key)
    assert again["conversation"]["day_state"] == "open"
    assert _count(world, "ready_conversation_days") == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_later_day_can_be_skipped_but_not_an_unscheduled_or_past_one_or_a_started_one() -> (
    None
):
    world = _world()
    weekly = await _save(
        world, cadence={"frequency": "weekly", "weekdays": [0], "local_time": "18:00"}
    )
    key = {"conversation_id": weekly["id"]}

    next_monday = await _ok(world, world.claude, "skip_ready_conversation", day="2026-11-30", **key)
    assert (next_monday["conversation"]["day"], next_monday["conversation"]["day_state"]) == (
        "2026-11-30",
        "skipped",
    )
    assert next_monday["conversation"]["ready"] is False
    for refused in ("2026-11-24", "2026-11-16", "2027-02-01"):
        result = await _call(world, world.claude, "skip_ready_conversation", day=refused, **key)
        assert _code(result) == "validation_error"

    daily = await _save(world, title="Daily")
    await _ok(world, world.claude, "start_ready_conversation", conversation_id=daily["id"])
    started = await _call(
        world, world.claude, "skip_ready_conversation", conversation_id=daily["id"]
    )
    assert _code(started) == "conflict"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_paused_conversation_cannot_be_started_or_skipped() -> None:
    world = _world()
    saved = await _save(world)
    await _ok(
        world,
        world.claude,
        "save_ready_conversation",
        conversation_id=saved["id"],
        expected_version=1,
        changes={"paused": True},
    )

    for name in ("start_ready_conversation", "skip_ready_conversation"):
        result = await _call(world, world.claude, name, conversation_id=saved["id"])
        assert _code(result) == "validation_error"
    assert _count(world, "ready_conversation_days") == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_day_marks_older_than_sixty_days_are_deleted_when_a_new_one_is_written() -> None:
    world = _world()
    saved = await _save(world)
    with world.container.session_factory.begin() as session:
        for day in ("2026-09-01", "2026-09-23", "2026-09-24"):
            session.execute(
                text(
                    "INSERT INTO sidekick.ready_conversation_days "
                    "(conversation_id, day, owner_id, state, changed_at, version) "
                    "VALUES (:c, :d, :o, 'skipped', now(), 1)"
                ),
                {"c": saved["id"], "d": day, "o": str(world.owner_id)},
            )

    await _ok(world, world.claude, "skip_ready_conversation", conversation_id=saved["id"])

    with world.container.session_factory.begin() as session:
        left = session.execute(
            text("SELECT day::text FROM sidekick.ready_conversation_days ORDER BY day")
        ).scalars()
        assert list(left) == ["2026-09-24", TODAY]


# --- scopes, owners, retries ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_every_tool_needs_its_scope_and_a_write_needs_the_read_of_its_reply() -> None:
    world = _world()
    saved = await _save(world)
    key = {"conversation_id": saved["id"]}
    reader = Actor(world.owner_id, frozenset({"start:read"}))
    writer = Actor(world.owner_id, frozenset({"start:write"}))
    nothing = Actor(world.owner_id, frozenset({"tasks:read"}))
    calls: list[tuple[str, dict[str, Any]]] = [
        ("list_ready_conversations", {}),
        ("save_ready_conversation", {"changes": {"title": "X", "cadence": CADENCE}}),
        ("start_ready_conversation", key),
        ("skip_ready_conversation", key),
    ]

    for name, arguments in calls:
        assert _code(await _call(world, nothing, name, **arguments)) == "forbidden", name
    assert not (await _call(world, reader, "list_ready_conversations")).is_error
    for name, arguments in calls[1:]:
        # Reading alone does not write; writing alone would reveal the record in its reply.
        assert _code(await _call(world, reader, name, **arguments)) == "forbidden", name
        assert _code(await _call(world, writer, name, **arguments)) == "forbidden", name
    assert _code(await _call(world, writer, "list_ready_conversations")) == "forbidden"
    # Nothing was committed by a refused call.
    assert _count(world, "ready_conversations") == 1
    assert _count(world, "ready_conversation_days") == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_owner_finds_nothing_and_changes_nothing() -> None:
    world = _world()
    saved = await _save(world)
    key = {"conversation_id": saved["id"]}

    attempts = [
        await _call(world, world.stranger, "start_ready_conversation", **key),
        await _call(world, world.stranger, "skip_ready_conversation", **key),
        await _call(
            world,
            world.stranger,
            "save_ready_conversation",
            expected_version=1,
            changes={"title": "Taken over"},
            **key,
        ),
    ]
    listed = await _ok(world, world.stranger, "list_ready_conversations")

    for result in attempts:
        assert _code(result) == "not_found"
        assert INSTRUCTION not in _all_text(result)
    assert listed["items"] == []
    assert _count(world, "ready_conversation_days") == 0
    own = await _ok(world, world.claude, "list_ready_conversations")
    assert own["items"][0]["title"] == TITLE and own["items"][0]["version"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_same_key_saves_one_conversation_and_a_different_request_is_refused() -> None:
    world = _world()
    key = f"ready-{uuid4().hex}"
    changes = {"title": TITLE, "cadence": CADENCE}

    first = await _ok(
        world, world.claude, "save_ready_conversation", changes=changes, idempotency_key=key
    )
    second = await _ok(
        world, world.claude, "save_ready_conversation", changes=changes, idempotency_key=key
    )
    other = await _call(
        world,
        world.claude,
        "save_ready_conversation",
        changes={**changes, "title": "Another"},
        idempotency_key=key,
    )

    assert first["conversation"]["id"] == second["conversation"]["id"]
    assert _code(other) == "conflict"
    assert _count(world, "ready_conversations") == 1
    assert _audit_events(world).count("ready_conversation.created") == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_audit_trail_names_each_change_and_who_made_it() -> None:
    world = _world()
    saved = await _save(world)
    key = {"conversation_id": saved["id"]}
    await _ok(
        world,
        world.claude,
        "save_ready_conversation",
        expected_version=1,
        changes={"title": "N"},
        **key,
    )
    await _ok(world, world.claude, "skip_ready_conversation", **key)
    await _ok(world, world.claude, "skip_ready_conversation", undo=True, **key)
    await _ok(world, world.claude, "start_ready_conversation", **key)

    assert sorted(_audit_events(world)) == [
        "ready_conversation.created",
        "ready_conversation.skip_undone",
        "ready_conversation.skipped",
        "ready_conversation.started",
        "ready_conversation.updated",
    ]


def _audit_events(world: World) -> list[str]:
    with world.container.session_factory.begin() as session:
        return list(
            session.execute(
                text(
                    "SELECT event FROM sidekick.audit_events "
                    "WHERE event LIKE 'ready_conversation.%'"
                )
            ).scalars()
        )


# --- what is kept out of logs ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_text_of_a_conversation_reaches_a_log_the_audit_trail_or_a_replay_record(
    all_logs: _Collector,
) -> None:
    world = _world()
    await _seed(world)
    saved = await _save(world, ingredients=EVERY_INGREDIENT)
    key = {"conversation_id": saved["id"]}
    await _ok(world, world.everything, "list_ready_conversations")
    await _ok(world, world.everything, "start_ready_conversation", **key)
    await _ok(world, world.everything, "skip_ready_conversation", undo=True, **key)
    await _ok(world, world.everything, "get_start")
    await _call(world, world.stranger, "start_ready_conversation", **key)
    await _call(world, world.claude, "save_ready_conversation", changes={"title": TITLE})

    rendered = all_logs.rendered()
    for sentinel in (TITLE, INSTRUCTION, "Overdue invoice", "Dagens post", "Erik Holm"):
        assert sentinel not in rendered
    assert all(record.exc_info is None for record in all_logs.records)
    with world.container.session_factory.begin() as session:
        audit = session.execute(
            text("SELECT string_agg(t::text, ' ') FROM sidekick.audit_events t")
        ).scalar_one()
        replays = session.execute(
            text(
                "SELECT coalesce(string_agg(result::text, ' '), '') "
                "FROM sidekick.idempotency_operations"
            )
        ).scalar_one()
    for sentinel in (TITLE, INSTRUCTION, "Overdue invoice", "Dagens post"):
        assert sentinel not in audit
        assert sentinel not in replays


# --- who wrote the instruction ---------------------------------------------------------------


def _owner_writes_instruction(world: World, text_: str) -> dict[str, Any]:
    """A conversation whose instruction the owner wrote themselves (a call outside any tool)."""

    view = world.container.ready_conversations.save(
        world.claude,
        None,
        expected_version=None,
        requested=ReadyChange(title="Owner's", instruction=text_, cadence=Cadence(**CADENCE)),
        idempotency_key=f"ready-{uuid4().hex}",
    )
    return {"id": str(view.conversation.id), "version": view.conversation.version}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_instruction_saved_through_a_tool_is_recorded_as_the_model_s_and_unverified() -> (
    None
):
    world = _world()
    saved = await _save(world)

    assert saved["instruction_written_by"] == "claude"
    assert (saved["instruction_edited_by_model"], saved["instruction_verified"]) == (False, False)
    listed = await _ok(world, world.claude, "list_ready_conversations")
    assert listed["items"][0]["instruction_verified"] is False
    assert listed["items"][0]["instruction_written_by"] == "claude"
    # No instruction, no writer.
    bare = await _save(world, title="Bare", instruction=None)
    assert (bare["instruction_written_by"], bare["instruction_verified"]) == (None, False)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_start_says_the_model_s_instruction_is_unverified_and_what_to_ask_first() -> None:
    world = _world()
    saved = await _save(world)

    started = await _ok(
        world, world.claude, "start_ready_conversation", conversation_id=saved["id"]
    )

    assert started["conversation"]["instruction"] == INSTRUCTION
    assert started["conversation"]["instruction_verified"] is False
    assert started["instruction_notice"] == UNVERIFIED_NOTICE
    notice = started["instruction_notice"]
    for words in (
        "not verified it",
        "not as the owner's command",
        "deletes, sends out or widens permissions",
    ):
        assert words in notice


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_owner_s_own_instruction_is_verified_until_the_model_changes_it() -> None:
    world = _world()
    own = _owner_writes_instruction(world, "Go through my day.")

    verified = await _ok(world, world.claude, "start_ready_conversation", conversation_id=own["id"])
    assert verified["conversation"]["instruction_written_by"] == "you"
    assert verified["conversation"]["instruction_verified"] is True
    assert verified["instruction_notice"] == VERIFIED_NOTICE

    edited = await _ok(
        world,
        world.claude,
        "save_ready_conversation",
        conversation_id=own["id"],
        expected_version=own["version"],
        changes={"instruction": "Go through my day and mail my boss."},
    )
    item = edited["conversation"]
    assert (item["instruction_written_by"], item["instruction_edited_by_model"]) == ("you", True)
    assert item["instruction_verified"] is False
    again = await _ok(
        world,
        world.claude,
        "start_ready_conversation",
        conversation_id=own["id"],
        idempotency_key=f"ready-{uuid4().hex}",
    )
    assert again["instruction_notice"] == UNVERIFIED_NOTICE


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_start_without_an_instruction_has_no_notice() -> None:
    world = _world()
    saved = await _save(world, instruction=None)

    started = await _ok(
        world, world.claude, "start_ready_conversation", conversation_id=saved["id"]
    )

    assert started["instruction_notice"] is None
    assert started["conversation"]["instruction"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_descriptions_do_not_call_the_instruction_the_owner_s_and_ask_first() -> None:
    world = _world()

    async with world.server.client(world.claude) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    start = tools["start_ready_conversation"].description or ""
    listing = tools["list_ready_conversations"].description or ""
    assert "unverified" in start and "instruction_verified" in start
    assert "ask the owner before anything that deletes, sends out or widens permissions" in start
    assert "Follow the instruction" not in start
    assert "owner's instruction" not in start + listing
    assert "unverified" in listing
    assert "written by Claude" in (tools["save_ready_conversation"].description or "")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_spoken_line_names_the_conversation_and_never_its_instruction() -> None:
    world = _world()

    result = await _call(
        world,
        world.claude,
        "save_ready_conversation",
        changes={"title": TITLE, "instruction": INSTRUCTION, "cadence": CADENCE},
    )

    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    assert texts[0].splitlines()[0] == f"Saved the ready conversation {TITLE}."
    assert INSTRUCTION not in texts[0].splitlines()[0]


# --- size and speed --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_start_stays_within_eight_kilobytes_and_composes_within_300_ms() -> None:
    world = _world()
    await _seed(world)
    long_title = "x" * 190
    for number in range(12):
        await _ok(
            world,
            world.seeder,
            "create_task",
            title=f"{number} {long_title}",
            due_at="2026-11-01T09:00:00+01:00",
        )
    saved = await _save(world, ingredients=EVERY_INGREDIENT)

    started = await _ok(
        world, world.everything, "start_ready_conversation", conversation_id=saved["id"]
    )
    # The composition itself, without the transport: the best of three, so that a slow neighbour on
    # the machine does not fail a read-only composition.
    timings: list[float] = []
    for _ in range(3):
        began = time.perf_counter()
        world.container.ready_conversations.start(
            world.everything,
            UUID(saved["id"]),
            idempotency_key=f"ready-{uuid4().hex}",
            correlation_id="timing",
        )
        timings.append(time.perf_counter() - began)

    assert len(json.dumps(started["blocks"], ensure_ascii=False).encode()) <= 8 * 1024
    overdue = _blocks(started)["overdue"]
    assert overdue["count"] == 13 and len(overdue["lines"]) == 5 and overdue["truncated"] is True
    assert all(len(line) <= 140 for line in overdue["lines"])
    assert min(timings) < 0.3, timings

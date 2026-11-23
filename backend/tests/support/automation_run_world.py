"""A real FastMCP client over a real database for the automation run tools.

One owner has an approved automation (a draft the owner's Claude wrote and the app approved). A
routine holds a token with `automation:run` and nothing else. The run service reads a clock the
test can move, set to the middle of a day so that a test never straddles midnight.
"""

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastmcp.client.client import CallToolResult
from mcp.types import TextContent
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.mcp.harness import SwitchableServer
from tests.support.app_origin import origin_for
from tests.support.automation_rows import insert_run
from tests.support.settings import make_settings

INSTRUCTION = "SENTINEL-INSTRUCTION read the landlord's mail and propose tasks"
PURPOSE = "SENTINEL-PURPOSE keep the rent paid"
TITLE = "SENTINEL-TITLE rent mail"
CADENCE = {"frequency": "daily", "local_time": "07:00"}
CHANGES: dict[str, Any] = {
    "title": TITLE,
    "purpose": PURPOSE,
    "instruction": INSTRUCTION,
    "sources": ["mail"],
    "allowed_effects": ["create_task"],
    "cadence": CADENCE,
}
START = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
SETUP_SCOPES = ("projects:write", "tasks:write", "contacts:write")


class MovableClock:
    """The time the run service sees; a test moves it."""

    def __init__(self) -> None:
        self.current = START

    def now(self) -> datetime:
        return self.current

    def advance(self, by: timedelta) -> None:
        self.current += by


@dataclass(frozen=True, slots=True)
class World:
    container: Container
    server: SwitchableServer
    clock: MovableClock
    claude: Actor  # the owner's Claude: reads and drafts
    app: Actor  # the owner in the app: approves
    runner: Actor  # a routine's token: runs automations, nothing else
    claude_runner: Actor  # a Claude connection that may also run
    claude_no_run: Actor  # the owner's Claude without `automation:run`
    stranger_runner: Actor  # another owner's routine
    setup: Actor  # the owner with the scopes to create projects, tasks and contacts
    stranger_setup: Actor


def make_world(*, settings_overrides: dict[str, Any] | None = None) -> World:
    settings = make_settings().model_copy(update=settings_overrides or {})
    container = create_container(settings, database_factory())
    owner = container.auth.provision_user("run-owner", "Run Owner")
    other = container.auth.provision_user("run-other", "Run Other")
    clock = MovableClock()
    container.automation_runs.clock = clock

    def actor(*scopes: str, user: Any = owner) -> Actor:
        return Actor(user, frozenset(scopes))

    claude = actor("automation:read", "automation:write")
    return World(
        container,
        SwitchableServer.build(container, claude),
        clock,
        claude=claude,
        app=actor("automation:read", "automation:write", "tasks:write", "contacts:write"),
        runner=actor("automation:run"),
        claude_runner=actor("automation:read", "automation:write", "automation:run"),
        claude_no_run=actor("automation:read", "automation:write", "tasks:read"),
        stranger_runner=actor("automation:run", user=other),
        setup=actor(*SETUP_SCOPES, "tasks:read", "contacts:read"),
        stranger_setup=actor(*SETUP_SCOPES, user=other),
    )


_WRITES = {
    "save_automation",
    "approve_automation",
    "start_automation_run",
    "record_automation_results",
}


async def call(world: World, actor: Actor, name: str, **arguments: Any) -> CallToolResult:
    if "idempotency_key" not in arguments and name in _WRITES:
        arguments["idempotency_key"] = f"run-{uuid4().hex}"
    async with world.server.client(actor) as client:
        return await client.call_tool(name, arguments, meta=origin_for(name), raise_on_error=False)


async def ok(world: World, actor: Actor, name: str, **arguments: Any) -> dict[str, Any]:
    result = await call(world, actor, name, **arguments)
    assert not result.is_error, (name, result.structured_content)
    assert result.structured_content is not None
    return result.structured_content


def refusal(result: CallToolResult) -> dict[str, Any]:
    assert result.is_error, result.structured_content
    assert result.structured_content is not None
    return result.structured_content


def all_text(result: CallToolResult) -> str:
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join([*texts, json.dumps(result.structured_content)])


def text_blocks(result: CallToolResult) -> list[str]:
    return [block.text for block in result.content if isinstance(block, TextContent)]


async def approved_automation(
    world: World, *, drop: tuple[str, ...] = (), auto_apply_confirmed: bool = False, **changes: Any
) -> dict[str, Any]:
    """An automation the owner has approved at its current spec; `drop` leaves fields out.
    `auto_apply_confirmed` is the owner's confirmation that suggestions apply without a click."""

    values = {key: value for key, value in {**CHANGES, **changes}.items() if key not in drop}
    saved = await ok(world, world.claude, "save_automation", changes=values)
    draft = saved["automation"]
    approved = await ok(
        world,
        world.app,
        "approve_automation",
        automation_id=draft["id"],
        spec_digest=draft["spec_digest"],
        **({"auto_apply_confirmed": True} if auto_apply_confirmed else {}),
    )
    return approved["automation"]


async def start(
    world: World, automation: dict[str, Any], actor: Actor | None = None, **arguments: Any
) -> CallToolResult:
    values: dict[str, Any] = {"runner": "claude", "occurrence": "scheduled", **arguments}
    return await call(
        world,
        actor or world.runner,
        "start_automation_run",
        automation_id=automation["id"],
        **values,
    )


async def started(
    world: World, automation: dict[str, Any], actor: Actor | None = None, **arguments: Any
) -> dict[str, Any]:
    result = await start(world, automation, actor, **arguments)
    assert not result.is_error, result.structured_content
    assert result.structured_content is not None
    assert result.structured_content["status"] == "started", result.structured_content
    return result.structured_content["run"]


def person(name: str = "Anna Svensson", **overrides: Any) -> dict[str, Any]:
    return {
        "kind": "person",
        "fields": {"name": name, "email": "anna@example.se", "is_sender": True},
        "source_kind": "mail",
        "source_ref": "<message-1@example.se>",
        "key": "anna",
        **overrides,
    }


def task_suggestion(title: str = "Call the dentist", **overrides: Any) -> dict[str, Any]:
    return {
        "effect": "create_task.v1",
        "payload": {"title": title},
        "rationale": "The mail asks for it.",
        "datapoint_refs": ["anna"],
        **overrides,
    }


async def record(
    world: World, run: dict[str, Any], actor: Actor | None = None, **arguments: Any
) -> CallToolResult:
    return await call(
        world, actor or world.runner, "record_automation_results", run_id=run["id"], **arguments
    )


async def recorded(
    world: World, run: dict[str, Any], actor: Actor | None = None, **arguments: Any
) -> dict[str, Any]:
    result = await record(world, run, actor, **arguments)
    assert not result.is_error, result.structured_content
    assert result.structured_content is not None
    return result.structured_content


def scalar(world: World, sql: str, **parameters: Any) -> Any:
    store: Any = world.container.session_factory
    with store.begin() as session:
        return session.execute(text(sql), parameters).scalar_one()


def count(world: World, table: str, **where: Any) -> int:
    clause = " AND ".join(f"{column} = :{column}" for column in where) or "true"
    sql = f"SELECT count(*) FROM sidekick.{table} WHERE {clause}"  # noqa: S608
    return int(scalar(world, sql, **where))


def run_row(world: World, run_id: str) -> dict[str, Any]:
    store: Any = world.container.session_factory
    with store.begin() as session:
        row = (
            session.execute(
                text("SELECT * FROM sidekick.automation_runs WHERE id = :id"),
                {"id": UUID(run_id)},
            )
            .mappings()
            .one()
        )
        return dict(row)


def with_limits(world: World, **changes: Any) -> None:
    """Change what bounds the runs for this test's service."""

    service = world.container.automation_runs
    service.limits = replace(service.limits, **changes)


def seed_run(world: World, automation_id: str, **overrides: Any) -> str:
    """A run row written straight to the table, for the owner of `world.claude`."""

    store: Any = world.container.session_factory
    with store.begin() as session:
        return insert_run(
            session.connection(), str(world.claude.user_id), automation_id, **overrides
        )


def dismiss(world: World, suggestion_id: str) -> None:
    """The owner dismisses a suggestion in the app."""

    store: Any = world.container.session_factory
    with store.begin() as session:
        session.execute(
            text(
                "UPDATE sidekick.automation_suggestions SET state = 'dismissed', "
                "decided_at = now(), decided_by = 'you', decision_channel = 'app' WHERE id = :id"
            ),
            {"id": UUID(suggestion_id)},
        )


def set_column(world: World, table: str, row_id: str, column: str, value: Any) -> None:
    store: Any = world.container.session_factory
    with store.begin() as session:
        session.execute(
            text(f"UPDATE sidekick.{table} SET {column} = :value WHERE id = :id"),  # noqa: S608
            {"value": value, "id": UUID(row_id)},
        )

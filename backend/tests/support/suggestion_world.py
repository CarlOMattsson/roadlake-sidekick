"""A real FastMCP client over a real database for the suggestion tools.

One owner has an approved automation, a run of it and cards the run proposed. The owner's Claude
reads and decides through the model's tools; the app sends the origin mark the model cannot add.
The checker is not built yet, so a test that needs a checked card writes the checker's answer to
the row, as the checker will.
"""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastmcp.client.client import CallToolResult
from sqlalchemy import text

from sidekick.mcp.change_source import APP_ORIGIN_META
from sidekick.shared.types import Actor
from tests.support.automation_run_world import (
    World,
    approved_automation,
    make_world,
    person,
    recorded,
    started,
    task_suggestion,
)

OWNER_SCOPES = (
    "automation:read",
    "automation:write",
    "tasks:read",
    "tasks:write",
    "contacts:read",
    "contacts:write",
    "projects:read",
    "projects:write",
)
APP_MARK = {APP_ORIGIN_META: "app"}
WRITES = {"decide_suggestions", "approve_suggestion_group", "undo_suggestion"}
RUN_SESSION = "session-that-ran-the-automation"
OTHER_SESSION = "another-conversation"


@dataclass(frozen=True, slots=True)
class Desk:
    """The world and the owner's two actors: the model's reach and the app's."""

    world: World
    automation: dict[str, Any]
    run: dict[str, Any]
    claude: Actor
    narrow: Actor
    other: Actor


def owner_actor(world: World, *scopes: str) -> Actor:
    return Actor(world.claude.user_id, frozenset(scopes))


async def make_desk(
    monkeypatch: pytest.MonkeyPatch,
    *,
    effects: tuple[str, ...] = ("create_task",),
    settings_overrides: dict[str, Any] | None = None,
) -> Desk:
    """An approved automation with a run in progress, started in the session `RUN_SESSION`."""

    world = make_world(settings_overrides=settings_overrides)
    world.container.automation_suggestions.clock = world.clock
    monkeypatch.setattr("sidekick.mcp.automation_run_tools.request_session_id", lambda: RUN_SESSION)
    automation = await approved_automation(world, allowed_effects=list(effects), sources=["mail"])
    run = await started(world, automation)
    other = Actor(world.stranger_runner.user_id, frozenset(OWNER_SCOPES))
    return Desk(
        world,
        automation,
        run,
        claude=owner_actor(world, *OWNER_SCOPES),
        narrow=owner_actor(world, "automation:read", "automation:write"),
        other=other,
    )


def decided_in_session(monkeypatch: pytest.MonkeyPatch, session: str | None) -> None:
    """The MCP session the next decision comes from."""

    monkeypatch.setattr("sidekick.mcp.suggestion_tools.request_session_id", lambda: session)


async def propose(
    desk: Desk, *suggestions: dict[str, Any], datapoints: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Cards the run proposes and finishes with; each is read back as the owner lists it."""

    recorded_results = await recorded(
        desk.world,
        desk.run,
        datapoints=datapoints if datapoints is not None else [person()],
        suggestions=list(suggestions or (task_suggestion(),)),
        final=True,
        outcome="ok",
    )
    ids = {item["id"] for item in recorded_results["suggestions"]}
    listed = await ok(desk, desk.claude, "list_suggestions")
    return [item for item in listed["items"] if item["id"] in ids]


async def call(
    desk: Desk, actor: Actor, name: str, *, app: bool = False, **arguments: Any
) -> CallToolResult:
    if "idempotency_key" not in arguments and name in WRITES:
        arguments["idempotency_key"] = f"sug-{uuid4().hex}"
    async with desk.world.server.client(actor) as client:
        return await client.call_tool(
            name, arguments, meta=APP_MARK if app else None, raise_on_error=False
        )


async def ok(
    desk: Desk, actor: Actor, name: str, *, app: bool = False, **arguments: Any
) -> dict[str, Any]:
    result = await call(desk, actor, name, app=app, **arguments)
    assert not result.is_error, (name, result.structured_content)
    assert result.structured_content is not None
    return result.structured_content


def decision(card: dict[str, Any], kind: str = "approve", **extra: Any) -> dict[str, Any]:
    return {
        "suggestion_id": card["id"],
        "expected_version": card["version"],
        "decision": kind,
        **extra,
    }


async def decide(
    desk: Desk,
    actor: Actor,
    *items: dict[str, Any],
    app: bool = False,
    **arguments: Any,
) -> dict[str, Any]:
    return await ok(desk, actor, "decide_suggestions", app=app, items=list(items), **arguments)


def set_card(desk: Desk, suggestion_id: str, **columns: Any) -> None:
    """Write columns of a card straight to its row, as the checker or a later event would."""

    assignments = ", ".join(
        f"{name} = CAST(:{name} AS jsonb)" if isinstance(value, dict) else f"{name} = :{name}"
        for name, value in columns.items()
    )
    columns = {
        name: json.dumps(value) if isinstance(value, dict) else value
        for name, value in columns.items()
    }
    store: Any = desk.world.container.session_factory
    with store.begin() as session:
        session.execute(
            text(
                f"UPDATE sidekick.automation_suggestions SET {assignments} "  # noqa: S608
                "WHERE id = :suggestion_id"
            ),
            {**columns, "suggestion_id": UUID(suggestion_id)},
        )


def checked(desk: Desk, card: dict[str, Any], verdict: str = "ok", confidence: int = 98) -> None:
    """The independent checker's answer for a card, as it will write it."""

    set_card(
        desk,
        card["id"],
        state="pending",
        check_state="checked",
        verdict=verdict,
        confidence=confidence,
        bulk_eligible=verdict == "ok",
    )

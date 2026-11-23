"""Decision tickets prove a decision the owner made came from the app.

They work even when the host drops the origin mark.

Claude Desktop over stdio drops `params._meta` on the app's `tools/call`, so the server hands the
app a signed single-use ticket in the result `_meta` (never in the content) and accepts it back as
`decision_ticket` in place of the origin mark (issue #53). These tests act as that app: they read a
tool result, take the ticket out of its `_meta` and send it with the decision, without the mark.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.mcp.change_source import (
    OWNER_DECISION_META,
    REQUIRES_APP_META,
    OwnerDecisionsFromTheApp,
    requires_app,
)
from sidekick.mcp.decision_ticket import (
    DECISION_TICKET_BINDING_META,
    DECISION_TICKETS_META,
    TICKET_ARGUMENT,
    TICKET_LIFETIME_SECONDS,
)
from sidekick.mcp.journal_photo_tools import JOURNAL_PHOTO_TOOL_NAMES
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.app_origin import APP_ORIGIN, AUTOMATION_REPORT_APP_TOOLS
from tests.support.automation_run_world import task_suggestion
from tests.support.settings import make_settings
from tests.support.suggestion_world import call, checked, make_desk, propose

STEP = {"title": "Ring", "performer": "ai", "ai_spec": {"goal": "Find the number"}}
OTHER_STEP = {"title": "Mejla", "performer": "ai", "ai_spec": {"goal": "Find the address"}}
AUTOMATION = {
    "title": "Morning mail",
    "purpose": "Collect what the morning mail asks of me",
    "instruction": "Read yesterday's mail and propose tasks for requests.",
    "sources": ["mail"],
    "allowed_effects": ["create_task"],
}


@dataclass
class World:
    container: Container
    server: Any
    client: Client[Any]
    owner: Actor
    stranger: Actor
    current: list[Actor]

    def act_as(self, actor: Actor) -> None:
        self.current[0] = actor


def _world() -> World:
    container = create_container(make_settings(), database_factory())
    owner = Actor(
        container.auth.provision_user("ticket-owner", "Ticket Owner"), frozenset(MCP_SCOPES)
    )
    stranger = Actor(
        container.auth.provision_user("ticket-stranger", "Ticket Stranger"), frozenset(MCP_SCOPES)
    )
    current = [owner]
    server = create_mcp_server(container, actor_provider=lambda: current[0], enable_auth=False)
    return World(container, server, Client(server), owner, stranger, current)


def _audit(container: Container) -> list[tuple[str, str]]:
    store: Any = container.session_factory
    with store.begin() as session:
        rows = session.execute(text("SELECT event, source FROM sidekick.audit_events")).all()
    return sorted((event, source) for event, source in rows)


async def _call(
    client: Client[Any],
    tool: str,
    arguments: dict[str, Any],
    *,
    ticket: str | None = None,
    meta: dict[str, str] | None = None,
) -> CallToolResult:
    sent = {**arguments, "idempotency_key": f"tk-{uuid4().hex}"}
    if ticket is not None:
        sent[TICKET_ARGUMENT] = ticket
    return await client.call_tool(tool, sent, meta=meta, raise_on_error=False)


async def _read(client: Client[Any], tool: str, arguments: dict[str, Any]) -> CallToolResult:
    sent = {**arguments, "idempotency_key": f"tk-{uuid4().hex}"}
    if tool.startswith(("get_", "list_")):
        sent.pop("idempotency_key")
    result = await client.call_tool(tool, sent, raise_on_error=False)
    assert not result.is_error, (tool, result.structured_content)
    return result


def _tickets(result: CallToolResult) -> dict[str, str]:
    return dict((result.meta or {}).get(DECISION_TICKETS_META) or {})


def _structured(result: CallToolResult) -> dict[str, Any]:
    assert result.structured_content is not None
    return dict(result.structured_content)


def _is_app_only(result: CallToolResult) -> bool:
    return (
        result.is_error
        and _structured(result).get("code") == "forbidden"
        and _structured(result).get("reason") == "app_only"
    )


def _everything_the_model_can_read(result: CallToolResult) -> str:
    blocks = [block.model_dump(mode="json") for block in result.content]
    return json.dumps([blocks, result.structured_content], default=str)


async def _plan(
    world: World, steps: list[dict[str, Any]] | None = None
) -> tuple[Any, dict[str, Any]]:
    """A task with an AI plan, as the set_ai_plan result and its `plan` record."""

    created = await world.client.call_tool(
        "create_task", {"title": "Boka tid", "idempotency_key": f"tk-{uuid4().hex}"}
    )
    task = _structured(created)["task"]
    result = await _read(
        world.client,
        "set_ai_plan",
        {"task_id": task["id"], "task_version": task["version"], "steps": steps or [STEP]},
    )
    return result, _structured(result)["plan"]


async def _draft(world: World) -> tuple[CallToolResult, dict[str, Any]]:
    result = await _read(world.client, "save_automation", {"changes": AUTOMATION})
    return result, _structured(result)["automation"]


def _plan_args(plan: dict[str, Any]) -> dict[str, Any]:
    return {"task_id": plan["task_id"], "digest": plan["digest"]}


def _automation_args(automation: dict[str, Any]) -> dict[str, Any]:
    return {"automation_id": automation["id"], "spec_digest": automation["spec_digest"]}


def _records(caplog: pytest.LogCaptureFixture, message: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.getMessage() == message]


def _codes(caplog: pytest.LogCaptureFixture, message: str) -> list[Any]:
    return [getattr(record, "mcp_error_code", None) for record in _records(caplog, message)]


def _signer(world: World) -> Any:
    """The server's ticket signer, so a test can move its clock (it has no other way in)."""

    guard = next(m for m in world.server.middleware if isinstance(m, OwnerDecisionsFromTheApp))
    return guard._tickets


# --- issuing --------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_plan_tools_hand_out_tickets_for_approving_and_running_in_meta_only() -> None:
    world = _world()
    async with world.client:
        set_result, plan = await _plan(world)
        key = (plan["task_id"],)
        wanted = {f"approve_ai_plan:{key[0]}", f"run_ai_plan:{key[0]}"}
        got = await _read(world.client, "get_ai_plan", {"task_id": plan["task_id"]})
        approved = await _call(world.client, "approve_ai_plan", _plan_args(plan), meta=APP_ORIGIN)
        assert not approved.is_error

        for result in (set_result, got, approved):
            tickets = _tickets(result)
            assert set(tickets) == wanted
            seen = _everything_the_model_can_read(result)
            assert all(ticket not in seen for ticket in tickets.values())
        # Each ticket is its own, so one tool's ticket never equals the other's.
        assert len(set(_tickets(set_result).values())) == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_plan_with_no_steps_and_a_declined_run_hand_out_no_tickets() -> None:
    world = _world()
    async with world.client:
        created = await world.client.call_tool(
            "create_task", {"title": "No plan", "idempotency_key": f"tk-{uuid4().hex}"}
        )
        task = _structured(created)["task"]
        empty = await _read(world.client, "get_ai_plan", {"task_id": task["id"]})
        assert _structured(empty)["plan"]["state"] == "none"
        assert _tickets(empty) == {}

        _, plan = await _plan(world)
        await _call(world.client, "approve_ai_plan", _plan_args(plan), meta=APP_ORIGIN)
        queued = await _call(world.client, "run_ai_plan", _plan_args(plan), meta=APP_ORIGIN)
        # The test server runs no AI, so the run is declined, and a declined call hands out none.
        assert queued.is_error
        assert _tickets(queued) == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_automation_tools_hand_out_the_approve_ticket_in_meta_only() -> None:
    world = _world()
    async with world.client:
        saved, automation = await _draft(world)
        got = await _read(world.client, "get_automation", {"automation_id": automation["id"]})
        wanted = {f"approve_automation:{automation['id']}"}
        for result in (saved, got):
            assert set(_tickets(result)) == wanted
            seen = _everything_the_model_can_read(result)
            assert all(ticket not in seen for ticket in _tickets(result).values())

        approved = await _call(
            world.client,
            "approve_automation",
            _automation_args(automation),
            ticket=_tickets(got)[next(iter(wanted))],
        )
        assert not approved.is_error
        assert set(_tickets(approved)) == wanted


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_suggestions_has_no_tickets_when_there_are_no_groups() -> None:
    world = _world()
    async with world.client:
        listed = await _read(world.client, "list_suggestions", {})
    assert _structured(listed)["groups"] == []
    assert _tickets(listed) == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_group_of_suggestions_is_approved_with_the_ticket_the_list_handed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    one, two = await propose(
        desk,
        task_suggestion("One", payload={"title": "One"}),
        task_suggestion("Two", payload={"title": "Two"}),
    )
    checked(desk, one)
    checked(desk, two)
    listed = await call(desk, desk.claude, "list_suggestions", group="high_confidence")
    (group,) = _structured(listed)["groups"]
    tickets = _tickets(listed)
    key = f"approve_suggestion_group:{group['group_digest']}"
    assert set(tickets) == {key}
    assert tickets[key] not in _everything_the_model_can_read(listed)

    arguments = {
        "group_digest": group["group_digest"],
        "suggestion_ids": group["suggestion_ids"],
    }
    # No origin mark: the model cannot have the ticket, the app has it from the list's `_meta`.
    refused = await call(desk, desk.claude, "approve_suggestion_group", **arguments)
    assert _is_app_only(refused)
    answer = await call(
        desk, desk.claude, "approve_suggestion_group", decision_ticket=tickets[key], **arguments
    )
    assert not answer.is_error
    assert [item["state"] for item in _structured(answer)["items"]] == ["applied", "applied"]
    # The spent ticket does not approve the same group again.
    again = await call(
        desk, desk.claude, "approve_suggestion_group", decision_ticket=tickets[key], **arguments
    )
    assert _is_app_only(again)


# --- deciding with a ticket -------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_automation_is_approved_with_the_ticket_and_no_origin_mark() -> None:
    world = _world()
    async with world.client:
        saved, automation = await _draft(world)
        ticket = _tickets(saved)[f"approve_automation:{automation['id']}"]
        before = _audit(world.container)
        answer = await _call(
            world.client, "approve_automation", _automation_args(automation), ticket=ticket
        )
        assert not answer.is_error, _structured(answer)
        assert _structured(answer)["automation"]["state"] != "draft"
    added = [row for row in _audit(world.container) if row not in before]
    assert added == [("automation.approved", "you")]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_plan_is_approved_and_run_with_the_tickets_and_no_origin_mark(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _world()
    caplog.set_level(logging.INFO, logger="sidekick.mcp.tool")
    async with world.client:
        _, plan = await _plan(world)
        tickets = _tickets(await _read(world.client, "get_ai_plan", {"task_id": plan["task_id"]}))
        approved = await _call(
            world.client,
            "approve_ai_plan",
            _plan_args(plan),
            ticket=tickets[f"approve_ai_plan:{plan['task_id']}"],
        )
        assert not approved.is_error, _structured(approved)
        # The run is the use case's to decline (the test server runs no AI); the guard lets it by.
        ran = await _call(
            world.client,
            "run_ai_plan",
            _plan_args(plan),
            ticket=tickets[f"run_ai_plan:{plan['task_id']}"],
        )
        assert not _is_app_only(ran)

    sources = [source for event, source in _audit(world.container) if "approved" in event]
    assert sources == ["you"]
    decisions = _records(caplog, "mcp_owner_decision")
    assert [getattr(r, "mcp_decision_via", None) for r in decisions] == ["ticket", "ticket"]
    assert {getattr(r, "mcp_origin_mark", None) for r in decisions} == {"absent"}


# --- refused ------------------------------------------------------------------------------------


async def _assert_refused_without_effect(
    world: World, tool: str, arguments: dict[str, Any], ticket: str, code: str, caplog: Any
) -> None:
    before = _audit(world.container)
    caplog.clear()
    refused = await _call(world.client, tool, arguments, ticket=ticket)
    assert _is_app_only(refused), _structured(refused)
    assert _audit(world.container) == before
    assert _codes(caplog, "mcp_tool_failed") == [code]
    assert _records(caplog, "mcp_owner_decision") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_ticket_for_another_tool_object_digest_or_owner_is_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _world()
    caplog.set_level(logging.INFO, logger="sidekick.mcp.tool")
    async with world.client:
        issued, plan = await _plan(world)
        tickets = _tickets(issued)
        approve_ticket = tickets[f"approve_ai_plan:{plan['task_id']}"]
        run_ticket = tickets[f"run_ai_plan:{plan['task_id']}"]
        mismatch = "decision_ticket_mismatch"

        # The run ticket on the approve tool.
        await _assert_refused_without_effect(
            world, "approve_ai_plan", _plan_args(plan), run_ticket, mismatch, caplog
        )
        # Another object: a second plan's ticket on the first plan.
        _, other = await _plan(world, [OTHER_STEP])
        other_ticket = _tickets(
            await _read(world.client, "get_ai_plan", {"task_id": other["task_id"]})
        )[f"approve_ai_plan:{other['task_id']}"]
        await _assert_refused_without_effect(
            world, "approve_ai_plan", _plan_args(plan), other_ticket, mismatch, caplog
        )
        # Another owner: a stranger holding the owner's ticket.
        world.act_as(world.stranger)
        await _assert_refused_without_effect(
            world, "approve_ai_plan", _plan_args(plan), approve_ticket, mismatch, caplog
        )
        world.act_as(world.owner)
        # The tickets above were refused, not spent: the owner's own ticket still decides.
        approved = await _call(
            world.client, "approve_ai_plan", _plan_args(plan), ticket=approve_ticket
        )
        assert not approved.is_error, _structured(approved)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_ticket_for_a_digest_the_owner_did_not_see_is_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _world()
    caplog.set_level(logging.INFO, logger="sidekick.mcp.tool")
    async with world.client:
        issued, plan = await _plan(world)
        old_ticket = _tickets(issued)[f"approve_ai_plan:{plan['task_id']}"]
        # The plan changes after the ticket was issued, so the owner never saw the new digest.
        changed = await _read(
            world.client,
            "set_ai_plan",
            {
                "task_id": plan["task_id"],
                "task_version": plan["task_version"],
                "steps": [OTHER_STEP],
            },
        )
        new_plan = _structured(changed)["plan"]
        assert new_plan["digest"] != plan["digest"]

        await _assert_refused_without_effect(
            world,
            "approve_ai_plan",
            _plan_args(new_plan),
            old_ticket,
            "decision_ticket_mismatch",
            caplog,
        )
        # The old digest with the old ticket is no longer what the owner decides on.
        fresh = _tickets(changed)[f"approve_ai_plan:{plan['task_id']}"]
        approved = await _call(world.client, "approve_ai_plan", _plan_args(new_plan), ticket=fresh)
        assert not approved.is_error, _structured(approved)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_ticket_for_another_automation_or_a_changed_digest_is_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _world()
    caplog.set_level(logging.INFO, logger="sidekick.mcp.tool")
    async with world.client:
        saved, automation = await _draft(world)
        ticket = _tickets(saved)[f"approve_automation:{automation['id']}"]
        second = await _read(
            world.client, "save_automation", {"changes": {**AUTOMATION, "title": "Other"}}
        )
        other = _structured(second)["automation"]
        mismatch = "decision_ticket_mismatch"

        await _assert_refused_without_effect(
            world, "approve_automation", _automation_args(other), ticket, mismatch, caplog
        )
        wrong_digest = {**_automation_args(automation), "spec_digest": "0" * 64}
        await _assert_refused_without_effect(
            world, "approve_automation", wrong_digest, ticket, mismatch, caplog
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_ticket_is_spent_by_a_decision_and_a_tampered_one_is_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _world()
    caplog.set_level(logging.INFO, logger="sidekick.mcp.tool")
    async with world.client:
        saved, automation = await _draft(world)
        ticket = _tickets(saved)[f"approve_automation:{automation['id']}"]
        arguments = _automation_args(automation)

        version, expires, nonce, mac = ticket.split(".")
        flipped = mac[:-1] + ("A" if mac[-1] != "A" else "B")
        for tampered in (
            ".".join([version, expires, nonce, flipped]),
            ".".join([version, str(int(expires) + 3600), nonce, mac]),
        ):
            await _assert_refused_without_effect(
                world, "approve_automation", arguments, tampered, "decision_ticket_mismatch", caplog
            )
        await _assert_refused_without_effect(
            world,
            "approve_automation",
            arguments,
            "not-a-ticket",
            "decision_ticket_malformed",
            caplog,
        )

        first = await _call(world.client, "approve_automation", arguments, ticket=ticket)
        assert not first.is_error, _structured(first)
        # The second use of the spent ticket is refused as used and changes nothing more.
        await _assert_refused_without_effect(
            world, "approve_automation", arguments, ticket, "decision_ticket_used", caplog
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_ticket_issued_to_another_client_is_refused() -> None:
    world = _world()
    async with world.client:
        # The read comes from one OAuth client, the decision from another (here: stdio).
        with patch("sidekick.mcp.decision_ticket.request_client_id", return_value="client-a"):
            saved, automation = await _draft(world)
        ticket = _tickets(saved)[f"approve_automation:{automation['id']}"]
        refused = await _call(
            world.client, "approve_automation", _automation_args(automation), ticket=ticket
        )
        assert _is_app_only(refused)


# --- a failed call gives the ticket back ----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_decision_the_use_case_declines_gives_the_ticket_back_for_a_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _world()
    caplog.set_level(logging.INFO, logger="sidekick.mcp.tool")
    async with world.client:
        issued, plan = await _plan(world)
        run_ticket = _tickets(issued)[f"run_ai_plan:{plan['task_id']}"]
        # The plan is not approved yet, so the use case declines the run; the guard let it by.
        first = await _call(world.client, "run_ai_plan", _plan_args(plan), ticket=run_ticket)
        assert first.is_error
        assert not _is_app_only(first)
        second = await _call(world.client, "run_ai_plan", _plan_args(plan), ticket=run_ticket)
        assert second.is_error
        assert not _is_app_only(second), "the failed call must not spend the ticket"
    assert _codes(caplog, "mcp_tool_failed").count("decision_ticket_used") == 0
    assert [
        getattr(r, "mcp_decision_via", None) for r in _records(caplog, "mcp_owner_decision")
    ] == [
        "ticket",
        "ticket",
    ]


# --- the transition: the origin mark still works for one release ---------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_origin_mark_alone_still_works_and_is_logged_as_the_mark(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _world()
    caplog.set_level(logging.INFO, logger="sidekick.mcp.tool")
    async with world.client:
        _, automation = await _draft(world)
        answer = await _call(
            world.client, "approve_automation", _automation_args(automation), meta=APP_ORIGIN
        )
        assert not answer.is_error, _structured(answer)
    (record,) = _records(caplog, "mcp_owner_decision")
    assert getattr(record, "mcp_decision_via", None) == "origin_mark"
    assert getattr(record, "mcp_error_code", None) == "decision_ticket_missing"
    assert [source for event, source in _audit(world.container) if "approved" in event] == ["you"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_mark_with_an_invalid_ticket_works_and_logs_why_the_ticket_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _world()
    caplog.set_level(logging.INFO, logger="sidekick.mcp.tool")
    async with world.client:
        saved, automation = await _draft(world)
        arguments = _automation_args(automation)
        wrong = {**arguments, "spec_digest": "f" * 64}
        # An unrelated, malformed ticket, then a real ticket on a digest it was not issued for.
        garbage = await _call(
            world.client, "approve_automation", arguments, ticket="garbage", meta=APP_ORIGIN
        )
        assert not garbage.is_error, _structured(garbage)
        ticket = _tickets(saved)[f"approve_automation:{automation['id']}"]
        # The wrong digest is the use case's refusal after the guard let the marked call by.
        wrong_digest = await _call(
            world.client, "approve_automation", wrong, ticket=ticket, meta=APP_ORIGIN
        )
        assert not _is_app_only(wrong_digest)
    assert [
        getattr(r, "mcp_decision_via", None) for r in _records(caplog, "mcp_owner_decision")
    ] == [
        "origin_mark",
        "origin_mark",
    ]
    assert _codes(caplog, "mcp_owner_decision") == [
        "decision_ticket_malformed",
        "decision_ticket_mismatch",
    ]
    assert _records(caplog, "mcp_tool_failed") == [] or all(
        getattr(r, "mcp_error_code", None) != "app_only"
        for r in _records(caplog, "mcp_tool_failed")
    )


# --- diagnosis in the log ------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_refusal_log_names_a_missing_an_expired_and_an_app_only_proof(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = _world()
    caplog.set_level(logging.INFO, logger="sidekick.mcp.tool")
    async with world.client:
        saved, automation = await _draft(world)
        arguments = _automation_args(automation)
        ticket = _tickets(saved)[f"approve_automation:{automation['id']}"]

        missing = await _call(world.client, "approve_automation", arguments)
        assert _is_app_only(missing)

        # The signer reads its own clock, so move that one past the ticket's lifetime.
        signer = _signer(world)
        signer._clock = lambda: time.time() + TICKET_LIFETIME_SECONDS + 60
        expired = await _call(world.client, "approve_automation", arguments, ticket=ticket)
        assert _is_app_only(expired)

        photo = await world.client.call_tool(
            "get_journal_photo", {"photo_id": str(uuid4())}, raise_on_error=False
        )
        assert _is_app_only(photo)
    assert _codes(caplog, "mcp_tool_failed") == [
        "decision_ticket_missing",
        "decision_ticket_expired",
        "app_only",
    ]


# --- the policy: every ticket tool is an app-only decision with a `decision_ticket` argument -----


@pytest.mark.asyncio
@pytest.mark.integration
async def test_every_tool_with_a_ticket_binding_takes_the_ticket_and_is_an_app_only_decision() -> (
    None
):
    world = _world()
    tools = await world.server.list_tools()
    bound = {tool.name: tool for tool in tools if DECISION_TICKET_BINDING_META in (tool.meta or {})}
    assert set(bound) == {
        "approve_ai_plan",
        "run_ai_plan",
        "approve_automation",
        "approve_suggestion_group",
    }
    for name, tool in bound.items():
        assert TICKET_ARGUMENT in tool.parameters["properties"], name
        assert requires_app(tool.meta), name
        meta = tool.meta or {}
        assert meta.get(OWNER_DECISION_META) is True or meta.get(REQUIRES_APP_META) is True, name
        binding = meta[DECISION_TICKET_BINDING_META]
        for argument in binding.values():
            assert argument in tool.parameters["properties"], (name, argument)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_app_only_tools_without_a_ticket_are_exactly_the_photo_and_report_tools() -> None:
    world = _world()
    tools = await world.server.list_tools()
    without_ticket = {
        tool.name
        for tool in tools
        if requires_app(tool.meta) and DECISION_TICKET_BINDING_META not in (tool.meta or {})
    }
    # No app card calls these yet, so none has a result that could carry a ticket for it; each is
    # still refused without the origin mark. A tool added here needs a ticket or a decision.
    assert without_ticket == set(JOURNAL_PHOTO_TOOL_NAMES) | AUTOMATION_REPORT_APP_TOOLS

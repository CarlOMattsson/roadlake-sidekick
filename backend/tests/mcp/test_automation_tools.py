"""The automation registry tools through a real FastMCP client and a real database.

The owner's Claude drafts an automation, the owner approves it in the app, and a later change to
what the automation does withdraws the approval. Each role holds only the scopes it needs:
`automation:write` drafts, approving also needs the write scope of every effect, and a runner token
(`automation:run`) can neither read nor change the registry.
"""

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.mcp.harness import SwitchableServer
from tests.support.app_origin import origin_for
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401  (the `all_logs` fixture)
    _Collector,
)
from tests.support.settings import make_settings

INSTRUCTION = "SENTINEL-INSTRUCTION read the landlord's mail and propose tasks"
PURPOSE = "SENTINEL-PURPOSE keep the rent paid"
TITLE = "SENTINEL-TITLE rent mail"
CHANGES: dict[str, Any] = {
    "title": TITLE,
    "purpose": PURPOSE,
    "instruction": INSTRUCTION,
    "sources": ["mail"],
    "allowed_effects": ["create_task"],
}


@dataclass(frozen=True, slots=True)
class World:
    container: Container
    server: SwitchableServer
    claude: Actor  # the owner's Claude: reads and drafts
    app: Actor  # the owner in the app: also holds the write scopes of the effects
    app_tasks_only: Actor  # the app without `contacts:write`
    runner: Actor  # a routine's token: runs automations, nothing else
    reader: Actor  # reads only
    stranger: Actor  # another owner with every scope


def _world() -> World:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("automation-owner", "Automation Owner")
    other = container.auth.provision_user("automation-other", "Automation Other")

    def actor(*scopes: str, user: Any = owner) -> Actor:
        return Actor(user, frozenset(scopes))

    claude = actor("automation:read", "automation:write")
    return World(
        container,
        SwitchableServer.build(container, claude),
        claude=claude,
        app=actor("automation:read", "automation:write", "tasks:write", "contacts:write"),
        app_tasks_only=actor("automation:read", "automation:write", "tasks:write"),
        runner=actor("automation:run"),
        reader=actor("automation:read"),
        stranger=actor(
            "automation:read", "automation:write", "tasks:write", "contacts:write", user=other
        ),
    )


async def _call(world: World, actor: Actor, name: str, **arguments: Any) -> CallToolResult:
    if "idempotency_key" not in arguments and name in _WRITES:
        arguments["idempotency_key"] = f"auto-{uuid4().hex}"
    async with world.server.client(actor) as client:
        return await client.call_tool(name, arguments, meta=origin_for(name), raise_on_error=False)


_WRITES = {"save_automation", "approve_automation"}


async def _ok(world: World, actor: Actor, name: str, **arguments: Any) -> dict[str, Any]:
    result = await _call(world, actor, name, **arguments)
    assert not result.is_error, result.structured_content
    assert result.structured_content is not None
    return result.structured_content


def _all_text(result: CallToolResult) -> str:
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join([*texts, json.dumps(result.structured_content)])


async def _draft(world: World, **changes: Any) -> dict[str, Any]:
    saved = await _ok(world, world.claude, "save_automation", changes={**CHANGES, **changes})
    return saved["automation"]


async def _approve(world: World, automation: dict[str, Any], actor: Actor | None = None) -> Any:
    return await _call(
        world,
        actor or world.app,
        "approve_automation",
        automation_id=automation["id"],
        spec_digest=automation["spec_digest"],
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_draft_is_not_runnable_until_the_owner_approves_its_digest() -> None:
    world = _world()
    draft = await _draft(world)

    assert draft["state"] == "draft"
    assert draft["approval"] == "not_approved"
    assert draft["runnable"] is False
    assert draft["model_tier"] == "standard"
    assert draft["run_budget_usd"] == 1.0
    assert draft["version"] == 1

    approved = await _ok(
        world,
        world.app,
        "approve_automation",
        automation_id=draft["id"],
        spec_digest=draft["spec_digest"],
    )

    record = approved["automation"]
    assert record["state"] == "active"
    assert record["approval"] == "approved"
    assert record["runnable"] is True
    assert record["approved_at"] is not None
    assert record["spec_digest"] == draft["spec_digest"]
    read = await _ok(world, world.reader, "get_automation", automation_id=draft["id"])
    assert read["automation"]["runnable"] is True
    assert read["automation"]["instruction"] == INSTRUCTION


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_change_by_the_model_withdraws_the_approval_and_the_old_digest_is_refused() -> None:
    world = _world()
    approved = (await _approve(world, await _draft(world))).structured_content["automation"]
    assert approved["runnable"] is True

    changed = await _ok(
        world,
        world.claude,
        "save_automation",
        automation_id=approved["id"],
        expected_version=approved["version"],
        changes={"instruction": "Read the mail and also create contacts for every sender."},
    )

    record = changed["automation"]
    assert record["state"] == "draft"
    assert record["approval"] == "not_approved"
    assert record["runnable"] is False
    assert record["approved_at"] is None
    assert record["spec_digest"] != approved["spec_digest"]
    stale = await _approve(world, approved)
    assert stale.is_error
    assert stale.structured_content is not None
    assert stale.structured_content["code"] == "conflict"
    assert stale.structured_content["reason"] == "automation_changed"
    current = await _approve(world, record)
    assert not current.is_error, current.structured_content


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_model_tier_is_part_of_what_the_owner_approves() -> None:
    world = _world()
    draft = await _draft(world)
    approved = (await _approve(world, draft)).structured_content["automation"]

    strong = await _ok(
        world,
        world.claude,
        "save_automation",
        automation_id=approved["id"],
        expected_version=approved["version"],
        changes={"model_tier": "strong"},
    )

    record = strong["automation"]
    assert record["model_tier"] == "strong"
    assert record["runnable"] is False
    assert record["spec_digest"] != approved["spec_digest"]
    refused = await _approve(world, approved)
    assert refused.is_error
    assert refused.structured_content is not None
    assert refused.structured_content["reason"] == "automation_changed"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_approving_needs_the_write_scope_of_every_effect() -> None:
    world = _world()
    both = await _draft(world, allowed_effects=["create_task", "create_contact"])
    tasks_only = await _draft(world, allowed_effects=["create_task"])

    refused = await _approve(world, both, world.app_tasks_only)
    allowed = await _approve(world, tasks_only, world.app_tasks_only)
    by_claude = await _approve(world, tasks_only, world.claude)
    full = await _approve(world, both)

    assert refused.is_error
    assert refused.structured_content is not None
    assert refused.structured_content["code"] == "forbidden"
    assert not allowed.is_error, allowed.structured_content
    assert by_claude.is_error
    assert by_claude.structured_content is not None
    assert by_claude.structured_content["code"] == "forbidden"
    assert not full.is_error, full.structured_content
    read = await _ok(world, world.reader, "get_automation", automation_id=both["id"])
    assert read["automation"]["runnable"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_refused_approval_changes_nothing() -> None:
    world = _world()
    both = await _draft(world, allowed_effects=["create_task", "create_contact"])

    await _approve(world, both, world.app_tasks_only)

    read = await _ok(world, world.reader, "get_automation", automation_id=both["id"])
    assert read["automation"]["state"] == "draft"
    assert read["automation"]["version"] == both["version"]
    assert read["automation"]["approved_at"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_every_tool_needs_its_scope_and_a_runner_token_reaches_none() -> None:
    world = _world()
    draft = await _draft(world)
    reads = {"list_automations": {}, "get_automation": {"automation_id": draft["id"]}}
    writes = {
        "save_automation": {"changes": {"title": "Renamed"}},
        "approve_automation": {"automation_id": draft["id"], "spec_digest": draft["spec_digest"]},
    }

    for actor in (world.runner, Actor(world.claude.user_id, frozenset({"tasks:read"}))):
        for name, arguments in {**reads, **writes}.items():
            result = await _call(world, actor, name, **arguments)
            assert result.is_error, name
            assert result.structured_content is not None
            assert result.structured_content["code"] == "forbidden", name
    for name, arguments in writes.items():
        result = await _call(world, world.reader, name, **arguments)
        assert result.is_error, name
        assert result.structured_content is not None
        assert result.structured_content["code"] == "forbidden", name
    unchanged = await _ok(world, world.reader, "get_automation", automation_id=draft["id"])
    assert unchanged["automation"]["title"] == TITLE
    assert unchanged["automation"]["version"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_writer_that_cannot_read_automations_gets_no_answer() -> None:
    world = _world()
    write_only = Actor(world.claude.user_id, frozenset({"automation:write"}))

    result = await _call(world, write_only, "save_automation", changes=CHANGES)

    assert result.is_error
    assert result.structured_content is not None
    assert result.structured_content["code"] == "forbidden"
    listed = await _ok(world, world.reader, "list_automations")
    assert listed["items"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_owner_finds_nothing_and_changes_nothing() -> None:
    world = _world()
    draft = await _draft(world)

    reads = await _call(world, world.stranger, "get_automation", automation_id=draft["id"])
    saves = await _call(
        world,
        world.stranger,
        "save_automation",
        automation_id=draft["id"],
        expected_version=1,
        changes={"title": "Taken over"},
    )
    approves = await _approve(world, draft, world.stranger)
    listed = await _ok(world, world.stranger, "list_automations")

    for result in (reads, saves, approves):
        assert result.is_error
        assert result.structured_content is not None
        assert result.structured_content["code"] == "not_found"
        assert INSTRUCTION not in _all_text(result)
    assert listed["items"] == []
    own = await _ok(world, world.reader, "get_automation", automation_id=draft["id"])
    assert own["automation"]["title"] == TITLE
    assert own["automation"]["state"] == "draft"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_same_key_creates_one_automation_and_a_different_request_is_refused() -> None:
    world = _world()
    key = f"auto-{uuid4().hex}"

    first = await _ok(world, world.claude, "save_automation", changes=CHANGES, idempotency_key=key)
    second = await _ok(world, world.claude, "save_automation", changes=CHANGES, idempotency_key=key)
    other = await _call(
        world,
        world.claude,
        "save_automation",
        changes={**CHANGES, "title": "Another"},
        idempotency_key=key,
    )

    assert first["automation"]["id"] == second["automation"]["id"]
    assert other.is_error
    assert other.structured_content is not None
    assert other.structured_content["code"] == "conflict"
    assert "reason" not in other.structured_content
    listed = await _ok(world, world.reader, "list_automations")
    assert len(listed["items"]) == 1
    assert _audit_count(world, first["automation"]["id"]) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_approval_repeated_with_its_key_or_on_its_own_changes_nothing_more() -> None:
    world = _world()
    draft = await _draft(world)
    key = f"auto-{uuid4().hex}"
    arguments = {"automation_id": draft["id"], "spec_digest": draft["spec_digest"]}

    first = await _ok(world, world.app, "approve_automation", idempotency_key=key, **arguments)
    again = await _ok(world, world.app, "approve_automation", idempotency_key=key, **arguments)
    fresh_key = await _ok(world, world.app, "approve_automation", **arguments)
    assert _audit_count(world, draft["id"]) == 2  # created, approved

    assert first["automation"]["version"] == 2
    assert again["automation"] == first["automation"]
    assert fresh_key["automation"] == first["automation"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_version_is_refused_and_a_change_needs_its_version() -> None:
    world = _world()
    draft = await _draft(world)
    renamed = await _ok(
        world,
        world.claude,
        "save_automation",
        automation_id=draft["id"],
        expected_version=1,
        changes={"title": "Renamed"},
    )

    stale = await _call(
        world,
        world.claude,
        "save_automation",
        automation_id=draft["id"],
        expected_version=1,
        changes={"title": "Lost update"},
    )
    unversioned = await _call(
        world, world.claude, "save_automation", automation_id=draft["id"], changes={"title": "X"}
    )

    assert renamed["automation"]["version"] == 2
    assert stale.is_error
    assert stale.structured_content is not None
    assert stale.structured_content["reason"] == "stale_version"
    assert unversioned.is_error
    assert unversioned.structured_content is not None
    assert unversioned.structured_content["code"] == "validation_error"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_run_budget_is_checked_against_the_cap_for_automations() -> None:
    world = _world()
    cap = world.container.settings.ai_automation_monthly_cap_usd

    over = await _call(
        world, world.claude, "save_automation", changes={**CHANGES, "run_budget_usd": cap + 0.01}
    )
    at_cap = await _draft(world, run_budget_usd=cap)

    assert over.is_error
    assert over.structured_content is not None
    assert over.structured_content["code"] == "validation_error"
    assert at_cap["run_budget_usd"] == cap


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_new_automation_needs_its_text_and_a_cadence_can_be_cleared() -> None:
    world = _world()

    incomplete = await _call(world, world.claude, "save_automation", changes={"title": "Only"})
    scheduled = await _draft(world, cadence={"frequency": "daily", "local_time": "07:30"})
    cleared = await _ok(
        world,
        world.claude,
        "save_automation",
        automation_id=scheduled["id"],
        expected_version=scheduled["version"],
        changes={},
        clear=["cadence"],
    )
    nulls = await _ok(
        world,
        world.claude,
        "save_automation",
        automation_id=scheduled["id"],
        expected_version=cleared["automation"]["version"],
        changes={"title": "Renamed", "instruction": None},
    )

    assert incomplete.is_error
    assert scheduled["cadence"]["local_time"] == "07:30"
    assert cleared["automation"]["cadence"] is None
    assert nulls["ignored_nulls"] == ["instruction"]
    assert nulls["automation"]["instruction"] == INSTRUCTION


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pausing_archiving_and_listing() -> None:
    world = _world()
    first = await _draft(world, title="First")
    second = await _draft(world, title="Second")
    third = await _draft(world, title="Third")
    approved = (await _approve(world, second)).structured_content["automation"]

    paused = await _ok(
        world,
        world.claude,
        "save_automation",
        automation_id=approved["id"],
        expected_version=approved["version"],
        changes={"paused": True},
    )
    archived = await _ok(
        world,
        world.claude,
        "save_automation",
        automation_id=third["id"],
        expected_version=third["version"],
        changes={"archived": True},
    )
    page = await _ok(world, world.reader, "list_automations", limit=1)
    rest = await _ok(world, world.reader, "list_automations", limit=1, cursor=page["next_cursor"])
    only_archived = await _ok(world, world.reader, "list_automations", state="archived")

    assert paused["automation"]["state"] == "paused"
    assert paused["automation"]["approval"] == "approved"
    assert paused["automation"]["runnable"] is False
    assert archived["automation"]["state"] == "archived"
    assert [item["id"] for item in page["items"]] == [first["id"]]
    assert page["next_cursor"] is not None
    assert [item["id"] for item in rest["items"]] == [second["id"]]
    assert rest["next_cursor"] is None
    assert [item["id"] for item in only_archived["items"]] == [third["id"]]
    assert "instruction" not in page["items"][0]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_cursor_of_another_list_or_owner_is_refused() -> None:
    world = _world()
    await _draft(world)
    await _draft(world, title="Second")
    page = await _ok(world, world.reader, "list_automations", limit=1)

    other_filter = await _call(
        world, world.reader, "list_automations", state="active", cursor=page["next_cursor"]
    )
    other_owner = await _call(world, world.stranger, "list_automations", cursor=page["next_cursor"])

    for result in (other_filter, other_owner):
        assert result.is_error
        assert result.structured_content is not None
        assert result.structured_content["code"] == "validation_error"


def _audit_count(world: World, automation_id: str) -> int:
    store: Any = world.container.session_factory
    with store.begin() as session:
        return int(
            session.execute(
                text("SELECT count(*) FROM sidekick.audit_events WHERE target_id = :id"),
                {"id": automation_id},
            ).scalar_one()
        )


def _audit(world: World, automation_id: str) -> dict[str, str]:
    store: Any = world.container.session_factory
    with store.begin() as session:
        rows = session.execute(
            text(
                "SELECT event, source FROM sidekick.audit_events "
                "WHERE target_id = :id AND event LIKE 'automation.%'"
            ),
            {"id": automation_id},
        ).all()
    return {event: source for event, source in rows}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_approval_is_the_owners_change_and_the_draft_is_claudes() -> None:
    world = _world()
    draft = await _draft(world)
    await _approve(world, draft)
    await _ok(
        world,
        world.claude,
        "save_automation",
        automation_id=draft["id"],
        expected_version=2,
        changes={"run_budget_usd": 0.5},
    )

    assert _audit(world, draft["id"]) == {
        "automation.created": "claude",
        "automation.approved": "you",
        "automation.updated": "claude",
        "automation.approval_withdrawn": "claude",
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_text_of_an_automation_reaches_a_log_or_the_audit_trail(
    all_logs: _Collector,
) -> None:
    world = _world()
    draft = await _draft(world)
    await _approve(world, draft)
    await _ok(world, world.reader, "list_automations")
    await _ok(world, world.reader, "get_automation", automation_id=draft["id"])
    await _call(world, world.claude, "save_automation", changes={"title": "Only"})
    await _approve(world, draft, world.stranger)

    rendered = all_logs.rendered()
    for sentinel in (TITLE, PURPOSE, INSTRUCTION):
        assert sentinel not in rendered
    assert all(record.exc_info is None for record in all_logs.records)
    store: Any = world.container.session_factory
    with store.begin() as session:
        audit = session.execute(
            text("SELECT string_agg(t::text, ' ') FROM sidekick.audit_events t")
        ).scalar_one()
        replays = session.execute(
            text(
                "SELECT coalesce(string_agg(result::text, ' '), '') "
                "FROM sidekick.idempotency_operations"
            )
        ).scalar_one()
    for sentinel in (TITLE, PURPOSE, INSTRUCTION):
        assert sentinel not in audit
        assert sentinel not in replays


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_spoken_line_names_the_automation_without_its_instruction() -> None:
    world = _world()

    result = await _call(world, world.claude, "save_automation", changes=CHANGES)

    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    assert texts
    assert texts[0].splitlines()[0] == f"Saved the automation {TITLE}."
    assert INSTRUCTION not in texts[0].splitlines()[0]
    assert "digest" in texts[0]

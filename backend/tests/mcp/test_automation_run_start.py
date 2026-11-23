"""Starting a run of an approved automation through a real FastMCP client and a real database.

A run starts only for an active automation whose current spec is the one the owner approved. The
same occurrence started twice is the same run; a run that goes silent is taken over after its
lease; the caps of the day and the month refuse a new run; and a routine's token reaches nothing
but the two runner tools.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from sidekick.automations.domain.runs import CredentialKind, OccurrenceKind, RunRunner
from sidekick.shared.errors import ConflictError
from sidekick.shared.types import Actor
from tests.support.automation_run_world import (
    INSTRUCTION,
    PURPOSE,
    TITLE,
    all_text,
    approved_automation,
    call,
    count,
    make_world,
    ok,
    record,
    recorded,
    refusal,
    run_row,
    seed_run,
    set_column,
    start,
    started,
    text_blocks,
    with_limits,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_an_approved_automation_starts_and_hands_over_its_brief() -> None:
    world = make_world()
    automation = await approved_automation(world)

    result = await start(world, automation)

    assert not result.is_error, result.structured_content
    output = result.structured_content
    assert output is not None
    run = output["run"]
    assert output["status"] == "started"
    assert (run["state"], run["attempt"], run["runner"]) == ("running", 1, "claude")
    assert run["occurrence"] == "d:2026-11-23"
    assert run["lease_until"] is not None
    assert output["limits"]["budget_usd"] == 1.0
    assert output["limits"]["max_suggestions_per_run"] == 15
    assert list(output["effect_schemas"]) == ["create_task.v1"]
    spoken, compact = text_blocks(result)
    assert INSTRUCTION in spoken
    assert f"run_id: {run['id']}" in spoken
    assert "brief" not in compact
    assert INSTRUCTION not in compact
    assert run_row(world, run["id"])["credential_kind"] == "token"


async def test_the_same_occurrence_started_again_is_the_same_run() -> None:
    world = make_world()
    automation = await approved_automation(world)
    key = f"run-{uuid4().hex}"

    first = await started(world, automation, idempotency_key=key)
    replay = await started(world, automation, idempotency_key=key)
    other_key = await started(world, automation)

    assert replay["id"] == first["id"] == other_key["id"]
    assert count(world, "automation_runs") == 1
    assert count(world, "audit_events", event="automation.run_started") == 1


async def test_a_key_used_for_another_request_is_refused() -> None:
    world = make_world()
    automation = await approved_automation(world)
    key = f"run-{uuid4().hex}"
    await started(world, automation, idempotency_key=key)

    other = await start(world, automation, idempotency_key=key, occurrence="manual")

    assert refusal(other)["code"] == "conflict"
    assert count(world, "automation_runs") == 1


async def test_a_manual_request_is_its_own_occurrence_every_time() -> None:
    world = make_world()
    automation = await approved_automation(world, drop=("cadence",))

    first = await started(world, automation, occurrence="manual")
    second = await started(world, automation, occurrence="manual")

    assert first["id"] != second["id"]
    assert first["occurrence"].startswith("m:")
    assert count(world, "automation_runs") == 2


async def test_without_a_cadence_nothing_is_due_on_a_schedule() -> None:
    world = make_world()
    automation = await approved_automation(world, drop=("cadence",))

    result = await start(world, automation)

    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["status"] == "nothing_due"
    assert result.structured_content["reason"] == "no_cadence"
    assert result.structured_content["run"] is None
    assert count(world, "automation_runs") == 0


async def test_a_day_that_is_done_has_nothing_due_until_the_next_day() -> None:
    world = make_world()
    automation = await approved_automation(world)
    run = await started(world, automation)
    await recorded(world, run, final=True, outcome="nothing_found")

    again = await ok(
        world,
        world.runner,
        "start_automation_run",
        automation_id=automation["id"],
        runner="claude",
        idempotency_key=f"run-{uuid4().hex}",
    )
    world.clock.advance(timedelta(days=1))
    next_day = await started(world, automation)

    assert again["status"] == "nothing_due"
    assert again["reason"] == "already_done"
    assert next_day["id"] != run["id"]
    assert next_day["occurrence"] == "d:2026-11-24"


async def test_a_weekly_cadence_waits_for_its_day() -> None:
    world = make_world()
    monday = await approved_automation(
        world, cadence={"frequency": "weekly", "weekdays": [0], "local_time": "07:00"}
    )
    first = await started(world, monday)
    await recorded(world, first, final=True, outcome="ok")

    world.clock.advance(timedelta(days=3))
    midweek = await ok(
        world,
        world.runner,
        "start_automation_run",
        automation_id=monday["id"],
        runner="claude",
        idempotency_key=f"run-{uuid4().hex}",
    )
    world.clock.advance(timedelta(days=4))
    next_monday = await started(world, monday)

    assert midweek["status"] == "nothing_due"
    assert midweek["reason"] == "not_due"
    assert next_monday["occurrence"] == "d:2026-11-30"


# --- who may start what -----------------------------------------------------------------------


async def test_a_draft_that_was_never_approved_does_not_start() -> None:
    world = make_world()
    saved = await ok(
        world,
        world.claude,
        "save_automation",
        changes={
            "title": TITLE,
            "purpose": PURPOSE,
            "instruction": INSTRUCTION,
            "sources": ["mail"],
            "allowed_effects": ["create_task"],
        },
    )

    refused = refusal(await start(world, saved["automation"]))

    assert (refused["code"], refused["reason"]) == ("conflict", "automation_not_active")
    assert count(world, "automation_runs") == 0


async def test_a_paused_automation_does_not_start() -> None:
    world = make_world()
    automation = await approved_automation(world)
    await ok(
        world,
        world.claude,
        "save_automation",
        automation_id=automation["id"],
        expected_version=automation["version"],
        changes={"paused": True},
    )

    refused = refusal(await start(world, automation))

    assert refused["reason"] == "automation_not_active"


async def test_a_change_after_the_approval_stops_the_next_start() -> None:
    world = make_world()
    automation = await approved_automation(world)
    await ok(
        world,
        world.claude,
        "save_automation",
        automation_id=automation["id"],
        expected_version=automation["version"],
        changes={"instruction": "Read the mail and also create contacts."},
    )

    refused = refusal(await start(world, automation))

    assert refused["reason"] == "automation_not_active"
    assert count(world, "automation_runs") == 0


async def test_a_spec_that_no_longer_matches_what_was_approved_does_not_start() -> None:
    world = make_world()
    automation = await approved_automation(world)
    set_column(world, "automations", automation["id"], "spec_digest", "e" * 64)

    refused = refusal(await start(world, automation))

    assert refused["reason"] == "automation_changed_since_approval"


async def test_an_automation_meant_for_another_runner_does_not_start() -> None:
    world = make_world()
    automation = await approved_automation(world, runner="claude_code")

    refused = refusal(await start(world, automation, runner="claude"))
    allowed = await started(world, automation, runner="claude_code")

    assert refused["reason"] == "automation_other_runner"
    assert allowed["runner"] == "claude_code"


async def test_a_client_cannot_start_a_server_run() -> None:
    world = make_world()
    automation = await approved_automation(world)

    result = await start(world, automation, runner="server")

    assert result.is_error
    assert count(world, "automation_runs") == 0


async def test_a_token_without_the_run_scope_cannot_start_or_record() -> None:
    world = make_world()
    automation = await approved_automation(world)
    run = await started(world, automation)
    outsiders: list[Actor] = [world.claude, world.claude_no_run, world.app]

    for actor in outsiders:
        started_by = await start(world, automation, actor, occurrence="manual")
        recorded_by = await record(world, run, actor, final=True)
        assert refusal(started_by)["code"] == "forbidden"
        assert refusal(recorded_by)["code"] == "forbidden"

    assert count(world, "automation_runs") == 1
    assert run_row(world, run["id"])["state"] == "running"


async def test_a_claude_connection_with_the_run_scope_can_run() -> None:
    world = make_world()
    automation = await approved_automation(world)

    run = await started(world, automation, world.claude_runner)

    assert run["state"] == "running"


async def test_a_runner_token_reaches_no_other_tool() -> None:
    world = make_world()
    automation = await approved_automation(world)
    attempts: dict[str, dict[str, Any]] = {
        "save_automation": {"changes": {"title": "Taken over"}},
        "approve_automation": {
            "automation_id": automation["id"],
            "spec_digest": automation["spec_digest"],
        },
        "list_automations": {},
        "get_automation": {"automation_id": automation["id"]},
        "create_task": {"title": "A task by a routine", "idempotency_key": "routine-task-key-1"},
        "list_tasks": {},
        "create_contact": {"display_name": "Somebody", "idempotency_key": "routine-contact-key-1"},
    }

    for name, arguments in attempts.items():
        refused = refusal(await call(world, world.runner, name, **arguments))
        assert refused["code"] == "forbidden", name

    assert count(world, "tasks") == 0
    assert count(world, "contacts") == 0


async def test_another_owners_routine_finds_nothing_and_starts_nothing() -> None:
    world = make_world()
    automation = await approved_automation(world)
    run = await started(world, automation)

    foreign_start = await start(world, automation, world.stranger_runner)
    foreign_record = await record(world, run, world.stranger_runner, final=True)

    for result in (foreign_start, foreign_record):
        assert refusal(result)["code"] == "not_found"
        assert INSTRUCTION not in all_text(result)
    assert count(world, "automation_runs") == 1
    assert run_row(world, run["id"])["state"] == "running"


# --- retries, leases and caps -----------------------------------------------------------------


async def test_a_failed_run_is_tried_again_up_to_three_attempts() -> None:
    world = make_world()
    automation = await approved_automation(world)

    attempts = []
    for _ in range(3):
        run = await started(world, automation)
        attempts.append(run["attempt"])
        await recorded(world, run, final=True, outcome="failed")
    fourth = await start(world, automation)

    assert attempts == [1, 2, 3]
    assert refusal(fourth)["reason"] == "ai_limit_reached"
    assert count(world, "automation_runs") == 3


async def test_a_silent_run_keeps_its_occurrence_until_the_lease_runs_out() -> None:
    world = make_world()
    automation = await approved_automation(world)
    first = await started(world, automation)

    world.clock.advance(timedelta(minutes=29))
    within = await started(world, automation)
    world.clock.advance(timedelta(minutes=31))
    taken_over = await started(world, automation)

    assert within["id"] == first["id"]
    assert taken_over["id"] != first["id"]
    assert taken_over["attempt"] == 2
    assert run_row(world, first["id"])["state"] == "lapsed"
    assert count(world, "audit_events", event="automation.run_ended") == 1


async def test_a_call_renews_the_lease() -> None:
    world = make_world()
    automation = await approved_automation(world)
    run = await started(world, automation)

    world.clock.advance(timedelta(minutes=25))
    renewed = await recorded(world, run)
    world.clock.advance(timedelta(minutes=25))
    again = await started(world, automation)

    assert renewed["run"]["lease_until"] > run["lease_until"]
    assert again["id"] == run["id"]


async def test_the_day_has_a_cap_on_new_runs() -> None:
    world = make_world()
    automation = await approved_automation(world, drop=("cadence",))
    with_limits(world, runs_per_day=2)

    await started(world, automation, occurrence="manual")
    await started(world, automation, occurrence="manual")
    third = await start(world, automation, occurrence="manual")
    world.clock.advance(timedelta(days=1))
    next_day = await start(world, automation, occurrence="manual")

    assert refusal(third)["reason"] == "ai_limit_reached"
    assert not next_day.is_error
    assert count(world, "automation_runs") == 3


@pytest.mark.parametrize("cap", [1, 3])
async def test_the_day_cap_holds_when_many_automations_start_at_once(cap: int) -> None:
    world = make_world()
    automations = [
        await approved_automation(world, drop=("cadence",), title=f"Automation {number}")
        for number in range(8)
    ]
    with_limits(world, runs_per_day=cap)
    service = world.container.automation_runs
    barrier = threading.Barrier(len(automations))

    def start_one(automation: dict[str, Any]) -> str:
        barrier.wait()
        try:
            service.start(
                world.runner,
                UUID(automation["id"]),
                runner=RunRunner.CLAUDE,
                occurrence=OccurrenceKind.MANUAL,
                idempotency_key=f"run-{uuid4().hex}",
                session_id=None,
                credential_kind=CredentialKind.TOKEN,
            )
        except ConflictError as error:
            return str(error.reason)
        return "started"

    with ThreadPoolExecutor(len(automations)) as pool:
        outcomes = list(pool.map(start_one, automations))

    assert outcomes.count("started") == cap
    assert set(outcomes) <= {"started", "ai_limit_reached"}
    assert count(world, "automation_runs") == cap


async def test_the_month_has_a_cap_on_what_automation_runs_cost() -> None:
    world = make_world()
    automation = await approved_automation(world, drop=("cadence",))
    with_limits(world, automation_monthly_cap_microusd=500_000)
    seed_run(
        world,
        automation["id"],
        occurrence_key="m:seeded",
        state="done",
        finished_at=world.clock.now(),
        created_at=world.clock.now(),
        cost_microusd=500_000,
        cost_source="provider",
    )

    refused = refusal(await start(world, automation, occurrence="manual"))

    assert refused["reason"] == "ai_budget_reached"


async def test_what_a_client_says_it_spent_never_counts_against_the_cap() -> None:
    world = make_world()
    automation = await approved_automation(world, drop=("cadence",))
    with_limits(world, automation_monthly_cap_microusd=500_000)
    seed_run(
        world,
        automation["id"],
        occurrence_key="m:seeded",
        state="done",
        finished_at=world.clock.now(),
        created_at=world.clock.now(),
        cost_microusd=900_000,
        cost_source="client_estimate",
    )

    result = await start(world, automation, occurrence="manual")

    assert not result.is_error, result.structured_content


# --- the session ------------------------------------------------------------------------------


async def test_the_session_is_kept_only_as_a_keyed_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    world = make_world()
    automation = await approved_automation(world)
    monkeypatch.setattr(
        "sidekick.mcp.automation_run_tools.request_session_id", lambda: "SENTINEL-SESSION-ID"
    )

    run = await started(world, automation)

    digest = run_row(world, run["id"])["session_digest"]
    assert digest is not None
    assert len(digest) == 64
    assert "SENTINEL-SESSION-ID" not in digest


async def test_a_transport_without_a_session_leaves_the_digest_unknown() -> None:
    world = make_world()
    automation = await approved_automation(world)

    run = await started(world, automation)

    assert run_row(world, run["id"])["session_digest"] is None

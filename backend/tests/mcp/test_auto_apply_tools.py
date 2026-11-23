"""Applying suggestions without the owner's click: an opt-in the owner makes in the app, and the
same apply, audit and undo as any approval.

The policy is off unless the owner approved an automation whose spec says so and confirmed it in
that call. It applies only what the independent check cleared, through the use case an approval
uses, and every card it applied is listed for the report with its undo.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest

from sidekick.automations.application.suggestions import AutoApplyOutcome
from sidekick.automations.domain.grouping import AutoApplyRefusal
from sidekick.automations.domain.suggestion import SuggestionState
from tests.support.automation_run_world import (
    all_text,
    count,
    person,
    refusal,
    scalar,
    task_suggestion,
)
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401  (the `all_logs` fixture)
    _Collector,
)
from tests.support.suggestion_world import Desk, call, checked, make_desk, ok, propose, set_card

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

AUTO = {"apply_mode": "auto_low_risk", "auto_effects": ["create_task"]}
TITLE_TEXT = "SENTINEL-AUTO-TITLE call the landlord"
RATIONALE = "SENTINEL-AUTO-RATIONALE the mail asks for it"


async def auto_desk(monkeypatch: pytest.MonkeyPatch, **spec: Any) -> Desk:
    return await make_desk(monkeypatch, spec={**AUTO, **spec}, auto_apply_confirmed=True)


def apply_policy(desk: Desk, *, checker_configured: bool = True) -> AutoApplyOutcome:
    return desk.world.container.automation_suggestions.auto_apply_run(
        desk.claude.user_id,
        UUID(desk.run["id"]),
        checker_configured=checker_configured,
    )


def task_titles(desk: Desk) -> list[str]:
    return [
        str(title)
        for title in scalar(
            desk.world,
            "SELECT coalesce(array_agg(title ORDER BY title), '{}') FROM sidekick.tasks "
            "WHERE trashed_at IS NULL",
        )
    ]


# --- the owner's choice ------------------------------------------------------------------------


async def test_an_automation_that_applies_without_a_click_is_approved_only_with_the_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(AssertionError) as unconfirmed:
        await make_desk(monkeypatch, spec=AUTO)
    assert "approve_automation" in str(unconfirmed.value)

    desk = await make_desk(monkeypatch, spec=AUTO, auto_apply_confirmed=True)

    assert desk.automation["approval"] == "approved"
    assert desk.automation["state"] == "active"


async def test_a_model_cannot_approve_the_choice_even_with_the_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    saved = await ok(
        desk,
        desk.claude,
        "save_automation",
        changes=AUTO,
        automation_id=desk.automation["id"],
        expected_version=desk.automation["version"],
        idempotency_key="auto-draft-1",
    )
    draft = saved["automation"]

    refused = await call(
        desk,
        desk.world.app,
        "approve_automation",
        automation_id=draft["id"],
        spec_digest=draft["spec_digest"],
        auto_apply_confirmed=True,
        idempotency_key="auto-approve-1",
    )

    assert refusal(refused)["code"] == "forbidden"
    assert draft["state"] == "draft"


async def test_a_change_to_the_spec_by_a_model_withdraws_the_choice_until_the_owner_approves_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await auto_desk(monkeypatch)
    (card,) = await propose(desk)
    checked(desk, card)
    await ok(
        desk,
        desk.claude,
        "save_automation",
        changes={"auto_threshold": 90},
        automation_id=desk.automation["id"],
        expected_version=desk.automation["version"],
        idempotency_key="auto-change-1",
    )

    outcome = apply_policy(desk)

    assert outcome.applied == ()
    assert outcome.refused == {AutoApplyRefusal.SPEC_NOT_APPROVED: 1}
    assert task_titles(desk) == []


# --- what the policy does ----------------------------------------------------------------------


async def test_a_card_the_check_cleared_is_applied_and_listed_and_the_owner_can_undo_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await auto_desk(monkeypatch)
    cards = {
        item["summary"]: item
        for item in await propose(
            desk, task_suggestion("Call the dentist"), task_suggestion("Water the plants")
        )
    }
    cleared = cards["Create task: Call the dentist"]
    doubtful = cards["Create task: Water the plants"]
    checked(desk, cleared)
    checked(desk, doubtful, verdict="uncertain", confidence=70)

    outcome = apply_policy(desk)

    assert [str(card_id) for card_id in outcome.applied] == [cleared["id"]]
    assert task_titles(desk) == ["Call the dentist"]
    applied = (await ok(desk, desk.claude, "get_suggestion", suggestion_id=cleared["id"]))[
        "suggestion"
    ]
    assert applied["state"] == "applied"
    other = (await ok(desk, desk.claude, "get_suggestion", suggestion_id=doubtful["id"]))[
        "suggestion"
    ]
    assert other["state"] == "pending"

    service = desk.world.container.automation_suggestions
    listed = service.list_auto_applied(desk.claude)
    assert [view.suggestion.id for view in listed.items] == [UUID(cleared["id"])]
    assert listed.hidden == 0
    (view,) = listed.items
    assert (view.suggestion.decided_by.value, view.suggestion.decision_channel.value) == (
        "policy",
        "policy",
    )

    await ok(
        desk,
        desk.claude,
        "undo_suggestion",
        app=True,
        suggestion_id=cleared["id"],
        expected_version=applied["version"],
    )
    assert task_titles(desk) == []
    after = service.list_auto_applied(desk.claude)
    assert [item.suggestion.state for item in after.items] == [SuggestionState.UNDONE]


async def test_the_policy_is_off_by_default_and_leaves_a_cleared_card_for_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    checked(desk, card)

    outcome = apply_policy(desk)

    assert outcome.applied == ()
    assert task_titles(desk) == []
    assert desk.world.container.automation_suggestions.list_auto_applied(desk.claude).items == ()


async def test_a_card_that_was_not_checked_is_never_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await auto_desk(monkeypatch)
    await propose(desk)

    outcome = apply_policy(desk)

    assert outcome.applied == ()
    assert task_titles(desk) == []


async def test_without_a_checker_nothing_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    desk = await auto_desk(monkeypatch)
    (card,) = await propose(desk)
    checked(desk, card)

    outcome = apply_policy(desk, checker_configured=False)

    assert outcome.applied == ()
    assert task_titles(desk) == []
    assert count(desk.world, "automation_suggestions", state="pending") == 1


async def test_a_card_past_its_time_to_live_is_left_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await auto_desk(monkeypatch)
    (card,) = await propose(desk)
    checked(desk, card)
    desk.world.clock.advance(timedelta(days=15))

    outcome = apply_policy(desk)

    assert outcome.applied == ()
    assert outcome.refused == {AutoApplyRefusal.EXPIRED: 1}
    assert task_titles(desk) == []


async def test_a_contact_is_applied_only_from_an_address_on_the_sender_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(
        monkeypatch,
        effects=("create_task", "create_contact"),
        spec={"apply_mode": "auto_low_risk", "auto_effects": ["create_contact"]},
        auto_apply_confirmed=True,
    )
    cards = await propose(
        desk,
        {
            "effect": "create_contact.v1",
            "payload": {"display_name": "Anna Svensson", "email": "anna@example.se"},
            "rationale": "From the mail.",
            "datapoint_refs": ["anna"],
        },
        {
            "effect": "create_contact.v1",
            "payload": {"display_name": "Bo Berg", "email": "bo@elsewhere.example"},
            "rationale": "From the mail.",
            "datapoint_refs": ["anna"],
        },
        datapoints=[person()],
    )
    for card in cards:
        checked(desk, card)
        if card["flags"]:  # the check never makes a flagged card eligible for a group
            set_card(desk, card["id"], bulk_eligible=False)

    outcome = apply_policy(desk)

    assert len(outcome.applied) == 1
    assert count(desk.world, "contacts") == len(outcome.applied)
    pending = count(desk.world, "automation_suggestions", state="pending")
    assert pending == len(cards) - len(outcome.applied)


# --- the report's read -------------------------------------------------------------------------


async def test_what_was_applied_is_the_owners_and_hides_a_domain_the_reader_may_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await auto_desk(monkeypatch)
    (card,) = await propose(desk)
    checked(desk, card)
    apply_policy(desk)
    service = desk.world.container.automation_suggestions
    now = desk.world.clock.now()

    narrow = service.list_auto_applied(desk.narrow)
    stranger = service.list_auto_applied(desk.other)
    recent = service.list_auto_applied(desk.claude, since=now - timedelta(hours=1))
    later = service.list_auto_applied(desk.claude, since=now + timedelta(hours=1))

    assert (narrow.items, narrow.hidden) == ((), 1)
    assert (stranger.items, stranger.hidden) == ((), 0)
    assert len(recent.items) == 1
    assert later.items == ()


# --- redaction ---------------------------------------------------------------------------------


async def test_no_text_of_a_card_reaches_a_log_the_audit_trail_or_a_replay_record(
    monkeypatch: pytest.MonkeyPatch, all_logs: _Collector
) -> None:
    desk = await auto_desk(monkeypatch)
    (card,) = await propose(
        desk, task_suggestion(TITLE_TEXT, payload={"title": TITLE_TEXT}, rationale=RATIONALE)
    )
    checked(desk, card)

    outcome = apply_policy(desk)

    assert len(outcome.applied) == 1
    rendered = all_logs.rendered()
    assert TITLE_TEXT not in rendered
    assert RATIONALE not in rendered
    assert all(record.exc_info is None for record in all_logs.records)
    audit = scalar(desk.world, "SELECT string_agg(t::text, ' ') FROM sidekick.audit_events t")
    assert TITLE_TEXT not in audit
    assert RATIONALE not in audit
    assert "suggestion.auto_applied" in audit
    shown = all_text(await call(desk, desk.claude, "get_suggestion", suggestion_id=card["id"]))
    assert RATIONALE in shown  # the owner reads the text; only the traces do not hold it


async def test_the_policy_locks_the_automation_before_the_run_as_every_run_writer_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await auto_desk(monkeypatch)
    (card,) = await propose(desk)
    checked(desk, card)
    store: Any = desk.world.container.automation_suggestions.store
    locks: list[str] = []
    get_automation, get_run = store.get_automation, store.get_run

    def automation_spy(*args: Any, lock: bool = False, **kwargs: Any) -> Any:
        if lock:
            locks.append("automation")
        return get_automation(*args, lock=lock, **kwargs)

    def run_spy(*args: Any, lock: bool = False, **kwargs: Any) -> Any:
        if lock:
            locks.append("run")
        return get_run(*args, lock=lock, **kwargs)

    monkeypatch.setattr(store, "get_automation", automation_spy)
    monkeypatch.setattr(store, "get_run", run_spy)

    apply_policy(desk)

    assert locks[:2] == ["automation", "run"]

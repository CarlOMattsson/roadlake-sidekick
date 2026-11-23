"""Reading, deciding, applying and undoing suggestions through a real FastMCP client and database.

The owner decides. A model decides at most three cards per call, and never a flagged one, one it
proposed in its own session or an edited one. Approving applies the effect through the Task or
Contact use case in the same transaction, once however the call is retried or overlapped, and an
undo moves the created record to the trash only while it is as it was created. Text of a card
stays in the card: no log, audit event or replay record holds it.
"""

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastmcp.client.client import CallToolResult
from sqlalchemy import text

from tests.support.automation_run_world import (
    all_text,
    count,
    person,
    recorded,
    refusal,
    scalar,
    set_column,
    task_suggestion,
    with_limits,
)
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401  (the `all_logs` fixture)
    _Collector,
)
from tests.support.suggestion_world import (
    OTHER_SESSION,
    RUN_SESSION,
    Desk,
    call,
    checked,
    decide,
    decided_in_session,
    decision,
    make_desk,
    ok,
    owner_actor,
    propose,
    set_card,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

TITLE_TEXT = "SENTINEL-TASK-TITLE call the landlord"
RATIONALE = "SENTINEL-RATIONALE the mail asks for it"


def row(desk: Desk, sql: str, **parameters: Any) -> dict[str, Any]:
    store: Any = desk.world.container.session_factory
    with store.begin() as session:
        return dict(session.execute(text(sql), parameters).mappings().one())


def card_row(desk: Desk, suggestion_id: str) -> dict[str, Any]:
    return row(
        desk,
        "SELECT * FROM sidekick.automation_suggestions WHERE id = :id",
        id=UUID(suggestion_id),
    )


def events(desk: Desk, target_id: str) -> list[tuple[str, str | None]]:
    store: Any = desk.world.container.session_factory
    with store.begin() as session:
        rows = session.execute(
            text(
                "SELECT event, source FROM sidekick.audit_events WHERE target_id = :id "
                "ORDER BY occurred_at, id"
            ),
            {"id": UUID(target_id)},
        ).all()
    return [(event, source) for event, source in rows]


async def get(desk: Desk, card: dict[str, Any]) -> dict[str, Any]:
    return (await ok(desk, desk.claude, "get_suggestion", suggestion_id=card["id"]))["suggestion"]


def contact_suggestion(name: str = "Anna Svensson", **payload: Any) -> dict[str, Any]:
    return {
        "effect": "create_contact.v1",
        "payload": {"display_name": name, "email": "anna@example.se", **payload},
        "rationale": "The mail is from her.",
        "datapoint_refs": ["anna"],
    }


# --- the inbox --------------------------------------------------------------------------------


async def test_the_inbox_lists_pending_cards_with_a_line_the_flags_and_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    await propose(desk, task_suggestion("Call the dentist"))

    listed = await ok(desk, desk.claude, "list_suggestions")

    (item,) = listed["items"]
    assert item["summary"] == "Create task: Call the dentist"
    assert (item["effect"], item["state"], item["version"]) == ("create_task", "pending", 2)
    assert item["flags"] == []
    assert item["check"] == {"state": "off", "verdict": None, "confidence": None}
    assert item["bulk_eligible"] is False
    assert item["automation_id"] == desk.automation["id"]
    assert listed["groups"] == []
    assert listed["hidden"] == 0
    assert listed["next_cursor"] is None


async def test_a_card_of_a_domain_the_session_cannot_read_is_counted_and_not_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk, task_suggestion("SENTINEL-HIDDEN-TITLE"))

    listed = await ok(desk, desk.narrow, "list_suggestions")
    detail = await call(desk, desk.narrow, "get_suggestion", suggestion_id=card["id"])

    assert listed["items"] == []
    assert listed["hidden"] == 1
    assert "SENTINEL-HIDDEN-TITLE" not in all_text(
        await call(desk, desk.narrow, "list_suggestions")
    )
    assert refusal(detail)["code"] == "forbidden"


async def test_the_inbox_pages_and_the_cursor_belongs_to_the_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    await propose(
        desk,
        task_suggestion("First", payload={"title": "First"}),
        task_suggestion("Second", payload={"title": "Second"}),
        task_suggestion("Third", payload={"title": "Third"}),
    )

    first = await ok(desk, desk.claude, "list_suggestions", limit=2)
    second = await ok(desk, desk.claude, "list_suggestions", limit=2, cursor=first["next_cursor"])
    other_query = await call(
        desk, desk.claude, "list_suggestions", state="dismissed", cursor=first["next_cursor"]
    )

    paged = [item["summary"] for item in [*first["items"], *second["items"]]]
    assert (len(first["items"]), len(second["items"])) == (2, 1)
    assert sorted(paged) == ["Create task: First", "Create task: Second", "Create task: Third"]
    assert second["next_cursor"] is None
    assert other_query.is_error


async def test_a_checked_card_is_in_the_high_confidence_group_and_the_others_are_single(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    sure, unsure = await propose(
        desk,
        task_suggestion("Sure", payload={"title": "Sure"}),
        task_suggestion("Unsure", payload={"title": "Unsure"}),
    )
    checked(desk, sure)

    group = await ok(desk, desk.claude, "list_suggestions", group="high_confidence")
    single = await ok(desk, desk.claude, "list_suggestions", group="single")

    assert [item["id"] for item in group["items"]] == [sure["id"]]
    assert group["items"][0]["bulk_eligible"] is True
    assert [item["id"] for item in single["items"]] == [unsure["id"]]
    (listed_group,) = group["groups"]
    assert listed_group["suggestion_ids"] == [sure["id"]]
    assert listed_group["count"] == 1
    assert listed_group["automation_id"] == desk.automation["id"]


async def test_a_card_is_one_in_full_with_its_rationale_and_the_facts_it_rests_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(
        desk,
        task_suggestion("Call the dentist", rationale=RATIONALE),
        datapoints=[person(source_label="Re: dentist")],
    )

    detail = await get(desk, card)

    assert detail["payload"]["title"] == "Call the dentist"
    assert detail["rationale"] == RATIONALE
    assert detail["source_label"] == "Re: dentist"
    (point,) = detail["datapoints"]
    assert (point["kind"], point["fields"]["name"]) == ("person", "Anna Svensson")
    assert detail["checks"] == []
    assert "not_checked" in detail["blockers"]
    assert detail["applied"] is None


async def test_another_owners_card_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    result = await call(desk, desk.other, "get_suggestion", suggestion_id=card["id"])

    assert refusal(result)["code"] == "not_found"


async def test_a_card_held_for_a_check_nobody_does_is_decidable_when_the_inbox_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    with_limits(desk.world, checker_enabled=True)
    await recorded(
        desk.world,
        desk.run,
        datapoints=[person()],
        suggestions=[task_suggestion()],
        final=True,
        outcome="ok",
    )
    with_limits(desk.world, checker_enabled=False)

    listed = await ok(desk, desk.claude, "list_suggestions")

    (item,) = listed["items"]
    assert item["state"] == "pending"
    answer = await decide(desk, desk.claude, decision(item), app=True)
    assert answer["items"][0]["state"] == "applied"


async def test_reading_a_card_also_ends_the_wait_for_a_check_nobody_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    with_limits(desk.world, checker_enabled=True)
    recorded_results = await recorded(
        desk.world,
        desk.run,
        datapoints=[person()],
        suggestions=[task_suggestion()],
        final=True,
        outcome="ok",
    )
    with_limits(desk.world, checker_enabled=False)
    (proposed,) = recorded_results["suggestions"]

    detail = await ok(desk, desk.claude, "get_suggestion", suggestion_id=proposed["id"])

    assert detail["suggestion"]["state"] == "pending"


async def test_a_session_that_may_not_read_suggestions_releases_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    with_limits(desk.world, checker_enabled=True)
    await recorded(
        desk.world,
        desk.run,
        datapoints=[person()],
        suggestions=[task_suggestion()],
        final=True,
        outcome="ok",
    )
    with_limits(desk.world, checker_enabled=False)
    blind = owner_actor(desk.world, "tasks:read")

    refused = await call(desk, blind, "list_suggestions")

    assert refusal(refused)["code"] == "forbidden"
    state = scalar(desk.world, "SELECT state FROM sidekick.automation_suggestions")
    assert state == "checking"


# --- deciding ---------------------------------------------------------------------------------


async def test_the_owner_approves_in_the_app_and_the_task_is_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(
        desk,
        task_suggestion(
            "Call the dentist",
            payload={"title": "Call the dentist", "priority": "high", "due_on": "2026-12-01"},
        ),
    )

    answer = await decide(desk, desk.claude, decision(card), app=True)

    (item,) = answer["items"]
    assert item["error_code"] is None
    assert (item["state"], item["version"]) == ("applied", card["version"] + 1)
    assert item["applied"]["kind"] == "task"
    task = row(
        desk,
        "SELECT title, priority, due_at, version FROM sidekick.tasks WHERE id = :id",
        id=UUID(item["applied"]["id"]),
    )
    assert (task["title"], task["priority"], task["version"]) == ("Call the dentist", "high", 1)
    assert task["due_at"].date().isoformat() in {"2026-12-01", "2026-11-30"}
    stored = card_row(desk, card["id"])
    assert (stored["decided_by"], stored["decision_channel"]) == ("you", "app")
    assert (stored["applied_kind"], stored["applied_version"]) == ("task", 1)
    assert [event for event, _ in events(desk, card["id"])] == ["suggestion.applied"]
    assert events(desk, card["id"])[0][1] == "you"


async def test_an_approved_contact_suggestion_creates_the_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch, effects=("create_contact",))
    (card,) = await propose(desk, contact_suggestion())

    answer = await decide(desk, desk.claude, decision(card), app=True)

    (item,) = answer["items"]
    assert item["applied"]["kind"] == "contact"
    contact = row(
        desk,
        "SELECT display_name, email, version FROM sidekick.contacts WHERE id = :id",
        id=UUID(item["applied"]["id"]),
    )
    assert (contact["display_name"], contact["email"]) == ("Anna Svensson", "anna@example.se")


async def test_a_dismissed_card_creates_nothing_and_cannot_be_decided_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    answer = await decide(desk, desk.claude, decision(card, "dismiss"), app=True)
    again = await decide(
        desk,
        desk.claude,
        decision({**card, "version": answer["items"][0]["version"]}),
        app=True,
    )

    assert answer["items"][0]["state"] == "dismissed"
    assert again["items"][0]["error_code"] == "not_pending"
    assert count(desk.world, "tasks") == 0
    assert [event for event, _ in events(desk, card["id"])] == ["suggestion.dismissed"]


async def test_a_call_decides_at_most_three_cards_by_its_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    cards = await propose(
        desk, *(task_suggestion(f"T{n}", payload={"title": f"T{n}"}) for n in range(4))
    )
    async with desk.world.server.client(desk.claude) as client:
        tool = next(item for item in await client.list_tools() if item.name == "decide_suggestions")

    refused = await call(
        desk, desk.claude, "decide_suggestions", items=[decision(card) for card in cards]
    )

    assert tool.inputSchema["properties"]["items"]["maxItems"] == 3
    assert refused.is_error
    assert count(desk.world, "tasks") == 0


async def test_a_stale_version_is_refused_for_that_card_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    stale, fresh = await propose(
        desk,
        task_suggestion("Stale", payload={"title": "Stale"}),
        task_suggestion("Fresh", payload={"title": "Fresh"}),
    )

    answer = await decide(
        desk,
        desk.claude,
        decision({**stale, "version": stale["version"] + 5}),
        decision(fresh),
        app=True,
    )

    assert [item["error_code"] for item in answer["items"]] == ["stale", None]
    assert [item["state"] for item in answer["items"]] == ["pending", "applied"]
    assert count(desk.world, "tasks") == 1


async def test_an_approval_needs_the_write_scope_of_the_domain_and_a_dismissal_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    approve_me, dismiss_me = await propose(
        desk,
        task_suggestion("A", payload={"title": "A"}),
        task_suggestion("B", payload={"title": "B"}),
    )

    approval = await call(
        desk, desk.narrow, "decide_suggestions", app=True, items=[decision(approve_me)]
    )
    dismissal = await ok(
        desk, desk.narrow, "decide_suggestions", app=True, items=[decision(dismiss_me, "dismiss")]
    )

    assert refusal(approval)["code"] == "forbidden"
    assert dismissal["items"][0]["state"] == "dismissed"
    assert count(desk.world, "tasks") == 0


async def test_another_owners_card_is_not_found_and_nothing_else_is_decided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    mine, theirs = await propose(
        desk,
        task_suggestion("Mine", payload={"title": "Mine"}),
        task_suggestion("Theirs", payload={"title": "Theirs"}),
    )

    result = await call(
        desk,
        desk.other,
        "decide_suggestions",
        app=True,
        items=[decision(theirs)],
    )

    assert refusal(result)["code"] == "not_found"
    assert card_row(desk, mine["id"])["state"] == "pending"
    assert card_row(desk, theirs["id"])["state"] == "pending"


# --- what a model may decide ------------------------------------------------------------------


async def test_a_model_decides_an_unflagged_card_from_another_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    decided_in_session(monkeypatch, OTHER_SESSION)

    answer = await decide(desk, desk.claude, decision(card))

    assert answer["items"][0]["state"] == "applied"
    stored = card_row(desk, card["id"])
    assert (stored["decided_by"], stored["decision_channel"]) == ("claude", "model")
    assert events(desk, card["id"]) == [("suggestion.applied", "claude")]


async def test_a_model_does_not_decide_in_the_session_that_ran_the_automation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    decided_in_session(monkeypatch, RUN_SESSION)

    answer = await decide(desk, desk.claude, decision(card))

    assert answer["items"][0]["error_code"] == "same_session"
    assert card_row(desk, card["id"])["state"] == "pending"
    assert count(desk.world, "tasks") == 0


async def test_a_session_the_transport_cannot_name_is_treated_as_the_running_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    decided_in_session(monkeypatch, None)

    answer = await decide(desk, desk.claude, decision(card))

    assert answer["items"][0]["error_code"] == "same_session"


async def test_a_model_never_decides_a_flagged_card_and_the_app_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(
        desk, task_suggestion("Pay at https://example.com/pay", payload={"title": "Open link"})
    )
    set_card(desk, card["id"], screening_flags=["contains_link"])
    decided_in_session(monkeypatch, OTHER_SESSION)

    by_model = await decide(desk, desk.claude, decision(card))
    by_owner = await decide(desk, desk.claude, decision(card), app=True)

    assert by_model["items"][0]["error_code"] == "needs_app"
    assert by_owner["items"][0]["state"] == "applied"


async def test_a_suspicious_card_needs_the_owners_second_tap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    checked(desk, card, "suspicious", 20)

    first = await decide(desk, desk.claude, decision(card), app=True)
    second = await decide(desk, desk.claude, decision(card, confirmed=True), app=True)

    assert first["items"][0]["error_code"] == "needs_confirmation"
    assert second["items"][0]["state"] == "applied"


async def test_a_model_cannot_edit_a_card(monkeypatch: pytest.MonkeyPatch) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    decided_in_session(monkeypatch, OTHER_SESSION)

    answer = await decide(desk, desk.claude, decision(card, edits={"title": "Changed"}))

    assert answer["items"][0]["error_code"] == "needs_app"
    assert card_row(desk, card["id"])["payload"]["title"] == "Call the dentist"
    assert count(desk.world, "tasks") == 0


async def test_an_edit_belongs_to_an_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    result = await call(
        desk,
        desk.claude,
        "decide_suggestions",
        app=True,
        items=[decision(card, "dismiss", edits={"title": "Changed"})],
    )

    assert refusal(result)["code"] == "validation_error"


# --- editing and applying ---------------------------------------------------------------------


async def test_the_owners_edit_is_validated_and_applied_with_the_proposal_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    answer = await decide(
        desk, desk.claude, decision(card, edits={"title": "Call the dentist before noon"}), app=True
    )

    task_id = answer["items"][0]["applied"]["id"]
    assert scalar(
        desk.world, "SELECT title FROM sidekick.tasks WHERE id = :id", id=UUID(task_id)
    ) == ("Call the dentist before noon")
    stored = card_row(desk, card["id"])
    assert stored["payload"]["title"] == "Call the dentist before noon"
    assert stored["proposed_payload"]["title"] == "Call the dentist"
    assert [event for event, _ in events(desk, card["id"])] == [
        "suggestion.edited",
        "suggestion.applied",
    ]


async def test_an_edit_that_is_not_a_valid_payload_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    answer = await decide(
        desk, desk.claude, decision(card, edits={"title": "", "send_to": "x"}), app=True
    )

    assert answer["items"][0]["error_code"] == "invalid_edit"
    stored = card_row(desk, card["id"])
    assert (stored["state"], stored["version"], stored["payload"]) == (
        "pending",
        card["version"],
        stored["proposed_payload"],
    )


async def test_an_edit_is_screened_again_and_a_link_it_adds_flags_the_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    set_card(desk, card["id"], screening_flags=[])

    await decide(
        desk,
        desk.claude,
        decision(card, edits={"description": "see https://example.com/x"}),
        app=True,
    )

    stored = card_row(desk, card["id"])
    assert stored["state"] == "applied"
    assert "contains_link" in stored["screening_flags"]


async def test_a_card_whose_project_is_gone_stays_pending_with_a_closed_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    gone = "00000000-0000-7000-8000-00000000dead"
    set_card(desk, card["id"], payload={"title": "Call", "project_id": gone})

    answer = await decide(desk, desk.claude, decision(card), app=True)

    (item,) = answer["items"]
    assert item["error_code"] == "apply_error:project_gone"
    assert item["state"] == "pending"
    stored = card_row(desk, card["id"])
    assert (stored["state"], stored["apply_error"]) == ("pending", "project_gone")
    assert count(desk.world, "tasks") == 0
    assert [event for event, _ in events(desk, card["id"])] == ["suggestion.apply_failed"]


async def test_an_expired_card_is_not_decided_or_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    set_card(desk, card["id"], expires_at=desk.world.clock.current - timedelta(minutes=1))

    answer = await decide(desk, desk.claude, decision(card), app=True)
    listed = await ok(desk, desk.claude, "list_suggestions")

    assert answer["items"][0]["error_code"] == "expired"
    assert listed["items"] == []


# --- once, however it is retried ---------------------------------------------------------------


async def test_a_retry_with_the_same_key_answers_the_same_and_creates_one_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    first = await decide(desk, desk.claude, decision(card), app=True, idempotency_key="retry-key-1")
    replay = await decide(
        desk, desk.claude, decision(card), app=True, idempotency_key="retry-key-1"
    )

    assert replay == first
    assert count(desk.world, "tasks") == 1
    assert len(events(desk, card["id"])) == 1


async def test_a_key_used_for_another_decision_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    desk = await make_desk(monkeypatch)
    one, two = await propose(
        desk,
        task_suggestion("One", payload={"title": "One"}),
        task_suggestion("Two", payload={"title": "Two"}),
    )
    await decide(desk, desk.claude, decision(one), app=True, idempotency_key="shared-key-1")

    other = await call(
        desk,
        desk.claude,
        "decide_suggestions",
        app=True,
        items=[decision(two)],
        idempotency_key="shared-key-1",
    )

    assert refusal(other)["code"] == "conflict"


async def test_two_calls_that_overlap_create_one_record(monkeypatch: pytest.MonkeyPatch) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    async def approve() -> CallToolResult:
        return await call(desk, desk.claude, "decide_suggestions", app=True, items=[decision(card)])

    first, second = await asyncio.gather(approve(), approve())

    results = [first, second]
    assert all(not result.is_error for result in results)
    codes = sorted(
        str((result.structured_content or {})["items"][0]["error_code"]) for result in results
    )
    assert codes == ["None", "stale"]
    assert count(desk.world, "tasks") == 1
    assert card_row(desk, card["id"])["state"] == "applied"


# --- a group ----------------------------------------------------------------------------------


async def _group(desk: Desk) -> dict[str, Any]:
    listed = await ok(desk, desk.claude, "list_suggestions", group="high_confidence")
    (group,) = listed["groups"]
    return group


async def test_the_owner_approves_the_group_they_saw_in_the_app(
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
    group = await _group(desk)

    answer = await ok(
        desk,
        desk.claude,
        "approve_suggestion_group",
        app=True,
        group_digest=group["group_digest"],
        suggestion_ids=group["suggestion_ids"],
    )

    assert [item["state"] for item in answer["items"]] == ["applied", "applied"]
    assert count(desk.world, "tasks") == 2
    assert {
        stored["decision_channel"]
        for stored in map(lambda card: card_row(desk, card["id"]), (one, two))
    } == {"app"}


async def test_a_model_cannot_approve_a_group_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    checked(desk, card)
    group = await _group(desk)

    refused = await call(
        desk,
        desk.claude,
        "approve_suggestion_group",
        group_digest=group["group_digest"],
        suggestion_ids=group["suggestion_ids"],
    )

    assert refusal(refused)["reason"] == "app_only"
    assert count(desk.world, "tasks") == 0


async def test_a_group_that_changed_since_it_was_shown_is_refused_as_a_whole(
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
    group = await _group(desk)
    set_card(desk, two["id"], version=two["version"] + 1)

    refused = await call(
        desk,
        desk.claude,
        "approve_suggestion_group",
        app=True,
        group_digest=group["group_digest"],
        suggestion_ids=group["suggestion_ids"],
    )

    assert refusal(refused)["reason"] == "suggestion_group_refused"
    assert count(desk.world, "tasks") == 0
    assert card_row(desk, one["id"])["state"] == "pending"


async def test_a_card_that_lost_its_eligibility_refuses_the_whole_group(
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
    group = await _group(desk)
    set_card(desk, two["id"], screening_flags=["contains_link"], bulk_eligible=False)

    refused = await call(
        desk,
        desk.claude,
        "approve_suggestion_group",
        app=True,
        group_digest=group["group_digest"],
        suggestion_ids=group["suggestion_ids"],
    )

    assert refusal(refused)["reason"] == "suggestion_group_refused"
    assert count(desk.world, "tasks") == 0


async def test_a_group_of_cards_nobody_checked_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    refused = await call(
        desk,
        desk.claude,
        "approve_suggestion_group",
        app=True,
        group_digest="0" * 64,
        suggestion_ids=[card["id"]],
    )

    assert refusal(refused)["reason"] == "suggestion_group_refused"
    assert count(desk.world, "tasks") == 0


async def test_a_group_and_a_single_approval_that_overlap_create_one_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    checked(desk, card)
    group = await _group(desk)

    async def approve_group() -> CallToolResult:
        return await call(
            desk,
            desk.claude,
            "approve_suggestion_group",
            app=True,
            group_digest=group["group_digest"],
            suggestion_ids=group["suggestion_ids"],
        )

    async def approve_one() -> CallToolResult:
        return await call(desk, desk.claude, "decide_suggestions", app=True, items=[decision(card)])

    await asyncio.gather(approve_group(), approve_one())

    assert count(desk.world, "tasks") == 1
    assert card_row(desk, card["id"])["state"] == "applied"


# --- undo -------------------------------------------------------------------------------------


async def _applied(desk: Desk, monkeypatch_card: dict[str, Any]) -> dict[str, Any]:
    answer = await decide(desk, desk.claude, decision(monkeypatch_card), app=True)
    return answer["items"][0]


async def test_an_undo_moves_the_created_record_to_the_trash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    applied = await _applied(desk, card)

    undone = await ok(
        desk,
        desk.claude,
        "undo_suggestion",
        suggestion_id=card["id"],
        expected_version=applied["version"],
    )

    assert (undone["state"], undone["trashed"]) == ("undone", applied["applied"])
    task = row(
        desk,
        "SELECT trashed_at FROM sidekick.tasks WHERE id = :id",
        id=UUID(applied["applied"]["id"]),
    )
    assert task["trashed_at"] is not None
    assert card_row(desk, card["id"])["undone_at"] is not None
    assert [event for event, _ in events(desk, card["id"])] == [
        "suggestion.applied",
        "suggestion.undone",
    ]
    assert "task.trashed" in [event for event, _ in events(desk, applied["applied"]["id"])]


async def test_an_undo_is_refused_after_the_record_was_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    applied = await _applied(desk, card)
    set_column(desk.world, "tasks", applied["applied"]["id"], "version", 2)

    refused = await call(
        desk,
        desk.claude,
        "undo_suggestion",
        suggestion_id=card["id"],
        expected_version=applied["version"],
    )

    assert refusal(refused)["reason"] == "suggestion_undo_refused"
    assert card_row(desk, card["id"])["state"] == "applied"
    assert (
        row(
            desk,
            "SELECT trashed_at FROM sidekick.tasks WHERE id = :id",
            id=UUID(applied["applied"]["id"]),
        )["trashed_at"]
        is None
    )


async def _undo_is_refused(desk: Desk, card: dict[str, Any], applied: dict[str, Any]) -> None:
    refused = await call(
        desk,
        desk.claude,
        "undo_suggestion",
        suggestion_id=card["id"],
        expected_version=applied["version"],
    )

    assert refusal(refused)["reason"] == "suggestion_undo_refused"
    assert card_row(desk, card["id"])["state"] == "applied"
    table = "tasks" if applied["applied"]["kind"] == "task" else "contacts"
    trashed = scalar(
        desk.world,
        f"SELECT trashed_at FROM sidekick.{table} WHERE id = :id",  # noqa: S608
        id=UUID(applied["applied"]["id"]),
    )
    assert trashed is None


async def test_an_undo_is_refused_after_a_step_was_added_to_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    applied = await _applied(desk, card)
    desk.world.container.steps.create_step(
        desk.claude,
        UUID(applied["applied"]["id"]),
        title="Look up the number",
        idempotency_key="step-key-12345",
    )

    await _undo_is_refused(desk, card, applied)


async def test_an_undo_is_refused_after_a_contact_was_linked_to_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch, effects=("create_task", "create_contact"))
    cards = await propose(
        desk, task_suggestion("Call Anna", payload={"title": "Call Anna"}), contact_suggestion()
    )
    task_card = next(card for card in cards if card["effect"] == "create_task")
    contact_card = next(card for card in cards if card["effect"] == "create_contact")
    task = await _applied(desk, task_card)
    contact = await _applied(desk, contact_card)
    desk.world.container.contact_relations.link_task(
        desk.claude,
        UUID(contact["applied"]["id"]),
        UUID(task["applied"]["id"]),
        idempotency_key="link-key-12345",
    )

    await _undo_is_refused(desk, task_card, task)
    await _undo_is_refused(desk, contact_card, contact)


async def test_an_undo_is_refused_after_an_alias_was_added_to_the_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch, effects=("create_contact",))
    (card,) = await propose(desk, contact_suggestion())
    applied = await _applied(desk, card)
    desk.world.container.contacts.add_alias(
        desk.claude,
        UUID(applied["applied"]["id"]),
        "Annie",
        1,
        "alias-key-12345",
    )

    await _undo_is_refused(desk, card, applied)


async def test_an_undo_is_refused_for_a_card_that_was_never_applied_or_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    pending = await call(
        desk,
        desk.claude,
        "undo_suggestion",
        suggestion_id=card["id"],
        expected_version=card["version"],
    )
    applied = await _applied(desk, card)
    stale = await call(
        desk,
        desk.claude,
        "undo_suggestion",
        suggestion_id=card["id"],
        expected_version=applied["version"] + 3,
    )

    assert refusal(pending)["reason"] == "suggestion_undo_refused"
    assert refusal(stale)["reason"] == "stale_version"


async def test_an_undo_needs_the_write_scope_of_the_domain_and_a_retry_changes_nothing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)
    applied = await _applied(desk, card)
    arguments = {
        "suggestion_id": card["id"],
        "expected_version": applied["version"],
        "idempotency_key": "undo-once",
    }

    narrow = await call(desk, desk.narrow, "undo_suggestion", **arguments)
    first = await ok(desk, desk.claude, "undo_suggestion", **arguments)
    replay = await ok(desk, desk.claude, "undo_suggestion", **arguments)

    assert refusal(narrow)["code"] == "forbidden"
    assert replay == first
    assert (
        len([event for event, _ in events(desk, card["id"]) if event == "suggestion.undone"]) == 1
    )


# --- text stays in the card -------------------------------------------------------------------


async def test_no_text_of_a_card_reaches_a_log_an_audit_event_a_replay_or_a_decision(
    monkeypatch: pytest.MonkeyPatch, all_logs: _Collector
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(
        desk, task_suggestion(TITLE_TEXT, payload={"title": TITLE_TEXT}, rationale=RATIONALE)
    )
    decided_in_session(monkeypatch, OTHER_SESSION)

    decided = await call(
        desk,
        desk.claude,
        "decide_suggestions",
        items=[decision(card)],
        idempotency_key="text-key-1",
    )
    undone = await call(
        desk,
        desk.claude,
        "undo_suggestion",
        suggestion_id=card["id"],
        expected_version=(decided.structured_content or {})["items"][0]["version"],
    )

    for answer in (decided, undone):
        shown = all_text(answer)
        assert TITLE_TEXT not in shown
        assert RATIONALE not in shown
    rendered = all_logs.rendered()
    assert RATIONALE not in rendered
    assert TITLE_TEXT not in rendered
    assert all(record.exc_info is None for record in all_logs.records)
    audit = scalar(desk.world, "SELECT string_agg(t::text, ' ') FROM sidekick.audit_events t")
    replays = scalar(
        desk.world,
        "SELECT coalesce(string_agg(result::text, ' '), '') FROM sidekick.idempotency_operations",
    )
    assert TITLE_TEXT not in audit
    assert RATIONALE not in audit
    assert TITLE_TEXT not in replays
    assert RATIONALE not in replays


async def test_a_decision_is_logged_by_id_and_a_closed_outcome_only(
    monkeypatch: pytest.MonkeyPatch, all_logs: _Collector
) -> None:
    desk = await make_desk(monkeypatch)
    (card,) = await propose(desk)

    await decide(desk, desk.claude, decision(card), app=True)

    logged = {
        (item.__dict__["automation_suggestion_id"], item.__dict__["outcome"])
        for item in all_logs.records
        if item.name == "sidekick.automations.suggestions"
        and item.getMessage() == "automation_suggestion_decided"
    }
    assert logged == {(card["id"], "applied")}


async def test_another_owners_inbox_does_not_show_the_card_or_count_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk = await make_desk(monkeypatch)
    await propose(desk)

    listed = await ok(desk, desk.other, "list_suggestions")

    assert listed["items"] == []
    assert listed["hidden"] == 0

"""Decision tickets: signed, expiring, single-use proofs that the app showed the owner a decision.

Pure unit tests: the clock is a list the test moves forward, and no database is involved.
"""

from uuid import uuid4

import pytest
from fastmcp.tools import ToolResult

from sidekick.mcp.decision_ticket import (
    DECISION_TICKET_BINDING_META,
    DECISION_TICKETS_META,
    TICKET_LIFETIME_SECONDS,
    DecisionTickets,
    SpentTicket,
    TicketEntry,
    TicketRefusal,
    binding_of,
    ticket_binding,
    ticket_key,
    with_tickets,
)
from sidekick.shared.types import Actor

SECRET = "x" * 40
ENTRY = TicketEntry("approve_plan", "plan-1", "digest-1")
OWNER = "owner-1"
CLIENT = "client-1"


@pytest.fixture
def now() -> list[float]:
    return [1_000_000.0]


@pytest.fixture
def tickets(now: list[float]) -> DecisionTickets:
    return DecisionTickets(SECRET, clock=lambda: now[0])


def _with_part(ticket: str, index: int, value: str) -> str:
    parts = ticket.split(".")
    parts[index] = value
    return ".".join(parts)


def test_a_ticket_verifies_for_the_call_it_was_issued_for(tickets: DecisionTickets) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)

    result = tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT)

    assert isinstance(result, SpentTicket)


@pytest.mark.parametrize(
    "other",
    [
        TicketEntry("run_plan", "plan-1", "digest-1"),
        TicketEntry("approve_plan", "plan-2", "digest-1"),
        TicketEntry("approve_plan", "plan-1", "digest-2"),
    ],
    ids=["action", "object_id", "digest"],
)
def test_a_ticket_does_not_verify_for_another_entry(
    tickets: DecisionTickets, other: TicketEntry
) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)

    assert tickets.verify(ticket, other, owner=OWNER, client=CLIENT) is TicketRefusal.MISMATCH


@pytest.mark.parametrize(
    ("owner", "client"),
    [("owner-2", CLIENT), (OWNER, "client-2")],
    ids=["owner", "client"],
)
def test_a_ticket_does_not_verify_for_another_owner_or_client(
    tickets: DecisionTickets, owner: str, client: str
) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)

    assert tickets.verify(ticket, ENTRY, owner=owner, client=client) is TicketRefusal.MISMATCH


def test_a_changed_signature_is_a_mismatch(tickets: DecisionTickets) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)
    last = "A" if ticket[-1] != "A" else "B"
    tampered = ticket[:-1] + last

    assert tickets.verify(tampered, ENTRY, owner=OWNER, client=CLIENT) is TicketRefusal.MISMATCH


def test_a_changed_expiry_is_a_mismatch(tickets: DecisionTickets) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)
    expires = int(ticket.split(".")[1])
    tampered = _with_part(ticket, 1, str(expires + 60))

    assert tickets.verify(tampered, ENTRY, owner=OWNER, client=CLIENT) is TicketRefusal.MISMATCH


def test_a_changed_nonce_is_a_mismatch(tickets: DecisionTickets) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)
    nonce = ticket.split(".")[2]
    tampered = _with_part(ticket, 2, nonce[:-1] + ("A" if nonce[-1] != "A" else "B"))

    assert tickets.verify(tampered, ENTRY, owner=OWNER, client=CLIENT) is TicketRefusal.MISMATCH


def test_a_ticket_is_expired_just_after_its_lifetime(
    tickets: DecisionTickets, now: list[float]
) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)
    now[0] += TICKET_LIFETIME_SECONDS + 1

    assert tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT) is TicketRefusal.EXPIRED


def test_a_ticket_is_still_valid_at_exactly_its_expiry(
    tickets: DecisionTickets, now: list[float]
) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)
    now[0] += TICKET_LIFETIME_SECONDS

    assert isinstance(tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT), SpentTicket)


def test_a_spent_ticket_cannot_be_used_again(tickets: DecisionTickets) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)
    assert isinstance(tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT), SpentTicket)

    assert tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT) is TicketRefusal.USED


def test_a_released_ticket_can_be_used_again(tickets: DecisionTickets) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)
    spent = tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT)
    assert isinstance(spent, SpentTicket)

    tickets.release(spent)

    assert isinstance(tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT), SpentTicket)


def test_a_mismatch_does_not_spend_the_nonce(tickets: DecisionTickets) -> None:
    ticket = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)
    assert tickets.verify(ticket, ENTRY, owner="owner-2", client=CLIENT) is TicketRefusal.MISMATCH

    assert isinstance(tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT), SpentTicket)


def test_a_ticket_from_another_secret_does_not_verify(
    tickets: DecisionTickets, now: list[float]
) -> None:
    other = DecisionTickets("y" * 40, clock=lambda: now[0])
    ticket = other.issue(ENTRY, owner=OWNER, client=CLIENT)

    assert tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT) is TicketRefusal.MISMATCH


@pytest.mark.parametrize(
    "ticket",
    [
        "",
        "v2.1000900.nonce.mac",
        "v1.1000900.nonce",
        "v1.1000900.nonce.mac.extra",
        "v1.abc.nonce.mac",
        "v1." + "a" * 200,
    ],
    ids=[
        "empty",
        "wrong_version",
        "too_few_parts",
        "too_many_parts",
        "non_numeric_expiry",
        "too_long",
    ],
)
def test_a_malformed_ticket_is_refused_as_malformed(tickets: DecisionTickets, ticket: str) -> None:
    assert tickets.verify(ticket, ENTRY, owner=OWNER, client=CLIENT) is TicketRefusal.MALFORMED


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (TicketEntry("a:b", "c", "d"), TicketEntry("a", "b:c", "d")),
        (TicketEntry("a", "b", "c:d"), TicketEntry("a", "b:c", "d")),
        (TicketEntry("a", 'b","c', "d"), TicketEntry("a", "b", 'c","d')),
        (TicketEntry("a", "b\x1fc", "d"), TicketEntry("a\x1fb", "c", "d")),
        (TicketEntry("a", 'x", "y', "z"), TicketEntry("a", "x", 'y", "z')),
    ],
    ids=[
        "colon_action_vs_object",
        "colon_object_vs_digest",
        "json_quote",
        "unit_separator",
        "quote_split",
    ],
)
def test_entries_that_could_be_confused_do_not_share_a_mac(
    tickets: DecisionTickets, first: TicketEntry, second: TicketEntry
) -> None:
    ticket = tickets.issue(first, owner=OWNER, client=CLIENT)

    assert tickets.verify(ticket, second, owner=OWNER, client=CLIENT) is TicketRefusal.MISMATCH


def test_spent_nonces_are_pruned_once_their_tickets_expire(
    tickets: DecisionTickets, now: list[float]
) -> None:
    # Reads the private nonce set on purpose: an expired ticket is refused before it reaches the
    # set, so pruning is observable only through the set's size.
    for index in range(50):
        entry = TicketEntry("approve_plan", f"plan-{index}", "digest")
        ticket = tickets.issue(entry, owner=OWNER, client=CLIENT)
        assert isinstance(tickets.verify(ticket, entry, owner=OWNER, client=CLIENT), SpentTicket)
    assert len(tickets._spent) == 50

    now[0] += TICKET_LIFETIME_SECONDS + 1
    fresh = tickets.issue(ENTRY, owner=OWNER, client=CLIENT)
    assert isinstance(tickets.verify(fresh, ENTRY, owner=OWNER, client=CLIENT), SpentTicket)

    assert len(tickets._spent) == 1


def test_issue_all_keys_each_ticket_by_action_and_object(tickets: DecisionTickets) -> None:
    entries = [
        TicketEntry("approve_plan", "plan-1", "digest-1"),
        TicketEntry("run_automation", "auto-1", "digest-2"),
    ]

    issued = tickets.issue_all(entries, owner=OWNER, client=CLIENT)

    assert set(issued) == {"approve_plan:plan-1", "run_automation:auto-1"}
    for entry in entries:
        ticket = issued[ticket_key(entry)]
        assert isinstance(tickets.verify(ticket, entry, owner=OWNER, client=CLIENT), SpentTicket)


def test_ticket_key_joins_action_and_object_with_a_colon() -> None:
    assert ticket_key(ENTRY) == "approve_plan:plan-1"


def test_binding_of_reads_the_object_and_digest_argument_names() -> None:
    assert binding_of(ticket_binding("task_id", "digest")) == ("task_id", "digest")


@pytest.mark.parametrize(
    "tool_meta",
    [
        None,
        {},
        {DECISION_TICKET_BINDING_META: {"object": "task_id"}},
        {DECISION_TICKET_BINDING_META: "task_id"},
        {DECISION_TICKET_BINDING_META: {"object": 1, "digest": "digest"}},
    ],
    ids=["none", "no_key", "missing_digest", "not_a_dict", "non_string_argument"],
)
def test_binding_of_is_none_without_a_usable_binding(tool_meta: dict[str, object] | None) -> None:
    assert binding_of(tool_meta) is None


def test_with_tickets_adds_nothing_without_a_signer() -> None:
    result = ToolResult(content="x", structured_content={"a": 1})
    actor = Actor(uuid4(), frozenset())

    out = with_tickets(result, None, actor, [ENTRY])

    assert DECISION_TICKETS_META not in (out.meta or {})


def test_with_tickets_puts_the_tickets_in_meta_only() -> None:
    signer = DecisionTickets(SECRET, clock=lambda: 1_000_000.0)
    result = ToolResult(content="x", structured_content={"a": 1}, meta={"kept": True})
    actor = Actor(uuid4(), frozenset())

    out = with_tickets(result, signer, actor, [ENTRY])

    assert out.meta is not None
    assert out.meta["kept"] is True
    issued = out.meta[DECISION_TICKETS_META]
    assert set(issued) == {ticket_key(ENTRY)}
    assert isinstance(
        signer.verify(issued[ticket_key(ENTRY)], ENTRY, owner=str(actor.user_id), client="stdio"),
        SpentTicket,
    )
    assert out.structured_content == {"a": 1}
    assert out.content == ToolResult(content="x").content
    assert issued[ticket_key(ENTRY)] not in repr(out.content)
    assert DECISION_TICKETS_META not in (out.structured_content or {})

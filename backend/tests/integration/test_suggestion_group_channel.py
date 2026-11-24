"""`approve_group(..., channel=...)`: only the owner approves a group, in the app or on the phone.

The channel is stored on each card and is part of what an idempotency key stands for, so a key used
on one channel is not a replay on another. A model or a policy never approves a group by name.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from sidekick.automations.application.suggestion_reads import GroupFilter
from sidekick.automations.application.suggestions import SuggestionService
from sidekick.automations.domain.suggestion import DecisionChannel, SuggestionState
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.types import Actor
from tests.support.companion import companion_app, owner
from tests.support.companion_suggestions import card_row, count_rows, seed_cards

SCOPES = frozenset(
    {"automation:read", "automation:write", "tasks:read", "tasks:write", "projects:read"}
)


def _group(service: SuggestionService, actor: Actor) -> tuple[str, list[UUID]]:
    listed = service.list_suggestions(
        actor,
        state=SuggestionState.PENDING,
        automation_id=None,
        group=GroupFilter.HIGH_CONFIDENCE,
        limit=25,
        cursor=None,
    )
    (group,) = listed.groups
    return group.digest, list(group.suggestion_ids)


def _setup(*titles: str) -> tuple[Any, SuggestionService, Actor, list[dict[str, Any]]]:
    app = companion_app()
    user_id = owner(app)
    cards = seed_cards(app, user_id, *titles, checked=True)
    return app, app.state.container.automation_suggestions, Actor(user_id, SCOPES), cards


@pytest.mark.integration
@pytest.mark.parametrize(
    ("channel", "stored"),
    [(DecisionChannel.COMPANION, "companion"), (DecisionChannel.APP, "app")],
)
def test_the_owner_approves_a_group_in_the_app_or_on_the_phone(
    channel: DecisionChannel, stored: str
) -> None:
    app, service, actor, cards = _setup("Ett", "Två")
    digest, ids = _group(service, actor)

    outcomes = service.approve_group(
        actor,
        group_digest=digest,
        suggestion_ids=ids,
        idempotency_key="group-key-0001",
        channel=channel,
    )

    assert [outcome.error for outcome in outcomes] == [None, None]
    for card in cards:
        row = card_row(app, card["id"])
        assert (row["state"], row["decided_by"], row["decision_channel"]) == (
            "applied",
            "you",
            stored,
        )
    assert count_rows(app, "tasks") == 2


@pytest.mark.integration
def test_the_channel_defaults_to_the_app() -> None:
    app, service, actor, cards = _setup("Ett")
    digest, ids = _group(service, actor)

    service.approve_group(
        actor, group_digest=digest, suggestion_ids=ids, idempotency_key="group-key-0002"
    )

    assert card_row(app, cards[0]["id"])["decision_channel"] == "app"


@pytest.mark.integration
@pytest.mark.parametrize("channel", [DecisionChannel.MODEL, DecisionChannel.POLICY])
def test_a_model_or_a_policy_never_approves_a_group(channel: DecisionChannel) -> None:
    app, service, actor, cards = _setup("Ett", "Två")
    digest, ids = _group(service, actor)

    with pytest.raises(ValidationError):
        service.approve_group(
            actor,
            group_digest=digest,
            suggestion_ids=ids,
            idempotency_key="group-key-0003",
            channel=channel,
        )

    assert {card_row(app, card["id"])["state"] for card in cards} == {"pending"}
    assert count_rows(app, "tasks") == 0


@pytest.mark.integration
def test_a_key_used_on_one_channel_is_not_a_replay_on_another() -> None:
    app, service, actor, cards = _setup("Ett")
    digest, ids = _group(service, actor)
    service.approve_group(
        actor,
        group_digest=digest,
        suggestion_ids=ids,
        idempotency_key="group-key-0004",
        channel=DecisionChannel.COMPANION,
    )

    with pytest.raises(ConflictError):
        service.approve_group(
            actor,
            group_digest=digest,
            suggestion_ids=ids,
            idempotency_key="group-key-0004",
            channel=DecisionChannel.APP,
        )

    assert card_row(app, cards[0]["id"])["decision_channel"] == "companion"
    assert count_rows(app, "tasks") == 1

"""The ready conversation store reads and writes only the caller's rows, refuses a stale version,
keeps an id another owner holds out of reach, and prunes day marks by age."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from sidekick.api.app import create_container
from sidekick.automations.domain.spec import Cadence
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import new_uuid7
from sidekick.start.domain.ready import (
    DayState,
    Ingredient,
    ReadyConversation,
    ReadyDay,
    ReadyKind,
    ReadyState,
)
from sidekick.start.persistence import ReadyStore
from tests.db import database_factory
from tests.support.settings import make_settings

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
DAY = date(2026, 11, 23)
CADENCE = Cadence(frequency="daily", local_time="18:00")


@dataclass
class Env:
    store: StoreBase
    owner: UUID
    other: UUID

    def conversation(self, owner: UUID | None = None, **overrides: object) -> ReadyConversation:
        values: dict[str, object] = {
            "id": new_uuid7(),
            "owner_id": owner or self.owner,
            "title": "Evening review",
            "kind": ReadyKind.EVENING_REVIEW,
            "instruction": None,
            "instruction_written_by": None,
            "instruction_edited_by_model": False,
            "ingredients": (Ingredient.OVERDUE,),
            "cadence": CADENCE,
            "state": ReadyState.ACTIVE,
            "version": 1,
            "created_at": NOW,
            "updated_at": NOW,
            **overrides,
        }
        return ReadyConversation(**values)  # type: ignore[arg-type]

    def save(self, conversation: ReadyConversation, expected: int | None = None) -> None:
        self.store.transaction(lambda s: ReadyStore.save_conversation(s, conversation, expected))

    def get(self, owner: UUID, conversation_id: UUID) -> ReadyConversation:
        return self.store.transaction(
            lambda s: ReadyStore.get_conversation(s, owner, conversation_id)
        )


@pytest.fixture
def env() -> Env:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    return Env(
        StoreBase(factory),
        container.auth.provision_user("ready-store-owner", "Owner"),
        container.auth.provision_user("ready-store-other", "Other"),
    )


@pytest.mark.integration
def test_a_conversation_is_read_back_as_it_was_written(env: Env) -> None:
    written = env.conversation(
        instruction="Ask one question at a time.",
        instruction_written_by="claude",
        instruction_edited_by_model=True,
    )

    env.save(written)

    assert env.get(env.owner, written.id) == written


@pytest.mark.integration
def test_another_owner_neither_reads_lists_nor_counts_a_conversation(env: Env) -> None:
    written = env.conversation()
    env.save(written)

    with pytest.raises(NotFoundError):
        env.get(env.other, written.id)
    assert env.store.transaction(lambda s: ReadyStore.list_conversations(s, env.other)) == []
    assert env.store.transaction(lambda s: ReadyStore.count_open_conversations(s, env.other)) == 0
    assert env.store.transaction(lambda s: ReadyStore.count_open_conversations(s, env.owner)) == 1


@pytest.mark.integration
def test_an_id_another_owner_holds_answers_as_missing_and_changes_nothing(env: Env) -> None:
    written = env.conversation(title="Mine")
    env.save(written)

    with pytest.raises(NotFoundError):
        env.save(replace(written, owner_id=env.other, title="Taken"), expected=None)

    assert env.get(env.owner, written.id).title == "Mine"


@pytest.mark.integration
def test_an_update_needs_the_stored_version(env: Env) -> None:
    written = env.conversation()
    env.save(written)

    with pytest.raises(ConflictError) as stale:
        env.save(replace(written, title="Late", version=4), expected=3)
    env.save(replace(written, title="On time", version=2), expected=1)

    assert stale.value.reason == "stale_version"
    assert (env.get(env.owner, written.id).title, env.get(env.owner, written.id).version) == (
        "On time",
        2,
    )


@pytest.mark.integration
def test_the_open_count_leaves_out_archived_conversations_and_a_list_can_name_states(
    env: Env,
) -> None:
    active, paused, archived = (
        env.conversation(state=state)
        for state in (ReadyState.ACTIVE, ReadyState.PAUSED, ReadyState.ARCHIVED)
    )
    for item in (active, paused, archived):
        env.save(item)

    assert env.store.transaction(lambda s: ReadyStore.count_open_conversations(s, env.owner)) == 2
    listed = env.store.transaction(
        lambda s: ReadyStore.list_conversations(s, env.owner, states=[ReadyState.ARCHIVED])
    )
    assert [item.id for item in listed] == [archived.id]


@pytest.mark.integration
def test_a_day_mark_moves_state_and_belongs_to_its_owner_and_day(env: Env) -> None:
    written = env.conversation()
    env.save(written)
    skipped = ReadyDay(written.id, DAY, DayState.SKIPPED, NOW, 1)

    env.store.transaction(lambda s: ReadyStore.save_day(s, env.owner, skipped))
    env.store.transaction(
        lambda s: ReadyStore.save_day(
            s, env.owner, replace(skipped, state=DayState.OPEN, version=2)
        )
    )

    assert env.store.transaction(lambda s: ReadyStore.get_day(s, env.owner, written.id, DAY)) == (
        replace(skipped, state=DayState.OPEN, version=2)
    )
    assert env.store.transaction(lambda s: ReadyStore.get_days(s, env.owner, DAY)) == {
        written.id: replace(skipped, state=DayState.OPEN, version=2)
    }
    assert env.store.transaction(lambda s: ReadyStore.get_days(s, env.other, DAY)) == {}
    assert (
        env.store.transaction(lambda s: ReadyStore.get_day(s, env.other, written.id, DAY)) is None
    )
    assert (
        env.store.transaction(lambda s: ReadyStore.get_days(s, env.owner, date(2026, 11, 24))) == {}
    )


@pytest.mark.integration
def test_pruning_removes_only_the_owners_marks_older_than_the_cutoff(env: Env) -> None:
    mine, theirs = env.conversation(), env.conversation(env.other)
    env.save(mine)
    env.save(theirs)
    old, edge = date(2026, 9, 1), date(2026, 9, 24)
    for owner, conversation in ((env.owner, mine), (env.other, theirs)):
        for day in (old, edge):
            env.store.transaction(
                lambda s, o=owner, c=conversation, d=day: ReadyStore.save_day(
                    s, o, ReadyDay(c.id, d, DayState.SKIPPED, NOW, 1)
                )
            )

    removed = env.store.transaction(lambda s: ReadyStore.prune_days(s, env.owner, edge))

    assert removed == 1
    assert env.store.transaction(lambda s: ReadyStore.get_days(s, env.owner, old)) == {}
    assert len(env.store.transaction(lambda s: ReadyStore.get_days(s, env.owner, edge))) == 1
    assert len(env.store.transaction(lambda s: ReadyStore.get_days(s, env.other, old))) == 1

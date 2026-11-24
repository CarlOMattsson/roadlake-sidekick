"""Ready conversations survive an export and a restore into another owner, and a restore of a
format 11 export leaves the target with none."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo
from typing import Any
from uuid import UUID, uuid4

import pytest

from sidekick.api.app import Container, create_container
from sidekick.automations.domain.spec import Cadence
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor
from sidekick.start.domain.ready import Ingredient, ReadyChange, ReadyKind
from tests.db import database_factory
from tests.support.older_export_formats import as_format_11
from tests.support.settings import make_settings

SCOPES = frozenset({"start:read", "start:write"})
CADENCE = Cadence(frequency="weekly", weekdays=(0, 3), local_time="18:30")
TITLE = "Weekly review of the work"
INSTRUCTION = "Start with what is overdue."


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _cadence_noon(zone: tzinfo) -> datetime:
    """Noon on the owner's first calendar day, today included, that CADENCE names.

    The test skips "today" in the owner's zone, and the cadence only names some weekdays. Pinning
    the clock to such a day keeps the test independent of the weekday, and of UTC versus the
    owner's zone, on which it runs.
    """

    day = datetime.now(zone).date()
    while day.weekday() not in CADENCE.weekdays:
        day += timedelta(days=1)
    return datetime.combine(day, time(12), tzinfo=zone)


@dataclass
class Env:
    container: Container
    store: StoreBase
    owner: UUID
    target: UUID

    def export(self) -> dict[str, Any]:
        return OwnerExportService(self.store).export(Actor(self.owner, frozenset()))

    def restore(self, document: dict[str, Any]) -> None:
        plan = build_restore_plan(document, self.target)
        assert plan.status == "ready", plan.unresolved_references
        OwnerRestoreService(self.store).restore(
            document,
            target_owner_id=self.target,
            expected_plan_checksum=plan.plan_checksum,
            refold=False,
        )

    def conversations(self, owner: UUID) -> list[Any]:
        return self.container.ready_conversations.list_conversations(Actor(owner, SCOPES))


@pytest.fixture
def env() -> Env:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner = container.auth.provision_user("ready-restore-source", "Source")
    target = container.auth.provision_user("ready-restore-target", "Target")
    container.ready_conversations.save(
        Actor(owner, SCOPES),
        None,
        expected_version=None,
        requested=ReadyChange(
            title=TITLE,
            kind=ReadyKind.WEEKLY_REVIEW,
            instruction=INSTRUCTION,
            ingredients=[Ingredient.OVERDUE, Ingredient.WAITING],
            cadence=CADENCE,
        ),
        idempotency_key=f"k-{uuid4()}",
    )
    return Env(container, StoreBase(factory), owner, target)


@pytest.mark.integration
def test_a_restore_carries_the_conversation_with_its_cadence_and_ingredients(env: Env) -> None:
    document = env.export()
    assert document["manifest"]["collection_counts"]["ready_conversations"] == 1

    env.restore(document)

    [source] = env.conversations(env.owner)
    [restored] = env.conversations(env.target)
    assert restored.conversation.id != source.conversation.id
    assert restored.conversation.owner_id == env.target
    assert restored.conversation.title == TITLE
    assert restored.conversation.instruction == INSTRUCTION
    assert (
        restored.conversation.instruction_written_by == source.conversation.instruction_written_by
    )
    assert restored.conversation.instruction_edited_by_model is False
    assert restored.conversation.kind is ReadyKind.WEEKLY_REVIEW
    assert tuple(restored.conversation.ingredients) == (Ingredient.OVERDUE, Ingredient.WAITING)
    assert restored.conversation.cadence == CADENCE
    assert restored.conversation.version == source.conversation.version
    # The source is as it was.
    assert len(env.conversations(env.owner)) == 1


@pytest.mark.integration
def test_the_day_marks_are_not_exported_so_a_restored_conversation_starts_open(env: Env) -> None:
    env.container.ready_conversations.clock = _FixedClock(_cadence_noon(make_settings().owner_zone))
    source = env.conversations(env.owner)[0].conversation
    env.container.ready_conversations.skip(
        Actor(env.owner, SCOPES),
        source.id,
        day=None,
        undo=False,
        idempotency_key=f"k-{uuid4()}",
    )
    document = env.export()
    assert "ready_conversation_days" not in document["collections"]

    env.restore(document)

    [restored] = env.conversations(env.target)
    assert restored.day_state is None


@pytest.mark.integration
def test_a_format_11_export_restores_and_leaves_the_target_without_conversations(env: Env) -> None:
    env.restore(as_format_11(env.export()))

    assert env.conversations(env.target) == []
    assert len(env.conversations(env.owner)) == 1

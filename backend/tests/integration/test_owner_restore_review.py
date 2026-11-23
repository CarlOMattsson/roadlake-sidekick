"""Repetition survives an export and a restore into another owner: the cards keep their schedule,
the answers keep their keys, and folding the restored answers again gives the schedule that was
restored (`refold`), which also shows a log that was cut or a schedule that was changed."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container, create_container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.owner_export.catalogue import COLLECTIONS_ADDED_IN_FORMAT_11
from sidekick.owner_export.document import export_checksum
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore import OwnerRestoreService, RestoreResult
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.review.domain.cards import (
    Answer,
    AnswerChannel,
    CardSource,
    default_settings,
)
from sidekick.review.domain.scheduling import Grade, ReviewConfig, fold
from sidekick.review.persistence import ReviewStore
from sidekick.shared.persistence.models import ContactRow, ReviewLogRow
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor, new_uuid7
from tests.db import database_factory
from tests.support.older_export_formats import as_format_9
from tests.support.settings import make_settings

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
CONFIG = ReviewConfig(0.85)
SCOPES = frozenset({"contacts:read", "contacts:write"})
# An answer key that looks like an id: it must come back exactly as written.
KEY_LIKE_AN_ID = "00000000-0000-4000-8000-0000000000f1"


def _answer(grade: Grade, at: datetime, key: str) -> Answer:
    return Answer(
        entry_id=new_uuid7(),
        grade=grade,
        reviewed_at=at,
        received_at=at + timedelta(seconds=1),
        client_review_id=key,
        channel=AnswerChannel.COMPANION,
        introduced_on=at.date(),
        duration_ms=1200,
    )


@dataclass
class Env:
    factory: sessionmaker[Session]
    container: Container
    owner: UUID
    target: UUID
    contact: UUID
    card: UUID

    @property
    def store(self) -> StoreBase:
        return StoreBase(self.factory)

    def export(self, owner: UUID | None = None) -> dict[str, Any]:
        return OwnerExportService(self.store).export(Actor(owner or self.owner, frozenset()))

    def restore(self, document: dict[str, Any], *, refold: bool) -> RestoreResult:
        plan = build_restore_plan(document, self.target)
        assert plan.status == "ready", plan.unresolved_references
        return OwnerRestoreService(self.store).restore(
            document,
            target_owner_id=self.target,
            expected_plan_checksum=plan.plan_checksum,
            refold=refold,
        )

    def target_cards(self) -> list[Any]:
        return self.store.transaction(lambda s: ReviewStore.list_cards(s, self.target))


def _seed(factory: sessionmaker[Session], container: Container, owner: UUID) -> tuple[UUID, UUID]:
    contact = container.contacts.create(
        Actor(owner, SCOPES), CreateContactCommand("Anna Svensson"), f"k-{uuid4()}"
    ).id
    store = StoreBase(factory)
    settings = replace(
        default_settings(owner, NOW),
        enabled=True,
        desired_retention=0.85,
        push_local_time=time(7, 30),
    )

    def write(session: Session) -> UUID:
        ReviewStore.save_settings(session, settings)
        card, _ = ReviewStore.ensure_card(
            session, owner, CardSource.CONTACT_FACE, contact, CONFIG, NOW
        )
        # The third answer reaches the server after the fourth, as a phone's outbox may deliver
        # them, so the card is refolded from its log once.
        arrival = [(Grade.GOOD, 0), (Grade.GOOD, 10), (Grade.GOOD, 60 * 25), (Grade.AGAIN, 60 * 24)]
        for number, (grade, minutes) in enumerate(arrival):
            key = KEY_LIKE_AN_ID if number == 0 else f"phone-{number}"
            ReviewStore.record_answer(
                session,
                owner,
                card.id,
                _answer(grade, NOW + timedelta(minutes=minutes), key),
                CONFIG,
                NOW,
            )
        return card.id

    return contact, store.transaction(write)


@pytest.fixture
def env() -> Env:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner = container.auth.provision_user("review-restore-source", "Source")
    contact, card = _seed(factory, container, owner)
    target = container.auth.provision_user("review-restore-target", "Target")
    return Env(factory, container, owner, target, contact, card)


def _reseal(document: dict[str, Any]) -> dict[str, Any]:
    document["manifest"] = {"collection_counts": document["manifest"]["collection_counts"]}
    document["manifest"]["sha256"] = export_checksum(document)
    return document


@pytest.mark.integration
def test_an_export_carries_the_settings_the_card_and_every_answer(env: Env) -> None:
    document = env.export()

    counts = document["manifest"]["collection_counts"]
    assert {name: counts[name] for name in COLLECTIONS_ADDED_IN_FORMAT_11} == {
        "review_settings": 1,
        "review_cards": 1,
        "review_log": 4,
    }
    assert document["format_version"] == 12
    settings = document["collections"]["review_settings"][0]
    assert (settings["push_local_time"], settings["desired_retention"]) == ("07:30:00", "0.85")


@pytest.mark.integration
def test_a_restore_carries_the_card_with_its_schedule_and_every_answer_with_its_key(
    env: Env,
) -> None:
    before = env.export()["collections"]

    result = env.restore(env.export(), refold=False)

    assert result.refold is None
    [card] = env.target_cards()
    source = env.store.transaction(lambda s: ReviewStore.get_card(s, env.owner, env.card))
    restored_contact = env.store.transaction(
        lambda s: s.scalars(select(ContactRow).where(ContactRow.owner_id == env.target)).one()
    )
    assert card.id != env.card
    assert card.contact_id == restored_contact.id != env.contact
    assert card.state == source.state
    assert card.introduced_on == source.introduced_on
    assert card.scheduler_version == CONFIG.scheduler_version
    entries = env.store.transaction(lambda s: ReviewStore.log_entries(s, env.target, card.id))
    assert len(entries) == 4
    keys = env.store.transaction(
        lambda s: set(
            s.scalars(
                select(ReviewLogRow.client_review_id).where(ReviewLogRow.owner_id == env.target)
            )
        )
    )
    assert keys == {KEY_LIKE_AN_ID, "phone-1", "phone-2", "phone-3"}
    settings = env.store.transaction(lambda s: ReviewStore.get_settings(s, env.target))
    assert settings is not None
    assert (settings.enabled, settings.desired_retention, settings.push_local_time) == (
        True,
        0.85,
        time(7, 30),
    )
    # The source is as it was.
    assert env.export()["collections"] == before


@pytest.mark.integration
def test_folding_the_restored_answers_gives_the_restored_schedule(env: Env) -> None:
    result = env.restore(env.export(), refold=True)

    assert result.refold is not None
    assert (result.refold.checked, result.refold.mismatched, result.refold.stale) == (1, 0, 0)
    [card] = env.target_cards()
    entries = env.store.transaction(lambda s: ReviewStore.log_entries(s, env.target, card.id))
    assert fold(entries, CONFIG) == card.state


@pytest.mark.integration
def test_a_schedule_that_was_changed_in_the_file_is_reported_and_the_rows_are_kept(
    env: Env,
) -> None:
    document = env.export()
    card = document["collections"]["review_cards"][0]
    card["due_at"] = (datetime.fromisoformat(card["due_at"]) + timedelta(days=30)).isoformat()

    result = env.restore(_reseal(document), refold=True)

    assert result.refold is not None
    assert (result.refold.checked, result.refold.mismatched) == (1, 1)
    assert not result.refold.consistent
    assert len(env.target_cards()) == 1


@pytest.mark.integration
def test_a_log_that_was_cut_is_reported_and_a_restore_without_refold_does_not_look(
    env: Env,
) -> None:
    document = env.export()
    log = document["collections"]["review_log"]
    log.pop()
    document["manifest"]["collection_counts"]["review_log"] = len(log)
    cut = _reseal(document)

    quiet = env.restore(cut, refold=False)

    assert quiet.refold is None
    report = env.store.transaction(lambda s: ReviewStore.verify_cards(s, env.target, CONFIG))
    assert (report.checked, report.mismatched) == (1, 1)


@pytest.mark.integration
def test_what_a_restore_wrote_exports_again_and_restores_in_turn(env: Env) -> None:
    env.restore(env.export(), refold=True)
    again = env.export(env.target)
    third = env.container.auth.provision_user("review-restore-third", "Third")

    assert (
        again["manifest"]["collection_counts"]["review_log"]
        == env.export()["manifest"]["collection_counts"]["review_log"]
    )
    plan = build_restore_plan(again, third)
    result = OwnerRestoreService(env.store).restore(
        again, target_owner_id=third, expected_plan_checksum=plan.plan_checksum, refold=True
    )

    assert result.refold is not None
    assert result.refold.consistent
    assert len(env.store.transaction(lambda s: ReviewStore.list_cards(s, third))) == 1


@pytest.mark.integration
def test_the_format_before_restores_without_repetition_and_leaves_the_target_empty(
    env: Env,
) -> None:
    older = as_format_9(env.export())

    result = env.restore(older, refold=True)

    assert result.refold is not None
    assert (result.refold.checked, result.refold.mismatched, result.refold.stale) == (0, 0, 0)
    assert env.target_cards() == []
    assert env.store.transaction(lambda s: ReviewStore.get_settings(s, env.target)) is None


@pytest.mark.integration
def test_the_contact_name_is_in_the_export_only_through_the_contact_and_never_in_the_plan(
    env: Env,
) -> None:
    document = env.export()
    plan = build_restore_plan(document, env.target)
    result = env.restore(document, refold=True)

    assert "Anna" not in str(plan.as_dict())
    assert "Anna" not in repr(result)
    assert "Anna" not in str(document["collections"]["review_cards"])

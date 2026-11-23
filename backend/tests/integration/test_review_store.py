"""The repetition store reads and writes only the caller's rows, keeps the log append-only, and a
card's schedule always equals folding its log."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container, create_container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.review.domain.cards import (
    Answer,
    AnswerChannel,
    AnswerOutcome,
    CardSource,
    default_settings,
)
from sidekick.review.domain.scheduling import CardState, Grade, Phase, ReviewConfig, fold
from sidekick.review.persistence import ReviewStore
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.models import ReviewCardRow
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor, new_uuid7
from tests.db import database_factory
from tests.support.settings import make_settings

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
CONFIG = ReviewConfig()
CONTACT_SCOPES = frozenset({"contacts:read", "contacts:write"})


@dataclass
class Env:
    factory: sessionmaker[Session]
    store: StoreBase
    container: Container
    owner: UUID
    other: UUID

    def run[T](self, operation: Any) -> T:
        return self.store.transaction(operation)

    def contact(self, owner: UUID) -> UUID:
        created = self.container.contacts.create(
            Actor(owner, CONTACT_SCOPES), CreateContactCommand("Anna Svensson"), f"k-{uuid4()}"
        )
        return created.id

    def card(self, owner: UUID | None = None) -> UUID:
        """A card of a new contact of `owner` (the store's owner by default)."""

        owner = owner or self.owner
        contact = self.contact(owner)
        card, _ = self.run(
            lambda session: ReviewStore.ensure_card(
                session, owner, CardSource.CONTACT_FACE, contact, CONFIG, NOW
            )
        )
        return card.id

    def answer_card(self, card_id: UUID, grade: Grade, at: datetime, key: str | None = None) -> Any:
        answer = answer_at(grade, at, key)
        return self.run(
            lambda session: ReviewStore.record_answer(
                session, self.owner, card_id, answer, CONFIG, NOW
            )
        )

    def stored(self, card_id: UUID) -> Any:
        return self.run(lambda session: ReviewStore.get_card(session, self.owner, card_id))

    def entries(self, card_id: UUID) -> Any:
        return self.run(lambda session: ReviewStore.log_entries(session, self.owner, card_id))


def answer_at(grade: Grade, at: datetime, key: str | None = None) -> Answer:
    return Answer(
        entry_id=new_uuid7(),
        grade=grade,
        reviewed_at=at,
        received_at=at + timedelta(seconds=1),
        client_review_id=key or str(uuid4()),
        channel=AnswerChannel.APP,
        introduced_on=at.date(),
    )


@pytest.fixture
def env() -> Env:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    return Env(
        factory,
        StoreBase(factory),
        container,
        container.auth.provision_user("review-owner", "Owner"),
        container.auth.provision_user("review-other", "Other"),
    )


@pytest.mark.integration
def test_an_owner_who_never_changed_the_settings_has_none_stored_and_the_defaults_apply(
    env: Env,
) -> None:
    assert env.run(lambda session: ReviewStore.get_settings(session, env.owner)) is None
    defaults = default_settings(env.owner, NOW)
    assert (defaults.enabled, defaults.new_per_day, defaults.push_local_time) == (
        False,
        10,
        time(18, 0),
    )


@pytest.mark.integration
def test_settings_are_saved_read_back_whole_and_a_stale_version_is_refused(env: Env) -> None:
    changed = replace(
        default_settings(env.owner, NOW),
        enabled=True,
        new_per_day=5,
        desired_retention=0.85,
        push_local_time=time(7, 30),
    )

    env.run(lambda session: ReviewStore.save_settings(session, changed))
    stored = env.run(lambda session: ReviewStore.get_settings(session, env.owner))
    assert stored == changed
    assert stored is not None
    assert stored.config == ReviewConfig(0.85)

    newer = replace(changed, version=2, enabled=False)
    env.run(lambda session: ReviewStore.save_settings(session, newer, expected_version=1))
    with pytest.raises(ConflictError):
        env.run(lambda session: ReviewStore.save_settings(session, newer, expected_version=1))


@pytest.mark.integration
def test_one_owners_settings_are_not_anothers(env: Env) -> None:
    env.run(lambda session: ReviewStore.save_settings(session, default_settings(env.owner, NOW)))

    assert env.run(lambda session: ReviewStore.get_settings(session, env.other)) is None


@pytest.mark.integration
def test_a_card_is_made_once_per_source_and_a_second_call_returns_it(env: Env) -> None:
    contact = env.contact(env.owner)

    def make(session: Session) -> Any:
        return ReviewStore.ensure_card(
            session, env.owner, CardSource.CONTACT_FACE, contact, CONFIG, NOW
        )

    (first, made), (second, again) = env.run(make), env.run(make)

    assert (made, again) == (True, False)
    assert first == second
    assert first.state.phase is Phase.NEW
    assert first.contact_id == contact
    assert first.scheduler_version == CONFIG.scheduler_version


@pytest.mark.integration
def test_a_contact_of_another_owner_cannot_be_the_source_of_a_card(env: Env) -> None:
    theirs = env.contact(env.other)

    with pytest.raises(NotFoundError):
        env.run(
            lambda session: ReviewStore.ensure_card(
                session, env.owner, CardSource.CONTACT_FACE, theirs, CONFIG, NOW
            )
        )
    assert env.run(lambda session: ReviewStore.list_cards(session, env.owner)) == []


@pytest.mark.integration
def test_a_card_of_another_owner_answers_as_not_found_everywhere(env: Env) -> None:
    theirs = env.card(env.other)
    answer = answer_at(Grade.GOOD, NOW)
    operations = [
        lambda session: ReviewStore.get_card(session, env.owner, theirs),
        lambda session: ReviewStore.get_card(session, env.owner, theirs, lock=True),
        lambda session: ReviewStore.set_suspended(session, env.owner, theirs, True, NOW),
        lambda session: ReviewStore.set_retired(session, env.owner, theirs, True, NOW),
        lambda session: ReviewStore.log_entries(session, env.owner, theirs),
        lambda session: ReviewStore.record_answer(session, env.owner, theirs, answer, CONFIG, NOW),
        lambda session: ReviewStore.refold_card(session, env.owner, theirs, CONFIG, NOW),
    ]

    for operation in operations:
        with pytest.raises(NotFoundError):
            env.run(operation)
    assert env.run(lambda session: ReviewStore.list_cards(session, env.owner)) == []
    assert len(env.run(lambda session: ReviewStore.list_cards(session, env.other))) == 1
    assert (
        env.run(
            lambda session: ReviewStore.count_answers(
                session, env.owner, NOW, NOW + timedelta(days=1)
            )
        )
        == 0
    )


@pytest.mark.integration
def test_the_first_answer_schedules_the_card_and_marks_the_day_it_was_introduced(
    env: Env,
) -> None:
    card_id = env.card()

    result = env.answer_card(card_id, Grade.GOOD, NOW)

    assert result.outcome is AnswerOutcome.OK
    assert result.card.state == fold(env.entries(card_id), CONFIG)
    assert result.card.state.phase is Phase.REVIEW
    assert result.card.introduced_on == NOW.date()
    assert result.card.version == 2
    day = env.run(lambda session: ReviewStore.count_introduced(session, env.owner, NOW.date()))
    assert day == 1
    other_day = date(2026, 11, 24)
    assert env.run(lambda s: ReviewStore.count_introduced(s, env.owner, other_day)) == 0


@pytest.mark.integration
def test_the_same_answer_twice_writes_once(env: Env) -> None:
    card_id = env.card()
    env.answer_card(card_id, Grade.GOOD, NOW, key="phone-1")
    before = env.stored(card_id)

    again = env.answer_card(card_id, Grade.AGAIN, NOW + timedelta(minutes=1), key="phone-1")

    assert again.outcome is AnswerOutcome.DUPLICATE
    assert again.card == before
    assert env.stored(card_id) == before
    assert len(env.entries(card_id)) == 1


@pytest.mark.integration
def test_answers_in_order_extend_the_schedule_to_what_folding_the_log_gives(env: Env) -> None:
    card_id = env.card()
    moments = [NOW, NOW + timedelta(minutes=10), NOW + timedelta(days=1), NOW + timedelta(days=5)]

    for grade, moment in zip(
        (Grade.GOOD, Grade.GOOD, Grade.AGAIN, Grade.GOOD), moments, strict=True
    ):
        env.answer_card(card_id, grade, moment)

    stored = env.stored(card_id)
    assert stored.state == fold(env.entries(card_id), CONFIG)
    assert stored.state.reps == 4
    assert stored.version == 5


@pytest.mark.integration
def test_a_late_answer_refolds_to_what_an_online_review_would_have_given(env: Env) -> None:
    online = env.card()
    offline = env.card()
    grades = [
        (Grade.GOOD, NOW),
        (Grade.GOOD, NOW + timedelta(minutes=10)),
        (Grade.AGAIN, NOW + timedelta(days=1)),
    ]
    for grade, moment in grades:
        env.answer_card(online, grade, moment)
    # The phone answered all three offline; they reach the server newest first.
    for grade, moment in reversed(grades):
        env.answer_card(offline, grade, moment)

    assert env.stored(offline).state == env.stored(online).state
    assert env.stored(offline).state == fold(env.entries(offline), CONFIG)


@pytest.mark.integration
def test_a_card_scheduled_under_other_rules_is_refolded_by_its_next_answer(env: Env) -> None:
    card_id = env.card()
    env.answer_card(card_id, Grade.GOOD, NOW)
    stricter = ReviewConfig(0.95)

    result = env.run(
        lambda session: ReviewStore.record_answer(
            session,
            env.owner,
            card_id,
            answer_at(Grade.GOOD, NOW + timedelta(minutes=11)),
            stricter,
            NOW,
        )
    )

    assert result.card.scheduler_version == stricter.scheduler_version
    assert result.card.state == fold(env.entries(card_id), stricter)


@pytest.mark.integration
def test_the_days_answers_are_counted_from_the_log_inside_the_bounds_only(env: Env) -> None:
    card_id = env.card()
    env.answer_card(card_id, Grade.GOOD, NOW)
    env.answer_card(card_id, Grade.GOOD, NOW + timedelta(days=1, hours=1))

    def count(since: datetime, until: datetime) -> int:
        return env.run(lambda s: ReviewStore.count_answers(s, env.owner, since, until))

    assert count(NOW - timedelta(hours=1), NOW + timedelta(hours=1)) == 1
    assert count(NOW, NOW + timedelta(days=2)) == 2
    assert count(NOW + timedelta(hours=1), NOW + timedelta(days=1)) == 0


@pytest.mark.integration
def test_suspending_and_retiring_are_idempotent_and_leave_the_history(env: Env) -> None:
    card_id = env.card()
    env.answer_card(card_id, Grade.GOOD, NOW)
    version = env.stored(card_id).version

    suspended = env.run(lambda s: ReviewStore.set_suspended(s, env.owner, card_id, True, NOW))
    again = env.run(lambda s: ReviewStore.set_suspended(s, env.owner, card_id, True, NOW))
    retired = env.run(lambda s: ReviewStore.set_retired(s, env.owner, card_id, True, NOW))
    revived = env.run(lambda s: ReviewStore.set_retired(s, env.owner, card_id, False, NOW))

    assert suspended.suspended_at == NOW
    assert again.version == suspended.version == version + 1
    assert retired.retired_at == NOW
    assert revived.retired_at is None
    assert len(env.entries(card_id)) == 1
    in_play = env.run(lambda s: ReviewStore.list_cards(s, env.owner, in_play_only=True))
    assert in_play == []
    env.run(lambda s: ReviewStore.set_suspended(s, env.owner, card_id, False, NOW))
    in_play = env.run(lambda s: ReviewStore.list_cards(s, env.owner, in_play_only=True))
    assert [card.id for card in in_play] == [card_id]


@pytest.mark.integration
def test_erasing_the_contact_takes_its_card_and_answers_with_it(env: Env) -> None:
    contact = env.contact(env.owner)
    card, _ = env.run(
        lambda s: ReviewStore.ensure_card(
            s, env.owner, CardSource.CONTACT_FACE, contact, CONFIG, NOW
        )
    )
    env.answer_card(card.id, Grade.GOOD, NOW)

    env.run(
        lambda s: s.execute(text("DELETE FROM sidekick.contacts WHERE id = :id"), {"id": contact})
    )

    assert env.run(lambda s: ReviewStore.list_cards(s, env.owner)) == []
    left = env.run(
        lambda s: s.execute(
            text("SELECT count(*) FROM sidekick.review_log WHERE owner_id = :o"), {"o": env.owner}
        ).scalar_one()
    )
    assert left == 0


@pytest.mark.integration
def test_the_store_never_changes_or_deletes_an_answer(env: Env) -> None:
    card_id = env.card()
    env.answer_card(card_id, Grade.GOOD, NOW)

    with pytest.raises(ProgrammingError, match="permission denied"):
        env.run(lambda s: s.execute(text("UPDATE sidekick.review_log SET rating = 1")))
    with pytest.raises(ProgrammingError, match="permission denied"):
        env.run(lambda s: s.execute(text("DELETE FROM sidekick.review_log")))

    assert len(env.entries(card_id)) == 1


@pytest.mark.integration
def test_verifying_finds_a_schedule_that_the_log_does_not_give(env: Env) -> None:
    sound, tampered, never_answered = env.card(), env.card(), env.card()
    for card_id in (sound, tampered):
        env.answer_card(card_id, Grade.GOOD, NOW)
        env.answer_card(card_id, Grade.GOOD, NOW + timedelta(days=1))

    clean = env.run(lambda s: ReviewStore.verify_cards(s, env.owner, CONFIG))
    assert (clean.checked, clean.mismatched, clean.stale, clean.consistent) == (3, 0, 0, True)

    def push_back(session: Session) -> None:
        row = session.scalars(select(ReviewCardRow).where(ReviewCardRow.id == tampered)).one()
        row.due_at = row.due_at + timedelta(days=30)

    env.run(push_back)
    found = env.run(lambda s: ReviewStore.verify_cards(s, env.owner, CONFIG))
    assert (found.checked, found.mismatched, found.consistent) == (3, 1, False)

    refolded = env.run(lambda s: ReviewStore.refold_card(s, env.owner, tampered, CONFIG, NOW))
    assert refolded.state == env.stored(sound).state
    assert env.run(lambda s: ReviewStore.verify_cards(s, env.owner, CONFIG)).consistent
    assert env.stored(never_answered).state == CardState()


@pytest.mark.integration
def test_cards_under_other_rules_are_counted_as_stale_and_not_compared(env: Env) -> None:
    card_id = env.card()
    env.answer_card(card_id, Grade.GOOD, NOW)

    report = env.run(lambda s: ReviewStore.verify_cards(s, env.owner, ReviewConfig(0.95)))

    assert (report.checked, report.mismatched, report.stale) == (0, 0, 1)


@pytest.mark.integration
def test_an_answer_is_scheduled_from_the_row_the_lock_returned_not_from_one_read_earlier(
    env: Env,
) -> None:
    """Two devices answer at once: this session read the card before the other one wrote, and the
    answer it records after the lock must still extend the other device's schedule."""

    card_id = env.card()
    second = answer_at(Grade.GOOD, NOW + timedelta(days=2))
    with env.factory() as session:
        # The session keeps the row it read (a caller that still holds it), so it is in the
        # identity map when the other device writes.
        held = session.get(ReviewCardRow, card_id)
        assert held is not None
        env.answer_card(card_id, Grade.GOOD, NOW + timedelta(days=1))

        result = ReviewStore.record_answer(session, env.owner, card_id, second, CONFIG, NOW)
        session.commit()

    assert result.card.state.reps == 2
    assert env.stored(card_id).state == fold(env.entries(card_id), CONFIG)
    assert env.stored(card_id).state.reps == 2

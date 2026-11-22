"""The automation store reads and writes only the caller's rows, and a check is never changed."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.automations.domain.automation import Automation, SuggestionCheck
from sidekick.automations.domain.spec import AutomationState, parse_spec, spec_digest
from sidekick.automations.domain.suggestion import SuggestionState
from sidekick.automations.persistence import AutomationStore
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import new_uuid7
from tests.db import database_factory
from tests.support.automation_rows import insert_run
from tests.support.automations import suggestion
from tests.support.settings import make_settings

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
CADENCE = {"frequency": "daily", "local_time": "07:00"}


def _automation(owner_id: UUID, **spec_overrides: Any) -> Automation:
    spec = parse_spec(
        {
            "purpose": "Collect what the morning mail asks of me",
            "instruction": "Read yesterday's mail and propose tasks for requests.",
            "sources": ["mail"],
            "allowed_effects": ["create_task", "create_contact"],
            **spec_overrides,
        }
    )
    return Automation(
        id=new_uuid7(),
        owner_id=owner_id,
        title="Morning mail",
        spec=spec,
        state=AutomationState.DRAFT,
        spec_digest=spec_digest(spec),
        approved_digest=None,
        approved_at=None,
        last_run_at=None,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class Env:
    factory: sessionmaker[Session]
    store: StoreBase
    owner: UUID
    other: UUID

    def run[T](self, operation: Any) -> T:
        return self.store.transaction(operation)

    def seed_run(self, session: Session, owner_id: UUID, automation_id: UUID) -> UUID:
        return UUID(insert_run(session.connection(), str(owner_id), str(automation_id)))

    def seed_suggestion(self, owner_id: UUID | None = None) -> tuple[Automation, UUID, Any]:
        """An automation, a run of it and a pending suggestion, written through the store."""

        owner_id = owner_id or self.owner
        automation = _automation(owner_id)
        fingerprint = uuid4().hex + uuid4().hex
        holder: dict[str, Any] = {}

        def write(session: Session) -> None:
            AutomationStore.save_automation(session, automation)
            session.flush()
            run_id = self.seed_run(session, owner_id, automation.id)
            holder["run"] = run_id
            holder["suggestion"] = replace(
                suggestion(),
                id=new_uuid7(),
                owner_id=owner_id,
                automation_id=automation.id,
                run_id=run_id,
                dedupe_fingerprint=fingerprint,
                datapoint_ids=(),
            )
            AutomationStore.save_suggestion(session, holder["suggestion"], NOW)

        self.run(write)
        return automation, holder["run"], holder["suggestion"]


@pytest.fixture
def env() -> Env:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    return Env(
        factory,
        StoreBase(factory),
        container.auth.provision_user("store-owner", "Owner"),
        container.auth.provision_user("store-other", "Other"),
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [{}, {"cadence": CADENCE, "apply_mode": "auto_low_risk", "auto_effects": ["create_task"]}],
)
def test_an_automation_is_saved_and_read_back_whole(env: Env, overrides: dict[str, Any]) -> None:
    automation = _automation(env.owner, **overrides)

    env.run(lambda session: AutomationStore.save_automation(session, automation))
    stored = env.run(
        lambda session: AutomationStore.get_automation(session, env.owner, automation.id)
    )

    assert stored == automation
    assert (stored.spec.cadence is None) == (not overrides)


@pytest.mark.integration
def test_an_automation_is_listed_for_its_owner_only_and_by_state(env: Env) -> None:
    mine = _automation(env.owner)
    paused = replace(_automation(env.owner), state=AutomationState.PAUSED)
    theirs = _automation(env.other)

    def write(session: Session) -> None:
        for automation in (mine, paused, theirs):
            AutomationStore.save_automation(session, automation)

    env.run(write)

    listed = env.run(lambda session: AutomationStore.list_automations(session, env.owner))
    drafts = env.run(
        lambda session: AutomationStore.list_automations(
            session, env.owner, states={AutomationState.DRAFT}
        )
    )

    assert {item.id for item in listed} == {mine.id, paused.id}
    assert [item.id for item in drafts] == [mine.id]
    assert env.run(lambda session: AutomationStore.list_automations(session, env.other)) == [theirs]


@pytest.mark.integration
def test_a_list_continues_after_the_offset_in_creation_order(env: Env) -> None:
    items = [_automation(env.owner) for _ in range(3)]

    def write(session: Session) -> None:
        for number, automation in enumerate(items):
            AutomationStore.save_automation(
                session, replace(automation, created_at=NOW + timedelta(minutes=number))
            )

    env.run(write)

    rest = env.run(
        lambda session: AutomationStore.list_automations(session, env.owner, limit=2, offset=1)
    )

    assert [item.id for item in rest] == [items[1].id, items[2].id]


@pytest.mark.integration
def test_pending_suggestions_are_counted_per_automation_for_the_owner_only(env: Env) -> None:
    automation, _, _ = env.seed_suggestion()
    quiet = _automation(env.owner)
    foreign, _, _ = env.seed_suggestion(env.other)
    env.run(lambda session: AutomationStore.save_automation(session, quiet))
    ids = [automation.id, quiet.id, foreign.id]

    counts = env.run(
        lambda session: AutomationStore.pending_suggestion_counts(session, env.owner, ids)
    )

    assert counts == {automation.id: 1}


@pytest.mark.integration
def test_another_owner_cannot_read_or_overwrite_an_automation(env: Env) -> None:
    automation = _automation(env.owner)
    env.run(lambda session: AutomationStore.save_automation(session, automation))

    with pytest.raises(NotFoundError):
        env.run(lambda session: AutomationStore.get_automation(session, env.other, automation.id))
    taken = replace(automation, owner_id=env.other, title="Taken", version=2)
    with pytest.raises(NotFoundError):
        env.run(lambda session: AutomationStore.save_automation(session, taken))

    stored = env.run(
        lambda session: AutomationStore.get_automation(session, env.owner, automation.id)
    )
    assert stored == automation


@pytest.mark.integration
def test_a_stale_version_is_refused_and_the_expected_one_updates(env: Env) -> None:
    automation = _automation(env.owner)
    env.run(lambda session: AutomationStore.save_automation(session, automation))
    changed = replace(automation, title="Renamed", version=2, updated_at=NOW + timedelta(hours=1))

    with pytest.raises(ConflictError):
        env.run(lambda session: AutomationStore.save_automation(session, changed, 7))
    env.run(lambda session: AutomationStore.save_automation(session, changed, 1))

    stored = env.run(
        lambda session: AutomationStore.get_automation(session, env.owner, automation.id)
    )
    assert (stored.title, stored.version) == ("Renamed", 2)
    assert stored.created_at == NOW


@pytest.mark.integration
def test_a_suggestion_is_saved_and_read_back_whole(env: Env) -> None:
    _, _, saved = env.seed_suggestion()

    stored = env.run(lambda session: AutomationStore.get_suggestion(session, env.owner, saved.id))

    assert stored == saved
    assert env.run(
        lambda session: AutomationStore.known_fingerprints(session, env.owner, saved.automation_id)
    ) == {saved.dedupe_fingerprint}


@pytest.mark.integration
def test_another_owner_sees_no_suggestion_and_no_fingerprint(env: Env) -> None:
    _, _, saved = env.seed_suggestion()

    with pytest.raises(NotFoundError):
        env.run(lambda session: AutomationStore.get_suggestion(session, env.other, saved.id))
    assert not env.run(lambda session: AutomationStore.list_suggestions(session, env.other))
    assert not env.run(
        lambda session: AutomationStore.known_fingerprints(session, env.other, saved.automation_id)
    )
    taken = replace(saved, owner_id=env.other, version=saved.version + 1)
    with pytest.raises(NotFoundError):
        env.run(lambda session: AutomationStore.save_suggestion(session, taken, NOW))
    # Neither the read nor the refused write changed what the owner has.
    assert (
        env.run(lambda session: AutomationStore.get_suggestion(session, env.owner, saved.id))
        == saved
    )


@pytest.mark.integration
def test_a_suggestion_cannot_name_the_run_or_automation_of_another_owner(env: Env) -> None:
    automation, run_id, saved = env.seed_suggestion()
    stolen = replace(
        saved,
        id=new_uuid7(),
        owner_id=env.other,
        dedupe_fingerprint="b" * 64,
    )
    assert (stolen.automation_id, stolen.run_id) == (automation.id, run_id)

    with pytest.raises(IntegrityError):
        env.run(lambda session: AutomationStore.save_suggestion(session, stolen, NOW))


@pytest.mark.integration
def test_a_suggestion_update_needs_the_version_it_was_read_at(env: Env) -> None:
    _, _, saved = env.seed_suggestion()
    changed = replace(saved, state=SuggestionState.EXPIRED, version=saved.version + 1)

    with pytest.raises(ConflictError):
        env.run(lambda session: AutomationStore.save_suggestion(session, changed, NOW, 99))
    env.run(lambda session: AutomationStore.save_suggestion(session, changed, NOW, saved.version))

    stored = env.run(lambda session: AutomationStore.get_suggestion(session, env.owner, saved.id))
    assert stored.state is SuggestionState.EXPIRED
    listed = env.run(
        lambda session: AutomationStore.list_suggestions(
            session, env.owner, states={SuggestionState.EXPIRED}
        )
    )
    assert [item.id for item in listed] == [saved.id]


@pytest.mark.integration
def test_a_purged_payload_stays_purged_when_the_suggestion_changes(env: Env) -> None:
    _, _, saved = env.seed_suggestion()

    def purge(session: Session) -> None:
        session.execute(
            text(
                "UPDATE sidekick.automation_suggestions SET payload = NULL, "
                "proposed_payload = NULL, payload_purged_at = now() WHERE id = :id"
            ),
            {"id": saved.id},
        )

    env.run(purge)
    purged = env.run(lambda session: AutomationStore.get_suggestion(session, env.owner, saved.id))
    assert dict(purged.payload) == {}

    changed = replace(purged, state=SuggestionState.EXPIRED, version=purged.version + 1)
    env.run(lambda session: AutomationStore.save_suggestion(session, changed, NOW))

    with env.factory() as session:
        row = session.execute(
            text("SELECT payload, proposed_payload FROM sidekick.automation_suggestions")
        ).one()
    assert tuple(row) == (None, None)


def _check(saved: Any, owner_id: UUID, attempt: int = 1) -> SuggestionCheck:
    return SuggestionCheck(
        id=new_uuid7(),
        owner_id=owner_id,
        suggestion_id=saved.id,
        run_id=saved.run_id,
        attempt=attempt,
        checker="openai_compat",
        model="checker",
        verdict="ok",
        confidence=97,
        reason_codes=("duplicate_likely",),
        checked_at=NOW,
    )


@pytest.mark.integration
def test_checks_are_appended_in_order_and_only_the_owner_reads_them(env: Env) -> None:
    _, _, saved = env.seed_suggestion()
    second = _check(saved, env.owner, 2)
    first = _check(saved, env.owner, 1)

    def write(session: Session) -> None:
        AutomationStore.append_check(session, second)
        AutomationStore.append_check(session, first)

    env.run(write)

    assert env.run(lambda session: AutomationStore.list_checks(session, env.owner, saved.id)) == [
        first,
        second,
    ]
    assert not env.run(lambda session: AutomationStore.list_checks(session, env.other, saved.id))


@pytest.mark.integration
def test_a_check_cannot_be_added_for_another_owners_suggestion_or_twice(env: Env) -> None:
    _, _, saved = env.seed_suggestion()

    with pytest.raises(IntegrityError):
        env.run(lambda session: AutomationStore.append_check(session, _check(saved, env.other)))
    env.run(lambda session: AutomationStore.append_check(session, _check(saved, env.owner)))
    with pytest.raises(IntegrityError):
        env.run(lambda session: AutomationStore.append_check(session, _check(saved, env.owner)))


@pytest.mark.integration
def test_a_check_is_append_only_in_the_store_and_in_the_database(env: Env) -> None:
    _, _, saved = env.seed_suggestion()
    env.run(lambda session: AutomationStore.append_check(session, _check(saved, env.owner)))

    names = {name for name in vars(AutomationStore) if "check" in name}
    assert names == {"append_check", "list_checks"}
    for statement in (
        "UPDATE sidekick.automation_checks SET verdict = 'suspicious'",
        "DELETE FROM sidekick.automation_checks",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):
            env.run(lambda session, statement=statement: session.execute(text(statement)))

    stored = env.run(lambda session: AutomationStore.list_checks(session, env.owner, saved.id))
    assert [item.verdict for item in stored] == ["ok"]


@pytest.mark.integration
def test_an_id_held_by_another_owner_answers_as_not_found_and_the_transaction_goes_on(
    env: Env,
) -> None:
    automation, _, saved = env.seed_suggestion()
    own = _automation(env.owner)

    def write(session: Session) -> None:
        with pytest.raises(NotFoundError):
            AutomationStore.save_automation(session, replace(automation, owner_id=env.other))
        with pytest.raises(NotFoundError):
            AutomationStore.save_suggestion(session, replace(saved, owner_id=env.other), NOW)
        AutomationStore.save_automation(session, own)

    env.run(write)

    stored = env.run(lambda session: AutomationStore.get_automation(session, env.owner, own.id))
    assert stored == own
    again = env.run(lambda session: AutomationStore.get_suggestion(session, env.owner, saved.id))
    assert again == saved

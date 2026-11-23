"""The store's run, datapoint and cursor operations read and write only the caller's rows."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.automations.domain.automation import Automation, ReportCursor
from sidekick.automations.domain.datapoints import Datapoint, DatapointKind, SourceKind
from sidekick.automations.domain.runs import (
    AutomationRun,
    CredentialKind,
    RunOutcome,
    RunRunner,
    RunState,
)
from sidekick.automations.domain.spec import AutomationState, parse_spec, spec_digest
from sidekick.automations.persistence import AutomationStore
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor, new_uuid7
from sidekick.work.domain.ai_runs import AiUsage, CostSource
from tests.db import database_factory
from tests.support.settings import make_settings

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
DIGEST = "d" * 64


def _automation(owner_id: UUID) -> Automation:
    spec = parse_spec(
        {
            "purpose": "Collect what the morning mail asks of me",
            "instruction": "Read yesterday's mail and propose tasks for requests.",
            "sources": ["mail"],
            "allowed_effects": ["create_task"],
        }
    )
    return Automation(
        id=new_uuid7(),
        owner_id=owner_id,
        title="Morning mail",
        spec=spec,
        state=AutomationState.ACTIVE,
        spec_digest=spec_digest(spec),
        approved_digest=spec_digest(spec),
        approved_at=NOW,
        last_run_at=None,
        version=3,
        created_at=NOW,
        updated_at=NOW,
    )


def _run(
    automation: Automation, occurrence: str = "d:2026-11-22", attempt: int = 1, **overrides: Any
) -> AutomationRun:
    claimed = AutomationRun.claim(
        run_id=new_uuid7(),
        owner_id=automation.owner_id,
        automation_id=automation.id,
        occurrence_key=occurrence,
        attempt=attempt,
        runner=RunRunner.CLAUDE,
        spec_digest=automation.spec_digest,
        session_digest="s" * 64,
        credential_kind=CredentialKind.TOKEN,
        now=NOW,
    )
    return replace(claimed, **overrides)


def _datapoint(run: AutomationRun, **overrides: Any) -> Datapoint:
    values: dict[str, Any] = {
        "id": new_uuid7(),
        "owner_id": run.owner_id,
        "run_id": run.id,
        "automation_id": run.automation_id,
        "kind": DatapointKind.PERSON,
        "fields": {"name": "Anna Svensson"},
        "source_kind": SourceKind.MAIL,
        "source_fingerprint": uuid4().hex + uuid4().hex,
        "source_label": "Re: rent",
        "source_received_at": NOW,
        "created_at": NOW,
        "purge_after": NOW + timedelta(days=30),
    }
    return Datapoint(**{**values, **overrides})


@dataclass
class Env:
    factory: sessionmaker[Session]
    store: StoreBase
    owner: UUID
    other: UUID

    def run[T](self, operation: Callable[[Session], T]) -> T:
        return self.store.transaction(operation)

    def seed(self, owner_id: UUID | None = None) -> tuple[Automation, AutomationRun]:
        automation = _automation(owner_id or self.owner)
        run = _run(automation)

        def write(session: Session) -> None:
            AutomationStore.save_automation(session, automation)
            session.flush()
            AutomationStore.save_run(session, run)

        self.run(write)
        return automation, run


@pytest.fixture
def env() -> Env:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    return Env(
        factory,
        StoreBase(factory),
        container.auth.provision_user("run-store-owner", "Owner"),
        container.auth.provision_user("run-store-other", "Other"),
    )


# --- runs -------------------------------------------------------------------------------------


@pytest.mark.integration
def test_a_run_is_saved_and_read_back_whole(env: Env) -> None:
    _, run = env.seed()

    stored = env.run(lambda session: AutomationStore.get_run(session, env.owner, run.id))

    assert stored == run
    assert stored.state is RunState.RUNNING
    assert stored.session_digest == "s" * 64


@pytest.mark.integration
def test_a_run_is_updated_only_from_the_version_it_was_read_at(env: Env) -> None:
    _, run = env.seed()
    moved = run.recorded(datapoints=2, suggestions=1, rejected=0, flagged=0, now=NOW)

    env.run(lambda session: AutomationStore.save_run(session, moved, expected_version=1))
    with pytest.raises(ConflictError) as error:
        env.run(lambda session: AutomationStore.save_run(session, moved, expected_version=1))

    stored = env.run(lambda session: AutomationStore.get_run(session, env.owner, run.id))
    assert error.value.reason == "stale_version"
    assert (stored.version, stored.datapoint_count, stored.suggestion_count) == (2, 2, 1)


@pytest.mark.integration
def test_a_finished_run_keeps_its_summary_outcome_and_usage(env: Env) -> None:
    _, run = env.seed()
    usage = AiUsage(
        input_tokens=10,
        output_tokens=5,
        cost_microusd=400_000,
        cost_source=CostSource.CLIENT_ESTIMATE,
        model="claude-x",
    )
    done = run.finished(
        outcome=RunOutcome.OK, summary="One request.", usage=usage, checker_enabled=False, now=NOW
    )

    env.run(lambda session: AutomationStore.save_run(session, done, expected_version=1))
    stored = env.run(lambda session: AutomationStore.get_run(session, env.owner, run.id))

    assert stored == done
    assert stored.usage == usage


@pytest.mark.integration
def test_another_owner_cannot_read_lock_or_overwrite_a_run(env: Env) -> None:
    _, run = env.seed()

    with pytest.raises(NotFoundError):
        env.run(lambda session: AutomationStore.get_run(session, env.other, run.id))
    with pytest.raises(NotFoundError):
        env.run(lambda session: AutomationStore.get_run(session, env.other, run.id, lock=True))
    taken = replace(run, owner_id=env.other, summary="Taken", version=2)
    with pytest.raises((NotFoundError, IntegrityError, ConflictError)):
        env.run(lambda session: AutomationStore.save_run(session, taken, expected_version=1))

    stored = env.run(lambda session: AutomationStore.get_run(session, env.owner, run.id))
    assert stored == run


@pytest.mark.integration
def test_only_one_run_of_an_occurrence_is_active_at_a_time(env: Env) -> None:
    automation, run = env.seed()
    second = _run(automation, attempt=2)

    with pytest.raises(IntegrityError):
        env.run(lambda session: AutomationStore.save_run(session, second))

    ended = run.ended(RunState.LAPSED, NOW)
    env.run(lambda session: AutomationStore.save_run(session, ended, expected_version=1))
    env.run(lambda session: AutomationStore.save_run(session, second))
    attempts = env.run(
        lambda session: AutomationStore.list_occurrence_runs(
            session, env.owner, automation.id, run.occurrence_key
        )
    )
    assert [item.attempt for item in attempts] == [1, 2]


@pytest.mark.integration
def test_the_attempts_of_an_occurrence_are_listed_for_its_owner_only(env: Env) -> None:
    automation, run = env.seed()

    mine = env.run(
        lambda session: AutomationStore.list_occurrence_runs(
            session, env.owner, automation.id, run.occurrence_key
        )
    )
    theirs = env.run(
        lambda session: AutomationStore.list_occurrence_runs(
            session, env.other, automation.id, run.occurrence_key
        )
    )
    elsewhere = env.run(
        lambda session: AutomationStore.list_occurrence_runs(
            session, env.owner, automation.id, "d:2026-11-21"
        )
    )

    assert mine == [run]
    assert theirs == [] and elsewhere == []


@pytest.mark.integration
def test_the_latest_scheduled_day_ignores_manual_occurrences_and_other_owners(env: Env) -> None:
    automation, _ = env.seed()
    foreign, _ = env.seed(env.other)

    def write(session: Session) -> None:
        AutomationStore.save_run(session, _run(automation, "d:2026-11-24", state=RunState.DONE))
        AutomationStore.save_run(session, _run(automation, "m:" + uuid4().hex, state=RunState.DONE))
        AutomationStore.save_run(session, _run(foreign, "d:2026-12-30", state=RunState.DONE))

    env.run(write)

    latest = env.run(
        lambda session: AutomationStore.latest_scheduled_day(session, env.owner, automation.id)
    )
    nothing = env.run(
        lambda session: AutomationStore.latest_scheduled_day(session, env.owner, foreign.id)
    )

    assert latest == date(2026, 11, 24)
    assert nothing is None


@pytest.mark.integration
def test_runs_are_counted_from_a_time_for_the_owner_only(env: Env) -> None:
    automation, _ = env.seed()
    env.seed(env.other)

    def write(session: Session) -> None:
        AutomationStore.save_run(
            session,
            replace(
                _run(automation, "m:old", state=RunState.DONE),
                created_at=NOW - timedelta(days=2),
            ),
        )

    env.run(write)

    since_today = env.run(
        lambda session: AutomationStore.count_runs_since(
            session, env.owner, NOW - timedelta(hours=1)
        )
    )
    since_ever = env.run(
        lambda session: AutomationStore.count_runs_since(
            session, env.owner, NOW - timedelta(days=9)
        )
    )

    assert (since_today, since_ever) == (1, 2)


@pytest.mark.integration
def test_the_cost_of_runs_is_summed_by_source_for_the_owner_only(env: Env) -> None:
    automation, _ = env.seed()
    foreign, _ = env.seed(env.other)

    def with_cost(run: AutomationRun, microusd: int, source: CostSource) -> AutomationRun:
        usage = AiUsage(cost_microusd=microusd, cost_source=source)
        return replace(run, state=RunState.DONE, usage=usage)

    def write(session: Session) -> None:
        for key, microusd, source in (
            ("m:a", 300_000, CostSource.PROVIDER),
            ("m:b", 200_000, CostSource.PRICE_TABLE),
            ("m:c", 900_000, CostSource.CLIENT_ESTIMATE),
        ):
            AutomationStore.save_run(session, with_cost(_run(automation, key), microusd, source))
        AutomationStore.save_run(
            session, with_cost(_run(foreign, "m:d"), 700_000, CostSource.PROVIDER)
        )

    env.run(write)
    since = NOW - timedelta(hours=1)
    counted = [CostSource.PROVIDER, CostSource.PRICE_TABLE]

    automations_only = env.run(
        lambda session: AutomationStore.sum_automation_cost_since(
            session, env.owner, since, counted
        )
    )
    everything = env.run(
        lambda session: AutomationStore.sum_ai_cost_since(session, env.owner, since, counted)
    )
    estimates = env.run(
        lambda session: AutomationStore.sum_automation_cost_since(
            session, env.owner, since, [CostSource.CLIENT_ESTIMATE]
        )
    )

    assert automations_only == 500_000
    assert everything == 500_000
    assert estimates == 900_000


@pytest.mark.integration
def test_noting_a_run_does_not_change_the_automations_version(env: Env) -> None:
    automation, _ = env.seed()
    later = NOW + timedelta(hours=1)

    env.run(
        lambda session: AutomationStore.touch_last_run(session, env.owner, automation.id, later)
    )
    env.run(lambda session: AutomationStore.touch_last_run(session, env.other, automation.id, NOW))

    stored = env.run(
        lambda session: AutomationStore.get_automation(session, env.owner, automation.id)
    )
    assert stored.last_run_at == later
    assert stored.version == automation.version


# --- datapoints -------------------------------------------------------------------------------


@pytest.mark.integration
def test_datapoints_are_stored_and_listed_with_their_run_for_the_owner_only(env: Env) -> None:
    _, run = env.seed()
    points = [_datapoint(run, created_at=NOW + timedelta(seconds=n)) for n in range(3)]

    env.run(lambda session: AutomationStore.add_datapoints(session, points))
    mine = env.run(lambda session: AutomationStore.list_run_datapoints(session, env.owner, run.id))
    theirs = env.run(
        lambda session: AutomationStore.list_run_datapoints(session, env.other, run.id)
    )

    assert mine == points
    assert theirs == []


@pytest.mark.integration
def test_a_datapoint_cannot_name_another_owners_run(env: Env) -> None:
    _, run = env.seed()
    foreign_owner = _datapoint(run, owner_id=env.other)

    with pytest.raises(IntegrityError):
        env.run(lambda session: AutomationStore.add_datapoints(session, [foreign_owner]))

    assert (
        env.run(lambda session: AutomationStore.list_run_datapoints(session, env.owner, run.id))
        == []
    )


@pytest.mark.integration
def test_a_purged_datapoint_reads_back_without_its_text(env: Env) -> None:
    _, run = env.seed()
    purged = _datapoint(run, fields=None, source_label=None, purged_at=NOW)

    env.run(lambda session: AutomationStore.add_datapoints(session, [purged]))
    stored = env.run(
        lambda session: AutomationStore.list_run_datapoints(session, env.owner, run.id)
    )

    assert stored == [purged]
    assert stored[0].fields is None


# --- suggestions of a run ---------------------------------------------------------------------


@pytest.mark.integration
def test_suggestions_are_listed_by_run(env: Env) -> None:
    from tests.support.automations import suggestion

    automation, run = env.seed()
    other_run = _run(automation, "d:2026-11-21", state=RunState.DONE)

    def write(session: Session) -> None:
        AutomationStore.save_run(session, other_run)
        for target in (run, run, other_run):
            AutomationStore.save_suggestion(
                session,
                replace(
                    suggestion(),
                    id=new_uuid7(),
                    owner_id=env.owner,
                    automation_id=automation.id,
                    run_id=target.id,
                    dedupe_fingerprint=uuid4().hex + uuid4().hex,
                    datapoint_ids=(),
                ),
                NOW,
            )

    env.run(write)

    in_run = env.run(
        lambda session: AutomationStore.list_suggestions(session, env.owner, run_id=run.id)
    )
    in_other = env.run(
        lambda session: AutomationStore.list_suggestions(session, env.owner, run_id=other_run.id)
    )
    foreign = env.run(
        lambda session: AutomationStore.list_suggestions(session, env.other, run_id=run.id)
    )

    assert (len(in_run), len(in_other), len(foreign)) == (2, 1, 0)


# --- what a proposal may refer to -------------------------------------------------------------


@pytest.mark.integration
def test_only_the_owners_open_projects_are_usable(env: Env) -> None:
    container = create_container(make_settings(), env.factory)
    mine = Actor(env.owner, frozenset({"projects:write"}))
    theirs = Actor(env.other, frozenset({"projects:write"}))

    def project(actor: Actor, title: str) -> UUID:
        domain = container.contexts.create_domain(
            actor, name=title, description=None, idempotency_key=f"d-{uuid4().hex}"
        )
        return container.projects.create(
            actor, title=title, domain_id=domain.id, idempotency_key=f"p-{uuid4().hex}"
        ).id

    own, foreign = project(mine, "Mine"), project(theirs, "Theirs")

    usable = env.run(
        lambda session: AutomationStore.usable_project_ids(
            session, env.owner, {own, foreign, uuid4()}
        )
    )
    nothing = env.run(lambda session: AutomationStore.usable_project_ids(session, env.owner, set()))

    assert usable == {own}
    assert nothing == frozenset()


@pytest.mark.integration
def test_contacts_and_open_tasks_are_matched_for_the_owner_only(env: Env) -> None:
    container = create_container(make_settings(), env.factory)
    scopes = frozenset({"contacts:write", "tasks:write"})
    mine, theirs = Actor(env.owner, scopes), Actor(env.other, scopes)
    from sidekick.contacts.application.models import CreateContactCommand

    container.contacts.create(
        mine, CreateContactCommand("Anna", email="Anna@Example.se"), f"c-{uuid4().hex}"
    )
    container.contacts.create(
        theirs, CreateContactCommand("Bo", email="bo@example.se"), f"c-{uuid4().hex}"
    )
    container.tasks.create(mine, title="Call The Dentist", idempotency_key=f"t-{uuid4().hex}")
    container.tasks.create(theirs, title="Their task", idempotency_key=f"t-{uuid4().hex}")

    emails = env.run(
        lambda session: AutomationStore.existing_contact_email_keys(
            session, env.owner, {"anna@example.se", "bo@example.se", "nobody@example.se"}
        )
    )
    titles = env.run(
        lambda session: AutomationStore.open_task_titles(
            session, env.owner, {"call the dentist", "their task"}
        )
    )

    assert emails == {"anna@example.se"}
    assert titles == ["Call The Dentist"]


# --- the report cursor ------------------------------------------------------------------------


@pytest.mark.integration
def test_the_report_cursor_is_each_owners_own_and_moves_by_version(env: Env) -> None:
    first = ReportCursor(env.owner, NOW, 1, NOW)

    assert env.run(lambda session: AutomationStore.get_report_cursor(session, env.owner)) is None
    env.run(lambda session: AutomationStore.save_report_cursor(session, first))
    moved = replace(first, seen_until=NOW + timedelta(days=1), version=2)
    env.run(lambda session: AutomationStore.save_report_cursor(session, moved, expected_version=1))
    with pytest.raises(ConflictError) as error:
        env.run(
            lambda session: AutomationStore.save_report_cursor(session, moved, expected_version=1)
        )

    assert error.value.reason == "stale_version"
    assert env.run(lambda session: AutomationStore.get_report_cursor(session, env.owner)) == moved
    assert env.run(lambda session: AutomationStore.get_report_cursor(session, env.other)) is None

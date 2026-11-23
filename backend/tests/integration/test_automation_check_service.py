"""The independent check of an automation run against a real database and a stand-in checker.

Every scene seeds an owner's run in the state `checking` with cards waiting, lets the service take
it, and reads back what was written: the check rows, the cards, the cost on the run and the group.
The stand-in answers as the test says, so the invariants (a missing answer is never "safe", money is
reserved before a call and never exceeded, one worker holds a run, text stays out of logs and the
audit trail) hold whatever a model does.
"""

import contextlib
import logging
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.automations.application.check_releaser import CheckReleaseService
from sidekick.automations.application.checking import AutoApplier, AutomationCheckService
from sidekick.automations.application.runs import AutomationRunLimits
from sidekick.automations.application.suggestions import AutoApplyOutcome, SuggestionService
from sidekick.automations.check_store import SqlCheckStore
from sidekick.automations.domain.automation import Automation
from sidekick.automations.domain.checking import (
    CheckAnswer,
    CheckContext,
    CheckerCall,
    CheckItem,
    ReasonCode,
)
from sidekick.automations.domain.datapoints import Datapoint, DatapointKind, SourceKind
from sidekick.automations.domain.grouping import AutoApplyRefusal
from sidekick.automations.domain.runs import (
    DEFAULT_CHECK_LEASE,
    DEFAULT_CHECK_RELEASE_AFTER,
    AutomationRun,
    CredentialKind,
    RunOutcome,
    RunRunner,
    RunState,
)
from sidekick.automations.domain.screening import ScreeningFlag
from sidekick.automations.domain.spec import (
    ApplyMode,
    AutomationState,
    auto_confirmed_digest,
    parse_spec,
    spec_digest,
)
from sidekick.automations.domain.suggestion import (
    CheckState,
    DecidedBy,
    DecisionChannel,
    Suggestion,
    SuggestionState,
    Verdict,
)
from sidekick.automations.persistence import AutomationStore
from sidekick.composition import create_auto_apply_service
from sidekick.shared.errors import NotFoundError
from sidekick.shared.observability import NoopTelemetryAdapter
from sidekick.shared.types import Actor, new_uuid7
from sidekick.work.domain.ai_model_port import (
    ModelError,
    ModelRejected,
    ModelTransient,
    ModelUncertain,
    RejectionKind,
)
from sidekick.work.domain.ai_runs import AiUsage, CostSource
from tests.db import database_factory
from tests.support.ai_steps import admin_rows
from tests.support.automations import parsed_task, suggestion
from tests.support.settings import make_settings

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
CANARY = "CANARY-31d8e2"
WORKER = "host:1:test"
OWNER_TEXT = (CANARY, f"title {CANARY}", f"purpose {CANARY}", f"label {CANARY}")


class Clock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


@dataclass
class FakeChecker:
    """Answers by the card's title; `script` has one entry per call, an error to raise or None."""

    kind: str = "openai_compat"
    model: str = "fake/check"
    max_batch: int = 1
    cost_source: CostSource = CostSource.PRICE_TABLE
    reserve: int = 1_000
    cost: int = 50
    script: list[ModelError | None] = field(default_factory=list[ModelError | None])
    usable: bool = True
    during: Callable[[], None] | None = None
    """Runs while the call is in flight: what the rest of the world does in the meantime."""
    calls: list[tuple[CheckContext, tuple[CheckItem, ...]]] = field(
        default_factory=list[tuple[CheckContext, tuple[CheckItem, ...]]]
    )

    def reserve_microusd(self, context: CheckContext, items: Sequence[CheckItem]) -> int:
        return self.reserve

    def check(self, context: CheckContext, items: Sequence[CheckItem]) -> CheckerCall:
        self.calls.append((context, tuple(items)))
        if self.during is not None:
            self.during()
        if self.script and (failure := self.script.pop(0)) is not None:
            raise failure
        usage = AiUsage(input_tokens=100, cost_microusd=self.cost, cost_source=self.cost_source)
        if not self.usable:
            return CheckerCall(None, usage)
        return CheckerCall({item.suggestion_id: _answer(item) for item in items}, usage)


def _answer(item: CheckItem) -> CheckAnswer:
    title = str(item.payload["title"])
    if title.startswith("bad"):
        return CheckAnswer(Verdict.SUSPICIOUS, 95, (ReasonCode.INSTRUCTION_LIKE_TEXT,))
    if title.startswith("unsure"):
        return CheckAnswer(Verdict.UNCERTAIN, 70, (ReasonCode.OTHER,))
    return CheckAnswer(Verdict.OK, 97)


@dataclass(frozen=True)
class Seeded:
    automation: Automation
    run: AutomationRun
    cards: tuple[Suggestion, ...]


@dataclass
class World:
    factory: sessionmaker[Session]
    store: SqlCheckStore
    owner: UUID
    other: UUID
    clock: Clock
    sleeps: list[float] = field(default_factory=list[float])

    def service(
        self, checker: FakeChecker, *, auto_applier: AutoApplier | None = None, **limits: Any
    ) -> AutomationCheckService:
        values: dict[str, Any] = {
            "runs_per_day": 20,
            "automation_monthly_cap_microusd": 15_000_000,
            "monthly_cap_microusd": 50_000_000,
            "local_models_exempt": False,
            "checker_enabled": True,
        }
        return AutomationCheckService(
            self.store,
            self.clock,
            AutomationRunLimits(**{**values, **limits}),
            checker,
            owner_timezone=UTC,
            telemetry=NoopTelemetryAdapter(),
            sleep=self.sleeps.append,
            auto_applier=auto_applier,
        )

    def releaser(self, **limits: Any) -> CheckReleaseService:
        values: dict[str, Any] = {
            "runs_per_day": 20,
            "automation_monthly_cap_microusd": 15_000_000,
            "monthly_cap_microusd": 50_000_000,
            "local_models_exempt": False,
            "checker_enabled": False,
        }
        return CheckReleaseService(
            self.store, self.clock, AutomationRunLimits(**{**values, **limits})
        )

    def seed(
        self,
        titles: Sequence[str] = ("Call the dentist",),
        *,
        owner_id: UUID | None = None,
        flags: dict[str, tuple[ScreeningFlag, ...]] | None = None,
        spec: dict[str, Any] | None = None,
        **run_changes: Any,
    ) -> Seeded:
        owner_id = owner_id or self.owner
        automation = _automation(owner_id, **(spec or {}))
        run = _checking_run(automation, **run_changes)
        point = Datapoint(
            id=new_uuid7(),
            owner_id=owner_id,
            run_id=run.id,
            automation_id=automation.id,
            kind=DatapointKind.PERSON,
            fields={"name": f"Anna {CANARY}"},
            source_kind=SourceKind.MAIL,
            source_fingerprint=uuid4().hex + uuid4().hex,
            source_label=f"label {CANARY}",
            source_received_at=NOW,
            created_at=NOW,
            purge_after=NOW + timedelta(days=30),
        )
        cards = tuple(
            replace(
                suggestion(
                    verdict=None,
                    parsed=parsed_task(title=title),
                    flags=(flags or {}).get(title, ()),
                    rationale=f"rationale {CANARY}",
                ),
                id=new_uuid7(),
                owner_id=owner_id,
                automation_id=automation.id,
                run_id=run.id,
                dedupe_fingerprint=uuid4().hex + uuid4().hex,
                datapoint_ids=(point.id,),
                state=SuggestionState.CHECKING,
                check_state=CheckState.QUEUED,
            )
            for title in titles
        )

        def write(session: Session) -> None:
            AutomationStore.save_automation(session, automation)
            session.flush()
            AutomationStore.save_run(session, run)
            session.flush()
            AutomationStore.add_datapoints(session, [point])
            for card in cards:
                AutomationStore.save_suggestion(session, card, NOW)

        self.store.transaction(write)
        return Seeded(automation, run, cards)

    def run_of(self, seeded: Seeded) -> AutomationRun:
        return self.store.transaction(
            lambda session: AutomationStore.get_run(session, seeded.run.owner_id, seeded.run.id)
        )

    def cards_of(self, seeded: Seeded) -> list[Suggestion]:
        owner = seeded.run.owner_id
        return self.store.transaction(
            lambda session: [
                AutomationStore.get_suggestion(session, owner, card.id) for card in seeded.cards
            ]
        )

    def by_title(self, seeded: Seeded) -> dict[str, Suggestion]:
        """The cards by title: the order the worker takes them in is the database's."""

        return {str(card.payload["title"]): card for card in self.cards_of(seeded)}

    def checks_of(self, seeded: Seeded, card: Suggestion) -> list[Any]:
        owner = seeded.run.owner_id
        return self.store.transaction(
            lambda session: AutomationStore.list_checks(session, owner, card.id)
        )


def _automation(owner_id: UUID, **spec_changes: Any) -> Automation:
    spec = parse_spec(
        {
            "purpose": f"purpose {CANARY}",
            "instruction": "Read yesterday's mail and propose tasks for requests.",
            "sources": ["mail"],
            "allowed_effects": ["create_task"],
            **spec_changes,
        }
    )
    return Automation(
        id=new_uuid7(),
        owner_id=owner_id,
        title=f"title {CANARY}",
        spec=spec,
        state=AutomationState.ACTIVE,
        spec_digest=spec_digest(spec),
        approved_digest=(
            auto_confirmed_digest(spec_digest(spec))
            if spec.apply_mode is ApplyMode.AUTO_LOW_RISK
            else spec_digest(spec)
        ),
        approved_at=NOW,
        last_run_at=None,
        version=3,
        created_at=NOW,
        updated_at=NOW,
    )


def _checking_run(automation: Automation, **changes: Any) -> AutomationRun:
    claimed = AutomationRun.claim(
        run_id=new_uuid7(),
        owner_id=automation.owner_id,
        automation_id=automation.id,
        occurrence_key="d:2026-11-22",
        attempt=1,
        runner=RunRunner.CLAUDE,
        spec_digest=automation.spec_digest,
        session_digest=None,
        credential_kind=CredentialKind.TOKEN,
        now=NOW,
    )
    values: dict[str, Any] = {
        "state": RunState.CHECKING,
        "outcome": RunOutcome.OK,
        "lease_until": None,
        "suggestion_count": 3,
        "summary": f"summary {CANARY}",
        "usage": AiUsage(
            cost_microusd=80_000,
            cost_source=CostSource.CLIENT_ESTIMATE,
            model="claude-sonnet-5-5",
        ),
    }
    return replace(claimed, **{**values, **changes})


@pytest.fixture
def world() -> World:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    return World(
        factory,
        SqlCheckStore(factory),
        container.auth.provision_user("check-owner", "Owner"),
        container.auth.provision_user("check-other", "Other"),
        Clock(),
    )


# The run through its check


@pytest.mark.integration
def test_every_card_gets_its_check_and_the_run_is_done(world: World) -> None:
    seeded = world.seed(["Call the dentist", "unsure about this", "bad instruction"])
    checker = FakeChecker()

    assert world.service(checker).run_next(WORKER) is True

    run = world.run_of(seeded)
    assert run.state is RunState.DONE
    assert run.outcome is RunOutcome.OK
    assert run.finished_at == NOW
    assert run.worker_id is None
    assert run.checker_model == "fake/check"
    assert len(checker.calls) == 3
    cards = world.by_title(seeded)
    ok, unsure, bad = (
        cards["Call the dentist"],
        cards["unsure about this"],
        cards["bad instruction"],
    )
    assert (ok.state, ok.check_state, ok.verdict, ok.confidence) == (
        SuggestionState.PENDING,
        CheckState.CHECKED,
        Verdict.OK,
        97,
    )
    assert (unsure.verdict, unsure.confidence) == (Verdict.UNCERTAIN, 70)
    assert (bad.verdict, bad.confidence) == (Verdict.SUSPICIOUS, 95)
    rows = world.checks_of(seeded, bad)
    assert [(row.attempt, row.checker, row.model, row.verdict) for row in rows] == [
        (1, "openai_compat", "fake/check", "suspicious")
    ]
    assert rows[0].confidence == 95
    assert rows[0].reason_codes == ("instruction_like_text",)
    assert rows[0].checked_at == NOW


@pytest.mark.integration
def test_the_cost_is_booked_on_the_run_and_a_clients_estimate_gives_way_to_it(
    world: World,
) -> None:
    seeded = world.seed(["One", "Two", "Three"])

    world.service(FakeChecker(cost=50)).run_next(WORKER)

    usage = world.run_of(seeded).usage
    assert usage.cost_microusd == 150
    assert usage.input_tokens == 300
    assert usage.cost_source is CostSource.PRICE_TABLE  # the estimate never counted
    assert usage.reserved_microusd == 0
    assert usage.model == "claude-sonnet-5-5"  # the proposer's model is kept


@pytest.mark.integration
def test_only_a_clean_checked_card_of_a_done_run_may_join_the_group(world: World) -> None:
    flagged = "Pay the invoice"
    seeded = world.seed(
        ["Call the dentist", "unsure about this", "bad instruction", flagged],
        flags={flagged: (ScreeningFlag.PAYMENT_RELATED,)},
    )

    world.service(FakeChecker()).run_next(WORKER)

    cards = world.by_title(seeded)
    assert {title: card.bulk_eligible for title, card in cards.items()} == {
        "Call the dentist": True,
        "unsure about this": False,
        "bad instruction": False,
        flagged: False,
    }
    # The group is a derived value: the card's version moved only by its check.
    assert cards["Call the dentist"].version == seeded.cards[0].version + 1


@pytest.mark.integration
def test_a_chat_model_checks_the_whole_run_in_one_call(world: World) -> None:
    seeded = world.seed([f"Task {number}" for number in range(6)])
    checker = FakeChecker(max_batch=25)

    world.service(checker).run_next(WORKER)

    assert len(checker.calls) == 1
    assert {card.check_state for card in world.cards_of(seeded)} == {CheckState.CHECKED}
    assert world.run_of(seeded).usage.cost_microusd == 50


@pytest.mark.integration
def test_the_checker_is_told_the_owners_setup_and_the_proposal_and_nothing_else(
    world: World,
) -> None:
    seeded = world.seed(["Call the dentist"])
    checker = FakeChecker()

    world.service(checker).run_next(WORKER)

    ((context, items),) = checker.calls
    assert context.title == f"title {CANARY}"
    assert context.sources == ("mail",)
    assert context.allowed_effects == ("create_task",)
    (item,) = items
    assert item.suggestion_id == seeded.cards[0].id
    assert [point.kind for point in item.datapoints] == ["person"]
    assert "rationale" not in repr(item)  # the checker is never shown the proposer's reasoning
    assert f"Anna {CANARY}" not in repr(item)  # nor what a datapoint holds


@pytest.mark.integration
def test_nothing_waits_when_no_run_is_in_its_check(world: World) -> None:
    assert world.service(FakeChecker()).run_next(WORKER) is False


@pytest.mark.integration
def test_a_run_is_checked_once(world: World) -> None:
    world.seed(["One"])
    service = world.service(FakeChecker())

    assert service.run_next(WORKER) is True
    assert service.run_next(WORKER) is False


# Failures never read as "safe"


@pytest.mark.integration
def test_a_missing_answer_shows_the_card_as_not_checked_and_keeps_the_cost(world: World) -> None:
    seeded = world.seed(["One", "Two"])
    checker = FakeChecker(usable=False, cost=30)

    world.service(checker).run_next(WORKER)

    cards = world.cards_of(seeded)
    assert {(card.state, card.check_state, card.verdict) for card in cards} == {
        (SuggestionState.PENDING, CheckState.FAILED, None)
    }
    assert not any(card.bulk_eligible for card in cards)
    assert [
        (row.verdict, row.confidence, row.reason_codes) for row in world.checks_of(seeded, cards[0])
    ] == [("error", None, ())]
    assert world.run_of(seeded).usage.cost_microusd == 60
    assert world.run_of(seeded).state is RunState.DONE


@pytest.mark.integration
def test_a_call_that_may_have_been_billed_is_booked_at_its_reservation(world: World) -> None:
    seeded = world.seed(["One", "Two"])
    checker = FakeChecker(script=[ModelUncertain(), None], reserve=700)

    world.service(checker).run_next(WORKER)

    states = sorted(card.check_state.value for card in world.cards_of(seeded))
    assert states == ["checked", "failed"]
    assert world.run_of(seeded).usage.cost_microusd == 700 + 50


@pytest.mark.integration
def test_a_busy_provider_is_waited_for_and_asked_again(world: World) -> None:
    seeded = world.seed(["One"])
    checker = FakeChecker(script=[ModelTransient(2.5), None])

    world.service(checker).run_next(WORKER)

    (card,) = world.cards_of(seeded)
    assert card.check_state is CheckState.CHECKED
    assert world.sleeps == [2.5]
    assert len(checker.calls) == 2
    assert world.run_of(seeded).usage.cost_microusd == 50  # a refused call cost nothing


@pytest.mark.integration
def test_a_provider_that_stays_busy_gives_up_after_three_calls(world: World) -> None:
    seeded = world.seed(["One", "Two"])
    checker = FakeChecker(script=[ModelTransient(0.0)] * 3)

    world.service(checker).run_next(WORKER)

    states = sorted(card.check_state.value for card in world.cards_of(seeded))
    assert states == ["checked", "failed"]
    assert len(checker.calls) == 4
    assert world.run_of(seeded).usage.cost_microusd == 50


@pytest.mark.integration
def test_a_refused_request_shows_the_card_as_not_checked_and_goes_on(world: World) -> None:
    seeded = world.seed(["One", "Two"])
    checker = FakeChecker(script=[ModelRejected(RejectionKind.REQUEST), None])

    world.service(checker).run_next(WORKER)

    states = sorted(card.check_state.value for card in world.cards_of(seeded))
    assert states == ["checked", "failed"]


@pytest.mark.integration
def test_a_refused_key_stops_the_worker_and_leaves_the_cards_to_be_checked_later(
    world: World,
) -> None:
    seeded = world.seed(["One", "Two"])
    checker = FakeChecker(script=[ModelRejected(RejectionKind.AUTH)])
    service = world.service(checker)

    service.run_next(WORKER)

    assert service.credentials_rejected is True
    assert {card.state for card in world.cards_of(seeded)} == {SuggestionState.CHECKING}
    run = world.run_of(seeded)
    assert run.state is RunState.CHECKING
    assert run.usage.reserved_microusd == 0
    assert service.run_next(WORKER) is False
    assert len(checker.calls) == 1
    # Once the key works again and the lease has run out, the next worker finishes the run.
    world.clock.current = NOW + DEFAULT_CHECK_LEASE + timedelta(seconds=1)
    assert world.service(FakeChecker()).run_next("later") is True
    assert world.run_of(seeded).state is RunState.DONE


# Money


@pytest.mark.integration
@pytest.mark.parametrize(
    ("limits", "reserve"),
    [
        ({"automation_monthly_cap_microusd": 900}, 1_000),
        ({"monthly_cap_microusd": 900}, 1_000),
        ({}, 1_000_001),  # the automation's own run budget is one dollar
    ],
    ids=["automation share", "month", "run budget"],
)
def test_a_check_that_would_pass_a_limit_is_not_made_and_its_cards_show_as_not_checked(
    world: World, limits: dict[str, Any], reserve: int
) -> None:
    seeded = world.seed(["One", "Two"])
    checker = FakeChecker(reserve=reserve)

    world.service(checker, **limits).run_next(WORKER)

    assert checker.calls == []
    cards = world.cards_of(seeded)
    assert {(card.state, card.check_state) for card in cards} == {
        (SuggestionState.PENDING, CheckState.FAILED)
    }
    assert {row.verdict for card in cards for row in world.checks_of(seeded, card)} == {"error"}
    run = world.run_of(seeded)
    assert run.state is RunState.DONE
    assert run.usage.reserved_microusd == 0
    assert run.usage.cost_source is CostSource.CLIENT_ESTIMATE  # nothing was spent


@pytest.mark.integration
def test_what_the_owners_runs_have_already_cost_counts_against_the_automation_share(
    world: World,
) -> None:
    earlier = world.seed(["One"])
    world.service(FakeChecker(cost=600)).run_next(WORKER)
    assert world.run_of(earlier).usage.cost_microusd == 600
    later = world.seed(["Two"])
    checker = FakeChecker(reserve=500)

    world.service(checker, automation_monthly_cap_microusd=1_000).run_next(WORKER)

    assert checker.calls == []  # 600 spent + 500 reserved passes 1 000
    assert world.cards_of(later)[0].check_state is CheckState.FAILED


@pytest.mark.integration
def test_a_local_model_the_owner_exempted_is_never_stopped_by_a_cap(world: World) -> None:
    seeded = world.seed(["One"])
    checker = FakeChecker(cost_source=CostSource.NONE, reserve=0, cost=0)

    world.service(checker, monthly_cap_microusd=1, local_models_exempt=True).run_next(WORKER)

    assert world.cards_of(seeded)[0].check_state is CheckState.CHECKED
    assert world.run_of(seeded).usage.cost_source is CostSource.NONE


@pytest.mark.integration
def test_a_reservation_whose_worker_went_silent_is_booked_as_cost_by_the_next_worker(
    world: World,
) -> None:
    dead = AiUsage(
        reserved_microusd=700, cost_microusd=100, cost_source=CostSource.PRICE_TABLE, model="m"
    )
    seeded = world.seed(
        ["One"],
        usage=dead,
        worker_id="host:0:dead",
        lease_until=NOW - timedelta(seconds=1),
        stage="check",
    )

    world.service(FakeChecker(cost=50)).run_next(WORKER)

    usage = world.run_of(seeded).usage
    assert usage.cost_microusd == 100 + 700 + 50
    assert usage.reserved_microusd == 0
    assert world.run_of(seeded).state is RunState.DONE


# Who may take a run


@pytest.mark.integration
def test_a_run_another_worker_holds_is_left_alone(world: World) -> None:
    seeded = world.seed(["One"], worker_id="host:0:other", lease_until=NOW + timedelta(minutes=1))
    checker = FakeChecker()

    assert world.service(checker).run_next(WORKER) is False
    assert checker.calls == []
    assert world.run_of(seeded).worker_id == "host:0:other"


@pytest.mark.integration
def test_a_run_whose_lease_ran_out_is_taken_over(world: World) -> None:
    seeded = world.seed(
        ["One"], worker_id="host:0:other", lease_until=NOW - timedelta(seconds=1), stage="check"
    )

    assert world.service(FakeChecker()).run_next(WORKER) is True
    assert world.run_of(seeded).state is RunState.DONE


@pytest.mark.integration
def test_each_owners_run_is_checked_for_that_owner_only(world: World) -> None:
    mine = world.seed(["Mine"])
    theirs = world.seed(["Theirs"], owner_id=world.other)
    checker = FakeChecker()
    service = world.service(checker)

    assert service.run_next(WORKER) is True
    assert service.run_next(WORKER) is True

    assert [len(items) for _, items in checker.calls] == [1, 1]
    for seeded in (mine, theirs):
        (card,) = world.cards_of(seeded)
        (row,) = world.checks_of(seeded, card)
        assert row.owner_id == seeded.run.owner_id
        assert row.suggestion_id == card.id
    assert mine.run.owner_id != theirs.run.owner_id


@pytest.mark.integration
def test_a_card_the_owner_no_longer_has_waiting_is_left_as_it_is(world: World) -> None:
    seeded = world.seed(["One", "Two"])
    first = seeded.cards[0]
    # Left checked by a worker that died before it finished the run.
    world.store.transaction(
        lambda session: AutomationStore.save_suggestion(
            session,
            first.record_check(Verdict.OK, 99, expected_version=first.version),
            NOW,
            expected_version=first.version,
        )
    )
    checker = FakeChecker()

    world.service(checker).run_next(WORKER)

    assert [len(items) for _, items in checker.calls] == [1]
    assert world.cards_of(seeded)[0].confidence == 99  # untouched
    assert world.run_of(seeded).state is RunState.DONE


# What leaves the process


@pytest.mark.integration
def test_no_text_of_the_owner_or_the_proposer_reaches_a_log_or_the_audit_trail(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    seeded = world.seed(["Call the dentist", "bad instruction"])
    checker = FakeChecker(script=[None, ModelUncertain()])

    with caplog.at_level(logging.DEBUG):
        world.service(checker).run_next(WORKER)

    logged = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert CANARY not in logged
    audit = admin_rows(
        "SELECT event, to_jsonb(a)::text FROM sidekick.audit_events a WHERE target_id = :id",
        id=seeded.run.id,
    )
    assert [row[0] for row in audit] == ["automation.run_checked"]
    assert CANARY not in str(audit)
    assert str(seeded.run.id) in str(audit)


@pytest.mark.integration
def test_every_failure_path_leaves_a_run_that_is_done_or_still_waiting(world: World) -> None:
    seeded = world.seed(["One", "Two", "Three"])
    errors: list[ModelError | None] = [
        ModelRejected(RejectionKind.REQUEST),
        ModelUncertain(),
        None,
    ]
    checker = FakeChecker(script=errors)

    world.service(checker).run_next(WORKER)

    states = sorted(card.check_state.value for card in world.cards_of(seeded))
    assert states == ["checked", "failed", "failed"]
    assert world.run_of(seeded).state is RunState.DONE


# The lease of a worker that is waiting for the model


@pytest.mark.integration
def test_a_call_that_takes_longer_than_five_minutes_does_not_let_another_worker_take_the_run(
    world: World,
) -> None:
    seeded = world.seed(["One"])
    rival = FakeChecker()
    attempts: list[bool] = []

    def slow_call() -> None:
        world.clock.current = NOW + timedelta(minutes=6)  # the provider's timeout allows 5
        attempts.append(world.service(rival).run_next("host:2:rival"))

    checker = FakeChecker(cost=50, during=slow_call)

    world.service(checker).run_next(WORKER)

    assert attempts == [False]
    assert rival.calls == []
    run = world.run_of(seeded)
    assert run.state is RunState.DONE
    assert (run.usage.cost_microusd, run.usage.reserved_microusd) == (50, 0)
    assert len(world.checks_of(seeded, world.cards_of(seeded)[0])) == 1


# A run that nobody checks


@pytest.mark.integration
def test_with_the_check_off_the_waiting_cards_are_shown_as_not_checked_and_the_run_is_done(
    world: World,
) -> None:
    seeded = world.seed(["One", "Two"])

    assert world.releaser(checker_enabled=False).run_next(WORKER) is True

    cards = world.cards_of(seeded)
    assert {(card.state, card.check_state) for card in cards} == {
        (SuggestionState.PENDING, CheckState.FAILED)
    }
    assert all(card.confidence is None for card in cards)
    assert [world.checks_of(seeded, card) for card in cards] == [[], []]  # no checker answered
    run = world.run_of(seeded)
    assert run.state is RunState.DONE
    assert run.outcome is RunOutcome.OK
    assert world.releaser(checker_enabled=False).run_next(WORKER) is False
    audit = admin_rows(
        "SELECT event FROM sidekick.audit_events WHERE target_id = :id", id=seeded.run.id
    )
    assert [row[0] for row in audit] == ["automation.run_released"]


@pytest.mark.integration
def test_with_the_check_on_a_run_is_released_only_after_it_waited_longer_than_the_limit(
    world: World,
) -> None:
    seeded = world.seed(["One"])
    releaser = world.releaser(checker_enabled=True)

    world.clock.current = NOW + DEFAULT_CHECK_RELEASE_AFTER - timedelta(seconds=1)
    assert releaser.run_next(WORKER) is False
    assert world.run_of(seeded).state is RunState.CHECKING

    world.clock.current = NOW + DEFAULT_CHECK_RELEASE_AFTER
    assert releaser.run_next(WORKER) is True

    assert world.run_of(seeded).state is RunState.DONE
    assert world.cards_of(seeded)[0].check_state is CheckState.FAILED


@pytest.mark.integration
def test_a_run_a_worker_holds_is_not_released_even_with_the_check_off(world: World) -> None:
    seeded = world.seed(
        ["One"], worker_id="host:0:other", stage="check", lease_until=NOW + timedelta(minutes=1)
    )

    assert world.releaser(checker_enabled=False).run_next(WORKER) is False

    assert world.run_of(seeded).state is RunState.CHECKING
    assert world.cards_of(seeded)[0].state is SuggestionState.CHECKING


@pytest.mark.integration
def test_releasing_a_run_books_a_reservation_that_never_reported_back_and_keeps_checked_cards(
    world: World,
) -> None:
    dead = AiUsage(reserved_microusd=700, cost_source=CostSource.PRICE_TABLE, model="m")
    seeded = world.seed(
        ["One", "Two"],
        usage=dead,
        worker_id="host:0:dead",
        stage="check",
        lease_until=NOW - timedelta(seconds=1),
    )
    first = seeded.cards[0]
    world.store.transaction(
        lambda session: AutomationStore.save_suggestion(
            session,
            first.record_check(Verdict.OK, 99, expected_version=first.version),
            NOW,
            expected_version=first.version,
        )
    )

    assert world.releaser(checker_enabled=False).run_next(WORKER) is True

    run = world.run_of(seeded)
    assert (run.usage.cost_microusd, run.usage.reserved_microusd) == (700, 0)
    assert run.state is RunState.DONE
    assert sorted(card.check_state.value for card in world.cards_of(seeded)) == [
        "checked",
        "failed",
    ]


# The opt-in policy after the check

AUTO = {"apply_mode": "auto_low_risk", "auto_effects": ["create_task"]}


def _auto_applier(world: World) -> SuggestionService:
    return create_auto_apply_service(make_settings(), world.factory, NoopTelemetryAdapter())


def _tasks_of(owner: UUID) -> list[str]:
    rows = admin_rows(
        "SELECT title FROM sidekick.tasks WHERE owner_id = :owner ORDER BY title", owner=owner
    )
    return [str(row[0]) for row in rows]


@pytest.mark.integration
def test_a_run_whose_automation_opted_in_has_what_the_check_cleared_applied_by_the_policy(
    world: World,
) -> None:
    seeded = world.seed(["Call the dentist", "unsure about this", "bad instruction"], spec=AUTO)

    world.service(FakeChecker(), auto_applier=_auto_applier(world)).run_next(WORKER)

    cards = world.by_title(seeded)
    done = cards["Call the dentist"]
    assert done.state is SuggestionState.APPLIED
    assert (done.decided_by, done.decision_channel) == (DecidedBy.POLICY, DecisionChannel.POLICY)
    assert done.applied_kind == "task"
    assert cards["unsure about this"].state is SuggestionState.PENDING
    assert cards["bad instruction"].state is SuggestionState.PENDING
    assert _tasks_of(world.owner) == ["Call the dentist"]
    assert world.run_of(seeded).auto_applied_count == 1
    audit = admin_rows(
        "SELECT event, source FROM sidekick.audit_events WHERE target_id = :id", id=done.id
    )
    assert audit == [("suggestion.auto_applied", None)]


@pytest.mark.integration
def test_an_automation_that_did_not_opt_in_applies_nothing(world: World) -> None:
    seeded = world.seed(["Call the dentist"])

    world.service(FakeChecker(), auto_applier=_auto_applier(world)).run_next(WORKER)

    (card,) = world.cards_of(seeded)
    assert card.state is SuggestionState.PENDING
    assert card.bulk_eligible is True
    assert _tasks_of(world.owner) == []
    assert world.run_of(seeded).auto_applied_count == 0


@pytest.mark.integration
def test_with_no_checker_configured_nothing_is_applied_even_for_an_opted_in_automation(
    world: World,
) -> None:
    seeded = world.seed(["Call the dentist"], spec=AUTO)

    world.service(FakeChecker(), auto_applier=_auto_applier(world), checker_enabled=False).run_next(
        WORKER
    )

    (card,) = world.cards_of(seeded)
    assert card.state is SuggestionState.PENDING
    assert _tasks_of(world.owner) == []


@pytest.mark.integration
def test_a_run_released_as_not_checked_is_never_applied_by_the_policy(world: World) -> None:
    seeded = world.seed(["Call the dentist"], spec=AUTO)
    world.releaser().run_next(WORKER)

    outcome = _auto_applier(world).auto_apply_run(
        world.owner, seeded.run.id, checker_configured=True
    )

    (card,) = world.cards_of(seeded)
    assert (card.state, card.check_state) == (SuggestionState.PENDING, CheckState.FAILED)
    assert outcome == AutoApplyOutcome()
    assert _tasks_of(world.owner) == []


@pytest.mark.integration
@pytest.mark.parametrize(
    "change", [{"approved_digest": "0" * 64}, {"state": AutomationState.PAUSED}]
)
def test_a_paused_automation_or_one_changed_since_its_approval_applies_nothing(
    world: World, change: dict[str, Any]
) -> None:
    seeded = world.seed(["Call the dentist"], spec=AUTO)
    world.service(FakeChecker()).run_next(WORKER)
    changed = replace(seeded.automation, **change)
    world.store.transaction(lambda session: AutomationStore.save_automation(session, changed))

    outcome = _auto_applier(world).auto_apply_run(
        world.owner, seeded.run.id, checker_configured=True
    )

    assert outcome.applied == ()
    assert sum(outcome.refused.values()) == 1
    assert _tasks_of(world.owner) == []


@pytest.mark.integration
def test_a_run_never_applies_more_than_the_cap_and_the_rest_stay_pending(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sidekick.automations.domain.grouping.MAX_AUTO_PER_RUN", 2)
    seeded = world.seed(["One", "Two", "Three", "Four"], spec=AUTO)

    world.service(FakeChecker(), auto_applier=_auto_applier(world)).run_next(WORKER)

    states = [card.state for card in world.cards_of(seeded)]
    assert states.count(SuggestionState.APPLIED) == 2
    assert states.count(SuggestionState.PENDING) == 2
    assert len(_tasks_of(world.owner)) == 2
    assert world.run_of(seeded).auto_applied_count == 2


@pytest.mark.integration
def test_the_cap_for_a_day_counts_across_runs_and_an_undone_one_does_not_make_room(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sidekick.automations.domain.grouping.MAX_AUTO_PER_DAY", 2)
    first = world.seed(["One", "Two"], spec=AUTO)
    applier = _auto_applier(world)
    world.service(FakeChecker(), auto_applier=applier).run_next(WORKER)
    applied = world.cards_of(first)
    assert [card.state for card in applied] == [SuggestionState.APPLIED] * 2
    owner = Actor(world.owner, frozenset({"automation:write", "tasks:write"}))
    applier.undo(
        owner, applied[0].id, expected_version=applied[0].version, idempotency_key="undo-1"
    )
    second = world.seed(["Three"], spec=AUTO)

    world.service(FakeChecker(), auto_applier=_auto_applier(world)).run_next(WORKER)

    (late,) = world.cards_of(second)
    assert late.state is SuggestionState.PENDING
    assert late.apply_error is None
    assert len(_tasks_of(world.owner)) == 2  # the undone one is in the trash, not deleted


@pytest.mark.integration
def test_a_failing_policy_leaves_the_run_done_and_the_cards_pending_and_logs_no_text(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken:
        def auto_apply_run(
            self,
            owner_id: UUID,
            run_id: UUID,
            *,
            checker_configured: bool,
            correlation_id: str | None = None,
        ) -> AutoApplyOutcome:
            raise RuntimeError(f"boom {CANARY}")

    seeded = world.seed(["Call the dentist"], spec=AUTO)

    with caplog.at_level(logging.DEBUG):
        world.service(FakeChecker(), auto_applier=Broken()).run_next(WORKER)

    assert world.run_of(seeded).state is RunState.DONE
    (card,) = world.cards_of(seeded)
    assert card.state is SuggestionState.PENDING
    logged = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert CANARY not in logged
    assert "automation_auto_apply_failed" in logged


@pytest.mark.integration
def test_applying_twice_creates_each_record_once(world: World) -> None:
    seeded = world.seed(["Call the dentist"], spec=AUTO)
    world.service(FakeChecker()).run_next(WORKER)
    applier = _auto_applier(world)

    first = applier.auto_apply_run(world.owner, seeded.run.id, checker_configured=True)
    second = applier.auto_apply_run(world.owner, seeded.run.id, checker_configured=True)

    assert len(first.applied) == 1
    assert second.applied == ()
    assert _tasks_of(world.owner) == ["Call the dentist"]
    assert world.run_of(seeded).auto_applied_count == 1


@pytest.mark.integration
def test_the_policy_reaches_only_the_owner_of_the_run(world: World) -> None:
    seeded = world.seed(["Call the dentist"], spec=AUTO)
    world.service(FakeChecker()).run_next(WORKER)

    with pytest.raises(NotFoundError):
        _auto_applier(world).auto_apply_run(world.other, seeded.run.id, checker_configured=True)

    assert _tasks_of(world.owner) == []
    assert _tasks_of(world.other) == []


@pytest.mark.integration
def test_a_spec_approved_without_the_confirmation_is_never_applied_automatically(
    world: World,
) -> None:
    seeded = world.seed(["Call the dentist"], spec=AUTO)
    world.service(FakeChecker()).run_next(WORKER)
    plain = replace(seeded.automation, approved_digest=seeded.automation.spec_digest)
    world.store.transaction(lambda session: AutomationStore.save_automation(session, plain))

    outcome = _auto_applier(world).auto_apply_run(
        world.owner, seeded.run.id, checker_configured=True
    )

    assert outcome.applied == ()
    assert outcome.refused == {AutoApplyRefusal.AUTO_NOT_CONFIRMED: 1}
    assert _tasks_of(world.owner) == []


class _MeetAtTheCreate:
    """Holds the first create until another run reaches its own, or a short time passes, so that
    two runs of one owner are inside their transactions together when the lock lets them be."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.barrier = threading.Barrier(2, timeout=2)

    def create(self, *args: Any) -> Any:
        with contextlib.suppress(threading.BrokenBarrierError):
            self.barrier.wait()
        return self.inner.create(*args)


@pytest.mark.integration
def test_the_daily_cap_holds_when_two_runs_of_one_owner_apply_at_the_same_time(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sidekick.automations.domain.grouping.MAX_AUTO_PER_DAY", 1)
    first = world.seed(["One"], spec=AUTO)
    second = world.seed(["Two"], spec=AUTO)
    world.service(FakeChecker()).run_next(WORKER)
    world.service(FakeChecker()).run_next(WORKER)
    applier = _auto_applier(world)
    applier.applier = _MeetAtTheCreate(applier.applier)  # type: ignore[assignment]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(applier.auto_apply_run, world.owner, seeded.run.id, checker_configured=True)
            for seeded in (first, second)
        ]
        outcomes = [future.result() for future in futures]

    assert sum(len(outcome.applied) for outcome in outcomes) == 1
    assert len(_tasks_of(world.owner)) == 1

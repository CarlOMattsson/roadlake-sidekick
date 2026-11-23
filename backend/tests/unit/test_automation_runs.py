"""The rules of a run: starting an occurrence, the lease, how a run ends and when a day is due."""

from dataclasses import replace
from datetime import UTC, date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sidekick.automations.domain.runs import (
    MAX_ATTEMPTS_PER_OCCURRENCE,
    RUN_LEASE,
    AutomationRun,
    CredentialKind,
    NothingDueReason,
    RunOutcome,
    RunRunner,
    RunState,
    StartAction,
    clean_summary,
    manual_key,
    plan_start,
    scheduled_day,
    scheduled_key,
    scheduled_run_is_due,
)
from sidekick.automations.domain.spec import Cadence
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.types import new_uuid7
from sidekick.work.domain.ai_runs import AiUsage, CostSource
from tests.support.automations import AUTOMATION_ID, NOW, OWNER_ID

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
STOCKHOLM = ZoneInfo("Europe/Stockholm")


def run(attempt: int = 1, **overrides: Any) -> AutomationRun:
    claimed = AutomationRun.claim(
        run_id=new_uuid7(),
        owner_id=OWNER_ID,
        automation_id=AUTOMATION_ID,
        occurrence_key="d:2026-11-22",
        attempt=attempt,
        runner=RunRunner.CLAUDE,
        spec_digest=DIGEST,
        session_digest=None,
        credential_kind=CredentialKind.TOKEN,
        now=NOW,
    )
    return replace(claimed, **overrides)


def cadence(**overrides: Any) -> Cadence:
    return Cadence.model_validate({"frequency": "daily", "local_time": "07:00", **overrides})


def test_a_claimed_run_is_running_with_a_lease() -> None:
    claimed = run()

    assert claimed.state is RunState.RUNNING
    assert claimed.lease_until == NOW + RUN_LEASE
    assert claimed.holds_lease(NOW + RUN_LEASE - timedelta(seconds=1))
    assert not claimed.holds_lease(NOW + RUN_LEASE)


# --- starting an occurrence ---------------------------------------------------------------------


def test_a_new_occurrence_starts_its_first_attempt() -> None:
    plan = plan_start([], spec_digest=DIGEST, now=NOW)

    assert plan.action is StartAction.NEW_ATTEMPT
    assert plan.attempt == 1
    assert plan.run is None


def test_starting_an_open_occurrence_again_returns_the_same_run() -> None:
    open_run = run()

    plan = plan_start([open_run], spec_digest=DIGEST, now=NOW + timedelta(minutes=5))

    assert plan.action is StartAction.RETURN_EXISTING
    assert plan.run == open_run


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (RunState.DONE, NothingDueReason.ALREADY_DONE),
        (RunState.CHECKING, NothingDueReason.CHECKING),
    ],
)
def test_a_finished_occurrence_has_nothing_due(state: RunState, reason: NothingDueReason) -> None:
    plan = plan_start([run(state=state)], spec_digest=DIGEST, now=NOW)

    assert plan.action is StartAction.NOTHING_DUE
    assert plan.reason is reason


@pytest.mark.parametrize("state", [RunState.FAILED, RunState.CANCELLED, RunState.LAPSED])
def test_a_run_that_ended_badly_is_tried_again_as_the_next_attempt(state: RunState) -> None:
    plan = plan_start([run(state=state)], spec_digest=DIGEST, now=NOW)

    assert plan.action is StartAction.NEW_ATTEMPT
    assert plan.attempt == 2
    assert plan.run is None


def test_a_run_whose_lease_ran_out_lapses_and_the_next_attempt_takes_over() -> None:
    silent = run()

    plan = plan_start([silent], spec_digest=DIGEST, now=NOW + RUN_LEASE + timedelta(seconds=1))

    assert plan.action is StartAction.NEW_ATTEMPT
    assert plan.attempt == 2
    assert plan.run == silent
    assert plan.end_as is RunState.LAPSED


def test_a_run_that_followed_an_older_spec_is_cancelled_not_returned() -> None:
    old = run()

    plan = plan_start([old], spec_digest=OTHER_DIGEST, now=NOW)

    assert plan.action is StartAction.NEW_ATTEMPT
    assert plan.end_as is RunState.CANCELLED
    assert plan.run == old


def test_the_third_attempt_is_the_last() -> None:
    attempts = [
        run(attempt=n, state=RunState.FAILED) for n in range(1, MAX_ATTEMPTS_PER_OCCURRENCE)
    ]
    assert plan_start(attempts, spec_digest=DIGEST, now=NOW).attempt == MAX_ATTEMPTS_PER_OCCURRENCE

    attempts.append(run(attempt=MAX_ATTEMPTS_PER_OCCURRENCE, state=RunState.FAILED))
    with pytest.raises(ConflictError) as error:
        plan_start(attempts, spec_digest=DIGEST, now=NOW)

    assert error.value.reason == "ai_limit_reached"


# --- what a run takes and how it ends -----------------------------------------------------------


def test_a_call_adds_to_the_counts_and_renews_the_lease() -> None:
    later = NOW + timedelta(minutes=20)

    updated = run().recorded(datapoints=3, suggestions=2, rejected=1, flagged=1, now=later)

    assert (updated.datapoint_count, updated.suggestion_count) == (3, 2)
    assert (updated.rejected_count, updated.flagged_count) == (1, 1)
    assert updated.lease_until == later + RUN_LEASE
    assert updated.version == 2


@pytest.mark.parametrize("state", [RunState.DONE, RunState.FAILED, RunState.CHECKING])
def test_only_a_running_run_takes_results(state: RunState) -> None:
    with pytest.raises(ConflictError) as error:
        run(state=state).recorded(datapoints=1, suggestions=0, rejected=0, flagged=0, now=NOW)

    assert error.value.reason == "run_not_open"


def _finish(
    outcome: RunOutcome, *, checker: bool, suggestions: int, summary: str | None = None
) -> AutomationRun:
    return run(suggestion_count=suggestions).finished(
        outcome=outcome, summary=summary, usage=AiUsage(), checker_enabled=checker, now=NOW
    )


def test_a_finished_run_is_done_when_nothing_waits_for_a_check() -> None:
    done = _finish(RunOutcome.OK, checker=False, suggestions=2)

    assert done.state is RunState.DONE
    assert done.finished_at == NOW
    assert done.lease_until is None


def test_a_finished_run_waits_for_a_configured_check_only_when_it_has_something_to_check() -> None:
    checking = _finish(RunOutcome.OK, checker=True, suggestions=2)
    nothing = _finish(RunOutcome.NOTHING_FOUND, checker=True, suggestions=0)

    assert checking.state is RunState.CHECKING
    assert checking.finished_at is None
    assert nothing.state is RunState.DONE


def test_a_failed_run_ends_failed_whatever_the_checker() -> None:
    failed = _finish(RunOutcome.FAILED, checker=True, suggestions=2)

    assert failed.state is RunState.FAILED
    assert failed.outcome is RunOutcome.FAILED


@pytest.mark.parametrize(
    "outcome",
    [RunOutcome.BUDGET, RunOutcome.PROVIDER, RunOutcome.INVALID_OUTPUT, RunOutcome.REFUSED],
)
def test_a_runner_cannot_report_what_only_the_server_finds_out(outcome: RunOutcome) -> None:
    with pytest.raises(ValidationError):
        _finish(outcome, checker=False, suggestions=0)


def test_a_run_ends_as_cancelled_or_lapsed_only_while_active() -> None:
    assert run().ended(RunState.LAPSED, NOW).state is RunState.LAPSED
    with pytest.raises(ConflictError):
        run(state=RunState.DONE).ended(RunState.CANCELLED, NOW)


def test_the_summary_is_one_clean_line_of_at_most_300_characters() -> None:
    assert clean_summary(None) is None
    assert clean_summary("   \u200b ") is None
    assert clean_summary("Two\nlines  <b>x</b>") == "Two lines \u2039b>x\u2039/b>"
    assert len(clean_summary("x" * 1_000) or "") == 300


def test_a_clients_usage_is_kept_as_it_was_reported() -> None:
    usage = AiUsage(cost_microusd=400_000, cost_source=CostSource.CLIENT_ESTIMATE, model="m")

    finished = run().finished(
        outcome=RunOutcome.OK, summary=None, usage=usage, checker_enabled=False, now=NOW
    )

    assert finished.usage == usage


# --- occurrences --------------------------------------------------------------------------------


def test_occurrence_keys_name_a_day_or_one_request() -> None:
    assert scheduled_key(date(2026, 11, 22)) == "d:2026-11-22"
    assert scheduled_day("d:2026-11-22") == date(2026, 11, 22)
    assert scheduled_day(manual_key("0" * 32)) is None
    assert scheduled_day("d:not-a-date") is None
    assert len(manual_key(new_uuid7().hex)) <= 40


TODAY = date(2026, 11, 22)


def due(
    cadence_: Cadence | None, last_day: date | None, today: date = TODAY
) -> NothingDueReason | None:
    return scheduled_run_is_due(cadence_, last_day=last_day, today=today, zone=STOCKHOLM)


def test_without_a_cadence_a_scheduled_run_is_never_due() -> None:
    assert due(None, None) is NothingDueReason.NO_CADENCE


def test_the_first_scheduled_run_is_due_when_asked_for() -> None:
    assert due(cadence(), None) is None


def test_a_daily_cadence_is_due_the_day_after_the_last_one() -> None:
    assert due(cadence(), date(2026, 11, 21)) is None
    assert due(cadence(), TODAY) is NothingDueReason.NOT_DUE


def test_several_missed_days_make_one_run_not_a_catch_up() -> None:
    assert due(cadence(), date(2026, 11, 10)) is None


def test_a_weekly_cadence_waits_for_its_weekday() -> None:
    monday = cadence(frequency="weekly", weekdays=[0])

    assert due(monday, date(2026, 11, 16), today=date(2026, 11, 22)) is NothingDueReason.NOT_DUE
    assert due(monday, date(2026, 11, 16), today=date(2026, 11, 23)) is None


def test_a_cadence_past_its_end_is_not_due() -> None:
    ended = cadence(until="2026-11-20")

    assert due(ended, None) is NothingDueReason.NOT_DUE
    assert due(cadence(until="2026-11-22"), None) is None


def test_the_clock_of_the_test_is_utc() -> None:
    assert NOW.tzinfo is UTC

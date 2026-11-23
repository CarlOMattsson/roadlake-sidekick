"""A run's way through its check: taken by one worker, a reservation per call, the cost booked on
the run, and the end. No database."""

from dataclasses import replace
from datetime import timedelta

import pytest

from sidekick.automations.domain.runs import (
    CHECK_RETRY_WAIT_SECONDS,
    DEFAULT_CHECK_LEASE,
    AutomationRun,
    CredentialKind,
    RunOutcome,
    RunRunner,
    RunState,
    check_lease,
)
from sidekick.shared.errors import ConflictError
from sidekick.shared.types import new_uuid7
from sidekick.work.domain.ai_runs import AiUsage, CostSource
from tests.support.automations import NOW

WORKER = "host:1:aaa"


def _checking(usage: AiUsage | None = None, **overrides: object) -> AutomationRun:
    running = AutomationRun.claim(
        run_id=new_uuid7(),
        owner_id=new_uuid7(),
        automation_id=new_uuid7(),
        occurrence_key="d:2026-11-22",
        attempt=1,
        runner=RunRunner.CLAUDE,
        spec_digest="d" * 64,
        session_digest=None,
        credential_kind=CredentialKind.TOKEN,
        now=NOW,
    )
    run = replace(
        running,
        state=RunState.CHECKING,
        outcome=RunOutcome.OK,
        lease_until=None,
        suggestion_count=2,
        usage=usage or AiUsage(),
        **overrides,
    )
    return run


def _held(**kwargs: object) -> AutomationRun:
    return _checking(**kwargs).claim_check(
        WORKER, "typesafe/jev-1.14", lease=DEFAULT_CHECK_LEASE, now=NOW
    )  # type: ignore[arg-type]


def test_a_free_run_is_taken_with_a_lease_and_the_checker_is_named() -> None:
    claimed = _checking().claim_check(
        WORKER, "typesafe/jev-1.14", lease=DEFAULT_CHECK_LEASE, now=NOW
    )

    assert claimed.state is RunState.CHECKING
    assert claimed.worker_id == WORKER
    assert claimed.stage == "check"
    assert claimed.checker_model == "typesafe/jev-1.14"
    assert claimed.lease_until == NOW + DEFAULT_CHECK_LEASE
    assert claimed.holds_check(WORKER, NOW)
    assert not claimed.holds_check("other", NOW)


def test_a_run_another_worker_holds_is_not_taken() -> None:
    with pytest.raises(ConflictError):
        _held().claim_check("other", "m", lease=DEFAULT_CHECK_LEASE, now=NOW + timedelta(seconds=1))


def test_a_run_whose_worker_went_silent_is_taken_over() -> None:
    later = NOW + DEFAULT_CHECK_LEASE + timedelta(seconds=1)

    taken = _held().claim_check("other", "m", lease=DEFAULT_CHECK_LEASE, now=later)

    assert taken.worker_id == "other"
    assert not taken.holds_check(WORKER, later)


def test_only_a_run_that_waits_for_its_check_is_taken() -> None:
    running = replace(_checking(), state=RunState.RUNNING)

    with pytest.raises(ConflictError):
        running.claim_check(WORKER, "m", lease=DEFAULT_CHECK_LEASE, now=NOW)


def test_a_call_is_reserved_by_the_worker_that_holds_the_run_and_settled_into_its_cost() -> None:
    reserved = _held().reserve_check(
        500, CostSource.PRICE_TABLE, worker_id=WORKER, lease=DEFAULT_CHECK_LEASE, now=NOW
    )

    assert reserved.usage.reserved_microusd == 500
    assert reserved.usage.cost_source is CostSource.PRICE_TABLE

    call = AiUsage(input_tokens=120, cost_microusd=7, cost_source=CostSource.PROVIDER)
    settled = reserved.settle_check(call, worker_id=WORKER, now=NOW)

    assert settled.usage.reserved_microusd == 0
    assert settled.usage.cost_microusd == 7
    assert settled.usage.input_tokens == 120
    assert settled.usage.cost_source is CostSource.PRICE_TABLE  # the run keeps a counted source


def test_two_calls_are_never_reserved_at_once() -> None:
    reserved = _held().reserve_check(
        500, CostSource.PRICE_TABLE, worker_id=WORKER, lease=DEFAULT_CHECK_LEASE, now=NOW
    )

    with pytest.raises(ConflictError):
        reserved.reserve_check(
            500, CostSource.PRICE_TABLE, worker_id=WORKER, lease=DEFAULT_CHECK_LEASE, now=NOW
        )


def test_a_worker_that_lost_the_run_reserves_nothing() -> None:
    held = _held()

    with pytest.raises(ConflictError):
        held.reserve_check(
            1, CostSource.PRICE_TABLE, worker_id="other", lease=DEFAULT_CHECK_LEASE, now=NOW
        )
    with pytest.raises(ConflictError):
        held.reserve_check(
            1,
            CostSource.PRICE_TABLE,
            worker_id=WORKER,
            lease=DEFAULT_CHECK_LEASE,
            now=NOW + DEFAULT_CHECK_LEASE + timedelta(seconds=1),
        )


def test_a_clients_estimate_never_counts_so_the_checks_own_cost_replaces_it() -> None:
    estimate = AiUsage(
        input_tokens=9_000,
        cost_microusd=80_000,
        cost_source=CostSource.CLIENT_ESTIMATE,
        model="claude-sonnet-5-5",
    )

    reserved = _held(usage=estimate).reserve_check(
        500, CostSource.PRICE_TABLE, worker_id=WORKER, lease=DEFAULT_CHECK_LEASE, now=NOW
    )
    settled = reserved.settle_check(
        AiUsage(input_tokens=120, cost_microusd=7, cost_source=CostSource.PRICE_TABLE),
        worker_id=WORKER,
        now=NOW,
    )

    assert settled.usage.cost_source is CostSource.PRICE_TABLE
    assert settled.usage.cost_microusd == 7
    assert settled.usage.input_tokens == 120
    assert settled.usage.model == "claude-sonnet-5-5"


def test_a_counted_cost_stays_counted_when_the_check_runs_on_a_local_model() -> None:
    counted = AiUsage(cost_microusd=1_000, cost_source=CostSource.PRICE_TABLE)

    reserved = _held(usage=counted).reserve_check(
        0, CostSource.NONE, worker_id=WORKER, lease=DEFAULT_CHECK_LEASE, now=NOW
    )
    settled = reserved.settle_check(AiUsage(cost_source=CostSource.NONE), worker_id=WORKER, now=NOW)

    assert settled.usage.cost_source is CostSource.PRICE_TABLE
    assert settled.usage.cost_microusd == 1_000


def test_a_reservation_whose_worker_went_silent_is_booked_as_cost() -> None:
    reserved = _held().reserve_check(
        500, CostSource.PRICE_TABLE, worker_id=WORKER, lease=DEFAULT_CHECK_LEASE, now=NOW
    )
    later = NOW + DEFAULT_CHECK_LEASE + timedelta(seconds=1)

    assert reserved.holds_lapsed_check_reservation(later)
    assert not reserved.holds_lapsed_check_reservation(NOW)
    freed = reserved.abandon_check_reservation(now=later)

    assert freed.usage.reserved_microusd == 0
    assert freed.usage.cost_microusd == 500
    assert freed.worker_id is None
    assert freed.lease_until is None
    with pytest.raises(ConflictError):
        freed.abandon_check_reservation(now=later)


def test_a_checked_run_is_done_and_keeps_its_outcome() -> None:
    done = _held().checked(now=NOW + timedelta(minutes=1))

    assert done.state is RunState.DONE
    assert done.outcome is RunOutcome.OK
    assert done.finished_at == NOW + timedelta(minutes=1)
    assert done.worker_id is None
    assert done.lease_until is None
    assert done.stage is None


def test_a_run_with_a_call_still_reserved_is_not_done() -> None:
    reserved = _held().reserve_check(
        500, CostSource.PRICE_TABLE, worker_id=WORKER, lease=DEFAULT_CHECK_LEASE, now=NOW
    )

    with pytest.raises(ConflictError):
        reserved.checked(now=NOW)


def test_the_checker_model_name_is_cut_to_the_column() -> None:
    claimed = _checking().claim_check(WORKER, "m" * 500, lease=DEFAULT_CHECK_LEASE, now=NOW)

    assert claimed.checker_model is not None
    assert len(claimed.checker_model) == 120


def test_the_lease_outlasts_a_call_that_takes_the_longest_the_provider_allows() -> None:
    longest_call = 300.0  # the provider's request timeout is at most this many seconds
    lease = check_lease(longest_call)

    assert lease > timedelta(seconds=longest_call + CHECK_RETRY_WAIT_SECONDS)
    assert check_lease(30.0) < lease  # it follows the configured timeout
    assert lease == DEFAULT_CHECK_LEASE


def test_a_call_that_ends_after_another_worker_took_over_leaves_that_workers_reservation() -> None:
    first = _held().reserve_check(
        500, CostSource.PRICE_TABLE, worker_id=WORKER, lease=DEFAULT_CHECK_LEASE, now=NOW
    )
    later = NOW + DEFAULT_CHECK_LEASE + timedelta(seconds=1)
    # The first worker's lease ran out; a second took the run (booking the first's reservation as
    # cost) and reserved a call of its own.
    second = (
        first.abandon_check_reservation(now=later)
        .claim_check("other", "m", lease=DEFAULT_CHECK_LEASE, now=later)
        .reserve_check(
            300, CostSource.PRICE_TABLE, worker_id="other", lease=DEFAULT_CHECK_LEASE, now=later
        )
    )

    settled = second.settle_check(
        AiUsage(cost_microusd=40, cost_source=CostSource.PRICE_TABLE), worker_id=WORKER, now=later
    )

    assert settled.usage.reserved_microusd == 300  # the second worker's call is still reserved
    assert settled.usage.cost_microusd == 500 + 40  # the first call is booked once, as it cost


def test_a_run_waiting_for_a_check_nobody_does_is_released_when_the_check_is_off() -> None:
    waiting = _checking()
    limit = timedelta(hours=1)

    assert waiting.releasable(NOW, checker_enabled=False, release_after=limit)
    assert not waiting.releasable(NOW, checker_enabled=True, release_after=limit)
    assert waiting.releasable(NOW + limit, checker_enabled=True, release_after=limit)


def test_a_run_a_worker_holds_is_never_released() -> None:
    held = _held()
    limit = timedelta(hours=1)

    assert not held.releasable(NOW, checker_enabled=False, release_after=limit)
    assert not replace(held, state=RunState.DONE).releasable(
        NOW, checker_enabled=False, release_after=limit
    )


def test_releasing_a_run_books_a_reservation_that_never_reported_back_and_ends_it() -> None:
    reserved = _held().reserve_check(
        500, CostSource.PRICE_TABLE, worker_id=WORKER, lease=DEFAULT_CHECK_LEASE, now=NOW
    )
    later = NOW + DEFAULT_CHECK_LEASE + timedelta(seconds=1)

    done = reserved.release_unchecked(now=later)

    assert done.state is RunState.DONE
    assert done.outcome is RunOutcome.OK
    assert done.usage.cost_microusd == 500
    assert done.usage.reserved_microusd == 0

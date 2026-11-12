"""The budget of failed pairings: per client, global and reserve, on a fake clock, no framework.

The point of the layers: a stranger who spends the shared budget must not refuse the owner's valid
code, and a client that keeps failing must still be stopped.
"""

from sidekick.api.pairing_budget import (
    DEFAULT_FAILURES_GLOBAL_PER_MINUTE,
    DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE,
    DEFAULT_RESERVE_PER_MINUTE,
    MAX_TRACKED_CLIENTS,
    PairingBudget,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def fail_until_refused(budget: PairingBudget, client: str, limit: int = 1000) -> int:
    """Count the attempts the budget admits for this client (each is a failure: no refund)."""

    admitted = 0
    while admitted < limit and budget.admit(client) is not None:
        admitted += 1
    return admitted


def test_one_client_is_stopped_after_its_own_budget_and_the_reserve() -> None:
    budget = PairingBudget(clock=Clock())
    admitted = fail_until_refused(budget, "198.51.100.1")
    assert admitted == DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE + DEFAULT_RESERVE_PER_MINUTE
    assert budget.retry_after("198.51.100.1") >= 1


def test_strangers_spending_the_global_budget_do_not_refuse_a_clean_client() -> None:
    budget = PairingBudget(clock=Clock())
    attackers = DEFAULT_FAILURES_GLOBAL_PER_MINUTE // DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE + 2
    for index in range(attackers):
        fail_until_refused(budget, f"203.0.113.{index}")
    # Global budget and reserve are both spent; an attacker's address is refused...
    assert budget.admit("203.0.113.0") is None
    # ...but an owner on another address, with no recent failure, still gets in.
    assert budget.admit("198.51.100.77") is not None


def test_a_client_that_failed_recently_is_gated_by_the_global_budget() -> None:
    clock = Clock()
    budget = PairingBudget(clock=clock)
    # The owner's address has failed once (a mistyped code) ...
    assert budget.admit("198.51.100.77") is not None
    for index in range(10):
        fail_until_refused(budget, f"203.0.113.{index}")
    # ... so the spent global budget now applies to it, until it refills.
    assert budget.admit("198.51.100.77") is None
    clock.now += 60.0
    assert budget.admit("198.51.100.77") is not None


def test_a_shared_address_attack_leaves_the_reserve_for_a_valid_code_then_blocks() -> None:
    budget = PairingBudget(clock=Clock())
    # Behind a tunnel owner and attacker share an address. The attacker spends the client budget.
    for _ in range(DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE):
        assert budget.admit("172.18.0.2") is not None
    # The owner's valid code passes through the reserve and gives it back on success.
    reservation = budget.admit("172.18.0.2")
    assert reservation is not None
    reservation.refund()
    # Brute force keeps being blocked once the reserve is used up.
    assert fail_until_refused(budget, "172.18.0.2") == DEFAULT_RESERVE_PER_MINUTE
    assert budget.admit("172.18.0.2") is None


def test_success_gives_the_whole_reservation_back() -> None:
    budget = PairingBudget(clock=Clock())
    for _ in range(DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE * 3):
        reservation = budget.admit("198.51.100.1")
        assert reservation is not None
        reservation.refund()


def test_refill_lets_a_client_in_again() -> None:
    clock = Clock()
    budget = PairingBudget(clock=clock)
    fail_until_refused(budget, "198.51.100.1")
    assert budget.admit("198.51.100.1") is None
    clock.now += 60.0
    assert budget.admit("198.51.100.1") is not None


def test_tracked_clients_are_bounded_and_the_busiest_attacker_stays_tracked() -> None:
    clock = Clock()
    budget = PairingBudget(clock=clock)
    fail_until_refused(budget, "attacker")
    for index in range(MAX_TRACKED_CLIENTS + 50):
        budget.admit(f"client-{index}")
    assert len(budget._clients) <= MAX_TRACKED_CLIENTS  # the table never grows past its bound
    assert "attacker" in budget._clients

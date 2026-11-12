"""Deadline polling for tests that must wait for something outside the test process.

Use this instead of a fixed `time.sleep(n)`: a fixed pause is too short on a loaded machine and
too long everywhere else, while a poll returns as soon as the condition holds and fails with a
named reason when the deadline passes. A sleep that *is* the behaviour under test (a stalled
client, a hanging server) stays a sleep and carries a comment saying so.
"""

import time
from collections.abc import Callable


def poll_until(condition: Callable[[], object], *, timeout: float, interval: float = 0.02) -> bool:
    """Call `condition` until it is truthy or `timeout` seconds have passed; say which happened."""

    deadline = time.monotonic() + timeout
    while True:
        if condition():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def wait_until(
    condition: Callable[[], object], *, timeout: float, what: str, interval: float = 0.02
) -> None:
    """Like `poll_until`, but fail the test with `what` when the deadline passes."""

    if not poll_until(condition, timeout=timeout, interval=interval):
        raise AssertionError(f"timed out after {timeout:g} s waiting for {what}")

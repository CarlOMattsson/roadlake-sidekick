"""The suite hands every test the same `sidekick` logger state, whatever ran before it."""

import logging


def test_sidekick_logging_is_configured_before_a_test_body_runs() -> None:
    """A capture handler attached in a fixture must survive the app's first `create_app`.

    `configure_observability` replaces the `sidekick` handlers once per process; the autouse
    fixture in `tests/conftest.py` runs it first, so a handler attached afterwards stays.
    """

    logger = logging.getLogger("sidekick")
    assert logger.handlers, "configure_observability has not run"
    assert logger.propagate is False
    assert not logger.disabled

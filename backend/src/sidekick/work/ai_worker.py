"""AI worker process: runs the AI steps the owner has queued, with the owner's own Anthropic key.

Run as `python -m sidekick.work.ai_worker` (or `sidekick-ai-worker`), its own process mode like the
push and memory workers. It is opt-in: the `ai` Compose profile starts it and
`SIDEKICK_AI_RUNNER_ENABLED` turns it on. It is the only process that may hold the key.

This module is only the loop and the CLI. The rules (reserve before a call, check the plan, settle
after) are in `work.application.ai_runner`. With the runner off the worker sleeps but still beats,
so its healthcheck passes. A worker whose key the provider refused takes no more runs and stops
beating its success, so the healthcheck reports it instead of letting it look idle.

SIGTERM lets a model call in flight finish and be booked before the process exits.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import threading
from collections.abc import Callable
from uuid import uuid4

from sidekick.activity.application.service import ActivityLedger
from sidekick.activity.persistence import ActivityStore
from sidekick.shared.cli_errors import run_guarded
from sidekick.shared.config import Settings, get_settings
from sidekick.shared.db_timeouts import database_timeout_reason
from sidekick.shared.errors.core import RefusedError
from sidekick.shared.observability import (
    TelemetryPort,
    configure_observability,
    configure_worker_logging,
    log_failure,
    safe_log_fields,
)
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.types import SystemClock
from sidekick.shared.worker_health import WorkerHeartbeat
from sidekick.work.application.ai_runner import AiRunnerService
from sidekick.work.application.ai_store import AiLimits, ServerRunnerConfig
from sidekick.work.infrastructure.anthropic_model import AnthropicModel
from sidekick.work.persistence.store import SqlWorkStore

LOGGER = logging.getLogger("sidekick.work.ai_worker")

# Sleep of a worker with nothing to do (the runner is off); it still beats, so its
# healthcheck passes.
IDLE_SLEEP_SECONDS = 3600


def build_runner(
    settings: Settings, stopping: Callable[[], bool], telemetry: TelemetryPort | None = None
) -> AiRunnerService:
    """The runner wired to the database and the model, or the refusal to start without the key."""

    key = settings.ai_anthropic_api_key
    if key is None:
        LOGGER.error("ai_runner_key_missing")
        raise RefusedError(
            "the AI runner is on but SIDEKICK_AI_ANTHROPIC_API_KEY_FILE gives it no key"
        )
    config = ServerRunnerConfig.from_settings(settings)
    if config.price is None:
        raise RefusedError(
            "the model has no built-in price; set all four SIDEKICK_AI_PRICE_* variables"
        )
    resolved_telemetry = telemetry or configure_observability(settings.environment)
    factory = create_session_factory(
        settings.database_url,
        require_unprivileged_role=settings.environment == "production",
        timeouts=settings.database_timeouts,
    )
    return AiRunnerService(
        SqlWorkStore(factory, resolved_telemetry),
        SystemClock(),
        AiLimits.from_settings(settings),
        config,
        AnthropicModel(
            key.get_secret_value(), settings.ai_model, settings.ai_request_timeout_seconds
        ),
        owner_timezone=settings.owner_zone,
        telemetry=resolved_telemetry,
        activity=ActivityLedger(ActivityStore(factory, resolved_telemetry)),
        stopping=stopping,
    )


def run_worker(
    settings: Settings,
    *,
    once: bool = False,
    stop: threading.Event | None = None,
    build: Callable[[Settings, Callable[[], bool]], AiRunnerService] = build_runner,
) -> None:
    stop = stop or threading.Event()
    heartbeat = WorkerHeartbeat("ai")
    if not settings.ai_runner_enabled:
        LOGGER.info("ai_runner", extra=safe_log_fields({"outcome": "disabled"}))
        if once:
            return
        while not stop.is_set():  # Nothing to do; stay up so a supervisor does not restart-loop.
            heartbeat.beat(IDLE_SLEEP_SECONDS)
            heartbeat.succeeded()
            stop.wait(IDLE_SLEEP_SECONDS)
        return
    runner = build(settings, stop.is_set)
    # The column holds 80 characters.
    worker_id = f"{socket.gethostname()[:50]}:{os.getpid()}:{uuid4().hex[:12]}"
    while not stop.is_set():
        heartbeat.beat(settings.ai_poll_seconds)
        recovered = _guarded(runner.recover_stalled, "recovery", "ai run recovery failed")
        drained = _drain(runner, worker_id, heartbeat, settings.ai_poll_seconds, stop, once)
        if recovered is not None and drained and not runner.credentials_rejected:
            heartbeat.succeeded()
        if once:
            return
        stop.wait(settings.ai_poll_seconds)


def _drain(
    runner: AiRunnerService,
    worker_id: str,
    heartbeat: WorkerHeartbeat,
    poll_seconds: int,
    stop: threading.Event,
    once: bool,
) -> bool:
    """Run the queued runs one after the other. False when one failed unexpectedly."""

    while not stop.is_set() and not runner.credentials_rejected:
        heartbeat.beat(poll_seconds)
        taken = _guarded(lambda: runner.run_next(worker_id), "run", "ai run failed")
        if taken is None:
            return False
        if not taken or once:
            break
    return True


def _guarded[Result](
    action: Callable[[], Result], step: str, failure_message: str
) -> Result | None:
    """Run one part of the cycle; a failure is logged (a database timeout as a warning) and does
    not stop the loop. Returns None when it failed."""

    try:
        return action()
    except Exception as error:
        if (reason := database_timeout_reason(error)) is not None:
            LOGGER.warning(
                "database timeout; retrying next cycle",
                extra={"db_timeout": reason, "worker_step": step},
            )
        else:
            log_failure(LOGGER, failure_message, error)
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Sidekick's AI worker")
    parser.add_argument("--once", action="store_true", help="run what is queued once and exit")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_worker_logging()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
    try:
        code = run_guarded(
            "sidekick-ai-worker", lambda: run_worker(get_settings(), once=args.once, stop=stop)
        )
    except KeyboardInterrupt:
        return
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()

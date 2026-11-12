"""Push worker process (ADR-005; D-078, push through UnifiedPush).

Run as `python -m sidekick.companion.push_worker` (or `sidekick-push-worker`), its own process mode
like `sidekick.backup.worker`.

This module is only the loop and the CLI. The delivery rules are in `push_delivery`, their SQL in
`push_delivery_store` and the HTTP send in `push_sender`. Each cycle also runs the reminder
scheduler (`push_reminders.ReminderScheduler`) every `SCHEDULE_INTERVAL`: it queues the morning
summary and the due reminders as `r` rows, which the delivery service then sends like any other
row. The push carries no content; the phone fetches it.

With push disabled the worker sleeps but still beats, so its healthcheck passes. A cycle in which
the scheduler or the delivery raised, or in which every delivery failed unexpectedly, is not marked
as a success. Nothing here logs an endpoint, a topic or a response.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol

from sidekick.companion.push_delivery import PushDeliveryService
from sidekick.companion.push_delivery_store import SqlPushDeliveryStore
from sidekick.companion.push_reminders import ReminderScheduler
from sidekick.companion.push_sender import HttpPushSender, create_client, silence_http_loggers
from sidekick.shared.cli_errors import run_guarded
from sidekick.shared.config import Settings, get_settings
from sidekick.shared.db_timeouts import database_timeout_reason
from sidekick.shared.observability import configure_worker_logging, log_failure, safe_log_fields
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.worker_health import WorkerHeartbeat

LOGGER = logging.getLogger("sidekick.companion.push_worker")

# How often the scheduler looks for reminders that are due (it needs no finer than a minute).
SCHEDULE_INTERVAL = 30.0
# Sleep of a worker with nothing to do (push disabled); it still beats, so its healthcheck passes.
IDLE_SLEEP_SECONDS = 3600


class DeliveryCycle(Protocol):
    last_run_failed: bool

    def run_once(self) -> int: ...


class ScheduleCycle(Protocol):
    def run_once(self) -> int: ...


def build_cycles(settings: Settings) -> tuple[DeliveryCycle, ScheduleCycle]:
    """The delivery service and the reminder scheduler, wired to the database and the network."""

    session_factory = create_session_factory(
        settings.database_url,
        require_unprivileged_role=settings.environment == "production",
        timeouts=settings.database_timeouts,
    )
    service = PushDeliveryService(
        SqlPushDeliveryStore(session_factory),
        HttpPushSender(create_client()),
        settings.push_allowed_host_set,
        wake_min_interval=timedelta(seconds=settings.push_wake_min_interval_seconds),
        auth_host=settings.push_auth_host,
        auth_token=settings.push_auth_token,
    )
    return service, ReminderScheduler.from_settings(settings, session_factory)


def run_worker(
    settings: Settings,
    *,
    once: bool = False,
    build: Callable[[Settings], tuple[DeliveryCycle, ScheduleCycle]] = build_cycles,
) -> None:
    heartbeat = WorkerHeartbeat("push")
    if not settings.push_enabled:
        LOGGER.info("push_delivery", extra=safe_log_fields({"push_outcome": "disabled"}))
        if once:
            return
        while True:  # Nothing to do; stay up so a supervisor does not restart-loop.
            heartbeat.beat(IDLE_SLEEP_SECONDS)
            heartbeat.succeeded()  # nothing to do is a success
            time.sleep(IDLE_SLEEP_SECONDS)
    service, scheduler = build(settings)
    next_schedule = 0.0
    while True:
        heartbeat.beat(settings.push_poll_seconds)
        succeeded = True
        if time.monotonic() >= next_schedule:
            next_schedule = time.monotonic() + SCHEDULE_INTERVAL
            succeeded = _step(
                scheduler.run_once, "reminder_scheduling", "push reminder scheduling failed"
            )
        delivered = _step(service.run_once, "delivery", "push delivery iteration failed")
        if not delivered or service.last_run_failed:
            succeeded = False
        if succeeded:
            heartbeat.succeeded()
        if once:
            return
        time.sleep(settings.push_poll_seconds)


def _step(action: Callable[[], object], step: str, failure_message: str) -> bool:
    """Run one part of the cycle; a failure is logged (a database timeout as a warning) and does
    not stop the loop. Returns whether it succeeded."""

    try:
        action()
    except Exception as error:
        if (reason := database_timeout_reason(error)) is not None:
            LOGGER.warning(
                "database timeout; retrying next cycle",
                extra={"db_timeout": reason, "worker_step": step},
            )
        else:
            log_failure(LOGGER, failure_message, error)
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Sidekick's push delivery worker")
    parser.add_argument("--once", action="store_true", help="send what is due once and exit")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_worker_logging()
    silence_http_loggers()
    try:
        code = run_guarded(
            "sidekick-push-worker", lambda: run_worker(get_settings(), once=args.once)
        )
    except KeyboardInterrupt:
        return
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()

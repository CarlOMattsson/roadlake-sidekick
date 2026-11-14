"""Small PostgreSQL-backed worker that materializes due process runs into tasks."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys
import time
from uuid import uuid4

from sidekick.composition import create_container
from sidekick.shared.cli_errors import EXIT_FAILED, run_guarded
from sidekick.shared.config import get_settings
from sidekick.shared.db_timeouts import database_timeout_reason
from sidekick.shared.observability import configure_worker_logging, log_failure
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.persistence.stores.base import IDEMPOTENCY_RETENTION, StoreBase
from sidekick.shared.types import utc_now
from sidekick.shared.worker_health import WorkerHeartbeat

LOGGER = logging.getLogger("sidekick.automation.worker")
POLL_SECONDS = 30
IDEMPOTENCY_PRUNE_SECONDS = 3600


def prune_idempotency_records(store: StoreBase) -> int:
    """Delete replay records older than `IDEMPOTENCY_RETENTION`; returns how many were removed."""

    cutoff = utc_now() - IDEMPOTENCY_RETENTION
    return store.transaction(lambda session: store.prune_idempotency(session, cutoff))


async def run_worker(*, once: bool = False) -> bool:
    """Run the worker loop. With `once`, return whether the single iteration succeeded.

    A failed iteration never stops the long-running loop, but `--once` is a one-shot, so a failure
    there must reach the exit status.
    """

    settings = get_settings()
    container = create_container(settings)
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"
    store = StoreBase(
        create_session_factory(settings.database_url, timeouts=settings.database_timeouts)
    )
    next_prune = time.monotonic()
    heartbeat = WorkerHeartbeat("automation")
    while True:
        heartbeat.beat(POLL_SECONDS)
        succeeded = True
        if time.monotonic() >= next_prune:
            next_prune = time.monotonic() + IDEMPOTENCY_PRUNE_SECONDS
            try:
                pruned = prune_idempotency_records(store)
                if pruned:
                    LOGGER.info(
                        "idempotency records pruned", extra={"idempotency_pruned_count": pruned}
                    )
            except Exception as error:
                succeeded = False
                if (reason := database_timeout_reason(error)) is not None:
                    LOGGER.warning(
                        "database timeout; retrying next cycle",
                        extra={"db_timeout": reason, "worker_step": "idempotency_prune"},
                    )
                else:
                    log_failure(LOGGER, "idempotency prune failed", error)
        try:
            container.process_runs.recover_stalled_outbox()
            process_runs_created = container.process_runs.run_due(worker_id)
            if process_runs_created:
                LOGGER.info(
                    "process runs materialized",
                    extra={"process_run_count": len(process_runs_created)},
                )
        except Exception as error:
            # The next poll can recover a claimed run. Database details are deliberately
            # not logged by this process.
            succeeded = False
            if (reason := database_timeout_reason(error)) is not None:
                LOGGER.warning(
                    "database timeout; retrying next cycle",
                    extra={"db_timeout": reason, "worker_step": "iteration"},
                )
            else:
                log_failure(LOGGER, "automation worker iteration failed", error)
        if succeeded:
            heartbeat.succeeded()
        if once:
            return succeeded
        await asyncio.sleep(POLL_SECONDS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Sidekick's process-run worker")
    parser.add_argument("--once", action="store_true", help="run one scheduling iteration")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_worker_logging()
    try:
        outcome: list[bool] = []
        code = run_guarded(
            "sidekick-automation-worker",
            lambda: outcome.append(asyncio.run(run_worker(once=args.once))),
        )
    except KeyboardInterrupt:
        # SIGINT is the normal shutdown signal for a local stack. Exit quietly instead of
        # printing a traceback.
        return
    if code:
        sys.exit(code)
    if not outcome[0]:
        sys.exit(EXIT_FAILED)


if __name__ == "__main__":
    main()

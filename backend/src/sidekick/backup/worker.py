"""Opt-in local encrypted-backup worker for the managed Sidekick stack."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from uuid import uuid4

from sidekick.backup.bundle import BackupTooLarge, OwnerBackupService
from sidekick.shared.cli_errors import run_guarded
from sidekick.shared.config import get_settings
from sidekick.shared.observability import configure_worker_logging, log_failure
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.worker_health import WorkerHeartbeat
from sidekick.store import SqlAlchemyStore

LOGGER = logging.getLogger("sidekick.backup.worker")


async def run_worker(*, once: bool = False) -> bool:
    """Run the backup loop. With `once`, return whether the single iteration succeeded.

    A failed iteration never stops the long-running loop, but `--once` is a one-shot used by the
    updater before it touches anything, so a failure there must reach the exit status.
    """

    settings = get_settings()
    if not settings.backup_enabled:
        LOGGER.info("encrypted local backups disabled")
        if once:
            return True

    service = OwnerBackupService(
        SqlAlchemyStore(
            create_session_factory(
                settings.database_url,
                require_unprivileged_role=settings.environment == "production",
                timeouts=settings.database_timeouts.unbounded_statements(),
            )
        )
    )
    key = settings.backup_encryption_key
    if settings.backup_enabled and key is None:
        LOGGER.error("backup encryption key is required when backups are enabled")
        raise RuntimeError("backup encryption key is required when backups are enabled")
    create_key = key if key is not None else ""
    heartbeat = WorkerHeartbeat("backup")
    while True:
        heartbeat.beat(settings.backup_interval_seconds)
        if settings.backup_enabled:
            # A random id for this run only; it names the run in the log, nothing else.
            run_id = uuid4().hex
            try:
                result = service.create(
                    directory=settings.backup_directory,
                    key=create_key,
                    retention_count=settings.backup_retention_count,
                    retention_days=settings.backup_retention_days,
                    min_keep=settings.backup_min_keep,
                    space_margin_percent=settings.backup_space_margin_pct,
                )
                LOGGER.info(
                    "encrypted local backup completed",
                    extra={
                        "backup_run_id": run_id,
                        "outcome": "success",
                        "backup_owner_count": result.owner_count,
                        "backup_pruned_count": result.pruned_count,
                    },
                )
            except BackupTooLarge:
                # Sizes and owner data are not logged: the message of this error is fixed text.
                LOGGER.error(
                    "encrypted backup refused: bundle is over the size ceiling",
                    extra={"backup_run_id": run_id, "outcome": "refused"},
                )
                if once:
                    return False
            except Exception as error:
                log_failure(
                    LOGGER,
                    "encrypted backup iteration failed",
                    error,
                    backup_run_id=run_id,
                    outcome="failed",
                )
                if once:
                    return False
        if once:
            return True
        await asyncio.sleep(settings.backup_interval_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Sidekick's local backup worker")
    parser.add_argument("--once", action="store_true", help="run one backup iteration")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_worker_logging()
    try:
        outcome: list[bool] = []
        code = run_guarded(
            "sidekick-backup-worker",
            lambda: outcome.append(asyncio.run(run_worker(once=args.once))),
        )
    except KeyboardInterrupt:
        return
    if code:
        sys.exit(code)
    if not outcome[0]:
        sys.exit(1)


if __name__ == "__main__":
    main()

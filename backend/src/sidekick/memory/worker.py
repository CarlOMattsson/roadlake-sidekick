"""Derived-memory worker CLI: the reconcile loop plus owner maintenance commands.

Default: one reconcile pass per owner every `PASS_SECONDS`, until interrupted. The first pass
after start and the first pass after 03:00 UTC each day is a full pass (every fingerprint is
recomputed, which picks up changes that never touched a record's `updated_at`, such as a renamed
contact mentioned in a journal entry). Each full pass ends with the orphan-bank sweep, which runs
only when `SIDEKICK_MEMORY_ORPHAN_SWEEP_ENABLED` is set. The first pass starts with the
lost-volume check (retried every pass until Hindsight has answered); both live in
`sidekick.memory.application.lifecycle`. `--once` runs one pass and exits.
`--rebuild-owner` marks an owner's rows dirty so the next pass resends them. `--wipe` and
`--forget-owner` delete memory documents through the provider and then their rows; both are
destructive and need `--confirm`.
`--forget-owner` first pauses the owner and switches every domain off, under the owner's lock, so
nothing is sent again behind the deletion; `--wipe` needs `--and-pause` for the same reason (or
`SIDEKICK_MEMORY_INGEST_ENABLED=false`).

Logs carry ids, counts and fixed categories only. Document text, titles, names and provider bodies
are never logged or printed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sidekick.memory.application.lifecycle import (
    BankCheckResult,
    SweepResult,
    sweep_orphan_banks,
    verify_banks_after_start,
)
from sidekick.memory.application.store import MemoryStore, SourceState
from sidekick.memory.application.sync import MemoryReconciler
from sidekick.memory.application.sync_rules import SUBMITTED, removal_hold_until
from sidekick.memory.application.sync_state import ReconcileResult, SyncPolicy
from sidekick.memory.factory import build_provider
from sidekick.memory.infrastructure.store import SqlAlchemyMemoryStore
from sidekick.memory.ports import MemoryProvider, MemoryProviderError
from sidekick.shared.cli_errors import run_guarded
from sidekick.shared.config import Settings, get_settings
from sidekick.shared.db_timeouts import database_timeout_reason
from sidekick.shared.observability import configure_worker_logging
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.types import Clock, SystemClock
from sidekick.shared.worker_health import WorkerHeartbeat

LOGGER = logging.getLogger("sidekick.memory.worker")
PASS_SECONDS = 60
WIPE_PAGE_SIZE = 100
#: The nightly full pass runs at the first pass after this hour (UTC, as everywhere in memory).
FULL_PASS_HOUR_UTC = 3

WipeOutcome = Literal["completed", "locked", "failed"]


@dataclass(slots=True)
class WipeResult:
    """Counts and fixed categories only. Safe to log."""

    owner_id: UUID
    outcome: WipeOutcome = "completed"
    documents_deleted: int = 0
    rows_removed: int = 0
    markers_kept: int = 0
    second_delete_pending: int = 0
    deferred: int = 0
    error_category: str | None = None


class FullPassSchedule:
    """Decides when the worker runs a full pass: at startup, then once after 03:00 UTC each day.

    Kept in memory: a restart simply starts with a full pass, which is the safe direction.
    """

    def __init__(self) -> None:
        self._last_full: datetime | None = None

    def due(self, now: datetime) -> bool:
        if self._last_full is None:
            return True
        return self._last_full < _latest_boundary(now)

    def mark_done(self, now: datetime) -> None:
        self._last_full = now


def _latest_boundary(now: datetime) -> datetime:
    """The most recent 03:00 UTC at or before `now`."""

    utc = now.astimezone(UTC)
    today = utc.replace(hour=FULL_PASS_HOUR_UTC, minute=0, second=0, microsecond=0)
    return today if utc >= today else today - timedelta(days=1)


def run_pass(
    *,
    settings: Settings,
    store: MemoryStore,
    provider: MemoryProvider,
    clock: Clock | None = None,
    full: bool = False,
) -> list[ReconcileResult]:
    """One reconcile pass for every owner with memory rows or settings."""

    reconciler = MemoryReconciler(store, provider, SyncPolicy.from_settings(settings), clock=clock)
    return reconciler.reconcile_all(full=full)


def pass_succeeded(results: Sequence[ReconcileResult]) -> bool:
    """A pass counts as a success when there was no owner, or at least one owner's pass went
    through without a failure. When every owner's pass failed it does not."""

    return not results or any(result.healthy for result in results)


def mark_owner_dirty(store: MemoryStore, owner_id: UUID, *, clock: Clock | None = None) -> int:
    """Make the owner's settled rows due again, so the next pass resends them.

    `_reconcile_record` sends a row whose status is `pending` with no retry time, even when its
    fingerprint is unchanged. The fingerprint itself cannot be cleared (CHECK constraint), and
    `pipeline_version` is only ever bumped by code. Left alone:

    - excluded rows and removal markers: their documents are already gone, or a second delete is
      still owed, and resetting a marker would forget it;
    - `submitted` rows: their `operation_id` must survive, or a late completion could not be
      matched to the row and a later delete would not wait for it. Rebuild again afterwards.

    A row that was attempted but never confirmed keeps its evidence in `retained_at` (set here when
    missing), because `attempts` is reset: a later delete still knows the bank may hold a document.
    """

    now = (clock or SystemClock()).now()
    with store.begin() as session:
        return store.mark_owner_dirty(session, owner_id, now)


def silence_owner(
    store: MemoryStore,
    owner_id: UUID,
    *,
    clear_domains: bool,
    clock: Clock | None = None,
) -> None:
    """Pause the owner's memory sync and, with `clear_domains`, switch every domain off.

    Updates the owner's settings row or creates it. Callers hold the owner's lock.
    """

    now = (clock or SystemClock()).now()
    with store.begin() as session:
        store.silence_owner(session, owner_id, clear_domains=clear_domains, now=now)


def wipe_owner(
    store: MemoryStore,
    provider: MemoryProvider,
    owner_id: UUID,
    *,
    pause: bool = False,
    clear_domains: bool = False,
    clock: Clock | None = None,
) -> WipeResult:
    """Delete one owner's documents, then their rows. Excluded rows stay as removal markers.

    The owner's advisory lock keeps a running pass out. With `pause` (and `clear_domains`) the
    owner is silenced under that lock before anything is deleted, so no pass sends the records
    again behind the deletion. A `submitted` row is deferred: its operation may still complete. A
    row that may have had a retain accepted without being confirmed keeps a marker for a second
    delete (see `sidekick.memory.application.sync`, "No resurrection"); the running worker finishes
    it. Every step is idempotent (a missing document is not an error), so a failed run can simply
    be repeated.
    """

    result = WipeResult(owner_id=owner_id)
    clock = clock or SystemClock()
    lock = store.owner_lock(owner_id)
    if not lock.acquire():
        result.outcome = "locked"
        return result
    try:
        if pause:
            silence_owner(store, owner_id, clear_domains=clear_domains, clock=clock)
        after: UUID | None = None
        while True:
            lock.assert_alive()
            with store.read() as session:
                page = store.source_state_page(session, owner_id, after=after, limit=WIPE_PAGE_SIZE)
            if not page:
                break
            for state in page:
                _wipe_row(store, provider, owner_id, result, clock, state)
            after = page[-1].row_id
    except MemoryProviderError as error:
        result.outcome = "failed"
        result.error_category = error.category
    except Exception as error:
        # Logged by exception type only; the message may echo record content.
        result.outcome = "failed"
        result.error_category = type(error).__name__
    finally:
        lock.release()
    return result


def _wipe_row(
    store: MemoryStore,
    provider: MemoryProvider,
    owner_id: UUID,
    result: WipeResult,
    clock: Clock,
    state: SourceState,
) -> None:
    now = clock.now()
    hold_until: datetime | None = None
    if state.status == SUBMITTED:
        result.deferred += 1
        return
    if state.removed_marker:
        if state.next_attempt_at is None and state.excluded:
            return  # The document is already gone; the row is only the exclusion marker.
        if state.next_attempt_at is not None and state.next_attempt_at > now:
            result.deferred += 1  # The second delete is not due yet; run the command again.
            return
    else:
        hold_until = removal_hold_until(
            status=state.status,
            attempts=state.attempts,
            operation_id=state.operation_id,
            retained_at=state.retained_at,
            now=now,
        )
    provider.delete_document(owner_id=owner_id, document_id=state.doc_key)
    result.documents_deleted += 1
    with store.begin() as session:
        kept = store.settle_removed_row(
            session,
            row_id=state.row_id,
            doc_key=state.doc_key,
            excluded=state.excluded,
            hold_until=hold_until,
        )
    if not kept:
        result.rows_removed += 1
        return
    result.markers_kept += 1
    if hold_until is not None:
        result.second_delete_pending += 1


def run_wipe(
    *,
    settings: Settings,
    store: MemoryStore,
    owner_id: UUID | None,
    and_pause: bool = False,
) -> int:
    """Wipe one owner (and forget them: paused, every domain off), or every owner with state.

    A wipe of every owner needs `and_pause`, or `SIDEKICK_MEMORY_INGEST_ENABLED=false`, because the
    records still exist and a running worker would send them again. Returns 0 only when
    everything is gone.
    """

    forget = owner_id is not None
    if not forget and not and_pause and settings.memory_ingest_enabled:
        LOGGER.error(
            "memory wipe refused: use --and-pause or set SIDEKICK_MEMORY_INGEST_ENABLED=false"
        )
        return 1
    provider = build_provider(settings)
    owners = [owner_id] if owner_id is not None else _owners_with_state(store)
    exit_code = 0
    for owner in owners:
        result = wipe_owner(
            store,
            provider,
            owner,
            pause=forget or and_pause,
            clear_domains=forget,
        )
        LOGGER.info(
            "memory wipe finished",
            extra={
                "outcome": result.outcome,
                "documents_deleted": result.documents_deleted,
                "rows_removed": result.rows_removed,
                "markers_kept": result.markers_kept,
                "second_delete_pending": result.second_delete_pending,
                "deferred": result.deferred,
                "error_category": result.error_category,
            },
        )
        if result.outcome != "completed" or result.deferred:
            exit_code = 1
        if result.outcome == "failed":
            break  # The provider is likely down for every owner; stop and let a rerun finish.
    return exit_code


def _owners_with_state(store: MemoryStore) -> list[UUID]:
    """Every owner with memory rows or memory settings (a settings-only owner is paused too)."""

    with store.read() as session:
        return sorted(store.owner_ids(session))


async def _guarded(
    task: Callable[[MemoryStore, MemoryProvider], BankCheckResult | SweepResult],
    store: MemoryStore,
    provider: MemoryProvider,
) -> bool:
    """Run a lifecycle task in a thread and log its counts. True when it ran to completion."""

    name = "memory bank check" if task is verify_banks_after_start else "memory orphan sweep"
    try:
        result = await asyncio.to_thread(task, store, provider)
    except Exception as error:
        # Logged by exception type only; the message may echo record content.
        LOGGER.error(
            "memory lifecycle task failed",
            extra={"worker_step": name, "error_type": type(error).__name__},
        )
        return False
    LOGGER.info(name, extra=asdict(result))
    if isinstance(result, BankCheckResult):
        return result.complete
    return result.error_category is None


async def run_worker(
    *,
    once: bool = False,
    rebuild_owner: UUID | None = None,
    wipe: bool = False,
    forget_owner: UUID | None = None,
    and_pause: bool = False,
    clock: Clock | None = None,
) -> int:
    settings = get_settings()
    clock = clock or SystemClock()
    factory = create_session_factory(
        settings.database_url,
        require_unprivileged_role=settings.environment == "production",
        timeouts=settings.database_timeouts,
    )
    store = SqlAlchemyMemoryStore(factory)
    if wipe or forget_owner is not None:
        try:
            return run_wipe(
                settings=settings, store=store, owner_id=forget_owner, and_pause=and_pause
            )
        except ValueError:
            LOGGER.error("memory provider configuration is incomplete")
            return 1
    if rebuild_owner is not None:
        marked = mark_owner_dirty(store, rebuild_owner)
        LOGGER.info(
            "memory rows marked for rebuild",
            extra={"row_count": marked},
        )
        if not once:
            return 0
    heartbeat = WorkerHeartbeat("memory")
    if not settings.memory_enabled:
        LOGGER.info("memory worker disabled; no reconcile passes")
        if once:
            return 0
        while True:
            # Idle like the backup worker, so a restart policy does not spin on a clean exit.
            heartbeat.beat(PASS_SECONDS)
            heartbeat.succeeded()  # nothing to do is a success
            await asyncio.sleep(PASS_SECONDS)

    provider = build_provider(settings)
    schedule = FullPassSchedule()
    bank_check_pending = True
    while True:
        heartbeat.beat(PASS_SECONDS)
        started = clock.now()
        full = schedule.due(started)
        if bank_check_pending:
            # At start, and again every pass until Hindsight has answered for every owner.
            bank_check_pending = not await _guarded(verify_banks_after_start, store, provider)
        try:
            results = await asyncio.to_thread(
                run_pass, settings=settings, store=store, provider=provider, full=full
            )
            if full:
                schedule.mark_done(started)
            LOGGER.info(
                "memory reconcile pass completed",
                extra={"owner_count": len(results), "full": full},
            )
            if pass_succeeded(results):
                heartbeat.succeeded()
            else:
                LOGGER.error("memory reconcile pass failed for every owner")
        except Exception as error:
            # Logged by exception type only; the message may echo record content.
            LOGGER.error(
                "memory reconcile pass failed",
                extra={
                    "error_type": type(error).__name__,
                    "db_timeout": database_timeout_reason(error),
                },
            )
        if full:
            if settings.memory_orphan_sweep_enabled:
                await _guarded(sweep_orphan_banks, store, provider)
            else:
                LOGGER.info("memory_orphan_sweep_disabled")
        if once:
            return 0
        await asyncio.sleep(PASS_SECONDS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Sidekick's derived-memory worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one reconcile pass and exit (with --rebuild-owner: then one pass)",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--rebuild-owner",
        metavar="OWNER_ID",
        type=UUID,
        help="mark one owner's rows dirty so the next pass resends them",
    )
    actions.add_argument(
        "--wipe",
        action="store_true",
        help="delete every memory document of every owner and their rows (needs --confirm)",
    )
    actions.add_argument(
        "--forget-owner",
        metavar="OWNER_ID",
        type=UUID,
        help="delete one owner's memory documents and rows (needs --confirm)",
    )
    parser.add_argument(
        "--and-pause",
        action="store_true",
        help="with --wipe: also pause every owner's memory sync before deleting",
    )
    parser.add_argument(
        "--confirm", action="store_true", help="confirm a destructive --wipe or --forget-owner"
    )
    return parser


def _check_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    destructive = args.wipe or args.forget_owner is not None
    if args.confirm and not destructive:
        parser.error("--confirm only applies to --wipe and --forget-owner")
    if destructive and not args.confirm:
        parser.error("--wipe and --forget-owner delete memory and require --confirm")
    if destructive and args.once:
        parser.error("--once cannot be combined with --wipe or --forget-owner")
    if args.and_pause and not args.wipe:
        parser.error("--and-pause only applies to --wipe (--forget-owner always pauses)")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _check_args(parser, args)
    configure_worker_logging()
    try:
        return run_guarded(
            "sidekick-memory-worker",
            lambda: asyncio.run(
                run_worker(
                    once=args.once,
                    rebuild_owner=args.rebuild_owner,
                    wipe=args.wipe,
                    forget_owner=args.forget_owner,
                    and_pause=args.and_pause,
                )
            ),
        )
    except KeyboardInterrupt:
        # SIGINT is the normal shutdown signal for a local stack. Exit quietly.
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Liveness of the long-running worker processes: a heartbeat file and the command that reads it.

A worker loop calls `WorkerHeartbeat.beat(sleep_seconds)` at the start of every iteration. That is a
promise: "I will beat again within the work budget of one iteration plus the sleep that follows".
The container healthcheck runs `sidekick-worker-health <worker>`
(`python -m sidekick.shared.worker_health`), which fails when the promise has run out, that is when
the loop is stuck (a hung database call, a provider that never answers) while the process itself
still runs and Docker would call it healthy.

The file lives in the temp directory, which is a tmpfs in the read-only worker containers. It holds
four numbers and nothing else: when the loop last made progress, how long it may stay silent, when
the worker started and when an iteration last succeeded. Older writers wrote two or three numbers;
those files are still read, and without the success time nothing is judged on success.
The command answers with one word on stdout and an exit status, like `sidekick.shared.readiness`.

A loop that beats but whose work fails every time (a database that rejects every query, a bug in
the pass) would look alive forever. So the memory, push and automation loops also call
`WorkerHeartbeat.succeeded()` after an iteration that did its work without an error; an iteration
with nothing to do counts as a success. When the last success (or, before the first one, the start
of the worker) is older than `SUCCESS_WINDOW_SECONDS`, the healthcheck answers `failing`. A new
installation is therefore healthy until the window has run out. The backup worker has its own,
stricter signal (below) and is not judged this way.

The backup worker has a second, separate signal. A live heartbeat only shows that the loop runs,
not that backups succeed, so `sidekick-worker-health backup` also checks the time of the newest
backup file in the backup directory (a file stays only when it was written and read back, so that
is the last successful backup). It answers `backup_missing` or `backup_stale` when that time is
absent or older than one backup interval plus a grace period. A worker that started less than
that long ago and has no backup yet is healthy ("waiting for the first backup").
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, NamedTuple

from sidekick.shared.backup_files import latest_backup_time
from sidekick.shared.cli_errors import report_failure

LOGGER = logging.getLogger("sidekick.worker_health")

# Closed vocabulary: the heartbeat file name is built from one of these, never from free text.
WORKERS: Final = ("automation", "backup", "memory", "push")

# What one iteration may take on top of the sleep before the next one, per worker. Only a loop that
# is silent for longer than this is reported as stuck, so a long legitimate pass is not.
WORK_BUDGET_SECONDS: Final = {
    "automation": 120,
    "backup": 1800,
    "memory": 1800,
    "push": 300,
}

# How long a worker may go without one successful iteration before it is `failing`, per worker. Well
# above the poll interval, so a few transient failures do not turn a worker unhealthy, and above the
# longest legitimate pass. The backup worker is absent: its last backup file is the signal.
SUCCESS_WINDOW_SECONDS: Final = {
    "automation": 900,
    "memory": 3600,
    "push": 900,
}

# How much later than one backup interval the newest successful backup may be (a nightly interval
# of 24 h therefore warns after 26 h).
BACKUP_GRACE_SECONDS: Final = 7200


def heartbeat_path(worker: str, directory: Path | None = None) -> Path:
    if worker not in WORKERS:
        raise ValueError(f"unknown worker: {worker}")
    return (directory or Path(tempfile.gettempdir())) / f"sidekick-heartbeat-{worker}"


class WorkerHeartbeat:
    """Writes the heartbeat of one worker loop. Never raises: health must not stop the worker."""

    def __init__(
        self,
        worker: str,
        *,
        directory: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = heartbeat_path(worker, directory)
        self._max_silence_base = WORK_BUDGET_SECONDS[worker]
        self._clock = clock
        self._started_at = clock()
        self._last_success = 0.0  # 0: no iteration has succeeded yet
        self._last_beat: tuple[float, float] | None = None

    def beat(self, sleep_seconds: float = 0) -> None:
        """Record progress; the loop promises to beat again within its work budget plus `sleep`."""

        self._last_beat = (self._clock(), self._max_silence_base + sleep_seconds)
        self._write()

    def succeeded(self) -> None:
        """Record that the iteration did its work without an error (nothing to do counts)."""

        self._last_success = self._clock()
        if self._last_beat is not None:
            self._write()

    def _write(self) -> None:
        if self._last_beat is None:
            return
        beat_at, max_silence = self._last_beat
        temporary = self._path.with_name(self._path.name + ".tmp")
        try:
            temporary.write_text(
                f"{beat_at:.3f} {max_silence:.3f} {self._started_at:.3f} "
                f"{self._last_success:.3f}\n",
                encoding="ascii",
            )
            os.replace(temporary, self._path)
        except OSError as error:
            # The healthcheck reports the missing or stale file; the loop carries on.
            LOGGER.warning(
                "worker heartbeat not written", extra={"error_type": type(error).__name__}
            )


class _Heartbeat(NamedTuple):
    beat_at: float
    max_silence: float
    started_at: float | None  # `None` from a writer that did not record it
    last_success: float | None  # `None` from a writer without the success marker; 0: no success yet


def _read_heartbeat(worker: str, directory: Path | None) -> _Heartbeat | str:
    """The parsed heartbeat, or the failing state as a word."""

    try:
        raw = heartbeat_path(worker, directory).read_text(encoding="ascii")
    except FileNotFoundError:
        return "missing"
    except (OSError, UnicodeDecodeError):
        return "invalid"
    try:
        parts = [float(part) for part in raw.split()]
    except ValueError:
        return "invalid"
    # Two numbers (oldest writers), three (plus the worker's start) or four (plus the last success).
    if len(parts) not in (2, 3, 4) or parts[1] <= 0:
        return "invalid"
    return _Heartbeat(
        parts[0],
        parts[1],
        parts[2] if len(parts) >= 3 else None,
        parts[3] if len(parts) == 4 else None,
    )


def check_worker(
    worker: str, *, directory: Path | None = None, now: Callable[[], float] = time.time
) -> str:
    """`ok`, `missing` (never beat), `invalid` (unreadable content), `stale` (promise run out) or
    `failing` (the loop runs but no iteration has succeeded within the worker's window)."""

    heartbeat = _read_heartbeat(worker, directory)
    if isinstance(heartbeat, str):
        return heartbeat
    current = now()
    if current - heartbeat.beat_at > heartbeat.max_silence:
        return "stale"
    window = SUCCESS_WINDOW_SECONDS.get(worker)
    if window is None or heartbeat.last_success is None:
        return "ok"  # the backup worker, or a file from a writer without the success marker
    # Before the first success the worker's start is the baseline: a new installation is healthy
    # until the window has run out. Without a known start nothing is judged.
    baseline = heartbeat.last_success or heartbeat.started_at
    if baseline is None:
        return "ok"
    return "ok" if current - baseline <= window else "failing"


def check_last_backup(
    directory: Path,
    interval_seconds: float,
    *,
    started_at: float | None = None,
    now: Callable[[], float] = time.time,
) -> str:
    """`ok`, `waiting_first_backup`, `backup_missing` or `backup_stale`.

    A worker on a new installation or volume has no backup file until its first iteration
    succeeds, so `backup_missing` only counts once the worker has run longer than one interval
    plus the grace period (`started_at`); before that it is `waiting_first_backup`, which is
    healthy. A worker whose start time is unknown is judged strictly.
    """

    allowed = interval_seconds + BACKUP_GRACE_SECONDS
    latest = latest_backup_time(directory)
    if latest is None:
        if started_at is not None and now() - started_at <= allowed:
            return "waiting_first_backup"
        return "backup_missing"
    return "ok" if now() - latest.timestamp() <= allowed else "backup_stale"


def _check_backup_worker() -> str:
    """Heartbeat first, then the recency of the last successful backup (when backups are on)."""

    state = check_worker("backup")
    if state != "ok":
        return state
    try:
        from sidekick.shared.config import get_settings

        settings = get_settings()
    except Exception as error:  # a broken configuration must not hide the heartbeat verdict
        LOGGER.warning("backup recency not checked", extra={"error_type": type(error).__name__})
        return state
    if not settings.backup_enabled:
        return state
    heartbeat = _read_heartbeat("backup", None)
    started_at = None if isinstance(heartbeat, str) else heartbeat.started_at
    return check_last_backup(
        settings.backup_directory, settings.backup_interval_seconds, started_at=started_at
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Healthcheck of a Sidekick background worker")
    parser.add_argument("worker", choices=WORKERS, help="the worker to check")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    worker = build_parser().parse_args(argv).worker
    try:
        state = _check_backup_worker() if worker == "backup" else check_worker(worker)
    except Exception as error:  # unhealthy, with one fixed line instead of a traceback
        report_failure("sidekick-worker-health", error)
        state = "check_failed"
    if state == "waiting_first_backup":
        # Healthy: the detail goes to stderr so stdout stays the one-word verdict.
        sys.stderr.write("waiting for the first backup\n")
        state = "ok"
    sys.stdout.write(f"{state}\n")
    sys.exit(0 if state == "ok" else 1)


if __name__ == "__main__":
    main()

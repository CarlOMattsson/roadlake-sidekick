"""The housekeeping around a backup, for ``tools/work.sh`` and ``deploy/selfhost/update.sh``:
the setting for how many are kept, the free-space check before one is written, the time stamp of a new set and the
pruning of the old ones.

Only files whose whole name is a finished backup name (an extended regular expression the caller builds from the
exact form, time stamp included) are ever looked at or removed: a temporary, hidden or half-written file never
matches, and neither does a symlink."""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from .restore import DB_PREFIX, DB_SUFFIX, MEMORY_PREFIX, MEMORY_SUFFIX

MARGIN_DEFAULT = 150
FLOOR_MB_DEFAULT = 64
MIN_MARGIN = 100
STAMP_FORMAT = "%Y%m%d-%H%M%S"

# Outcomes of ``check_space``.
ENOUGH, TOO_LITTLE, UNKNOWN = "enough", "too-little", "unknown"


class SpaceCheck(NamedTuple):
    outcome: str
    needed: int
    free: int


def _is_uint(value: str) -> bool:
    return re.fullmatch(r"[0-9]+", value) is not None


def valid_keep(value: str) -> bool:
    """A whole number of at least 1."""
    return _is_uint(value) and int(value) >= 1


def finished(directory: Path, pattern: re.Pattern[str]) -> list[str]:
    """The regular files (no symlinks) of ``directory`` whose whole name matches, oldest first: the time stamp
    in the name sorts by time, so the order does not depend on file times that a copy or a restore can change."""
    if not directory.is_dir():
        return []
    names = sorted(name for name in os.listdir(directory) if pattern.fullmatch(name))
    return [name for name in names if (directory / name).is_file() and not (directory / name).is_symlink()]


def newest_size(directory: Path, pattern: re.Pattern[str]) -> int:
    """Bytes of the newest finished file, 0 when there is none."""
    names = finished(directory, pattern)
    return (directory / names[-1]).stat().st_size if names else 0


def free_bytes(directory: Path) -> int | None:
    """Bytes available to this user on the file system of ``directory`` (``df -Pk``); ``None`` when unreadable."""
    command = ["df", "-Pk", str(directory)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603 - fixed arguments
    except OSError:
        return None
    lines = done.stdout.splitlines()
    fields = lines[1].split() if len(lines) > 1 else []
    return int(fields[3]) * 1024 if len(fields) > 3 and _is_uint(fields[3]) else None


def check_space(directory: Path, environment: Mapping[str, str], patterns: Sequence[str]) -> SpaceCheck:
    """A new backup is written only when ``directory`` has at least max(sum of the newest finished file of each
    ``patterns`` kind times the margin in percent, the floor in MiB) free. The first backup has no earlier size, so
    only the floor applies. A free size that cannot be read, or a setting that is not a valid number (the margin is
    at least 100), is ``UNKNOWN``: a refusal, never "enough"."""
    margin = environment.get("SIDEKICK_BACKUP_SPACE_MARGIN_PCT") or str(MARGIN_DEFAULT)
    floor_mb = environment.get("SIDEKICK_BACKUP_SPACE_FLOOR_MB") or str(FLOOR_MB_DEFAULT)
    if not (_is_uint(margin) and _is_uint(floor_mb)) or int(margin) < MIN_MARGIN:
        return SpaceCheck(UNKNOWN, 0, 0)
    baseline = sum(newest_size(directory, re.compile(pattern)) for pattern in patterns)
    needed = max(baseline * int(margin) // 100, int(floor_mb) * 1048576)
    free = free_bytes(directory)
    if free is None:
        return SpaceCheck(UNKNOWN, needed, 0)
    return SpaceCheck(ENOUGH if free >= needed else TOO_LITTLE, needed, free)


def next_stamp(
    directory: Path,
    now: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """The time stamp of a new set. A set is never written over an existing one (two backups within one second):
    wait for the next stamp."""
    while True:
        stamp = now().strftime(STAMP_FORMAT)
        if (
            not (directory / f"{DB_PREFIX}{stamp}{DB_SUFFIX}").exists()
            and not (directory / f"{MEMORY_PREFIX}{stamp}{MEMORY_SUFFIX}").exists()
        ):
            return stamp
        sleep(1)


def prune(directory: Path, keep: int, pattern: str, protected: str) -> int:
    """Remove the finished files matching ``pattern`` beyond the newest ``keep`` and return how many went. Never
    removes ``protected`` (the file just written and read back), and does nothing unless that file is there, not
    empty and not a symlink, so a failed backup never prunes older ones."""
    path = directory / protected
    if not protected or not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        return 0
    removed = 0
    for name in reversed(finished(directory, re.compile(pattern))[:-keep]):
        if name != protected:
            try:
                (directory / name).unlink(missing_ok=True)
            except OSError:
                continue
            removed += 1
    return removed

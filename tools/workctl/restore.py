"""The decisions of ``work.sh restore``: which backup sets exist, what a typed reference names, and what undoing a
half-done restore has to do. The shell runs the commands that follow from them."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

TIMESTAMP = re.compile(r"[0-9]{8}-[0-9]{6}")
DB_PREFIX, DB_SUFFIX = "sidekick-", ".sql.enc"
MEMORY_PREFIX, MEMORY_SUFFIX = "hindsight-", ".tar.gz.enc"
KEEP, RENAME_BACK, FAIL = "keep", "rename-back", "fail"


class BackupRef(NamedTuple):
    directory: str
    timestamp: str


def complete_sets(directory: Path, memory: bool) -> list[str]:
    """The time stamps with a database file and, when the memory is on, a non-empty memory archive, oldest first
    (the names sort by time)."""
    found: list[str] = []
    for path in sorted(directory.glob(f"{DB_PREFIX}*{DB_SUFFIX}")):
        stamp = path.name[len(DB_PREFIX) : -len(DB_SUFFIX)]
        archive = directory / f"{MEMORY_PREFIX}{stamp}{MEMORY_SUFFIX}"
        if not memory or (archive.is_file() and archive.stat().st_size > 0):
            found.append(stamp)
    return found


def parse_reference(argument: str, default_directory: str) -> BackupRef | None:
    """A time stamp names a set in ``default_directory``; a path or a file name of either file names the set it
    belongs to, in that file's directory. ``None`` when the result is not a time stamp."""
    if "/" in argument or argument.endswith((DB_SUFFIX, MEMORY_SUFFIX)):
        name = argument.rsplit("/", 1)[-1]
        directory = os.path.dirname(argument) or "."
        for prefix in (DB_PREFIX, MEMORY_PREFIX):
            name = name[len(prefix) :] if name.startswith(prefix) else name
        for suffix in (DB_SUFFIX, MEMORY_SUFFIX):
            name = name[: -len(suffix)] if name.endswith(suffix) else name
    else:
        directory, name = default_directory, argument
    return BackupRef(directory, name) if TIMESTAMP.fullmatch(name) else None


def rollback_action(existing: Sequence[str], old_name: str) -> str:
    """Undoing the database swap, decided by which of the two names Postgres has: the old name present means the
    rename ran (drop the new one, rename back); only ``sidekick`` present means it never ran or was undone already;
    neither is a failure."""
    if old_name in existing:
        return RENAME_BACK
    return KEEP if "sidekick" in existing else FAIL

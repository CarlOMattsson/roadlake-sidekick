"""The state files of ``deploy/selfhost/update.sh``: the update journal, the release pointer, the lock owner and the
name of the snapshot taken before a migration, written and read here.

The formats are the ones installations already have on disk, so they do not change:

* journal (``update-state/journal.log``): one line per phase, ``<UTC time> <STATE> <detail>``; the last line is the
  state the next run recovers from. It is only ever replaced as a whole.
* release pointer (``release.env``): ``SIDEKICK_API_IMAGE=<ref>`` and ``SIDEKICK_API_IMAGE_PREVIOUS=<ref>``, the
  second file compose reads next to ``selfhost.env``.
* lock owner (``update.lock.pid``): the pid of the run that holds the flock, informational only.

Both files are replaced by an atomic rename of a temporary file in the same directory that has been flushed, and
the directory is flushed after the rename: after a power loss the file is the old one or the new one, never a torn
one. A file that is missing reads as nothing; a file that exists but cannot be read is an error, never an empty
answer."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

JOURNAL_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SNAPSHOT_TIME_FORMAT = "%Y%m%dT%H%M%SZ"
SNAPSHOT_PREFIX = "sidekick-pre-"
SNAPSHOT_SUFFIX = ".dump.enc"
# The finished name as an extended regular expression (for ``backupfiles``); a half-written file never matches.
SNAPSHOT_PATTERN = r"sidekick-pre-[0-9]{8}T[0-9]{6}Z\.dump\.enc"

Flush = Callable[[Path], None]
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def flush_path(path: Path) -> None:
    """Make a file, or a directory entry, durable. A directory that cannot be opened for it falls back to flushing
    everything, as ``sync`` does."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        os.sync()
        return
    try:
        os.fsync(descriptor)
    except OSError:
        os.sync()
    finally:
        os.close(descriptor)


def replace_file(target: Path, content: bytes, flush: Flush = flush_path) -> None:
    """Write ``content`` to ``target`` through ``<target>.tmp``, flushed before the rename; the directory is flushed
    after it. A file that is replaced keeps its mode; a new one gets the mode the umask allows."""
    temporary = target.with_name(target.name + ".tmp")
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    with os.fdopen(descriptor, "wb") as handle:
        if target.is_file():
            os.fchmod(handle.fileno(), stat.S_IMODE(target.stat().st_mode))
        handle.write(content)
    flush(temporary)
    os.replace(temporary, target)
    flush(target.parent)


def journal_line(state: str, detail: str, now: datetime) -> str:
    """``<UTC time> <STATE> <detail>``; an empty detail leaves the separating blank, as before."""
    return f"{now.astimezone(timezone.utc).strftime(JOURNAL_TIME_FORMAT)} {state} {detail}\n"


def add_journal_entry(journal: Path, state: str, detail: str, now: Clock = utc_now, flush: Flush = flush_path) -> None:
    """Append one line by rewriting the journal: every earlier line, byte for byte, plus the new one."""
    earlier = journal.read_bytes() if journal.is_file() else b""
    replace_file(journal, earlier + journal_line(state, detail, now()).encode("utf-8"), flush)


def last_journal_state(journal: Path) -> str | None:
    """The state (second field) of the last journal line, empty when that line has none; ``None`` without a journal
    or with an empty one. Fields are separated by blanks and tabs, as awk does."""
    if not journal.is_file():
        return None
    lines = journal.read_bytes().decode("utf-8", errors="replace").split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines:
        return None
    fields = re.findall(r"[^ \t]+", lines[-1])
    return fields[1] if len(fields) > 1 else ""


def release_value(release: Path, key: str) -> str | None:
    """The value of the last ``<key>=<value>`` line of the release pointer; ``None`` without a pointer or a line."""
    if not release.is_file():
        return None
    prefix = f"{key}="
    values = [
        line[len(prefix) :]
        for line in release.read_bytes().decode("utf-8", errors="replace").split("\n")
        if line.startswith(prefix)
    ]
    return values[-1] if values else None


def release_content(image: str, previous: str) -> str:
    return f"SIDEKICK_API_IMAGE={image}\nSIDEKICK_API_IMAGE_PREVIOUS={previous}\n"


def write_release(release: Path, image: str, previous: str, flush: Flush = flush_path) -> None:
    replace_file(release, release_content(image, previous).encode("utf-8"), flush)


def restore_release(release: Path, pinned: str, new_image: str, flush: Flush = flush_path) -> None:
    """After a rollback to the previous image: an installation that had a pinned image gets it back (with the failed
    one as its previous); one that had none (a local build) loses the pointer file, so compose resolves what it did
    before the update."""
    if release.is_file() and pinned:
        write_release(release, pinned, new_image, flush)
        return
    release.unlink(missing_ok=True)
    flush(release.parent)


def lock_owner(pid_file: Path) -> str:
    """The pid recorded by the run that holds the lock, or an empty string when nothing usable is recorded."""
    try:
        recorded = pid_file.read_text(encoding="utf-8", errors="replace").rstrip("\n")
    except OSError:
        return ""
    return recorded if re.fullmatch(r"[0-9]+", recorded) else ""


def snapshot_name(now: datetime) -> str:
    """The finished name of the snapshot taken before a migration; it matches ``SNAPSHOT_PATTERN``."""
    stamp = now.astimezone(timezone.utc).strftime(SNAPSHOT_TIME_FORMAT)
    return f"{SNAPSHOT_PREFIX}{stamp}{SNAPSHOT_SUFFIX}"

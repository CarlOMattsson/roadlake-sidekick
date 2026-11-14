"""The lock of the commands that change the stack, for a flow that is started without ``work.sh``.

``work.sh`` takes the lock itself (``flock`` on its file descriptor 9, or a ``mkdir`` lock where there is no flock) and
tells the flow so with ``SIDEKICK_WORK_LOCK_HELD=1``. A flow started directly (``python3 -m workctl backup``) takes the
same ``.work.lock`` file here, so two changing commands never run at once whichever way they were started.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Callable, Generator
from pathlib import Path

from .stack import Stack

HELD_VARIABLE = "SIDEKICK_WORK_LOCK_HELD"
LOCK_FILE = ".work.lock"
BUSY_EXIT = 1


def _holder(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return handle.readline().strip() or "?"
    except OSError:
        return "?"


@contextlib.contextmanager
def held(stack: Stack, command: str) -> Generator[bool]:
    """Holds the lock for the length of the block and yields True; yields False, after a message, when another
    command has it. Holds nothing and yields True when the caller says it holds the lock already."""
    if stack.environ.get(HELD_VARIABLE) == "1":
        yield True
        return
    path = stack.work / LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stack.errf("busy", _holder(path), path)
            yield False
            return
        os.ftruncate(fd, 0)
        os.write(fd, f"PID {os.getpid()}: {command}\n".encode())
        yield True
    finally:
        os.close(fd)  # the kernel releases the lock with the descriptor


def run_locked(stack: Stack, command: str, flow: Callable[[], int], needed: bool = True) -> int:
    """The exit status of ``flow`` run under the lock; ``BUSY_EXIT`` when another command has it. ``needed`` is False
    for a command that only reads (the dry run of a restore)."""
    if not needed:
        return flow()
    with held(stack, command) as acquired:
        return flow() if acquired else BUSY_EXIT

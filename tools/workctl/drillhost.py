"""The processes, ports and clock the drill depends on, in one place so that a test can replace them.

The real ``Host`` runs a program and returns what it printed. A program that cannot be started answers 127, as a shell
does; nothing here raises for a failed command, the caller decides what a failure means.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from . import drillpolicy

COMMAND_NOT_FOUND = 127


class Done(NamedTuple):
    """The end of one program: its exit status, what it printed on stdout (and on stderr when the two were merged)
    and what it printed on stderr otherwise."""

    rc: int
    out: bytes = b""
    err: bytes = b""


class Host:
    """Runs programs, asks for a free port and keeps time."""

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        stdin: bytes | None = None,
        cwd: Path | None = None,
        merge: bool = False,
    ) -> Done:
        """Run ``argv`` with exactly ``env``. Without ``stdin`` the program reads nothing (never the terminal)."""
        try:
            done = subprocess.run(  # noqa: S603 - the argv is built by the drill, never from outside input
                list(argv),
                env=dict(env),
                cwd=cwd,
                input=stdin,
                stdin=subprocess.DEVNULL if stdin is None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT if merge else subprocess.PIPE,
                check=False,
            )
        except OSError as error:
            return Done(COMMAND_NOT_FOUND, b"", f"{argv[0]}: {error}\n".encode())
        return Done(done.returncode, done.stdout, done.stderr or b"")

    def free_port(self, reserved: Sequence[int], used: Sequence[int]) -> int | None:
        return drillpolicy.pick_port(reserved, used)

    def port_open(self, port: int) -> bool:
        return drillpolicy.listening(port)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def clock(self) -> float:
        return time.monotonic()

"""A stand-in for ``workctl.stack.Stack`` that runs nothing: the flows' decisions are tested without
docker.

Every call is recorded as one line (``compose <arguments>``, ``docker <arguments>``, a pipeline
with its stages joined by `` | ``) and answered by ``answer(call)``: a write returns whether it
succeeded, a read the text it printed (``None`` for a failure), a pipeline whether it succeeded or
the bytes the last stage printed."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, Any

from tools.workctl import backupflow
from tools.workctl.stack import Stack, Stage

DUMP = b"-- PostgreSQL database dump complete\n"
ARCHIVE_LISTING = b"./PG_VERSION\n"
STOP_WRITERS = "compose stop api memory-worker automation-worker"
START_WRITERS = "compose up -d --wait --wait-timeout 300 api memory-worker automation-worker"
START_HINDSIGHT = "compose up -d --wait --wait-timeout 300 --no-deps hindsight"
STOP_HINDSIGHT = "compose stop hindsight"


class Healthy:
    """Answers the calls of a backup the way a healthy stack does.

    ``fail`` makes every call that contains one of its parts fail; ``running`` are the writers that
    are up until they are stopped."""

    def __init__(
        self, fail: tuple[str, ...] = (), running: tuple[str, ...] = backupflow.WRITERS
    ) -> None:
        self.fail = fail
        self.running = set(running)

    def __call__(self, call: str) -> object:
        if any(part in call for part in self.fail):
            return False
        if call.startswith("live "):
            return ["cid"] if call.removeprefix("live ") in self.running else []
        if call.startswith("compose stop "):
            self.running -= set(call.split()[2:])
            return True
        if "ps -q postgres" in call:
            return "cid\n"
        if "volume ls" in call:
            return "p_hindsight_pg0\n"
        if "config --images" in call:
            return "ghcr.io/vectorize-io/hindsight@sha256:0000\n"
        if "pg_dump" in call:
            return b"ciphertext"
        if "--network none" in call:
            return b"ciphertext"
        if call == "crypto decrypt":
            return DUMP
        if call == "crypto decrypt | tar -tz":
            return ARCHIVE_LISTING
        return True


def _failed(reply: Any) -> bool:
    return reply is False or reply is None


class FakeStack(Stack):
    def __init__(
        self,
        root: Path,
        answer: Callable[[str], Any] | None = None,
        *,
        memory: bool = True,
        lang: str = "en",
    ) -> None:
        super().__init__(root, project="p", lang=lang, memory=memory, environ={})
        for directory in (self.selfhost, self.work, self.secrets, self.gen, self.backups):
            directory.mkdir(parents=True, exist_ok=True)
        self.calls: list[str] = []
        self.synced: list[Path] = []
        self.answer: Callable[[str], Any] = answer or (lambda _call: True)

    def _ask(self, call: str) -> Any:
        self.calls.append(call)
        reply = self.answer(call)
        self.signals.check()
        return reply

    def compose_argv(self, args: Sequence[str]) -> list[str]:
        return ["compose", *args]

    def compose(self, *args: str) -> bool:
        return not _failed(self._ask(" ".join(["compose", *args])))

    def compose_stdin(self, stdin: IO[bytes], *args: str) -> bool:
        return not _failed(self._ask(" ".join(["compose", *args])))

    def compose_into(self, out: IO[bytes], stdin: IO[bytes], *args: str) -> bool:
        reply = self._ask(" ".join(["compose", *args]))
        if isinstance(reply, bytes):
            out.write(reply)
        return not _failed(reply)

    def compose_read(self, *args: str, quiet: bool = False) -> str | None:
        reply = self._ask(" ".join(["compose", *args]))
        return None if _failed(reply) else (reply if isinstance(reply, str) else "")

    def docker(self, *args: str) -> bool:
        return not _failed(self._ask(" ".join(["docker", *args])))

    def docker_read(self, *args: str, quiet: bool = False) -> str | None:
        reply = self._ask(" ".join(["docker", *args]))
        return None if _failed(reply) else (reply if isinstance(reply, str) else "")

    def program(self, argv: Sequence[str]) -> int:
        reply = self._ask(" ".join(["run", *argv]))
        return (
            reply if isinstance(reply, int) and not isinstance(reply, bool) else int(_failed(reply))
        )

    def git_read(self, *args: str) -> str | None:
        reply = self._ask(" ".join(["git", *args]))
        return None if _failed(reply) else (reply if isinstance(reply, str) else "")

    def live_containers(self, service: str) -> list[str] | None:
        """``live <service>`` is answered with the live container ids, or ``None`` when unknown."""
        reply = self._ask(f"live {service}")
        if reply is None:
            return None
        return reply if isinstance(reply, list) else []

    def crypto(self, mode: str) -> Stage | None:
        return Stage(["crypto", mode], {})

    def pipeline(
        self,
        stages: Sequence[Stage],
        *,
        stdin: IO[bytes] | None = None,
        stdout: IO[bytes] | None = None,
        scan: Callable[[bytes], None] | None = None,
    ) -> bool:
        reply = self._ask(" | ".join(" ".join(stage.argv) for stage in stages))
        if isinstance(reply, bytes):
            if stdout is not None:
                stdout.write(reply)
            if scan is not None:
                for line in reply.splitlines(keepends=True):
                    scan(line)
        return not _failed(reply)

    def fsync(self, path: Path) -> None:
        self.synced.append(path)

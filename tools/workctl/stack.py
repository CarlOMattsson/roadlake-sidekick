"""The compose project of the package and the processes around it: where its files are, the docker commands, their
log, the encryption of the backups and the signals a command that changes the stack has to survive.

The flows (``backupflow``, ``updateflow``, ``restoreflow``) decide what happens in which order; this module runs the
processes. Tests of the flows replace it with a stand-in that has the same methods.

A signal (interrupt, terminate, hang-up) is recorded when it arrives and acted on after the command that is running
has ended, as a shell trap does: a docker call is never cut off half way, and the flow's cleanup runs.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Generator, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from types import FrameType, ModuleType
from typing import IO, NamedTuple

from . import messages, secretfiles

# The exit status of a command ended by a signal: 128 + the signal number, as a shell reports it.
SIGNAL_EXIT = {signal.SIGINT: 130, signal.SIGTERM: 143, signal.SIGHUP: 129}
# The self-hosted file demands a domain for its Caddy service (profile vps, never used here), even to parse.
PLACEHOLDER_DOMAIN = "work.invalid"
CRYPTO_SCRIPT = "snapshot_crypto.py"
KEY_VARIABLE = "SIDEKICK_BACKUP_ENCRYPTION_KEY"
COMMAND_NOT_FOUND = 127
HINDSIGHT_IMAGE = "vectorize-io/hindsight"


class Stop(Exception):
    """Not an error: the command ends with this exit status, like ``exit N`` of a shell; the cleanup of the flow
    still runs."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class Stage(NamedTuple):
    """One process of a pipeline and the environment it gets."""

    argv: list[str]
    env: Mapping[str, str]


class Signals:
    """Records an interrupt, a terminate and a hang-up (unless the caller ignores them) until ``check`` ends the
    command with the shell's status. ``defer`` is for the cleanup of a flow: a signal that arrives from then on is
    still recorded, but ``check`` no longer ends the command, so the cleanup runs to its end; the flow then asks
    ``take`` for the status the signal asks for. ``release`` puts the previous handlers back and forgets what was
    recorded."""

    def __init__(self) -> None:
        self.pending = 0
        self.deferred = False
        self.raising = False
        self._previous: dict[int, object] = {}

    def record(self, number: int, _frame: FrameType | None = None) -> None:
        """The handler. While ``interruptible`` is on (the command waits for a person to answer) it ends the wait at
        once; otherwise it only notes the signal."""
        code = SIGNAL_EXIT[signal.Signals(number)]
        self.pending = self.pending or code
        if self.raising and not self.deferred:
            self.pending = 0
            raise Stop(code)

    def catch(self) -> None:
        for number in SIGNAL_EXIT:
            previous = signal.getsignal(number)
            if previous != signal.SIG_IGN and number not in self._previous:
                self._previous[number] = previous
                signal.signal(number, self.record)

    def release(self) -> None:
        for number, previous in self._previous.items():
            signal.signal(number, previous)  # type: ignore[arg-type]
        self._previous = {}
        self.pending = 0
        self.deferred = False
        self.raising = False

    def defer(self) -> None:
        self.deferred = True

    def take(self) -> int:
        """The status a signal that arrived during the cleanup asks for, or 0; forgotten once taken."""
        code, self.pending = self.pending, 0
        return code

    def settle(self, code: int) -> int:
        """The exit status of a flow after its cleanup: the status of the signal that ended it if there was one, else
        that of a signal that came during the cleanup, else ``code``."""
        late = self.take()
        return code if code in SIGNAL_EXIT.values() else late or code

    def check(self) -> None:
        if self.pending and not self.deferred:
            raise Stop(self.take())

    @contextlib.contextmanager
    def interruptible(self) -> Generator[None]:
        """A wait for a person (a question on the terminal): a signal ends it at once with its status instead of
        being acted on after the answer. A signal that came earlier ends it before it begins."""
        self.check()
        self.raising = True
        try:
            yield
        finally:
            self.raising = False


class Stack:
    """The compose project ``sidekick-work`` of one checkout."""

    def __init__(
        self,
        repo: Path,
        *,
        project: str,
        lang: str,
        memory: bool,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.repo = repo
        self.lang = lang
        self.memory = memory
        self.project = project
        self.environ = dict(os.environ if environ is None else environ)
        self.selfhost = repo / "deploy" / "selfhost"
        self.work = repo / "deploy" / "work"
        self.work_env = self.work / "work.env"
        self.secrets = self.work / "secrets"
        self.gen = self.work / "generated"
        self.backups = self.work / "backups"
        self.log = self.work / "work.log"
        self.backup_key_file = Path(self.environ.get("SIDEKICK_WORK_BACKUP_KEY_FILE") or self.secrets / "backup.key")
        self.signals = Signals()
        self._policy_loaded: list[ModuleType | None] = []

    # -- what the user is told ------------------------------------------------------------------------------

    def say(self, key: str) -> None:
        print(messages.text(self.lang, key), flush=True)

    def sayf(self, key: str, *values: object) -> None:
        print(messages.render(self.lang, key, *values), flush=True)

    def errf(self, key: str, *values: object) -> None:
        sys.stdout.flush()
        print(messages.render(self.lang, key, *values), file=sys.stderr, flush=True)

    def mark(self, text: str) -> None:
        """A line in the log that says when a command began."""
        self.log_line(f"=== {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')} {text} ===")

    def log_line(self, text: str) -> None:
        with self.log.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    def log_after(self, lines: int) -> str:
        """The log from line ``lines`` + 1 on: what this run wrote."""
        try:
            data = self.log.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return "".join(data.splitlines(keepends=True)[lines:])

    def tail_log(self, lines: int = 20) -> None:
        """The last lines of the log on stderr, shown when a step failed."""
        with contextlib.suppress(OSError):
            data = self.log.read_bytes().splitlines(keepends=True)[-lines:]
            sys.stderr.flush()
            sys.stderr.buffer.write(b"".join(data))
            sys.stderr.flush()

    # -- docker ---------------------------------------------------------------------------------------------

    def compose_argv(self, args: Sequence[str]) -> list[str]:
        argv = [
            "docker",
            "compose",
            "-p",
            self.project,
            "--project-directory",
            str(self.selfhost),
            "-f",
            str(self.selfhost / "compose.yaml"),
            "-f",
            str(self.work / "compose.yaml"),
        ]
        allow = self.gen / "allow.compose.yaml"
        if allow.is_file():
            argv += ["-f", str(allow)]
        # The memory profile (Hindsight, memory worker) only when memory is on.
        if self.memory:
            argv += ["--profile", "memory"]
        return [*argv, "--env-file", str(self.work_env), *args]

    def compose_env(self) -> dict[str, str]:
        return {**self.environ, "SELFHOST_DOMAIN": PLACEHOLDER_DOMAIN}

    def _run(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        stdout: int | IO[bytes] | None,
        stderr: int | IO[bytes] | None,
        stdin: int | IO[bytes] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            done = subprocess.run(argv, env=dict(env), stdin=stdin, stdout=stdout, stderr=stderr, check=False)  # noqa: S603
        except OSError:
            done = subprocess.CompletedProcess(list(argv), COMMAND_NOT_FOUND, b"", b"")
        self.signals.check()
        return done

    def _to_log(self, argv: Sequence[str], env: Mapping[str, str], stdin: int | IO[bytes] | None = None) -> bool:
        with self.log.open("ab") as log:
            return self._run(argv, env, log, subprocess.STDOUT, stdin).returncode == 0

    def _read(self, argv: Sequence[str], env: Mapping[str, str], quiet: bool) -> str | None:
        with self.log.open("ab") as log:
            done = self._run(argv, env, subprocess.PIPE, subprocess.DEVNULL if quiet else log)
        return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None

    def compose(self, *args: str) -> bool:
        """Run compose with its output appended to the log; True when it succeeded."""
        return self._to_log(self.compose_argv(args), self.compose_env())

    def compose_stdin(self, stdin: IO[bytes], *args: str) -> bool:
        """Compose with its input from ``stdin`` and its output appended to the log."""
        return self._to_log(self.compose_argv(args), self.compose_env(), stdin)

    def compose_into(self, out: IO[bytes], stdin: IO[bytes], *args: str) -> bool:
        """Compose with its output written to ``out`` and its errors to the log."""
        with self.log.open("ab") as log:
            return self._run(self.compose_argv(args), self.compose_env(), out, log, stdin).returncode == 0

    def compose_read(self, *args: str, quiet: bool = False) -> str | None:
        """Compose's output (its errors go to the log, or nowhere when ``quiet``); None when it failed."""
        return self._read(self.compose_argv(args), self.compose_env(), quiet)

    def docker(self, *args: str) -> bool:
        return self._to_log(["docker", *args], self.environ)

    def docker_read(self, *args: str, quiet: bool = False) -> str | None:
        return self._read(["docker", *args], self.environ, quiet)

    def program(self, argv: Sequence[str]) -> int:
        """Run a program of the host with its output appended to the log; its exit status."""
        with self.log.open("ab") as log:
            return self._run(argv, self.environ, log, subprocess.STDOUT).returncode

    def git_read(self, *args: str) -> str | None:
        """What git prints for the checkout, without a trailing newline; None when it failed."""
        out = self._read(["git", "-C", str(self.repo), *args], self.environ, quiet=True)
        return None if out is None else out.rstrip("\n")

    def container_id(self, service: str) -> str:
        return (self.compose_read("ps", "-q", service, quiet=True) or "").rstrip("\n")

    def _policy(self) -> ModuleType | None:
        """The decision about a container's state is the self-hosted updater's, one copy
        (deploy/selfhost/update_policy.py)."""
        if not self._policy_loaded:
            self._policy_loaded.append(self._load_policy())
        return self._policy_loaded[0]

    def _load_policy(self) -> ModuleType | None:
        try:
            spec = importlib.util.spec_from_file_location("update_policy", self.selfhost / "update_policy.py")
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except (OSError, ImportError, SyntaxError):
            return None
        return module

    def live_containers(self, service: str) -> list[str] | None:
        """Ids of the containers of ``service`` that are, or may become, active. Every status counts, not only
        "running": a service in a restart loop is "restarting" between two attempts and Docker starts it again; a
        paused one is still alive; a created one starts by itself when it has a restart policy. None when compose
        or docker cannot tell (the caller fails closed). Same rule as live_containers() in deploy/selfhost/update.sh."""
        listed = self.compose_read("ps", "-a", "-q", service)
        if listed is None:
            return None
        active: list[str] = []
        for cid in listed.split():
            line = self.docker_read("inspect", "-f", "{{.State.Status}} {{.HostConfig.RestartPolicy.Name}}", cid)
            policy = self._policy()
            # A crash or no answer is never "not active".
            if line is None or policy is None:
                return None
            if policy.container_active(line.rstrip("\n")):
                active.append(cid)
        return active

    def hindsight_volume(self) -> str:
        """The volume compose created for hindsight_pg0 in this project, or nothing."""
        listed = self.docker_read(
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={self.project}",
            "--filter",
            "label=com.docker.compose.volume=hindsight_pg0",
            quiet=True,
        )
        return (listed or "").splitlines()[0] if listed else ""

    def hindsight_image(self) -> str:
        """The pinned Hindsight image of this stack (its tar and sh are used offline on the volume), or nothing."""
        images = (self.compose_read("config", "--images") or "").splitlines()
        return next((line for line in images if HINDSIGHT_IMAGE in line), "")

    def pg_admin(self, *args: str) -> list[str]:
        """Compose arguments that run psql as the superuser inside the postgres container, stopping at the first
        error."""
        return ["exec", "-T", "postgres", "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-q", *args]

    def db_scalar(self, sql: str) -> str | None:
        """One value from the database, whitespace removed. None (never "empty") when it cannot be asked."""
        out = self.compose_read(*self.pg_admin("-d", "sidekick", "-tAc", sql))
        return None if out is None else "".join(out.split())

    # -- pipelines and the encryption -----------------------------------------------------------------------

    def pipeline(
        self,
        stages: Sequence[Stage],
        *,
        stdin: IO[bytes] | None = None,
        stdout: IO[bytes] | None = None,
        scan: Callable[[bytes], None] | None = None,
    ) -> bool:
        """``a | b | c``: every stage's errors go to the log; the output of the last goes to ``stdout`` (a file),
        else line by line to ``scan``. True only when every stage succeeded (the shell's pipefail)."""
        with self.log.open("ab") as log:
            processes: list[subprocess.Popen[bytes] | None] = []
            upstream: IO[bytes] | None = None
            for index, stage in enumerate(stages):
                last = index == len(stages) - 1
                source = stdin if index == 0 else (upstream or subprocess.DEVNULL)
                sink = (stdout if stdout is not None else subprocess.PIPE) if last else subprocess.PIPE
                try:
                    process = subprocess.Popen(stage.argv, env=dict(stage.env), stdin=source, stdout=sink, stderr=log)  # noqa: S603
                except OSError:
                    process = None
                processes.append(process)
                if upstream is not None:
                    upstream.close()
                upstream = process.stdout if process is not None else None
            final = processes[-1]
            if final is not None and stdout is None and final.stdout is not None:
                for line in final.stdout:
                    if scan is not None:
                        scan(line)
                final.stdout.close()
            codes = [COMMAND_NOT_FOUND if process is None else process.wait() for process in processes]
        self.signals.check()
        return all(code == 0 for code in codes)

    def crypto(self, mode: str) -> Stage | None:
        """stdin to stdout through the api image: ``encrypt`` or ``decrypt`` (the code is
        deploy/selfhost/snapshot_crypto.py, run in a one-off container from the image that is already here). The
        key is read into the environment of this one process, never onto a command line. None without a usable key
        file: a backup or a check then fails, never passes."""
        try:
            key = "".join(self.backup_key_file.read_bytes().decode("utf-8", errors="replace").split())
            script = (self.selfhost / CRYPTO_SCRIPT).read_text(encoding="utf-8").rstrip("\n")
        except OSError:
            return None
        if not key:
            return None
        argv = self.compose_argv(["run", "--rm", "-T", "--no-deps", "-e", KEY_VARIABLE, "api"])
        return Stage([*argv, "python", "-I", "-c", script, mode], {**self.compose_env(), KEY_VARIABLE: key})

    def fsync(self, path: Path) -> None:
        """Flush one file or directory entry; where that is not possible, everything (as ``sync`` does)."""
        try:
            secretfiles.fsync_path(path)
        except OSError:
            os.sync()

    @contextlib.contextmanager
    def caught_signals(self) -> Generator[None]:
        self.signals.catch()
        try:
            yield
        finally:
            self.signals.release()

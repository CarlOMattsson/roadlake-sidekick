"""What the steps of the drill are made of: the state they share, a step's output and the programs it runs, the
checks that fail a step and the small docker helpers both scenarios use (the Hindsight volume, a marker file, the
deploy files copied into a scenario's own directory).

A step is a function of one ``Step``. It fails by raising ``StepFailed`` (a failed program or a failed check), as the
steps of a shell script fail on the first command that does. Its output, a failed program's included, goes to the
drill log.
"""

from __future__ import annotations

import base64
import fnmatch
import io
import os
import secrets
import shutil
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .drillhost import Done, Host

CARRIER_PROJECT = "label=com.docker.compose.project="
MARKER_FILE = "drill-marker.txt"
SNAPSHOT_FORMAT = "SIDEKICK-SNAPSHOT-1"
# The deploy files a scenario needs; the env files and secrets of the repository (a developer's own) are left out.
LEFT_OUT = ("*.env", "*secrets", "update-state", "Caddyfile", "*.partial")


class StepFailed(Exception):
    """A step failed. ``code`` is the exit status the log reports (that of the program that failed, else 1)."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Run:
    """What the scenarios of one run share. ``kv`` carries values from one step to the next (the steps used to run in
    separate shells); the images are replaced by the built ones with ``--local-images``."""

    repo: Path
    tmp: Path
    host: Host
    env: dict[str, str]
    dry: bool
    from_image: str
    to_image: str
    identity: str
    allow_same_schema: bool
    kv: dict[str, str] = field(default_factory=lambda: {})


class Step:
    """One step's output and the programs it runs (with the environment of the run)."""

    def __init__(self, shared: Run) -> None:
        self.shared = shared
        self.output = bytearray()

    def note(self, text: str) -> None:
        self.output += (text + "\n").encode()

    def call(
        self,
        argv: Sequence[str],
        *,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        merge: bool = False,
    ) -> Done:
        """Run a program; the step's output gets what it printed on stderr (everything when ``merge``). Whether the
        status matters is the caller's."""
        done = self.shared.host.run(argv, env={**self.shared.env, **(env or {})}, stdin=stdin, cwd=cwd, merge=merge)
        self.output += done.err
        if merge:
            self.output += done.out
        return done

    def sh(
        self,
        argv: Sequence[str],
        *,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        """Run a program whose output belongs in the log; a failure fails the step."""
        _need(self.call(argv, stdin=stdin, env=env, cwd=cwd, merge=True), argv)

    def read_bytes(
        self, argv: Sequence[str], *, stdin: bytes | None = None, env: Mapping[str, str] | None = None
    ) -> bytes:
        """What a program prints on stdout; a failure fails the step."""
        done = self.call(argv, stdin=stdin, env=env)
        _need(done, argv)
        return done.out

    def read(self, argv: Sequence[str], *, stdin: bytes | None = None, env: Mapping[str, str] | None = None) -> str:
        """The text a program prints, without its trailing newlines (as a command substitution gives it)."""
        return self.read_bytes(argv, stdin=stdin, env=env).decode("utf-8", errors="replace").rstrip("\n")

    def succeeds(self, argv: Sequence[str]) -> bool:
        """Whether a program succeeds; its output is thrown away."""
        done = self.shared.host.run(argv, env=self.shared.env, merge=True)
        return done.rc == 0


def _need(done: Done, argv: Sequence[str]) -> None:
    if done.rc != 0:
        raise StepFailed(f"{' '.join(argv[:2])} exited {done.rc}", done.rc)


def expect_eq(label: str, actual: object, expected: object) -> None:
    if str(actual) != str(expected):
        raise StepFailed(f"{label}: expected '{expected}', got '{actual}'")


def first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def last_line(text: str) -> str:
    return text.splitlines()[-1] if text else ""


def count_lines(text: str) -> int:
    return len(text.splitlines())


def count_in_archive(archive: bytes, name: str) -> int:
    """How many entries of a gzip tar archive have ``name`` in their name."""
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            return sum(1 for entry in tar.getnames() if name in entry)
    except (tarfile.TarError, OSError, EOFError) as error:
        raise StepFailed(f"not a gzip tar archive: {error}") from error


def check_backup_file(path: Path, marker: str, what: str) -> None:
    """A backup file exists, has the snapshot format and does not hold the marker in clear."""
    data = path.read_bytes() if path.is_file() else b""
    if not data:
        raise StepFailed(f"missing or empty {path}")
    expect_eq("backup format", data.split(b"\n", 1)[0].decode("utf-8", errors="replace"), SNAPSHOT_FORMAT)
    if marker.encode() in data:
        raise StepFailed(f"{what} holds the marker in clear")


# -- random values -------------------------------------------------------------------------------------------------


def rand_secret(size: int = 48) -> str:
    return secrets.token_urlsafe(size)


def rand_hex() -> str:
    return secrets.token_hex(32)


def rand_hex8() -> str:
    return os.urandom(4).hex()


def fernet_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


# -- the docker side of a scenario ---------------------------------------------------------------------------------


def carrier_image(step: Step, project: str, service: str) -> str:
    """The container image of a service of a compose project (a carrier with tar, sh and cat for volume files)."""
    listed = step.read(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"{CARRIER_PROJECT}{project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.Image}}",
        ]
    )
    return first_line(listed)


def hindsight_volume(step: Step, project: str) -> str:
    listed = step.read(
        [
            "docker",
            "volume",
            "ls",
            "-q",
            "--filter",
            f"{CARRIER_PROJECT}{project}",
            "--filter",
            "label=com.docker.compose.volume=hindsight_pg0",
        ]
    )
    return first_line(listed)


def project_volumes(step: Step, project: str) -> int:
    """How many volumes of the compose project exist."""
    return count_lines(step.read(["docker", "volume", "ls", "-q", "--filter", f"{CARRIER_PROJECT}{project}"]))


def _hindsight_carrier(step: Step, project: str, service: str) -> tuple[str, str]:
    volume = hindsight_volume(step, project)
    image = carrier_image(step, project, service)
    if not volume or not image:
        raise StepFailed("no Hindsight volume or carrier image")
    return volume, image


def hs_write(step: Step, project: str, service: str, token: str) -> None:
    volume, image = _hindsight_carrier(step, project, service)
    step.sh(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{volume}:/dst",
            "--entrypoint",
            "sh",
            image,
            "-c",
            f"printf '%s' '{token}' > /dst/{MARKER_FILE}",
        ]
    )


def hs_read(step: Step, project: str, service: str) -> str:
    volume, image = _hindsight_carrier(step, project, service)
    return step.read(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{volume}:/src:ro",
            "--entrypoint",
            "cat",
            image,
            f"/src/{MARKER_FILE}",
        ]
    )


def hs_present(step: Step, project: str, service: str) -> bool:
    """Whether the marker file can be read from the Hindsight volume."""
    try:
        hs_read(step, project, service)
    except StepFailed:
        return False
    return True


def marker_sql(token: str) -> str:
    table = "CREATE TABLE public.drill_marker (token text PRIMARY KEY)"
    return f"{table}; INSERT INTO public.drill_marker VALUES ('{token}');"  # noqa: S608 - a token the drill made


# -- files ---------------------------------------------------------------------------------------------------------


def copy_selfhost_files(source: Path, destination: Path) -> None:
    """The deploy files of ``deploy/selfhost`` a scenario needs, with a Caddyfile made from its example."""
    destination.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source.iterdir()):
        if any(fnmatch.fnmatchcase(entry.name, pattern) for pattern in LEFT_OUT):
            continue
        target = destination / entry.name
        if entry.is_dir() and not entry.is_symlink():
            shutil.copytree(entry, target, symlinks=True)
        else:
            shutil.copy2(entry, target, follow_symlinks=False)
    shutil.copy(destination / "Caddyfile.example", destination / "Caddyfile")


def copy_workctl(repo: Path, destination: Path) -> None:
    """The package ``tools/workctl`` next to the script that calls it, without its bytecode."""
    shutil.copytree(repo / "tools" / "workctl", destination, ignore=shutil.ignore_patterns("__pycache__"))

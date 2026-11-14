"""The files compose mounts that depend on settings, written for a checkout: the gateway configuration with the
allowed addresses, and the build information file the interface reads. ``generated`` holds what goes into them."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import generated
from .stack import Stack

UNKNOWN = "unknown"
BUILD_INFO = "build-info.json"


def _git(repo: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)  # noqa: S603, S607
    except OSError:
        return UNKNOWN
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else UNKNOWN


def write_build_info(stack: Stack, previous: str = "", updated: bool = False) -> None:
    """build-info.json: which commit this checkout is on, when the image was built and when it was last updated."""
    stack.gen.mkdir(parents=True, exist_ok=True)
    path = stack.gen / BUILD_INFO
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = _git(stack.repo, "rev-parse", "HEAD")
    date = _git(stack.repo, "log", "-1", "--format=%cI")
    generated.write_build_info(path, commit, date, now, previous, updated)
    path.chmod(0o644)


def ensure_build_info(stack: Stack) -> None:
    """The file must exist before compose mounts it (a missing file would become a directory), and from the first
    day on, so the update reminder has a date to count from."""
    stack.gen.mkdir(parents=True, exist_ok=True)
    stack.gen.chmod(0o755)
    if not (stack.gen / BUILD_INFO).is_file():
        write_build_info(stack)


def render_generated(stack: Stack, allow: list[tuple[str, int]]) -> None:
    """The gateway configuration with one passthrough listener per allowed address, the matching network aliases
    and the build information file."""
    # The shared selfhost entrypoint also copies this file with mode 755 before dropping privileges.
    (stack.selfhost / "postgres-init.sh").chmod(0o755)
    stack.gen.mkdir(parents=True, exist_ok=True)
    # The gateway container runs as an unprivileged user, so what it mounts must be world-readable.
    stack.gen.chmod(0o755)
    generated.write_gateway_files(stack.work / "gateway.haproxy.cfg", stack.gen, allow)
    (stack.gen / "gateway.haproxy.cfg").chmod(0o644)
    if (stack.gen / "allow.compose.yaml").is_file():
        (stack.gen / "allow.compose.yaml").chmod(0o644)
    ensure_build_info(stack)

"""Shared test helpers moved out of `tests/mcp/test_stdio.py`."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import sidekick
from sidekick.shared.rooms import ROOMS
from tests.db import DATABASE_URL
from tests.db_guard import child_process_environment, validate_child_env_file

SOURCE_ROOT = str(Path(sidekick.__file__).resolve().parents[1])


OWNER_VARIABLE = "SIDEKICK_MCP_STDIO_OWNER_ID"


ALL_ROOMS = ",".join(ROOMS)


def _environment(owner_id: object | None, rooms: str = ALL_ROOMS) -> dict[str, str]:
    """A clean child environment: only what the settings need, nothing inherited from SIDEKICK_*."""

    environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": SOURCE_ROOT,
        "PYTHONDONTWRITEBYTECODE": "1",
        "SIDEKICK_ENVIRONMENT": "test",
        "SIDEKICK_DATABASE_URL": DATABASE_URL,
        "SIDEKICK_CURSOR_SIGNING_SECRET": "session-secret-for-tests-only-123456",
        "SIDEKICK_TOKEN_PEPPER": "token-pepper-for-tests-only-12345678",
        "SIDEKICK_ENABLED_ROOMS": rooms,
    }
    if owner_id is not None:
        environment[OWNER_VARIABLE] = str(owner_id)
    # The child has no in-process connection guard: no PG* variables and a validated database URL.
    return child_process_environment(environment)


def _run(environment: Mapping[str, str], cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the module to its end; it must stop on its own because it refuses to start."""

    # The child has no in-process connection guard, so its database target is checked here, from
    # the three places it can come from: its environment, the `--env-file` and a `.env` in its cwd.
    child_environment = child_process_environment(environment)
    file_url = None
    if "--env-file" in args:
        file_url = validate_child_env_file(Path(args[args.index("--env-file") + 1]))
    if (cwd / ".env").exists():
        raise RuntimeError("Refusing to start a child next to a .env file")
    if file_url is None and not child_environment.get("SIDEKICK_DATABASE_URL"):
        raise RuntimeError("Refusing to start a child without an explicit database URL")

    return subprocess.run(
        [sys.executable, "-m", "sidekick.mcp.stdio", *args],
        env=child_environment,
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )

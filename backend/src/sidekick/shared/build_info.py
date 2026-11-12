"""The date of the code that is running, for the update reminder (`SIDEKICK_UPDATE_REMINDER_DAYS`).

A self-hosted instance may sit on a machine with no network, so the app cannot ask anyone whether
a newer version exists. It reminds from the age of the running code instead: the commit date and
the short hash, resolved once when the process first needs them, from (in this order)

1. the file named by `SIDEKICK_BUILD_INFO_FILE` (`tools/work.sh update` writes it and mounts it into
   the container): JSON with `commit` and `updated_at`, or `built_at` when there is no `updated_at`,
2. `SIDEKICK_BUILD_COMMIT` and `SIDEKICK_BUILD_DATE`, which a Docker build bakes into the image (the
   image holds no git history),
3. `git log -1` in the repository the code is read from, when it is a checkout with git on the path,
4. nothing: the age is unknown and there is no reminder.

None of it can stop the start: every failure ends in "unknown".
"""

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Final, cast

# backend/src/sidekick/shared/build_info.py -> the repository root.
REPO_ROOT: Final = Path(__file__).resolve().parents[4]
SHORT_HASH_LENGTH: Final = 7
_GIT_TIMEOUT_SECONDS: Final = 3
_HASH = re.compile(r"[0-9a-f]{4,40}")


@dataclass(frozen=True)
class BuildInfo:
    """The running code: its short commit hash and when that commit was made (timezone aware)."""

    commit: str
    committed_at: datetime


@dataclass(frozen=True)
class UpdateReminder:
    """What the app document declares: the running build and the age in days at which to remind."""

    build: BuildInfo
    after_days: int


def parse_build_info(commit: str, committed_at: str) -> BuildInfo | None:
    """A build from a hash and an ISO 8601 date with a timezone; anything else is unknown."""
    short = commit.strip().lower()
    if _HASH.fullmatch(short) is None:
        return None
    try:
        moment = datetime.fromisoformat(committed_at.strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return BuildInfo(short[:SHORT_HASH_LENGTH], moment.astimezone(UTC))


def read_build_info_file(path: str) -> BuildInfo | None:
    """The build a file names; None when no file is set, it is missing, unreadable or malformed.

    The date that counts is when the instance was last updated (`updated_at`), else when the code
    was built (`built_at`).
    """
    if not path.strip():
        return None
    try:
        data: object = json.loads(Path(path.strip()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    fields = cast("dict[str, object]", data)
    commit, updated, built = (fields.get(key) for key in ("commit", "updated_at", "built_at"))
    when = updated if isinstance(updated, str) and updated.strip() else built
    if not isinstance(commit, str) or not isinstance(when, str):
        return None
    return parse_build_info(commit, when)


def read_git_build_info(repo: Path) -> BuildInfo | None:
    """The last commit of the checkout at `repo`; None when it is no checkout or git cannot say."""
    if not (repo / ".git").exists():
        # Without this, git would walk upwards and report a repository around the install.
        return None
    try:
        completed = subprocess.run(  # noqa: S603  # fixed argv, no shell
            ["git", "-C", str(repo), "log", "-1", "--format=%cI %h"],  # noqa: S607  # git on PATH
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    committed_at, _, commit = completed.stdout.strip().partition(" ")
    return parse_build_info(commit, committed_at)


def resolve_build_info(
    info_file: str, commit: str, committed_at: str, repo: Path = REPO_ROOT
) -> BuildInfo | None:
    """The build file, else the configured build, else the last commit of the checkout."""
    return (
        read_build_info_file(info_file)
        or parse_build_info(commit, committed_at)
        or read_git_build_info(repo)
    )


@cache
def resolved_build_info(info_file: str, commit: str, committed_at: str) -> BuildInfo | None:
    return resolve_build_info(info_file, commit, committed_at)


def update_reminder(
    after_days: int, info_file: str, commit: str, committed_at: str
) -> UpdateReminder | None:
    """The reminder to declare, or None when it is off (0 days) or the age of the code is unknown.

    The build is resolved once per process; the same two settings give the same answer afterwards.
    """
    if after_days <= 0:
        return None
    build = resolved_build_info(info_file, commit, committed_at)
    return None if build is None else UpdateReminder(build, after_days)

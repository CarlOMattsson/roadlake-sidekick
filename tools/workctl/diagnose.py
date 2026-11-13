"""The decisions behind the hint ``work.sh start`` prints after a failed first database start.

The shell gathers the evidence (container logs, two read-only queries, the volume list) and asks the
functions here what it means. Nothing is ever deleted: the hint only names the volume and the commands.

An absent or empty yoyo table is what "no migration has been applied" looks like, but it must be confirmed over
the local superuser socket by the caller: an unknown state is never treated as empty.
"""

from __future__ import annotations

import re
import shlex

from . import messages

# The migration role cannot log in, or the role-initialisation script could not run. Lines are tested one at a
# time (``.`` does not cross a newline), like ``grep`` did.
MIGRATOR_AUTH_FAILURE = re.compile(
    r"(password authentication failed|authentication failed|role .* does not exist).*sidekick_migrator"
    r"|sidekick_migrator.*(password authentication failed|authentication failed|does not exist)",
    re.IGNORECASE,
)
INITDB_DENIED = re.compile(r"initdb\.d.*permission denied", re.IGNORECASE)
ABSENT = "absent"
MIGRATION_TABLES = ("_yoyo_migration", "public._yoyo_migration")
# One Docker volume name: it is put into a suggested shell command, so nothing else may pass.
VOLUME_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")


def has_failure_evidence(evidence: str, postgres_log: str) -> bool:
    """True when ``evidence`` (migration log plus this start's log lines) shows the migrator failing to
    authenticate, or ``postgres_log`` shows the init scripts denied."""
    return bool(MIGRATOR_AUTH_FAILURE.search(evidence) or INITDB_DENIED.search(postgres_log))


def count_needed(table: str) -> bool:
    """True when the yoyo table exists, so its row count decides; False for an absent table or anything else."""
    return table in MIGRATION_TABLES


def nothing_applied(table: str, count: str) -> bool:
    """True when the yoyo table is absent, or exists with no rows. Any other answer is not proof."""
    if table == ABSENT:
        return True
    return count_needed(table) and count == "0"


def volume_hint(lang: str, project: str, volume: str, table: str, count: str) -> str:
    """The message naming ``volume``, or an empty string when the state is not provably an unmigrated database
    or ``volume`` is not exactly one safe volume name."""
    if not nothing_applied(table, count) or not VOLUME_NAME.fullmatch(volume):
        return ""
    stop_command = f"SIDEKICK_WORK_PROJECT={shlex.quote(project)} bash tools/work.sh stop"
    return messages.render(lang, "first_start_volume", volume, stop_command, f"docker volume rm {shlex.quote(volume)}")

"""The hint after a failed first start: the logs and two read-only queries are the evidence, ``diagnose`` decides what
it means. Logs are inspected in memory, never echoed (they may contain URLs). An absent or empty yoyo table must be
confirmed over the local superuser socket; an unknown state is never empty. Nothing is ever deleted."""

from __future__ import annotations

import sys

from . import diagnose
from .stack import Stack

TABLE_QUERY = "select coalesce(to_regclass('public._yoyo_migration')::text, 'absent')"
COUNT_QUERY = "select count(*) from public._yoyo_migration"


def print_hint(stack: Stack, log_start: int) -> None:
    """Print the hint naming the data volume on stderr when the failed start provably left an unmigrated database.
    ``log_start`` is the number of lines the log had when the start began."""
    migration_log = (stack.compose_read("logs", "--no-color", "--tail", "80", "migrate", quiet=True) or "").rstrip("\n")
    postgres_log = (stack.compose_read("logs", "--no-color", "--tail", "120", "postgres", quiet=True) or "").rstrip(
        "\n"
    )
    if not diagnose.has_failure_evidence(f"{migration_log}\n{stack.log_after(log_start)}", postgres_log):
        return
    table = stack.db_scalar(TABLE_QUERY)
    if table is None:
        return
    count = ""
    if diagnose.count_needed(table):
        found = stack.db_scalar(COUNT_QUERY)
        if found is None:
            return
        count = found
    elif not diagnose.nothing_applied(table, ""):
        return
    volume = stack.docker_read(
        "volume",
        "ls",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={stack.project}",
        "--filter",
        "label=com.docker.compose.volume=pgdata",
        quiet=True,
    )
    if volume is None:
        return
    hint = diagnose.volume_hint(stack.lang, stack.project, volume.rstrip("\n"), table, count)
    if hint:
        print(hint, file=sys.stderr, flush=True)

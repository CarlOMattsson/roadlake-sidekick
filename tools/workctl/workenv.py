"""Reading ``deploy/work/work.env``. The file is never sourced (values hold spaces): one value is looked up
the way ``work.sh`` always did, the last assignment wins and surrounding quotes are stripped."""

from __future__ import annotations

import re
from pathlib import Path

# SIDEKICK_WORK_MEMORY: these values mean "on"; no such line at all also means on (a work.env from before the
# setting existed keeps its old behaviour).
_MEMORY_ON = ("on", "ON", "true", "yes", "1", "")


def env_value(env_file: Path, key: str) -> str:
    """The value of ``KEY=...`` in ``env_file`` ("" when the file or the line is missing)."""
    try:
        with env_file.open(encoding="utf-8", errors="surrogateescape", newline="") as handle:
            lines = handle.read().split("\n")
    except OSError:
        return ""
    assignment = re.compile(r"[ \t\r\n\f\v]*" + re.escape(key) + "=")
    value = ""
    for line in lines:
        match = assignment.match(line)
        if match:
            value = line[match.end() :]
    # The same two steps in the same order as the sed expressions this replaces: double quotes, then single.
    for quote in ('"', "'"):
        if len(value) >= 2 and value.startswith(quote) and value.endswith(quote):
            value = value[1:-1]
    return value


def memory_wanted(env_file: Path) -> bool:
    return env_value(env_file, "SIDEKICK_WORK_MEMORY") in _MEMORY_ON

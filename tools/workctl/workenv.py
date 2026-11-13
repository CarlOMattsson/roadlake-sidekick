"""Reading and editing ``deploy/work/work.env``. The file is never sourced (values hold spaces): one value is looked
up the way ``work.sh`` always did, the last assignment wins and surrounding quotes are stripped. An edit touches
only the lines of its own key, so every other setting and comment survives a second run of the guide."""

from __future__ import annotations

import re
from pathlib import Path

from .secretfiles import write_private

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


_LINE = re.compile(r"([^\r\n]*)(\r\n|\r|\n)|([^\r\n]+)")


def _read_lines(env_file: Path) -> list[tuple[str, str]]:
    """The lines of ``env_file`` as (content, line break); the break is kept as it is (LF, CRLF or a lone CR) and
    is empty for an unterminated last line. A missing file has no lines."""
    try:
        with env_file.open(encoding="utf-8", errors="surrogateescape", newline="") as handle:
            text = handle.read()
    except FileNotFoundError:
        return []
    return [(m.group(1), m.group(2)) if m.group(2) else (m.group(3), "") for m in _LINE.finditer(text)]


def _write_lines(env_file: Path, lines: list[tuple[str, str]]) -> None:
    write_private(env_file, "".join(f"{content}{ending}" for content, ending in lines))


def set_value(env_file: Path, key: str, value: str) -> None:
    """Replace the first ``KEY=...`` or ``# KEY=...`` line with ``KEY=value`` (later ones are dropped), or append
    the line when there is none. The value is taken literally; a value with a line break is refused (``ValueError``)
    before anything is written. Line breaks of the file are kept."""
    if "\n" in value or "\r" in value:
        raise ValueError("a value cannot hold a line break")
    active = re.compile("(# ?)?" + re.escape(key) + "=")
    lines: list[tuple[str, str]] = []
    done = False
    for content, ending in _read_lines(env_file):
        if active.match(content):
            if not done:
                lines.append((f"{key}={value}", ending))
                done = True
            continue
        lines.append((content, ending))
    if not done:
        if lines and not lines[-1][1]:
            lines[-1] = (lines[-1][0], "\n")
        lines.append((f"{key}={value}", "\n"))
    _write_lines(env_file, lines)


def unset_value(env_file: Path, key: str) -> None:
    """Turn every active ``KEY=...`` line into a comment (the setting is then off)."""
    active = re.compile(re.escape(key) + "=")
    _write_lines(
        env_file,
        [(f"# {content}" if active.match(content) else content, ending) for content, ending in _read_lines(env_file)],
    )

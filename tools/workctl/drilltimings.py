"""The step durations of ``tools/drill.sh``: one record per step (``PASS|FAIL scenario/step seconds``, in run
order), the plain-text table after the summary and the Markdown table for the GitHub Actions job summary."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Timing:
    status: str
    step: str
    seconds: int


def parse(lines: Iterable[str]) -> list[Timing]:
    """The records, blank lines skipped. A record that is not ``STATUS STEP SECONDS`` is a ``ValueError``."""
    timings: list[Timing] = []
    for line in lines:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 3 or not fields[2].isdigit():
            raise ValueError(f"not a timing record: {line.strip()!r}")
        timings.append(Timing(fields[0], fields[1], int(fields[2])))
    return timings


def text_table(timings: list[Timing]) -> list[str]:
    """The lines of the plain table, ending in the total."""
    lines = ["TIMINGS (seconds):"]
    lines += [f"  {timing.status} {timing.step} {timing.seconds}" for timing in timings]
    lines.append(f"  total {sum(timing.seconds for timing in timings)}")
    return lines


def markdown_table(timings: list[Timing]) -> list[str]:
    """The lines of the job-summary table (a heading, a blank line and the table)."""
    lines = ["### Drill steps", "", "| Step | Result | Seconds |", "| --- | --- | ---: |"]
    lines += [f"| {timing.step} | {timing.status} | {timing.seconds} |" for timing in timings]
    lines.append(f"| total | | {sum(timing.seconds for timing in timings)} |")
    return lines

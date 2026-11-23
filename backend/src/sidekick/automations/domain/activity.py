"""What the owner's automations have been doing, as the counts and names an overview shows.

These are plain values read from the runs and suggestions. A title and a summary are text the
owner or a model wrote, so a caller that shows them cleans them first.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PendingSuggestions:
    """Suggestions that wait for a decision, and how many automations they come from."""

    total: int
    automations: int


@dataclass(frozen=True, slots=True)
class RunFacts:
    """The recent state of the runs, without anything a run read or proposed."""

    failed_today: int
    """Runs that failed since the start of the owner's day."""
    failed_automation: str | None
    """Title of the newest automation whose latest finished run failed; archived ones count not."""
    latest_summary: str | None
    """What the newest successful run wrote about itself: model-written and untrusted."""


@dataclass(frozen=True, slots=True)
class WindowCounts:
    """What happened in `(since, until]`, the window since the owner last looked."""

    since: datetime
    until: datetime
    runs: int
    failed_runs: int
    suggestions_created: int
    suggestions_decided: int

    @property
    def is_empty(self) -> bool:
        return not (
            self.runs or self.failed_runs or self.suggestions_created or self.suggestions_decided
        )

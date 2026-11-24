"""The structured content of the Start view, shared by `get_start` and the companion API.

`start_structured` composes the parts in `sidekick.start.application.start` from the same use
cases the rest of Sidekick reads, so neither surface adds a selection rule of its own and nothing
is stored. A part needs the read scope of the data it shows and is left out without an error when
the actor lacks it; a part that fails is named in `unavailable` and the others stand. The day is
the owner's calendar day in `Settings.owner_zone`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from sidekick.shared.observability import log_failure
from sidekick.shared.types import Actor
from sidekick.start.application.start import (
    PartName,
    PartUnavailable,
    StartInsight,
    StartMore,
    StartParts,
    StartReady,
    StartSinceLast,
    StartSources,
    StartSuggestions,
    StartToday,
    StartWaiting,
    compose_start,
)
from sidekick.start.sources import ReadyNowSource, WaitingTasksSource, WorkAgendaSource
from sidekick.structured.base import Output

if TYPE_CHECKING:
    from sidekick.composition import Container

LOGGER = logging.getLogger(__name__)


class StartOutput(Output):
    """A part is present only when its scope was held and it had something to say."""

    day: date
    insight: StartInsight | None = None
    ready: StartReady | None = None
    suggestions: StartSuggestions | None = None
    today: StartToday | None = None
    waiting: StartWaiting | None = None
    since_last: StartSinceLast | None = None
    more: StartMore | None = None
    unavailable: list[PartUnavailable] | None = None


@dataclass(frozen=True, slots=True)
class StartResult:
    """The closed record, and the parts it was built from (the MCP tool reads counts off them)."""

    output: StartOutput
    parts: StartParts


def start_structured(container: Container, actor: Actor, *, correlation_id: str) -> StartResult:
    """Every part of Start the actor's scopes allow, in the owner's zone and the app language."""

    now = container.work_lists.clock.now()
    zone = container.settings.owner_zone
    sources = StartSources(
        agenda=WorkAgendaSource(container.work_lists),
        waiting=WaitingTasksSource(container.work_lists, container.contacts),
        automations=container.automation_activity,
        contacts=container.contacts,
        ready=ReadyNowSource(container.ready_conversations),
    )

    def note_failure(part: PartName, error: Exception) -> None:
        log_failure(
            LOGGER,
            "start_part_unavailable",
            error,
            correlation_id=correlation_id,
            operation=f"get_start.{part}",
        )

    view = compose_start(actor, now, zone, container.settings.mcp_app_locale, sources, note_failure)
    failures = {"unavailable": view.unavailable} if view.unavailable else {}
    output = StartOutput(day=now.astimezone(zone).date(), **view.parts, **failures)
    return StartResult(output, view.parts)

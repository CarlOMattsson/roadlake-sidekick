"""The parts of the Start view, composed on read from what the actor's scopes allow.

Start stores nothing of its own here: every part is read from the context that owns the data, when
the view is asked for. A part appears only when the actor holds the read scope of the data it shows
and the part has something to say; a track that is not built yet has no part. One part that fails
does not fail the others: it is named in `unavailable` and the rest stands.

The one sentence, `insight`, is chosen from a closed catalogue (`start.domain.insights`); only the
latest automation run's own summary in it was written by a model, and it says so.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, tzinfo
from typing import Literal, Protocol, TypedDict
from uuid import UUID

from sidekick.automations.domain.activity import PendingSuggestions, RunFacts, WindowCounts
from sidekick.shared.locale import AppLocale
from sidekick.shared.types import Actor
from sidekick.start.application.compose import (
    AgendaItem,
    AgendaSource,
    BriefTaskRecord,
    ClosedRecord,
    read_agenda,
    tasks_from_agenda,
)
from sidekick.start.domain.insights import (
    OVERDUE_BACKLOG_DAYS,
    InsightCode,
    InsightFacts,
    WrittenBy,
    choose_insight,
)

TODAY_ROW_LIMIT = 3
WAITING_ROW_LIMIT = 2

PartName = Literal["insight", "suggestions", "today", "waiting", "since_last", "more"]
"""The parts that can fail. `insight` is pure and is named for completeness."""


class StartInsight(ClosedRecord):
    code: InsightCode
    written_by: WrittenBy
    text: str
    """One clean line. When `written_by` is `ai` a model wrote it and the page says so."""


class StartSuggestions(ClosedRecord):
    pending_count: int
    automation_count: int
    """How many automations the pending suggestions come from."""


class StartToday(ClosedRecord):
    overdue_count: int
    today_count: int
    items: list[BriefTaskRecord]
    """At most `TODAY_ROW_LIMIT` rows, the oldest due first."""
    truncated: bool


class StartWaitingRow(ClosedRecord):
    id: UUID
    title: str
    version: int
    waiting_since: datetime
    days: int
    contact_id: UUID | None
    contact_name: str | None
    """Only with `contacts:read`."""


class StartWaiting(ClosedRecord):
    total: int
    items: list[StartWaitingRow]
    """At most `WAITING_ROW_LIMIT` rows, the longest wait first."""
    capped: bool
    """True when more tasks wait than the bounded read can count."""


class StartSinceLast(ClosedRecord):
    since: datetime
    runs: int
    failed_runs: int
    suggestions_created: int
    suggestions_decided: int


class StartMore(ClosedRecord):
    """Counts the menu shows next to its entries; a count of nothing is left out."""

    contacts: int | None = None
    automations_failed_today: int | None = None


class PartUnavailable(ClosedRecord):
    part: PartName
    error: Literal["unavailable"] = "unavailable"


class StartParts(TypedDict, total=False):
    """The parts the actor's scopes allow; a missing key is a part left out."""

    insight: StartInsight
    suggestions: StartSuggestions
    today: StartToday
    waiting: StartWaiting
    since_last: StartSinceLast
    more: StartMore


@dataclass(frozen=True, slots=True)
class StartView:
    parts: StartParts
    unavailable: list[PartUnavailable]


@dataclass(frozen=True, slots=True)
class WaitingTask:
    id: UUID
    title: str
    version: int
    waiting_since: datetime
    contact_id: UUID | None
    contact_name: str | None


@dataclass(frozen=True, slots=True)
class WaitingTasks:
    items: Sequence[WaitingTask]
    """Longest wait first."""
    total: int
    capped: bool


class WaitingSource(Protocol):
    def waiting_tasks(self, actor: Actor) -> WaitingTasks:
        """Open tasks that wait on something, with the name of the contact when readable."""
        ...


class AutomationSource(Protocol):
    def pending(self, actor: Actor) -> PendingSuggestions: ...

    def recent(self, actor: Actor, *, day_start: datetime) -> RunFacts: ...

    def since_last_look(self, actor: Actor, until: datetime) -> WindowCounts | None: ...


class ContactsSource(Protocol):
    def count(self, actor: Actor) -> int: ...


@dataclass(frozen=True, slots=True)
class StartSources:
    agenda: AgendaSource
    waiting: WaitingSource
    automations: AutomationSource
    contacts: ContactsSource


class _Composer:
    def __init__(
        self,
        actor: Actor,
        now: datetime,
        zone: tzinfo,
        sources: StartSources,
        on_failure: Callable[[PartName, Exception], None],
    ) -> None:
        self.actor = actor
        self.now = now
        self.zone = zone
        self.sources = sources
        self.on_failure = on_failure
        self.parts: StartParts = {}
        self.facts = InsightFacts()
        self.unavailable: list[PartUnavailable] = []
        self.contacts_total: int | None = None
        self.failed_today: int | None = None

    def _attempt[T](self, part: PartName, read: Callable[[], T]) -> T | None:
        """The result of `read`, or None after noting that `part` is unavailable."""

        try:
            return read()
        except Exception as error:  # one failing part must not fail the others
            self.on_failure(part, error)
            if all(item.part != part for item in self.unavailable):
                self.unavailable.append(PartUnavailable(part=part, error="unavailable"))
            return None

    def tasks(self) -> None:
        agenda = self._attempt(
            "today", lambda: read_agenda(self.sources.agenda, self.actor, self.now)
        )
        if agenda is None:
            return
        items, capped = agenda
        brief = tasks_from_agenda(items, capped, show_project="projects:read" in self.actor.scopes)
        if brief.overdue_count or brief.today_count:
            self.parts["today"] = StartToday(
                overdue_count=brief.overdue_count,
                today_count=brief.today_count,
                items=brief.items[:TODAY_ROW_LIMIT],
                truncated=brief.overdue_count + brief.today_count > TODAY_ROW_LIMIT,
            )
        self.facts = replace(
            self.facts,
            overdue_for_a_week=_overdue_for_a_week(items, self.now),
            today_tasks=brief.today_count,
            tomorrow_tasks=_due_tomorrow(items, self.now, self.zone),
        )

    def waiting(self) -> None:
        waiting = self._attempt("waiting", lambda: self.sources.waiting.waiting_tasks(self.actor))
        if waiting is None or not waiting.total:
            return
        self.parts["waiting"] = StartWaiting(
            total=waiting.total,
            items=[
                StartWaitingRow(
                    id=task.id,
                    title=task.title,
                    version=task.version,
                    waiting_since=task.waiting_since,
                    days=_whole_days(self.now - task.waiting_since),
                    contact_id=task.contact_id,
                    contact_name=task.contact_name,
                )
                for task in waiting.items[:WAITING_ROW_LIMIT]
            ],
            capped=waiting.capped,
        )
        named = next((task for task in waiting.items if task.contact_name is not None), None)
        if named is not None:
            self.facts = replace(
                self.facts,
                longest_waiting_contact=named.contact_name,
                longest_waiting_days=_whole_days(self.now - named.waiting_since),
            )

    def suggestions(self) -> None:
        pending = self._attempt("suggestions", lambda: self.sources.automations.pending(self.actor))
        if pending is not None and pending.total:
            self.parts["suggestions"] = StartSuggestions(
                pending_count=pending.total, automation_count=pending.automations
            )

    def automation_activity(self) -> None:
        day_start = datetime.combine(
            self.now.astimezone(self.zone).date(), time.min, tzinfo=self.zone
        )
        recent = self._attempt(
            "more", lambda: self.sources.automations.recent(self.actor, day_start=day_start)
        )
        if recent is not None:
            self.failed_today = recent.failed_today or None
            self.facts = replace(
                self.facts,
                failed_automation=recent.failed_automation,
                automation_summary=recent.latest_summary,
            )
        window = self._attempt(
            "since_last", lambda: self.sources.automations.since_last_look(self.actor, self.now)
        )
        if window is not None and not window.is_empty:
            self.parts["since_last"] = StartSinceLast(
                since=window.since,
                runs=window.runs,
                failed_runs=window.failed_runs,
                suggestions_created=window.suggestions_created,
                suggestions_decided=window.suggestions_decided,
            )

    def contacts(self) -> None:
        count = self._attempt("more", lambda: self.sources.contacts.count(self.actor))
        if count is not None:
            self.contacts_total = count or None

    def finish(self, locale: AppLocale) -> StartView:
        counts = {
            name: value
            for name, value in (
                ("contacts", self.contacts_total),
                ("automations_failed_today", self.failed_today),
            )
            if value is not None
        }
        if counts:
            self.parts["more"] = StartMore(**counts)
        insight = choose_insight(self.facts, locale)
        if insight is not None:
            self.parts["insight"] = StartInsight(
                code=insight.code, written_by=insight.written_by, text=insight.text
            )
        return StartView(parts=self.parts, unavailable=self.unavailable)


def compose_start(
    actor: Actor,
    now: datetime,
    zone: tzinfo,
    locale: AppLocale,
    sources: StartSources,
    on_failure: Callable[[PartName, Exception], None],
) -> StartView:
    """Every part the actor's read scopes allow, in the owner's zone and the app's language.

    `on_failure` is told which part failed and why, so the caller can log the class of the error;
    the part itself is named in `unavailable` and the others are composed as usual.
    """

    composer = _Composer(actor, now, zone, sources, on_failure)
    scopes = actor.scopes
    if "tasks:read" in scopes:
        composer.tasks()
        composer.waiting()
    if "automation:read" in scopes:
        composer.suggestions()
        composer.automation_activity()
    if "contacts:read" in scopes:
        composer.contacts()
    return composer.finish(locale)


def _whole_days(delta: timedelta) -> int:
    return max(0, delta.days)


def _overdue_for_a_week(items: Sequence[AgendaItem], now: datetime) -> int:
    limit = now - timedelta(days=OVERDUE_BACKLOG_DAYS)
    return sum(
        1
        for item in items
        if item.agenda_group == "overdue" and item.due_at is not None and item.due_at < limit
    )


def _due_tomorrow(items: Sequence[AgendaItem], now: datetime, zone: tzinfo) -> int:
    tomorrow = now.astimezone(zone).date() + timedelta(days=1)
    return sum(
        1
        for item in items
        if item.agenda_group == "upcoming"
        and item.due_at is not None
        and item.due_at.astimezone(zone).date() == tomorrow
    )

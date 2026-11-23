"""What a ready conversation reads when it is started: the blocks of its ingredients.

Each ingredient is composed from the context that owns the data, when the conversation starts; the
result is returned and never stored. An ingredient the caller cannot read (a read scope is missing)
is left out without an error. One that fails is named in `unavailable` and the others stand, so a
broken source never blocks the conversation. The blocks hold counts and short one-line items; the
whole answer is kept within `MAX_OUTPUT_BYTES`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Protocol

from sidekick.shared.types import Actor
from sidekick.start.application.compose import (
    AgendaItem,
    AgendaSource,
    ShoppingSource,
    read_agenda,
    shopping_part,
)
from sidekick.start.application.start import AutomationSource, WaitingSource
from sidekick.start.domain.ready import (
    BLOCK_LINE_LIMIT,
    Ingredient,
    ReadyBlock,
    fit_blocks,
    one_line,
    readable_ingredients,
)


@dataclass(frozen=True, slots=True)
class DiaryEntryLine:
    title: str
    summary: str | None


@dataclass(frozen=True, slots=True)
class DiaryDay:
    """What one diary day holds, for the ingredients that read it."""

    done_task_count: int
    done_task_titles: tuple[str, ...]
    entry_count: int
    entries: tuple[DiaryEntryLine, ...]
    entries_more: bool
    """True when the day holds more entries than were read."""


class DiaryDaySource(Protocol):
    def diary_day(self, actor: Actor, day: date) -> DiaryDay:
        """The tasks done and the entries written on `day`; needs the journal read scope."""
        ...


@dataclass(frozen=True, slots=True)
class IngredientSources:
    agenda: AgendaSource
    waiting: WaitingSource
    automations: AutomationSource
    shopping: ShoppingSource
    diary: DiaryDaySource


@dataclass(frozen=True, slots=True)
class Composition:
    blocks: tuple[ReadyBlock, ...]
    unavailable: tuple[Ingredient, ...]
    truncated: bool


def _lines(titles: Sequence[str]) -> tuple[tuple[str, ...], bool]:
    return tuple(one_line(title) for title in titles[:BLOCK_LINE_LIMIT]), len(titles) > (
        BLOCK_LINE_LIMIT
    )


def _titled(ingredient: Ingredient, titles: Sequence[str]) -> ReadyBlock:
    lines, more = _lines(titles)
    return ReadyBlock(ingredient, count=len(titles), lines=lines, truncated=more)


class _Reads:
    """The reads shared by several ingredients, each made at most once per start."""

    def __init__(self, actor: Actor, now: datetime, zone: tzinfo, sources: IngredientSources):
        self.actor = actor
        self.now = now
        self.zone = zone
        self.sources = sources
        self.today = now.astimezone(zone).date()
        self._agenda: list[AgendaItem] | None = None
        self._diary: DiaryDay | None = None

    def agenda(self) -> list[AgendaItem]:
        if self._agenda is None:
            self._agenda, _ = read_agenda(self.sources.agenda, self.actor, self.now)
        return self._agenda

    def diary(self) -> DiaryDay:
        if self._diary is None:
            self._diary = self.sources.diary.diary_day(self.actor, self.today)
        return self._diary

    def overdue(self) -> ReadyBlock:
        items = [item for item in self.agenda() if item.agenda_group == "overdue"]
        return _titled(Ingredient.OVERDUE, [item.title for item in items])

    def due_today(self) -> ReadyBlock:
        """Tasks due today that are not overdue; a Project's title only for a caller who may read
        Projects."""

        show_project = "projects:read" in self.actor.scopes
        titles = [
            f"{item.title} ({item.project_title})"
            if show_project and item.project_title
            else item.title
            for item in self.agenda()
            if item.agenda_group == "today"
        ]
        return _titled(Ingredient.TASKS_DUE_TODAY, titles)

    def due_tomorrow(self) -> ReadyBlock:
        tomorrow = self.today + timedelta(days=1)
        items = [
            item
            for item in self.agenda()
            if item.agenda_group == "upcoming"
            and item.due_at is not None
            and item.due_at.astimezone(self.zone).date() == tomorrow
        ]
        return _titled(Ingredient.TASKS_DUE_TOMORROW, [item.title for item in items])

    def waiting(self) -> ReadyBlock:
        waiting = self.sources.waiting.waiting_tasks(self.actor)
        lines, more = _lines([task.title for task in waiting.items])
        return ReadyBlock(
            Ingredient.WAITING, count=waiting.total, lines=lines, truncated=more or waiting.capped
        )

    def done_today(self) -> ReadyBlock:
        diary = self.diary()
        lines, more = _lines(diary.done_task_titles)
        return ReadyBlock(
            Ingredient.TASKS_DONE_TODAY, count=diary.done_task_count, lines=lines, truncated=more
        )

    def journal_today(self) -> ReadyBlock:
        diary = self.diary()
        titles = [
            entry.title if not entry.summary else f"{entry.title}: {entry.summary}"
            for entry in diary.entries
        ]
        lines, more = _lines(titles)
        return ReadyBlock(
            Ingredient.JOURNAL_TODAY,
            count=diary.entry_count,
            lines=lines,
            truncated=more or diary.entries_more,
        )

    def suggestions(self) -> ReadyBlock:
        pending = self.sources.automations.pending(self.actor)
        return ReadyBlock(
            Ingredient.SUGGESTIONS,
            count=pending.total,
            details={"automations": pending.automations},
        )

    def automation_report(self) -> ReadyBlock | None:
        window = self.sources.automations.since_last_look(self.actor, self.now)
        if window is None or window.is_empty:
            return None
        return ReadyBlock(
            Ingredient.AUTOMATION_REPORT,
            count=window.runs,
            details={
                "failed_runs": window.failed_runs,
                "suggestions_created": window.suggestions_created,
                "suggestions_decided": window.suggestions_decided,
            },
        )

    def shopping_open(self) -> ReadyBlock:
        shopping = shopping_part(self.sources.shopping, self.actor)
        lines, more = _lines(
            [
                f"{item.name}: {item.open_item_count}"
                for item in shopping.lists
                if item.open_item_count
            ]
        )
        return ReadyBlock(
            Ingredient.SHOPPING_OPEN, count=shopping.open_item_count, lines=lines, truncated=more
        )

    def read(self, ingredient: Ingredient) -> ReadyBlock | None:
        readers: dict[Ingredient, Callable[[], ReadyBlock | None]] = {
            Ingredient.OVERDUE: self.overdue,
            Ingredient.TASKS_DUE_TODAY: self.due_today,
            Ingredient.TASKS_DUE_TOMORROW: self.due_tomorrow,
            Ingredient.WAITING: self.waiting,
            Ingredient.TASKS_DONE_TODAY: self.done_today,
            Ingredient.JOURNAL_TODAY: self.journal_today,
            Ingredient.SUGGESTIONS: self.suggestions,
            Ingredient.AUTOMATION_REPORT: self.automation_report,
            Ingredient.SHOPPING_OPEN: self.shopping_open,
        }
        reader = readers.get(ingredient)
        # `review` has no source yet: the ingredient is accepted and composes nothing.
        return None if reader is None else reader()


def compose_ingredients(
    actor: Actor,
    now: datetime,
    zone: tzinfo,
    ingredients: Sequence[Ingredient],
    sources: IngredientSources,
    on_failure: Callable[[Ingredient, Exception], None],
) -> Composition:
    """The block of every ingredient the actor may read, in the catalogue's order.

    `on_failure` is told which ingredient failed and why, so the caller can log the class of the
    error; the ingredient is named in `unavailable` and the others are composed as usual.
    """

    reads = _Reads(actor, now, zone, sources)
    blocks: list[ReadyBlock] = []
    unavailable: list[Ingredient] = []
    for ingredient in readable_ingredients(ingredients, actor.scopes):
        try:
            block = reads.read(ingredient)
        except Exception as error:  # one failing source must not stop the conversation
            on_failure(ingredient, error)
            unavailable.append(ingredient)
            continue
        if block is not None:
            blocks.append(block)
    fitted, truncated = fit_blocks(blocks)
    return Composition(fitted, tuple(unavailable), truncated)

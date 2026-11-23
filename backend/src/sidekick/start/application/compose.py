"""The parts of the owner's day, composed on read from what the actor's scopes allow.

`get_today_brief` and the Start view read the same parts, so the selection rules live here once.
Tasks come from the Work agenda, the day's journal entries from the journal day, and the open
shopping lists from Shopping. Each source is a port: the contexts that own the data are adapted
to it in `sidekick.start.sources`, so this layer imports no other context's application code.
A part whose read scope is missing is left out without an error.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Protocol, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sidekick.shared.types import Actor

UPCOMING_DAYS = 7
"""How many days ahead the agenda counts as upcoming."""
TASK_ROW_LIMIT = 10
PAGE_SIZE = 100
# The Work and shopping reads are already capped at 1000 records per call; this bounds the pages.
MAX_PAGES = 10

AgendaGroupName = Literal["overdue", "today", "upcoming", "scheduled_later"]


class _ClosedRecord(BaseModel):
    """A record with no unknown fields, as the reviewed tool output is."""

    model_config = ConfigDict(extra="forbid")


class BriefTaskRecord(_ClosedRecord):
    """One overdue or due-today Work record, with the id and version a follow-up call needs."""

    id: UUID
    kind: str
    title: str
    version: int
    agenda_group: Literal["overdue", "today"]
    due_at: datetime | None
    project_title: str | None


class BriefTasks(_ClosedRecord):
    overdue_count: int
    today_count: int
    upcoming_7d_count: int
    items: list[BriefTaskRecord]
    truncated: bool
    """True when more overdue or due-today records exist than `items` shows."""
    capped: bool
    """True when the window held more records than the bounded reads can count."""


class BriefDiary(_ClosedRecord):
    entry_count: int
    has_summary: bool
    truncated: bool


class BriefShoppingList(_ClosedRecord):
    id: UUID
    name: str
    version: int
    open_item_count: int


class BriefShopping(_ClosedRecord):
    open_list_count: int
    open_item_count: int
    lists: list[BriefShoppingList]


class BriefParts(TypedDict, total=False):
    """The parts of the day the actor's scopes allow; a missing key is a part left out."""

    tasks: BriefTasks
    diary: BriefDiary
    shopping: BriefShopping


@dataclass(frozen=True, slots=True)
class AgendaItem:
    id: UUID
    kind: str
    title: str
    version: int
    agenda_group: AgendaGroupName | None
    due_at: datetime | None
    project_title: str | None


@dataclass(frozen=True, slots=True)
class AgendaPage:
    items: Sequence[AgendaItem]
    next_cursor: str | None


class AgendaSource(Protocol):
    def agenda_page(
        self, actor: Actor, *, due_to: datetime, limit: int, cursor: str | None
    ) -> AgendaPage:
        """Agenda rows by due time up to `due_to`, in the Work agenda's own grouping."""
        ...


@dataclass(frozen=True, slots=True)
class DayFacts:
    entry_count: int
    has_summary: bool
    has_more: bool


class JournalDaySource(Protocol):
    def day_facts(self, actor: Actor, day: date, *, limit: int) -> DayFacts:
        """What one journal day holds, without entry text."""
        ...


@dataclass(frozen=True, slots=True)
class ShoppingListRef:
    id: UUID
    name: str
    version: int


@dataclass(frozen=True, slots=True)
class ShoppingListsPage:
    lists: Sequence[ShoppingListRef]
    next_offset: int | None


@dataclass(frozen=True, slots=True)
class OpenItemsPage:
    open_count: int
    """Unpurchased items on this page of the list."""
    next_offset: int | None


class ShoppingSource(Protocol):
    def lists_page(self, actor: Actor, *, offset: int, limit: int) -> ShoppingListsPage: ...

    def open_items_page(
        self, actor: Actor, list_id: UUID, *, offset: int, limit: int
    ) -> OpenItemsPage: ...


def compose_brief(
    actor: Actor,
    now: datetime,
    day: date,
    *,
    agenda: AgendaSource,
    journal: JournalDaySource,
    shopping: ShoppingSource,
) -> BriefParts:
    """Every part the actor's read scopes allow; `day` is the owner's calendar day."""

    parts: BriefParts = {}
    if "tasks:read" in actor.scopes:
        parts["tasks"] = tasks_part(agenda, actor, now)
    if "journal:read" in actor.scopes:
        parts["diary"] = diary_part(journal, actor, day)
    if "shopping:read" in actor.scopes:
        parts["shopping"] = shopping_part(shopping, actor)
    return parts


def tasks_part(source: AgendaSource, actor: Actor, now: datetime) -> BriefTasks:
    window_end = now + timedelta(days=UPCOMING_DAYS)
    items: list[AgendaItem] = []
    cursor: str | None = None
    capped = True
    for _ in range(MAX_PAGES):
        page = source.agenda_page(actor, due_to=window_end, limit=PAGE_SIZE, cursor=cursor)
        items.extend(page.items)
        if page.next_cursor is None:
            capped = False
            break
        cursor = page.next_cursor
    rows: list[BriefTaskRecord] = []
    listed = 0
    for item in items:
        group = item.agenda_group
        if group not in ("overdue", "today"):
            continue
        listed += 1
        if len(rows) < TASK_ROW_LIMIT:
            rows.append(
                BriefTaskRecord(
                    id=item.id,
                    kind=item.kind,
                    title=item.title,
                    version=item.version,
                    agenda_group=group,
                    due_at=item.due_at,
                    project_title=item.project_title,
                )
            )
    return BriefTasks(
        overdue_count=sum(1 for item in items if item.agenda_group == "overdue"),
        today_count=sum(1 for item in items if item.agenda_group == "today"),
        upcoming_7d_count=sum(1 for item in items if item.agenda_group == "upcoming"),
        items=rows,
        truncated=listed > TASK_ROW_LIMIT,
        capped=capped,
    )


def diary_part(source: JournalDaySource, actor: Actor, day: date) -> BriefDiary:
    facts = source.day_facts(actor, day, limit=PAGE_SIZE)
    return BriefDiary(
        entry_count=facts.entry_count, has_summary=facts.has_summary, truncated=facts.has_more
    )


def shopping_part(source: ShoppingSource, actor: Actor) -> BriefShopping:
    lists: list[ShoppingListRef] = []
    offset = 0
    for _ in range(MAX_PAGES):
        page = source.lists_page(actor, offset=offset, limit=PAGE_SIZE)
        lists.extend(page.lists)
        if page.next_offset is None:
            break
        offset = page.next_offset
    records: list[BriefShoppingList] = []
    for shopping_list in lists:
        open_items = 0
        item_offset = 0
        for _ in range(MAX_PAGES):
            items = source.open_items_page(
                actor, shopping_list.id, offset=item_offset, limit=PAGE_SIZE
            )
            open_items += items.open_count
            if items.next_offset is None:
                break
            item_offset = items.next_offset
        records.append(
            BriefShoppingList(
                id=shopping_list.id,
                name=shopping_list.name,
                version=shopping_list.version,
                open_item_count=open_items,
            )
        )
    return BriefShopping(
        open_list_count=len(records),
        open_item_count=sum(record.open_item_count for record in records),
        lists=records,
    )

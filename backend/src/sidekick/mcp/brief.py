"""Read-only "Dagens läge": one bounded summary of the owner's day in one call.

`get_today_brief` adds no selection rules of its own. Tasks come from the Work agenda use case
(`WorkListService.work_agenda_page`, the same rules as `get_work_agenda`), the day's entries and
summary status from `JournalService.get_day` (as `get_journal_day`), and the open shopping lists
from `ShoppingService`. Each part needs its own read scope. A part whose scope is missing is left
out of structuredContent without an error, as the Journal tools leave out content they may not see.
The day is the owner's calendar day in `Settings.owner_zone`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from sidekick.mcp.annotations import READ
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.text import AGENDA_UPCOMING_DAYS
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale
from sidekick.shared.types import Actor
from sidekick.structured.base import Output
from sidekick.work.application.models import WorkQuery, WorkRow

if TYPE_CHECKING:
    from sidekick.composition import Container

TASK_ROW_LIMIT = 10
PAGE_SIZE = 100
# The Work and shopping reads are already capped at 1000 records per call; this bounds the pages.
MAX_PAGES = 10


class BriefTaskRecord(Output):
    """One overdue or due-today Work record, with the id and version a follow-up call needs."""

    id: UUID
    kind: str
    title: str
    version: int
    agenda_group: Literal["overdue", "today"]
    due_at: datetime | None
    project_title: str | None


class BriefTasks(Output):
    overdue_count: int
    today_count: int
    upcoming_7d_count: int
    items: list[BriefTaskRecord]
    truncated: bool
    """True when more overdue or due-today records exist than `items` shows."""
    capped: bool
    """True when the window held more records than the bounded reads can count."""


class BriefDiary(Output):
    entry_count: int
    has_summary: bool
    truncated: bool


class BriefShoppingList(Output):
    id: UUID
    name: str
    version: int
    open_item_count: int


class BriefShopping(Output):
    open_list_count: int
    open_item_count: int
    lists: list[BriefShoppingList]


class BriefOutput(Output):
    """A part is present only when its read scope was held; a missing scope omits its key."""

    day: date
    tasks: BriefTasks | None = None
    diary: BriefDiary | None = None
    shopping: BriefShopping | None = None


@dataclass(frozen=True)
class _Words:
    """The wording of the summary sentences in one app language."""

    none: str
    overdue_task: tuple[str, str]
    task: tuple[str, str]
    entry: tuple[str, str]
    open_list: tuple[str, str]
    open_item: tuple[str, str]
    tasks: str
    """Template over {overdue}, {today}, {upcoming} and {days}."""
    diary_empty: str
    diary: str
    """Template over {entries} and {summary}."""
    with_summary: str
    without_summary: str
    no_lists: str
    shopping: str
    """Template over {lists} and {items}."""
    nothing: str


_WORDS: dict[AppLocale, _Words] = {
    "sv": _Words(
        none="inga",
        overdue_task=("försenad uppgift", "försenade uppgifter"),
        task=("uppgift", "uppgifter"),
        entry=("post", "poster"),
        open_list=("öppen inköpslista", "öppna inköpslistor"),
        open_item=("ej köpt vara", "ej köpta varor"),
        tasks="Du har {overdue} och {today} idag, och {upcoming} inom {days} dagar.",
        diary_empty="Dagboken är tom idag.",
        diary="Dagboken har {entries} idag, {summary}.",
        with_summary="med dagssammanfattning",
        without_summary="utan dagssammanfattning",
        no_lists="Inga öppna inköpslistor.",
        shopping="Du har {lists} med {items}.",
        nothing="Inga delar av dagens läge är tillgängliga med dina behörigheter.",
    ),
    "en": _Words(
        none="no",
        overdue_task=("overdue task", "overdue tasks"),
        task=("task", "tasks"),
        entry=("entry", "entries"),
        open_list=("open shopping list", "open shopping lists"),
        open_item=("item left to buy", "items left to buy"),
        tasks="You have {overdue} and {today} today, and {upcoming} in the next {days} days.",
        diary_empty="Your journal is empty today.",
        diary="Your journal has {entries} today, {summary}.",
        with_summary="with a daily summary",
        without_summary="without a daily summary",
        no_lists="No open shopping lists.",
        shopping="You have {lists} with {items}.",
        nothing="No part of today\u2019s brief is available with your permissions.",
    ),
}


def _phrase(words: _Words, count: int, forms: tuple[str, str]) -> str:
    singular, plural = forms
    if count == 0:
        return f"{words.none} {plural}"
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural}"


def _summary_text(parts: dict[str, Any], locale: AppLocale = DEFAULT_LOCALE) -> str:
    """Return at most three sentences in the app language for the model to read aloud, with no
    titles."""

    words = _WORDS[locale]
    sentences: list[str] = []
    tasks: BriefTasks | None = parts.get("tasks")
    if tasks is not None:
        sentences.append(
            words.tasks.format(
                overdue=_phrase(words, tasks.overdue_count, words.overdue_task),
                today=_phrase(words, tasks.today_count, words.task),
                upcoming=_phrase(words, tasks.upcoming_7d_count, words.task),
                days=AGENDA_UPCOMING_DAYS,
            )
        )
    diary: BriefDiary | None = parts.get("diary")
    if diary is not None:
        if diary.entry_count == 0:
            sentences.append(words.diary_empty)
        else:
            sentences.append(
                words.diary.format(
                    entries=_phrase(words, diary.entry_count, words.entry),
                    summary=words.with_summary if diary.has_summary else words.without_summary,
                )
            )
    shopping: BriefShopping | None = parts.get("shopping")
    if shopping is not None:
        if shopping.open_list_count == 0:
            sentences.append(words.no_lists)
        else:
            sentences.append(
                words.shopping.format(
                    lists=_phrase(words, shopping.open_list_count, words.open_list),
                    items=_phrase(words, shopping.open_item_count, words.open_item),
                )
            )
    if not sentences:
        return words.nothing
    return " ".join(sentences)


def _tasks_part(container: Container, actor: Actor, now: datetime) -> BriefTasks:
    window_end = now + timedelta(days=AGENDA_UPCOMING_DAYS)
    query = WorkQuery(limit=PAGE_SIZE, sort="due_asc", due_to=window_end)
    items: list[WorkRow] = []
    cursor: str | None = None
    capped = True
    for _ in range(MAX_PAGES):
        page = container.work_lists.work_agenda_page(actor, replace(query, cursor=cursor))
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


def _diary_part(container: Container, actor: Actor, day: date) -> BriefDiary:
    journal_day = container.journal_day.get_day(
        actor, journal_date=day, include_archived=False, limit=PAGE_SIZE, include_done=False
    )
    return BriefDiary(
        entry_count=len(journal_day.entries),
        has_summary=journal_day.summary is not None,
        truncated=journal_day.next_cursor is not None,
    )


def _shopping_part(container: Container, actor: Actor) -> BriefShopping:
    lists: list[dict[str, Any]] = []
    offset = 0
    for _ in range(MAX_PAGES):
        page = container.shopping.list_lists(
            actor, include_archived=False, limit=PAGE_SIZE, offset=offset
        )
        lists.extend(page["lists"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    records: list[BriefShoppingList] = []
    for shopping_list in lists:
        open_items = 0
        item_offset = 0
        for _ in range(MAX_PAGES):
            detail = container.shopping.get_list(
                actor, UUID(shopping_list["id"]), limit=PAGE_SIZE, offset=item_offset
            )
            open_items += sum(1 for item in detail["items"] if not item["purchased"])
            if detail["next_offset"] is None:
                break
            item_offset = detail["next_offset"]
        records.append(
            BriefShoppingList(
                id=UUID(shopping_list["id"]),
                name=shopping_list["name"],
                version=shopping_list["version"],
                open_item_count=open_items,
            )
        )
    return BriefShopping(
        open_list_count=len(records),
        open_item_count=sum(record.open_item_count for record in records),
        lists=records,
    )


def register_brief_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the read-only day brief; it opens no app card."""

    @mcp.tool(
        name="get_today_brief",
        description=(
            "Use this when the user asks how today stands, or a scheduled morning or evening "
            "check needs the day at a glance. Returns, in the owner's zone: overdue and "
            "today's tasks (at most 10 rows with id and version), the count due in the next 7 "
            "days, today's journal entry count and whether a daily summary exists, and open "
            "shopping lists with unbought item counts. Read-only; each part needs its own read "
            "scope and is left out without an error when the scope is missing."
        ),
        output_schema=output_schema(BriefOutput),
        annotations=READ,
    )
    @ctx.instrument("get_today_brief")
    def get_today_brief() -> ToolResult:
        actor = ctx.actor_provider()
        now = ctx.container.work_lists.clock.now()
        day = now.astimezone(ctx.container.settings.owner_zone).date()
        parts: dict[str, Any] = {}
        if "tasks:read" in actor.scopes:
            parts["tasks"] = _tasks_part(ctx.container, actor, now)
        if "journal:read" in actor.scopes:
            parts["diary"] = _diary_part(ctx.container, actor, day)
        if "shopping:read" in actor.scopes:
            parts["shopping"] = _shopping_part(ctx.container, actor)
        structured = BriefOutput(day=day, **parts).model_dump(mode="json", exclude_unset=True)
        return result(structured, _summary_text(parts, ctx.container.settings.mcp_app_locale))

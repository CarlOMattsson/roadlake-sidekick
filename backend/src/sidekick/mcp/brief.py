"""Read-only "Dagens läge": one bounded summary of the owner's day in one call.

`get_today_brief` adds no selection rules of its own: `sidekick.start.application.compose` reads
the parts. Tasks come from the Work agenda use case (the same rules as `get_work_agenda`), the
day's entries and summary status from the journal day (as `get_journal_day`), and the open
shopping lists from Shopping. Each part needs its own read scope. A part whose scope is missing
is left out of structuredContent without an error, as the Journal tools leave out content they may
not see.
The day is the owner's calendar day in `Settings.owner_zone`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from sidekick.mcp.annotations import READ
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale
from sidekick.start.application.compose import (
    UPCOMING_DAYS,
    BriefDiary,
    BriefParts,
    BriefShopping,
    BriefShoppingList,
    BriefTasks,
    compose_brief,
)
from sidekick.start.sources import JournalDayFactsSource, ShoppingListsSource, WorkAgendaSource
from sidekick.structured.base import Output

# The part records live with the composition; this module still names them for its callers.
__all__ = ["BriefDiary", "BriefShopping", "BriefShoppingList", "BriefTasks", "register_brief_tools"]


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
        tasks="You have {overdue}, {today} due today, and {upcoming} due in the next {days} days.",
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


def _summary_text(parts: BriefParts, locale: AppLocale = DEFAULT_LOCALE) -> str:
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
                days=UPCOMING_DAYS,
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
        parts = compose_brief(
            actor,
            now,
            day,
            agenda=WorkAgendaSource(ctx.container.work_lists),
            journal=JournalDayFactsSource(ctx.container.journal_day),
            shopping=ShoppingListsSource(ctx.container.shopping),
        )
        structured = BriefOutput(day=day, **parts).model_dump(mode="json", exclude_unset=True)
        return result(structured, _summary_text(parts, ctx.container.settings.mcp_app_locale))

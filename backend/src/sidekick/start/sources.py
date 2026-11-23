"""Adapters from the Work, journal and Shopping services to the ports of the day composition.

The services answer in their own records; the composition in `start.application.compose` asks
for the few facts it needs. Each adapter only maps, and holds no selection rule.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID

from sidekick.journal.application.day import JournalDayService
from sidekick.shared.types import Actor
from sidekick.shopping.application.service import ShoppingService
from sidekick.start.application.compose import (
    AgendaItem,
    AgendaPage,
    DayFacts,
    OpenItemsPage,
    ShoppingListRef,
    ShoppingListsPage,
)
from sidekick.work.application.models import WorkQuery
from sidekick.work.application.work_lists import WorkListService


class WorkAgendaSource:
    def __init__(self, work_lists: WorkListService) -> None:
        self._work_lists = work_lists

    def agenda_page(
        self, actor: Actor, *, due_to: datetime, limit: int, cursor: str | None
    ) -> AgendaPage:
        query = WorkQuery(limit=limit, sort="due_asc", due_to=due_to)
        page = self._work_lists.work_agenda_page(actor, replace(query, cursor=cursor))
        return AgendaPage(
            items=[
                AgendaItem(
                    id=row.id,
                    kind=row.kind,
                    title=row.title,
                    version=row.version,
                    agenda_group=row.agenda_group,
                    due_at=row.due_at,
                    project_title=row.project_title,
                )
                for row in page.items
            ],
            next_cursor=page.next_cursor,
        )


class JournalDayFactsSource:
    def __init__(self, journal_day: JournalDayService) -> None:
        self._journal_day = journal_day

    def day_facts(self, actor: Actor, day: date, *, limit: int) -> DayFacts:
        journal_day = self._journal_day.get_day(
            actor, journal_date=day, include_archived=False, limit=limit, include_done=False
        )
        return DayFacts(
            entry_count=len(journal_day.entries),
            has_summary=journal_day.summary is not None,
            has_more=journal_day.next_cursor is not None,
        )


class ShoppingListsSource:
    def __init__(self, shopping: ShoppingService) -> None:
        self._shopping = shopping

    def lists_page(self, actor: Actor, *, offset: int, limit: int) -> ShoppingListsPage:
        page = self._shopping.list_lists(actor, include_archived=False, limit=limit, offset=offset)
        return ShoppingListsPage(
            lists=[
                ShoppingListRef(id=row.id, name=row.name, version=row.version) for row in page.lists
            ],
            next_offset=page.next_offset,
        )

    def open_items_page(
        self, actor: Actor, list_id: UUID, *, offset: int, limit: int
    ) -> OpenItemsPage:
        detail = self._shopping.get_list(actor, list_id, limit=limit, offset=offset)
        return OpenItemsPage(
            open_count=sum(1 for item in detail.items if not item.purchased),
            next_offset=detail.next_offset,
        )

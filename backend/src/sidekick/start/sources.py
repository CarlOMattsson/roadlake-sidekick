"""Adapters from the Work, journal, Shopping and Contacts services to the ports of the composition.

The services answer in their own records; the composition in `start.application.compose` asks
for the few facts it needs. Each adapter only maps, and holds no selection rule.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID

from sidekick.contacts.application.service import ContactService
from sidekick.journal.application.day import JournalDayService
from sidekick.shared.types import Actor
from sidekick.shopping.application.service import ShoppingService
from sidekick.start.application.compose import (
    MAX_PAGES,
    PAGE_SIZE,
    AgendaItem,
    AgendaPage,
    DayFacts,
    OpenItemsPage,
    ShoppingListRef,
    ShoppingListsPage,
)
from sidekick.start.application.ingredients import DiaryDay, DiaryEntryLine
from sidekick.start.application.ready import ReadyConversationService
from sidekick.start.application.start import ReadyFacts, WaitingTask, WaitingTasks
from sidekick.work.application.models import WorkQuery, WorkRow
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


class WaitingTasksSource:
    """Open tasks that wait on something, longest first; the contact name needs contacts:read."""

    def __init__(self, work_lists: WorkListService, contacts: ContactService) -> None:
        self._work_lists = work_lists
        self._contacts = contacts

    def waiting_tasks(self, actor: Actor) -> WaitingTasks:
        rows: list[WorkRow] = []
        cursor: str | None = None
        capped = True
        for _ in range(MAX_PAGES):
            query = WorkQuery(
                kind="task", waiting="waiting", sort="updated_desc", limit=PAGE_SIZE, cursor=cursor
            )
            page = self._work_lists.work_list_page(actor, query)
            rows.extend(page.items)
            if page.next_cursor is None:
                capped = False
                break
            cursor = page.next_cursor
        waiting = [(row.waiting_since, row) for row in rows if row.waiting_since is not None]
        waiting.sort(key=lambda pair: (pair[0], pair[1].id))
        wanted = [row.waiting_on_contact_id for _, row in waiting if row.waiting_on_contact_id]
        names = (
            self._contacts.waiting_contact_names(actor, wanted)
            if wanted and "contacts:read" in actor.scopes
            else {}
        )
        return WaitingTasks(
            items=[
                WaitingTask(
                    id=row.id,
                    title=row.title,
                    version=row.version,
                    waiting_since=since,
                    contact_id=row.waiting_on_contact_id,
                    contact_name=names.get(row.waiting_on_contact_id)
                    if row.waiting_on_contact_id
                    else None,
                )
                for since, row in waiting
            ],
            total=len(waiting),
            capped=capped,
        )


class ReadyNowSource:
    """The conversations that are ready now, as the Start view's part reads them."""

    def __init__(self, ready: ReadyConversationService) -> None:
        self._ready = ready

    def ready_now(self, actor: Actor) -> list[ReadyFacts]:
        return [
            ReadyFacts(
                id=view.conversation.id,
                title=view.conversation.title,
                kind=view.conversation.kind.value,
                local_time=view.conversation.cadence.local_time,
                version=view.conversation.version,
            )
            for view in self._ready.ready_now(actor)
        ]


class JournalDiaryDaySource:
    """One diary day for the ingredients of a ready conversation: done tasks and the entries."""

    def __init__(self, journal_day: JournalDayService) -> None:
        self._journal_day = journal_day

    def diary_day(self, actor: Actor, day: date) -> DiaryDay:
        journal_day = self._journal_day.get_day(
            actor, journal_date=day, include_archived=False, limit=PAGE_SIZE, include_done=True
        )
        return DiaryDay(
            done_task_count=journal_day.done.counts.tasks,
            done_task_titles=tuple(task.title for task in journal_day.done.tasks),
            entry_count=len(journal_day.entries),
            entries=tuple(
                DiaryEntryLine(title=entry.title, summary=entry.summary)
                for entry in journal_day.entries
            ),
            entries_more=journal_day.next_cursor is not None,
        )

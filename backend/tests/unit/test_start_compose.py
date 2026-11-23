"""The day composition against in-memory sources: scopes, counts, rows and bounded paging."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sidekick.shared.types import Actor
from sidekick.start.application.compose import (
    MAX_PAGES,
    PAGE_SIZE,
    TASK_ROW_LIMIT,
    UPCOMING_DAYS,
    AgendaGroupName,
    AgendaItem,
    AgendaPage,
    DayFacts,
    OpenItemsPage,
    ShoppingListRef,
    ShoppingListsPage,
    compose_brief,
)

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
DAY = date(2026, 11, 22)
OWNER = uuid4()


def actor(*scopes: str) -> Actor:
    return Actor(user_id=OWNER, scopes=frozenset(scopes))


def item(group: AgendaGroupName | None, title: str = "T") -> AgendaItem:
    return AgendaItem(
        id=uuid4(),
        kind="task",
        title=title,
        version=1,
        agenda_group=group,
        due_at=None,
        project_title=None,
    )


class FakeAgenda:
    def __init__(self, pages: Sequence[Sequence[AgendaItem]]) -> None:
        self.pages = pages
        self.calls: list[tuple[datetime, int, str | None]] = []

    def agenda_page(
        self, actor: Actor, *, due_to: datetime, limit: int, cursor: str | None
    ) -> AgendaPage:
        self.calls.append((due_to, limit, cursor))
        index = int(cursor or "0")
        more = index + 1 < len(self.pages)
        return AgendaPage(items=self.pages[index], next_cursor=str(index + 1) if more else None)


class FakeJournal:
    def __init__(self) -> None:
        self.days: list[date] = []

    def day_facts(self, actor: Actor, day: date, *, limit: int) -> DayFacts:
        self.days.append(day)
        return DayFacts(entry_count=2, has_summary=True, has_more=False)


class FakeShopping:
    """Two lists; the second spans two item pages."""

    def __init__(self) -> None:
        self.list_ids = [uuid4(), uuid4()]

    def lists_page(self, actor: Actor, *, offset: int, limit: int) -> ShoppingListsPage:
        refs = [
            ShoppingListRef(id=list_id, name=f"L{index}", version=1)
            for index, list_id in enumerate(self.list_ids)
        ]
        return ShoppingListsPage(lists=refs, next_offset=None)

    def open_items_page(
        self, actor: Actor, list_id: UUID, *, offset: int, limit: int
    ) -> OpenItemsPage:
        if list_id == self.list_ids[0]:
            return OpenItemsPage(open_count=3, next_offset=None)
        if offset == 0:
            return OpenItemsPage(open_count=4, next_offset=PAGE_SIZE)
        return OpenItemsPage(open_count=1, next_offset=None)


def compose(
    scopes: tuple[str, ...], agenda: FakeAgenda | None = None, journal: FakeJournal | None = None
):
    return compose_brief(
        actor(*scopes),
        NOW,
        DAY,
        agenda=agenda or FakeAgenda([[]]),
        journal=journal or FakeJournal(),
        shopping=FakeShopping(),
    )


def test_a_part_without_its_read_scope_is_left_out() -> None:
    assert compose(()) == {}
    assert set(compose(("tasks:read",))) == {"tasks"}
    assert set(compose(("journal:read", "shopping:read"))) == {"diary", "shopping"}
    assert set(compose(("tasks:write", "journal:write"))) == set()


def test_a_scope_that_is_missing_never_reaches_its_source() -> None:
    agenda, journal = FakeAgenda([[item("today")]]), FakeJournal()
    compose(("shopping:read",), agenda, journal)
    assert agenda.calls == []
    assert journal.days == []


def test_the_agenda_is_read_up_to_the_upcoming_window_and_counted_by_group() -> None:
    agenda = FakeAgenda(
        [[item("overdue"), item("today"), item("today"), item("upcoming"), item("scheduled_later")]]
    )
    tasks = compose(("tasks:read",), agenda)["tasks"]
    assert agenda.calls == [(NOW + timedelta(days=UPCOMING_DAYS), PAGE_SIZE, None)]
    assert (tasks.overdue_count, tasks.today_count, tasks.upcoming_7d_count) == (1, 2, 1)
    assert [row.agenda_group for row in tasks.items] == ["overdue", "today", "today"]
    assert not tasks.truncated and not tasks.capped


def test_the_task_rows_are_bounded_and_the_overflow_is_flagged() -> None:
    agenda = FakeAgenda([[item("today", f"T{index}") for index in range(TASK_ROW_LIMIT + 3)]])
    tasks = compose(("tasks:read",), agenda)["tasks"]
    assert len(tasks.items) == TASK_ROW_LIMIT
    assert tasks.today_count == TASK_ROW_LIMIT + 3
    assert tasks.truncated


def test_paging_stops_at_the_page_cap_and_says_the_count_is_capped() -> None:
    agenda = FakeAgenda([[item("upcoming")] for _ in range(MAX_PAGES + 5)])
    tasks = compose(("tasks:read",), agenda)["tasks"]
    assert len(agenda.calls) == MAX_PAGES
    assert tasks.upcoming_7d_count == MAX_PAGES
    assert tasks.capped


def test_the_diary_carries_counts_and_never_entry_text() -> None:
    journal = FakeJournal()
    diary = compose(("journal:read",), journal=journal)["diary"]
    assert journal.days == [DAY]
    assert diary.model_dump() == {"entry_count": 2, "has_summary": True, "truncated": False}


def test_the_open_items_of_every_list_are_summed_across_pages() -> None:
    shopping = compose(("shopping:read",))["shopping"]
    assert shopping.open_list_count == 2
    assert [entry.open_item_count for entry in shopping.lists] == [3, 5]
    assert shopping.open_item_count == 8

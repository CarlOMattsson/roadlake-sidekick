"""The diary day's `done` section: day bounds, owner scoping, exclusions, caps and step times."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sidekick.journal.application.day import JournalDayService
from sidekick.shared.auth import AuthService
from sidekick.shared.observability import NoopTelemetryAdapter
from sidekick.shared.persistence.models import DomainRow, ProjectRow, StepRow, TaskRow
from sidekick.shared.types import Actor, new_uuid7
from sidekick.shopping.application.schemas import BatchItem
from sidekick.shopping.application.service import ShoppingService
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow
from sidekick.shopping.persistence.store import ShoppingStore
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.application import TaskService, UpdateTaskCommand
from sidekick.tasks.domain import TaskStatus
from sidekick.work.application.steps_service import StepsService
from tests.db import database_factory
from tests.support.fakes import make_cursor_codec

ALL_SCOPES = frozenset(
    {"journal:read", "tasks:read", "tasks:write", "shopping:read", "shopping:write"}
)
DAY = date(2026, 7, 21)
# Stockholm is UTC+2 in July, so the day runs 2026-07-20T22:00Z up to 2026-07-21T22:00Z.
DAY_START = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)
NOON = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)


@dataclass(slots=True)
class Clock:
    value: datetime = NOON

    def now(self) -> datetime:
        return self.value


@dataclass(slots=True)
class World:
    factory: sessionmaker[Session]
    journal: JournalDayService
    owner: UUID
    other: UUID
    clock: Clock

    def actor(self, owner: UUID | None = None, scopes: frozenset[str] = ALL_SCOPES) -> Actor:
        return Actor(owner or self.owner, scopes)

    def done(self, day: date = DAY, **kwargs: Any) -> Any:
        return self.journal.get_day(self.actor(**kwargs), journal_date=day).done


@pytest.fixture
def world() -> World:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    clock = Clock()
    return World(
        factory=factory,
        journal=JournalDayService(SqlAlchemyStore(factory), clock, make_cursor_codec()),
        owner=auth.provision_user("done-owner", "Owner"),
        other=auth.provision_user("done-other", "Other"),
        clock=clock,
    )


def _task(owner: UUID, title: str, **extra: Any) -> TaskRow:
    completed_at = extra.get("completed_at")
    return TaskRow(
        id=new_uuid7(),
        owner_id=owner,
        title=title,
        status="completed" if completed_at else "todo",
        priority="normal",
        created_at=DAY_START - timedelta(days=3),
        updated_at=DAY_START - timedelta(days=3),
        version=1,
        **extra,
    )


def _step(owner: UUID, task_id: UUID, title: str, **extra: Any) -> StepRow:
    extra.setdefault("status", "completed" if extra.get("completed_at") else "todo")
    return StepRow(
        id=new_uuid7(),
        owner_id=owner,
        task_id=task_id,
        title=title,
        position=0,
        created_at=DAY_START - timedelta(days=3),
        updated_at=DAY_START - timedelta(days=3),
        version=1,
        **extra,
    )


def _shopping_list(
    owner: UUID, name: str = "Veckohandling", archived: bool = False
) -> ShoppingListRow:
    return ShoppingListRow(
        id=new_uuid7(),
        owner_id=owner,
        name=name,
        archived=archived,
        version=1,
        created_at=DAY_START,
        updated_at=DAY_START,
    )


def _item(owner: UUID, list_id: UUID, name: str, **extra: Any) -> ShoppingItemRow:
    purchased_at = extra.get("purchased_at")
    return ShoppingItemRow(
        id=new_uuid7(),
        owner_id=owner,
        list_id=list_id,
        name=name,
        quantity=1,
        purchased=purchased_at is not None,
        version=1,
        created_at=DAY_START - timedelta(days=3),
        updated_at=DAY_START - timedelta(days=3),
        **extra,
    )


def _titles(records: Any) -> list[str]:
    return [record.title for record in records]


@pytest.mark.integration
def test_an_untouched_day_has_empty_lists_zero_counts_and_is_still_a_day(world: World) -> None:
    day = world.journal.get_day(world.actor(), journal_date=DAY)

    assert day.entries == ()
    assert day.next_cursor is None
    assert day.done.tasks == day.done.steps == day.done.purchases == ()
    assert (day.done.counts.tasks, day.done.counts.steps, day.done.counts.purchases) == (0, 0, 0)
    assert day.done.truncated is False


@pytest.mark.integration
def test_the_day_runs_midnight_to_midnight_in_stockholm_in_summer_time(world: World) -> None:
    edge = timedelta(seconds=1)
    with world.factory.begin() as session:
        session.add_all(
            [
                _task(world.owner, "före", completed_at=DAY_START - edge),
                _task(world.owner, "första sekunden", completed_at=DAY_START),
                _task(
                    world.owner,
                    "sista sekunden",
                    completed_at=DAY_START + timedelta(hours=24) - edge,
                ),
                _task(world.owner, "nästa dag", completed_at=DAY_START + timedelta(hours=24)),
            ]
        )

    assert _titles(world.done().tasks) == ["första sekunden", "sista sekunden"]
    assert world.done().counts.tasks == 2
    assert _titles(world.done(DAY + timedelta(days=1)).tasks) == ["nästa dag"]
    assert _titles(world.done(DAY - timedelta(days=1)).tasks) == ["före"]


@pytest.mark.integration
def test_the_clock_change_days_are_23_and_25_hours_long(world: World) -> None:
    # 2026-03-29: Stockholm moves from UTC+1 to UTC+2 at 01:00 UTC, so the day is 23 hours,
    # 2026-03-28T23:00Z up to 2026-03-29T22:00Z.
    spring = datetime(2026, 3, 28, 23, 0, tzinfo=UTC)
    # 2026-10-25: back to UTC+1, a 25-hour day, 2026-10-24T22:00Z up to 2026-10-25T23:00Z.
    autumn = datetime(2026, 10, 24, 22, 0, tzinfo=UTC)
    with world.factory.begin() as session:
        session.add_all(
            [
                _task(world.owner, "vår före", completed_at=spring - timedelta(minutes=1)),
                _task(world.owner, "vår start", completed_at=spring),
                _task(
                    world.owner, "vår slut", completed_at=spring + timedelta(hours=23, minutes=-1)
                ),
                _task(world.owner, "vår nästa", completed_at=spring + timedelta(hours=23)),
                _task(world.owner, "höst före", completed_at=autumn - timedelta(minutes=1)),
                _task(world.owner, "höst start", completed_at=autumn),
                _task(
                    world.owner, "höst slut", completed_at=autumn + timedelta(hours=25, minutes=-1)
                ),
                _task(world.owner, "höst nästa", completed_at=autumn + timedelta(hours=25)),
            ]
        )

    assert _titles(world.done(date(2026, 3, 29)).tasks) == ["vår start", "vår slut"]
    assert _titles(world.done(date(2026, 3, 30)).tasks) == ["vår nästa"]
    assert _titles(world.done(date(2026, 10, 25)).tasks) == ["höst start", "höst slut"]
    assert _titles(world.done(date(2026, 10, 26)).tasks) == ["höst nästa"]


@pytest.mark.integration
def test_only_the_owners_own_records_show_and_another_owner_sees_nothing_of_them(
    world: World,
) -> None:
    other_list = _shopping_list(world.other, "Annans lista")
    own_list = _shopping_list(world.owner)
    other_task = _task(world.other, "annans uppgift", completed_at=NOON)
    own_task = _task(world.owner, "min uppgift", completed_at=NOON)
    with world.factory.begin() as session:
        session.add_all([other_task, own_task, other_list, own_list])
        session.flush()
        session.add_all(
            [
                _step(world.other, other_task.id, "annans steg", completed_at=NOON),
                _step(world.owner, own_task.id, "mitt steg", completed_at=NOON),
                _item(world.other, other_list.id, "annans vara", purchased_at=NOON),
                _item(world.owner, own_list.id, "min vara", purchased_at=NOON),
            ]
        )

    mine = world.done()
    assert (_titles(mine.tasks), _titles(mine.steps), _titles(mine.purchases)) == (
        ["min uppgift"],
        ["mitt steg"],
        ["min vara"],
    )
    theirs = world.done(owner=world.other)
    assert (_titles(theirs.tasks), _titles(theirs.steps), _titles(theirs.purchases)) == (
        ["annans uppgift"],
        ["annans steg"],
        ["annans vara"],
    )
    assert (mine.counts.tasks, mine.counts.steps, mine.counts.purchases) == (1, 1, 1)


@pytest.mark.integration
def test_records_carry_the_fields_the_diary_needs(world: World) -> None:
    domain = DomainRow(
        id=new_uuid7(),
        owner_id=world.owner,
        name="Hemmet",
        status="active",
        created_at=DAY_START,
        updated_at=DAY_START,
        version=1,
    )
    project = ProjectRow(
        id=new_uuid7(),
        owner_id=world.owner,
        domain_id=domain.id,
        title="Sommarstugan",
        status="active",
        created_at=DAY_START,
        updated_at=DAY_START,
        version=1,
    )
    shopping_list = _shopping_list(world.owner, "Måndagshandling")
    with world.factory.begin() as session:
        session.add(domain)
        session.flush()
        session.add(project)
        session.flush()
        task = _task(world.owner, "Måla altanen", completed_at=NOON, project_id=project.id)
        loose = _task(world.owner, "Lös uppgift", completed_at=NOON + timedelta(minutes=1))
        session.add_all([task, loose, shopping_list])
        session.flush()
        step = _step(world.owner, task.id, "Köp färg", completed_at=NOON)
        item = _item(world.owner, shopping_list.id, "Penslar", purchased_at=NOON)
        session.add_all([step, item])

    done = world.done()
    assert [(t.title, t.project_title, t.recurring) for t in done.tasks] == [
        ("Måla altanen", "Sommarstugan", False),
        ("Lös uppgift", None, False),
    ]
    assert done.tasks[0].completed_at == NOON
    assert (done.steps[0].task_id, done.steps[0].task_title) == (task.id, "Måla altanen")
    assert (done.purchases[0].list_id, done.purchases[0].list_title) == (
        shopping_list.id,
        "Måndagshandling",
    )
    assert done.purchases[0].purchased_at == NOON


@pytest.mark.integration
def test_archived_and_trashed_records_and_open_steps_and_wanted_items_are_left_out(
    world: World,
) -> None:
    shopping_list = _shopping_list(world.owner)
    live = _task(world.owner, "levande", completed_at=NOON)
    archived = _task(world.owner, "arkiverad", completed_at=NOON, archived_at=NOON)
    trashed = _task(world.owner, "papperskorg", completed_at=NOON, trashed_at=NOON)
    with world.factory.begin() as session:
        session.add_all([live, archived, trashed, shopping_list])
        session.flush()
        session.add_all(
            [
                _step(world.owner, live.id, "levande steg", completed_at=NOON),
                _step(world.owner, live.id, "arkiverat steg", completed_at=NOON, archived_at=NOON),
                _step(
                    world.owner, live.id, "steg i papperskorgen", completed_at=NOON, trashed_at=NOON
                ),
                _step(world.owner, live.id, "öppet steg"),
                _step(world.owner, live.id, "äldre steg utan klartid", status="completed"),
                _step(world.owner, archived.id, "steg under arkiverad uppgift", completed_at=NOON),
                _step(world.owner, trashed.id, "steg under borttagen uppgift", completed_at=NOON),
                _item(world.owner, shopping_list.id, "köpt vara", purchased_at=NOON),
                _item(
                    world.owner,
                    shopping_list.id,
                    "vara i papperskorgen",
                    purchased_at=NOON,
                    trashed_at=NOON,
                ),
                _item(world.owner, shopping_list.id, "önskad vara"),
            ]
        )

    done = world.done()
    assert _titles(done.tasks) == ["levande"]
    assert _titles(done.steps) == ["levande steg"]
    assert _titles(done.purchases) == ["köpt vara"]
    assert (done.counts.tasks, done.counts.steps, done.counts.purchases) == (1, 1, 1)


@pytest.mark.integration
def test_a_recurring_task_shows_by_its_last_completed_cycle_and_is_marked_recurring(
    world: World,
) -> None:
    recurrence = {"kind": "daily"}
    with world.factory.begin() as session:
        session.add_all(
            [
                # Reopened for the next cycle: open now, completed within the day.
                _task(world.owner, "veckostäd", recurrence=recurrence, last_completed_at=NOON),
                # Completed on another day: not part of this one.
                _task(
                    world.owner,
                    "gammal rutin",
                    recurrence=recurrence,
                    last_completed_at=NOON - timedelta(days=3),
                ),
                # Open, never completed.
                _task(world.owner, "ny rutin", recurrence=recurrence),
            ]
        )

    done = world.done()
    assert [(t.title, t.recurring, t.completed_at) for t in done.tasks] == [
        ("veckostäd", True, NOON)
    ]
    assert world.done(DAY - timedelta(days=3)).counts.tasks == 1


@pytest.mark.integration
def test_a_task_whose_repeat_was_removed_is_not_done_by_its_old_cycle(world: World) -> None:
    with world.factory.begin() as session:
        session.add(_task(world.owner, "inte längre återkommande", last_completed_at=NOON))

    assert world.done().tasks == ()
    assert world.done().counts.tasks == 0


@pytest.mark.integration
def test_a_step_ticked_off_and_opened_again_leaves_the_day_it_was_ticked_off_on(
    world: World,
) -> None:
    steps = StepsService(SqlAlchemyStore(world.factory), world.clock, make_cursor_codec())
    actor = world.actor()
    task = _task(world.owner, "Flytta")
    with world.factory.begin() as session:
        session.add(task)
        session.flush()
        row = _step(world.owner, task.id, "Packa lådor")
        session.add(row)
    assert world.done().steps == ()

    world.clock.value = NOON
    completed = steps.complete_step(actor, row.id, version=1, idempotency_key="step-done-1")
    assert completed.completed_at == NOON
    assert _titles(world.done().steps) == ["Packa lådor"]

    # Opened again the same day: it is no longer done, and the time is cleared.
    world.clock.value = NOON + timedelta(hours=1)
    reopened = steps.update_step(
        actor,
        row.id,
        version=completed.version,
        idempotency_key="step-done-2",
        status=TaskStatus.TODO,
    )
    assert reopened.completed_at is None
    assert world.done().steps == ()
    assert world.done().counts.steps == 0

    # Ticked off the next day: it belongs to that day only.
    world.clock.value = NOON + timedelta(days=1)
    again = steps.update_step(
        actor,
        row.id,
        version=reopened.version,
        idempotency_key="step-done-3",
        status=TaskStatus.COMPLETED,
    )
    assert again.completed_at == world.clock.value
    assert world.done().steps == ()
    assert _titles(world.done(DAY + timedelta(days=1)).steps) == ["Packa lådor"]


@pytest.mark.integration
def test_an_item_bought_and_then_unbought_is_not_done_and_bought_again_counts_at_the_new_time(
    world: World,
) -> None:
    telemetry = NoopTelemetryAdapter()
    service = ShoppingService(ShoppingStore(world.factory, telemetry), world.clock, telemetry)
    actor = world.actor()
    created = service.create_list(actor, "Fredagsmiddag", idempotency_key="shopping-list-1")
    added = service.add_items(
        actor,
        UUID(created["shopping_list"]["id"]),
        [BatchItem(client_ref="a", name="Citron")],
        idempotency_key="shopping-items-1",
    )
    item = added["items"][0]["item"]
    item_id = UUID(item["id"])

    bought = service.set_purchased(
        actor, item_id, purchased=True, version=item["version"], idempotency_key="shopping-buy-1"
    )
    assert _titles(world.done().purchases) == ["Citron"]

    world.clock.value = NOON + timedelta(hours=2)
    undone = service.set_purchased(
        actor,
        item_id,
        purchased=False,
        version=bought["item"]["version"],
        idempotency_key="shopping-buy-2",
    )
    assert world.done().purchases == ()
    assert world.done().counts.purchases == 0

    world.clock.value = NOON + timedelta(hours=3)
    service.set_purchased(
        actor,
        item_id,
        purchased=True,
        version=undone["item"]["version"],
        idempotency_key="shopping-buy-3",
    )
    done = world.done()
    assert [(p.title, p.list_title, p.purchased_at) for p in done.purchases] == [
        ("Citron", "Fredagsmiddag", NOON + timedelta(hours=3))
    ]


@pytest.mark.integration
def test_lists_are_cut_at_fifty_earliest_first_with_the_true_counts(world: World) -> None:
    shopping_list = _shopping_list(world.owner)
    parent = _task(world.owner, "föräldrauppgift")
    with world.factory.begin() as session:
        session.add_all([parent, shopping_list])
        session.flush()
        for index in range(53):
            moment = DAY_START + timedelta(minutes=index)
            session.add(_task(world.owner, f"u{index:02d}", completed_at=moment))
            session.add(_step(world.owner, parent.id, f"s{index:02d}", completed_at=moment))
        for index in range(7):
            session.add(
                _item(
                    world.owner,
                    shopping_list.id,
                    f"v{index}",
                    purchased_at=DAY_START + timedelta(minutes=index),
                )
            )

    done = world.done()
    assert (len(done.tasks), len(done.steps), len(done.purchases)) == (50, 50, 7)
    assert (done.counts.tasks, done.counts.steps, done.counts.purchases) == (53, 53, 7)
    assert done.truncated is True
    assert _titles(done.tasks)[0] == "u00" and _titles(done.tasks)[-1] == "u49"
    assert _titles(done.steps)[-1] == "s49"
    assert [task.completed_at for task in done.tasks] == sorted(t.completed_at for t in done.tasks)


@pytest.mark.integration
def test_exactly_fifty_is_not_truncated(world: World) -> None:
    with world.factory.begin() as session:
        session.add_all(
            _task(world.owner, f"u{index}", completed_at=DAY_START + timedelta(minutes=index))
            for index in range(50)
        )

    done = world.done()
    assert (len(done.tasks), done.counts.tasks, done.truncated) == (50, 50, False)


@pytest.mark.integration
def test_a_reader_without_the_other_domains_read_scope_gets_those_lists_empty(
    world: World,
) -> None:
    shopping_list = _shopping_list(world.owner)
    task = _task(world.owner, "hemlig uppgift", completed_at=NOON)
    with world.factory.begin() as session:
        session.add_all([task, shopping_list])
        session.flush()
        session.add_all(
            [
                _step(world.owner, task.id, "hemligt steg", completed_at=NOON),
                _item(world.owner, shopping_list.id, "hemlig vara", purchased_at=NOON),
            ]
        )

    only_journal = world.done(scopes=frozenset({"journal:read"}))
    assert only_journal.tasks == only_journal.steps == only_journal.purchases == ()
    assert (
        only_journal.counts.tasks,
        only_journal.counts.steps,
        only_journal.counts.purchases,
    ) == (
        0,
        0,
        0,
    )
    tasks_only = world.done(scopes=frozenset({"journal:read", "tasks:read"}))
    assert (len(tasks_only.tasks), len(tasks_only.steps), len(tasks_only.purchases)) == (1, 1, 0)
    shopping_only = world.done(scopes=frozenset({"journal:read", "shopping:read"}))
    assert (len(shopping_only.tasks), len(shopping_only.steps), len(shopping_only.purchases)) == (
        0,
        0,
        1,
    )


@pytest.mark.integration
def test_items_of_an_archived_list_still_count_because_they_were_bought_that_day(
    world: World,
) -> None:
    archived_list = _shopping_list(world.owner, "Klar lista", archived=True)
    with world.factory.begin() as session:
        session.add(archived_list)
        session.flush()
        session.add(_item(world.owner, archived_list.id, "Kaffe", purchased_at=NOON))

    assert _titles(world.done().purchases) == ["Kaffe"]


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["project", "domain"])
def test_done_tasks_and_steps_of_a_trashed_parent_are_left_out_until_it_is_restored(
    world: World, kind: str
) -> None:
    domain = DomainRow(
        id=new_uuid7(),
        owner_id=world.owner,
        name="Hemmet",
        status="active",
        created_at=DAY_START,
        updated_at=DAY_START,
        version=1,
    )
    project = ProjectRow(
        id=new_uuid7(),
        owner_id=world.owner,
        domain_id=domain.id,
        title="Sommarstugan",
        status="active",
        created_at=DAY_START,
        updated_at=DAY_START,
        version=1,
    )
    parent = project if kind == "project" else domain
    context: dict[str, Any] = (
        {"project_id": project.id} if kind == "project" else {"domain_id": domain.id}
    )
    child = _task(world.owner, "under förälder", completed_at=NOON, **context)
    loose = _task(world.owner, "lös", completed_at=NOON)
    with world.factory.begin() as session:
        session.add(domain)
        session.flush()
        session.add_all([project, child, loose])
        session.flush()
        session.add_all(
            [
                _step(world.owner, child.id, "steg under", completed_at=NOON),
                _step(world.owner, loose.id, "steg lös", completed_at=NOON),
            ]
        )

    def set_trashed(value: datetime | None) -> None:
        with world.factory.begin() as session:
            session.get(type(parent), parent.id).trashed_at = value  # type: ignore[union-attr]

    set_trashed(NOON)
    hidden = world.done()
    assert _titles(hidden.tasks) == ["lös"]
    assert _titles(hidden.steps) == ["steg lös"]
    assert (hidden.counts.tasks, hidden.counts.steps) == (1, 1)

    set_trashed(None)
    shown = world.done()
    assert sorted(_titles(shown.tasks)) == ["lös", "under förälder"]
    assert sorted(_titles(shown.steps)) == ["steg lös", "steg under"]
    assert (shown.counts.tasks, shown.counts.steps) == (2, 2)


@pytest.mark.integration
def test_undoing_a_recurring_completion_removes_it_from_the_day_and_restores_the_due_date(
    world: World,
) -> None:
    tasks = TaskService(SqlAlchemyStore(world.factory), world.clock, make_cursor_codec())
    actor = world.actor()
    due = NOON + timedelta(hours=6)
    task = tasks.create(
        actor,
        title="veckostäd",
        idempotency_key="done-undo-create",
        due_at=due,
        recurrence={"frequency": "daily"},
    )
    completed = tasks.complete(
        actor, task.id, version=task.version, idempotency_key="done-undo-complete"
    )
    assert _titles(world.done().tasks) == ["veckostäd"]

    undone = tasks.update(
        actor,
        task.id,
        version=completed.version,
        idempotency_key="done-undo-undo",
        command=UpdateTaskCommand(due_at=due, last_completed_at=None),
    )

    assert undone.due_at == due
    assert undone.last_completed_at is None
    assert world.done().tasks == ()
    assert world.done().counts.tasks == 0

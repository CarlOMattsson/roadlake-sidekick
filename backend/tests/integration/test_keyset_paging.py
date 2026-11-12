"""Keyset paging: rows added or removed between two pages never repeat or hide a surviving row.

The Work list, the Task list, the Project list and the Contact list all continue after the sort
key of the last row served (not after a row count), and a cursor only works for the actor and
the filter set it was issued for. See docs/architecture/pagination.md for the model.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert

from sidekick.contacts.application.service import ContactService
from sidekick.projects.application.service import ProjectService
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.persistence.models import ContactRow, ProjectRow, TaskRow
from sidekick.shared.types import MAX_CURSOR_LENGTH, Actor, SystemClock, new_uuid7
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.application.service import TaskService
from sidekick.work.application.models import WorkQuery
from tests.support.work_paging import NOW, SCOPES, WorkFixture


def _new_task(owner_id: UUID, title: str, when: datetime, **extra: Any) -> dict[str, Any]:
    return {
        "id": new_uuid7(),
        "owner_id": owner_id,
        "title": title,
        "status": "todo",
        "priority": "normal",
        "created_at": when,
        "updated_at": when,
        "version": 1000,
        **extra,
    }


def _contact_row(owner_id: UUID, number: int) -> dict[str, Any]:
    return {
        "id": new_uuid7(),
        "owner_id": owner_id,
        "display_name": f"Person {number:02}",
        "display_name_key": f"person {number:02}",
        "archived": False,
        "created_at": NOW,
        "updated_at": NOW,
        "version": 1,
    }


def _walk_with_changes(
    fixture: WorkFixture, query: WorkQuery, between: Callable[[list[UUID]], None]
) -> tuple[list[UUID], list[UUID]]:
    """Page through `query`; `between` runs once after the first page.

    Returns every id served and the ids of the first page.
    """

    first = fixture.work_lists.work_list_page(fixture.actor, query)
    assert first.next_cursor is not None
    first_ids = [item.id for item in first.items]
    between(first_ids)
    ids = list(first_ids)
    cursor: str | None = first.next_cursor
    while cursor is not None:
        page = fixture.work_lists.work_list_page(fixture.actor, replace(query, cursor=cursor))
        ids.extend(item.id for item in page.items)
        cursor = page.next_cursor
    return ids, first_ids


@pytest.mark.integration
@pytest.mark.parametrize("sort", ["updated_desc", "due_asc", "title_asc", "priority_desc"])
def test_work_list_survives_inserts_and_deletes_between_pages(sort: str) -> None:
    fixture = WorkFixture()
    fixture.seed(20, 40)
    query = WorkQuery(sort=sort, limit=10)  # type: ignore[arg-type]
    before = [item.id for item in fixture.walk(replace(query, limit=100))]
    removed: list[UUID] = []

    def between(served: list[UUID]) -> None:
        # Rows are added that sort before and after the cursor; rows already served and rows
        # not yet served are moved to the trash.
        # Only Tasks: trashing a Project would hide its Tasks as well.
        tasks = set(fixture.ids(TaskRow))
        unserved = [row for row in before if row not in served and row in tasks]
        removed.extend([row for row in served if row in tasks][:2] + unserved[:2] + unserved[-2:])
        with fixture.factory.begin() as session:
            session.execute(
                insert(TaskRow),
                [
                    _new_task(
                        fixture.owner_id,
                        f"Aaa {index}" if index % 2 else f"Zzz {index}",
                        NOW + timedelta(minutes=index),
                        due_at=NOW - timedelta(days=30 * (index + 1)),
                        domain_id=fixture.domain_id,
                    )
                    for index in range(8)
                ],
            )
            session.execute(update(TaskRow).where(TaskRow.id.in_(removed)).values(trashed_at=NOW))

    ids, first_page = _walk_with_changes(fixture, query, between)

    assert len(ids) == len(set(ids)), "a row was served twice"
    survivors_after_cursor = [row for row in before if row not in first_page and row not in removed]
    assert set(survivors_after_cursor) <= set(ids), "a surviving row was skipped"


@pytest.mark.integration
def test_task_list_survives_inserts_and_deletes_between_pages() -> None:
    fixture = WorkFixture()
    fixture.seed(0, 30)
    tasks = TaskService(SqlAlchemyStore(fixture.factory), SystemClock(), fixture.codec)
    actor = fixture.actor
    first = tasks.list(actor, limit=8)
    assert first.next_cursor is not None
    served = {task.id for task in first.items}
    everyone = {task.id for task in tasks.list(actor, limit=100).items}

    with fixture.factory.begin() as session:
        session.execute(
            insert(TaskRow),
            [_new_task(fixture.owner_id, f"Ny {n}", NOW + timedelta(minutes=n)) for n in range(6)],
        )
        gone = sorted(everyone - served, key=str)[:3] + sorted(served, key=str)[:2]
        session.execute(delete(TaskRow).where(TaskRow.id.in_(gone)))

    seen = list(served)
    cursor: str | None = first.next_cursor
    while cursor is not None:
        page = tasks.list(actor, limit=8, cursor=cursor)
        seen.extend(task.id for task in page.items)
        cursor = page.next_cursor

    assert len(seen) == len(set(seen))
    assert (everyone - served - set(gone)) <= set(seen)


@pytest.mark.integration
def test_contact_list_survives_inserts_and_deletes_between_pages() -> None:
    fixture = WorkFixture()
    contacts = ContactService(SqlAlchemyStore(fixture.factory), SystemClock(), fixture.codec)
    actor = Actor(fixture.owner_id, frozenset({"contacts:read"}))
    with fixture.factory.begin() as session:
        session.execute(
            insert(ContactRow), [_contact_row(fixture.owner_id, n) for n in range(2, 40, 2)]
        )
    first = contacts.list(actor, limit=6)
    assert first.next_cursor is not None
    served = [contact.id for contact in first.items]
    everyone = [contact.id for contact in contacts.list(actor, limit=100).items]

    with fixture.factory.begin() as session:
        # New names that sort both before and after the cursor.
        session.execute(
            insert(ContactRow), [_contact_row(fixture.owner_id, n) for n in (1, 3, 5, 25, 27)]
        )
        gone = [served[0], everyone[8], everyone[12]]
        session.execute(delete(ContactRow).where(ContactRow.id.in_(gone)))

    seen = list(served)
    cursor: str | None = first.next_cursor
    while cursor is not None:
        page = contacts.list(actor, limit=6, cursor=cursor)
        seen.extend(contact.id for contact in page.items)
        cursor = page.next_cursor

    assert len(seen) == len(set(seen))
    assert (set(everyone) - set(served) - set(gone)) <= set(seen)
    assert not (set(gone) - set(served)) & set(seen)


@pytest.mark.integration
def test_foreign_malformed_and_legacy_cursors_are_rejected() -> None:
    fixture = WorkFixture()
    fixture.seed(12, 12)
    store = SqlAlchemyStore(fixture.factory)
    tasks = TaskService(store, SystemClock(), fixture.codec)
    projects = ProjectService(store, SystemClock(), fixture.codec)
    actor = fixture.actor
    other = Actor(fixture.other_id, SCOPES)

    cursor = tasks.list(actor, limit=5).next_cursor
    assert cursor is not None
    # Another filter set, another actor, another list and tampering are all validation errors.
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        tasks.list(actor, limit=5, cursor=cursor, unsorted=True)
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        tasks.list(other, limit=5, cursor=cursor)
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        projects.list(actor, limit=5, cursor=cursor)
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        tasks.list(actor, limit=5, cursor=cursor[:-2] + "AA")
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        tasks.list(actor, limit=5, cursor="garbage")
    # A legacy offset cursor, correctly signed for this actor and filter, is no longer accepted.
    legacy = fixture.codec.encode(actor.user_id, 5, "tasks:v1:project=*:process=*:status=*")
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        tasks.list(actor, limit=5, cursor=legacy)


@pytest.mark.integration
def test_signed_cursor_with_a_forged_position_is_rejected_not_a_server_error() -> None:
    fixture = WorkFixture()
    fixture.seed(3, 12)
    tasks = TaskService(SqlAlchemyStore(fixture.factory), SystemClock(), fixture.codec)
    actor = fixture.actor
    key = "tasks:v1:project=*:process=*:status=*"
    forged: list[tuple[Any, ...]] = [
        (UUID(int=1), UUID(int=2)),  # wrong type for the timestamp
        ("not a time", UUID(int=2)),
        (NOW, "not an id"),
        (NOW,),  # wrong arity
        (None, UUID(int=2)),  # NULL where none is allowed
        (datetime(2026, 1, 1), UUID(int=2)),  # naive timestamp
    ]
    for position in forged:
        cursor = fixture.codec.encode_keyset(actor.user_id, position, key)
        with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
            tasks.list(actor, limit=5, cursor=cursor)
    # A well-formed position from the very same codec is accepted.
    good = fixture.codec.encode_keyset(actor.user_id, (NOW, UUID(int=2)), key)
    assert tasks.list(actor, limit=5, cursor=good).items is not None


@pytest.mark.integration
def test_work_cursor_is_bound_to_its_sort_and_filter() -> None:
    fixture = WorkFixture()
    fixture.seed(10, 20)
    query = WorkQuery(sort="due_asc", limit=5)
    cursor = fixture.work_lists.work_list_page(fixture.actor, query).next_cursor
    assert cursor is not None
    for other_query in (
        replace(query, sort="title_asc"),
        replace(query, kind="task"),
        replace(query, status="todo"),
        replace(query, group="kind"),
    ):
        with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
            fixture.work_lists.work_list_page(fixture.actor, replace(other_query, cursor=cursor))


@pytest.mark.integration
def test_today_walk_is_stable_when_a_task_is_added_between_pages() -> None:
    fixture = WorkFixture()
    fixture.seed(0, 60)
    first = fixture.work_lists.work_today_page(fixture.actor, limit=4)
    assert first.next_cursor is not None
    with fixture.factory.begin() as session:
        session.execute(
            insert(TaskRow),
            [_new_task(fixture.owner_id, "Brådskande", NOW - timedelta(days=90))],
        )
    seen = [item.id for item in first.items]
    cursor: str | None = first.next_cursor
    while cursor is not None:
        page = fixture.work_lists.work_today_page(fixture.actor, limit=4, cursor=cursor)
        seen.extend(item.id for item in page.items)
        cursor = page.next_cursor
    assert len(seen) == len(set(seen))


@pytest.mark.integration
def test_project_list_never_repeats_a_project_with_equal_timestamps() -> None:
    """Many rows can share an `updated_at`; the id tiebreak keeps the order total."""

    fixture = WorkFixture()
    with fixture.factory.begin() as session:
        session.execute(
            insert(ProjectRow),
            [
                {
                    "id": new_uuid7(),
                    "owner_id": fixture.owner_id,
                    "domain_id": fixture.domain_id,
                    "title": f"P{n}",
                    "status": "active",
                    "created_at": NOW,
                    "updated_at": NOW,
                    "version": 1,
                }
                for n in range(23)
            ],
        )
    projects = ProjectService(SqlAlchemyStore(fixture.factory), SystemClock(), fixture.codec)
    seen: list[UUID] = []
    cursor: str | None = None
    while True:
        page = projects.list(fixture.actor, limit=5, cursor=cursor)
        seen.extend(project.id for project in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 23


@pytest.mark.integration
@pytest.mark.parametrize(
    "sort",
    ["updated_desc", "due_asc", "not_before_asc", "estimate_asc", "title_asc", "priority_desc"],
)
@pytest.mark.parametrize("group", ["none", "kind", "status", "context"])
def test_small_pages_reproduce_the_whole_list_in_every_sort_and_group(
    sort: str, group: str
) -> None:
    fixture = WorkFixture()
    fixture.seed(15, 45)
    query = WorkQuery(sort=sort, group=group, limit=100)  # type: ignore[arg-type]

    whole = [(item.kind, item.id) for item in fixture.walk(query)]
    paged = [(item.kind, item.id) for item in fixture.walk(replace(query, limit=7))]

    assert paged == whole
    assert len(whole) == len(set(whole)) > 50


@pytest.mark.integration
@pytest.mark.parametrize("character", ["a", "\x01", '"', "\\", "\U00020000"])
def test_contacts_with_maximum_length_names_keep_paging(character: str) -> None:
    """A 200-character name (4-byte characters too) fits the cursor, and paging goes on."""

    fixture = WorkFixture()
    contacts = ContactService(SqlAlchemyStore(fixture.factory), SystemClock(), fixture.codec)
    actor = Actor(fixture.owner_id, frozenset({"contacts:read"}))
    names = [character * 199 + suffix for suffix in "bcdefg"]
    with fixture.factory.begin() as session:
        rows = [_contact_row(fixture.owner_id, 0) | {"display_name": name} for name in names]
        for row in rows:
            row["display_name_key"] = row["display_name"]
        session.execute(insert(ContactRow), rows)

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = contacts.list(actor, limit=2, cursor=cursor)
        seen.extend(contact.display_name for contact in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
        assert len(cursor) <= MAX_CURSOR_LENGTH
        with pytest.raises(InvalidInputError):  # still bound to its filter
            contacts.list(actor, limit=2, cursor=cursor, include_archived=True)

    assert seen == names


@pytest.mark.integration
@pytest.mark.parametrize("character", ["a", "\x01", '"', "\\", "\U00020000"])
def test_work_titles_of_maximum_length_keep_paging_in_title_order(character: str) -> None:
    fixture = WorkFixture()
    titles = [character * 199 + suffix for suffix in "bcdefg"]
    with fixture.factory.begin() as session:
        session.execute(
            insert(TaskRow),
            [_new_task(fixture.owner_id, title, NOW) for title in titles],
        )
    query = WorkQuery(kind="task", sort="title_asc", limit=2)

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = fixture.work_lists.work_list_page(fixture.actor, replace(query, cursor=cursor))
        seen.extend(item.title for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
        assert len(cursor) <= MAX_CURSOR_LENGTH

    assert seen == titles


@pytest.mark.integration
def test_text_keys_that_fold_longer_than_the_cut_off_still_page_without_gaps() -> None:
    """NFKC grows these titles past 200 characters; ties beyond the cut fall to the id."""

    fixture = WorkFixture()
    titles = [("\ufdfa" * 40) + str(n) for n in range(5)]  # one character folds to eighteen
    with fixture.factory.begin() as session:
        session.execute(
            insert(TaskRow), [_new_task(fixture.owner_id, title, NOW) for title in titles]
        )
    query = WorkQuery(kind="task", sort="title_asc", limit=2)

    seen = [item.id for item in fixture.walk(query)]

    assert len(seen) == len(set(seen)) == 5

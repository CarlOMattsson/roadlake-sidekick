"""Work lists filter, sort and page in the database, however many records the owner has.

Every test seeds well over 1 000 Projects and Tasks with bulk inserts and reads them back through
the public `ContextService` use cases (the ones the MCP tools and REST routes share).
"""

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.dialects.postgresql import insert

from sidekick.shared.errors import PermissionDeniedError
from sidekick.shared.persistence.models import (
    ActionRow,
    ProjectRow,
    ProjectTagRow,
    StepRow,
    TaskRow,
    TaskTagRow,
    WorkTagRow,
)
from sidekick.shared.types import Actor, new_uuid7
from sidekick.work.application.models import WorkQuery, WorkRow
from tests.support.work_paging import (
    NOW,
    SCOPES,
    WorkFixture,
)

PROJECTS = 1_150
TASKS = 1_250


@pytest.mark.integration
def test_full_page_walk_over_a_thousand_records_has_no_gaps_or_duplicates() -> None:
    fixture = WorkFixture()
    fixture.seed(PROJECTS, TASKS)
    expected = len(fixture.ids(ProjectRow)) + len(fixture.ids(TaskRow)) + 1  # + the Domain

    items = fixture.walk(WorkQuery(limit=100))

    ids = [item.id for item in items]
    assert len(ids) == expected == PROJECTS + TASKS + 1
    assert len(set(ids)) == len(ids)
    assert {item.kind for item in items} == {"domain", "project", "task"}
    # Default order is `updated_desc`: the last change, then id, both descending. The seed gives
    # every record a version and a time that do not rank the records alike.
    changed = fixture.updated_at_by_id()
    assert [(changed[item.id], str(item.id)) for item in items] == sorted(
        ((changed[item.id], str(item.id)) for item in items), reverse=True
    )


@pytest.mark.integration
def test_title_sorted_walk_of_tasks_is_complete_and_ordered() -> None:
    fixture = WorkFixture()
    fixture.seed(PROJECTS, TASKS)

    items = fixture.walk(WorkQuery(kind="task", sort="title_asc", limit=100))

    assert len(items) == len({item.id for item in items}) == TASKS
    titles = [item.title.casefold() for item in items]
    assert titles == sorted(titles)


@pytest.mark.integration
def test_oldest_matching_project_and_task_are_found() -> None:
    fixture = WorkFixture()
    fixture.seed(PROJECTS, TASKS)

    projects = fixture.walk(WorkQuery(kind="project", q="gammal nål"))
    tasks = fixture.walk(WorkQuery(kind="task", q="GAMMAL UPPGIFT"))

    assert [item.title for item in projects] == ["Gammal nål"]
    assert [item.title for item in tasks] == ["Gammal uppgift"]


@pytest.mark.integration
def test_status_priority_and_project_filters_see_every_record() -> None:
    fixture = WorkFixture()
    fixture.seed(PROJECTS, TASKS)
    with fixture.factory() as session:
        completed = session.query(TaskRow).filter(TaskRow.status == "completed").count()
        in_project = session.query(TaskRow).filter(TaskRow.project_id.is_not(None)).count()
        project_id = (
            session.query(TaskRow.project_id).filter(TaskRow.project_id.is_not(None)).first()
        )
    assert project_id is not None

    done = fixture.walk(WorkQuery(kind="task", status="completed", limit=50))
    in_a_project = fixture.walk(WorkQuery(project_id=project_id[0], limit=50))
    normal = fixture.walk(WorkQuery(kind="task", priority="normal", limit=100))

    assert len(done) == completed
    assert {item.project_id for item in in_a_project} == {project_id[0]}
    assert len(normal) == TASKS
    assert 0 < in_project < TASKS


@pytest.mark.integration
def test_tag_filter_finds_the_oldest_tagged_records() -> None:
    fixture = WorkFixture()
    fixture.seed(PROJECTS, TASKS)
    tag_id, other_tag_id = new_uuid7(), new_uuid7()
    oldest_project = fixture.ids(ProjectRow)
    with fixture.factory() as session:
        project = (
            session.query(ProjectRow.id).order_by(ProjectRow.updated_at.asc()).limit(1).scalar()
        )
        task = session.query(TaskRow.id).order_by(TaskRow.updated_at.asc()).limit(1).scalar()
    assert project in oldest_project
    with fixture.factory.begin() as session:
        session.execute(
            insert(WorkTagRow),
            [
                {
                    "id": identifier,
                    "owner_id": fixture.owner_id,
                    "slug": slug,
                    "label": slug,
                    "created_at": NOW,
                    "updated_at": NOW,
                    "version": 1,
                }
                for identifier, slug in ((tag_id, "viktig"), (other_tag_id, "hemma"))
            ],
        )
        session.execute(
            insert(ProjectTagRow),
            [
                {
                    "owner_id": fixture.owner_id,
                    "tag_id": t,
                    "project_id": project,
                    "created_at": NOW,
                }
                for t in (tag_id, other_tag_id)
            ],
        )
        session.execute(
            insert(TaskTagRow),
            [{"owner_id": fixture.owner_id, "tag_id": tag_id, "task_id": task, "created_at": NOW}],
        )

    any_match = fixture.walk(WorkQuery(tags=("viktig",)))
    all_match = fixture.walk(WorkQuery(tags=("viktig", "hemma"), tag_match="all"))

    assert {item.id for item in any_match} == {project, task}
    assert {tuple(item.tags) for item in any_match} == {("hemma", "viktig"), ("viktig",)}
    assert [item.id for item in all_match] == [project]


@pytest.mark.integration
def test_steps_and_actions_of_the_oldest_task_are_listed() -> None:
    fixture = WorkFixture()
    fixture.seed(PROJECTS, TASKS)
    with fixture.factory() as session:
        task = session.query(TaskRow.id).order_by(TaskRow.updated_at.asc()).limit(1).scalar()
    step_id = new_uuid7()
    with fixture.factory.begin() as session:
        session.execute(
            insert(StepRow),
            [
                {
                    "id": step_id,
                    "owner_id": fixture.owner_id,
                    "task_id": task,
                    "title": "Steg ett",
                    "status": "todo",
                    "position": 0,
                    "created_at": NOW,
                    "updated_at": NOW,
                    "version": 1,
                }
            ],
        )
        session.execute(
            insert(ActionRow),
            [
                {
                    "id": new_uuid7(),
                    "owner_id": fixture.owner_id,
                    "step_id": step_id,
                    "title": "Åtgärd ett",
                    "status": "open",
                    "position": 0,
                    "created_at": NOW,
                    "updated_at": NOW,
                    "version": 1,
                }
            ],
        )

    steps = fixture.walk(WorkQuery(kind="step"))
    actions = fixture.walk(WorkQuery(kind="action"))

    assert [(item.title, item.parent_id) for item in steps] == [("Steg ett", task)]
    assert [(item.title, item.parent_id) for item in actions] == [("Åtgärd ett", step_id)]


@pytest.mark.integration
def test_other_owners_records_never_appear() -> None:
    fixture = WorkFixture()
    fixture.seed(3, 3)
    fixture.seed(1_100, 1_100, owner_id=fixture.other_id)

    items = fixture.walk(WorkQuery(limit=100))

    assert len(items) == 3 + 3 + 1
    with fixture.factory() as session:
        theirs = {
            *session.scalars(
                ProjectRow.__table__.select()
                .with_only_columns(ProjectRow.id)
                .where(ProjectRow.owner_id == fixture.other_id)
            )
        }
    assert not theirs & {item.id for item in items}


@pytest.mark.integration
def test_agenda_and_today_cover_overdue_tasks_beyond_the_thousand_newest() -> None:
    fixture = WorkFixture()
    fixture.seed(PROJECTS, TASKS)
    overdue = sum(1 for index in range(TASKS) if index % 10 == 0)
    due_today = sum(1 for index in range(TASKS) if index % 10 == 1)

    cursor: str | None = None
    seen: list[WorkRow] = []
    totals: set[tuple[int, int, int]] = set()
    for _ in range(20):
        today = fixture.work_lists.work_today_page(fixture.actor, limit=100, cursor=cursor)
        totals.add((today.total, today.overdue_total, today.today_total))
        seen.extend(today.items)
        cursor = today.next_cursor
        if cursor is None:
            break

    assert totals == {(overdue + due_today, overdue, due_today)}
    assert len({item.id for item in seen}) == len(seen) == overdue + due_today
    groups = [item.agenda_group for item in seen]
    assert groups == ["today"] * due_today + ["overdue"] * overdue
    overdue_due = [
        item.due_at for item in seen if item.agenda_group == "overdue" and item.due_at is not None
    ]
    assert overdue_due == sorted(overdue_due)
    # The oldest Task by update time (index 0) is the most recently overdue, so it ends the list.
    assert seen[-1].title == "Gammal uppgift"

    agenda_items: list[WorkRow] = []
    cursor = None
    for _ in range(20):
        page = fixture.work_lists.work_agenda_page(
            fixture.actor, WorkQuery(kind="task", sort="due_asc", limit=100, cursor=cursor)
        )
        agenda_items.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len({item.id for item in agenda_items}) == len(agenda_items)
    assert {item.agenda_group for item in agenda_items} == {"overdue", "today"}
    assert len(agenda_items) == overdue + due_today


@pytest.mark.integration
def test_statement_count_per_page_does_not_grow_with_the_number_of_records() -> None:
    fixture = WorkFixture()
    fixture.seed(20, 40)
    queries: dict[str, WorkQuery] = {
        # One kind per query, so the records a page names (and the lookups it needs) are alike.
        "projects": WorkQuery(kind="project", limit=10),
        "tasks": WorkQuery(kind="task", sort="due_asc", limit=10),
    }

    def measure() -> dict[str, int]:
        counts: dict[str, int] = {}
        for name, query in queries.items():
            with fixture.count_statements() as statements:
                first = fixture.work_lists.work_list_page(fixture.actor, query)
            assert first.next_cursor is not None
            counts[name] = len(statements)
            with fixture.count_statements() as statements:
                fixture.work_lists.work_list_page(
                    fixture.actor, replace(query, cursor=first.next_cursor)
                )
            counts[name + " (page 2)"] = len(statements)
        with fixture.count_statements() as statements:
            fixture.work_lists.work_agenda_page(fixture.actor, WorkQuery(sort="due_asc", limit=10))
        counts["agenda"] = len(statements)
        with fixture.count_statements() as statements:
            fixture.work_lists.work_today_page(fixture.actor, limit=10)
        counts["today"] = len(statements)
        return counts

    few = measure()
    fixture.seed(PROJECTS, TASKS)
    many = measure()

    print(f"statements per page, 60 records: {few}; {PROJECTS + TASKS} records: {many}")
    assert many == few
    assert max(many.values()) <= 10


@pytest.mark.integration
def test_cursor_is_a_keyset_position_and_bad_cursors_are_rejected() -> None:
    fixture = WorkFixture()
    fixture.seed(30, 30)
    query = WorkQuery(limit=10)

    first = fixture.work_lists.work_list_page(fixture.actor, query)

    assert first.next_cursor is not None
    # The cursor is a keyset position (last change, id, kind of the last record served), not an
    # offset.
    position = fixture.codec.decode_keyset(
        fixture.owner_id,
        first.next_cursor,
        "work:v2:" + query.key(),
        kinds=(datetime, UUID, str),
    )
    changed = fixture.updated_at_by_id()
    assert position == (
        changed[first.items[-1].id],
        first.items[-1].id,
        first.items[-1].kind,
    )
    with pytest.raises(ValueError, match="invalid pagination cursor"):
        fixture.work_lists.work_list_page(fixture.actor, replace(query, cursor="garbage"))
    with pytest.raises(ValueError, match="invalid pagination cursor"):
        fixture.work_lists.work_list_page(
            fixture.actor, replace(query, cursor=first.next_cursor, kind="task")
        )
    stranger = Actor(fixture.other_id, SCOPES)
    with pytest.raises(ValueError, match="invalid pagination cursor"):
        fixture.work_lists.work_list_page(stranger, replace(query, cursor=first.next_cursor))


@pytest.mark.integration
def test_work_reads_require_the_tasks_read_scope() -> None:
    fixture = WorkFixture()
    fixture.seed(2, 2)
    unscoped = Actor(fixture.owner_id, frozenset({"projects:read"}))

    with pytest.raises(PermissionDeniedError):
        fixture.work_lists.work_list_page(unscoped, WorkQuery())
    with pytest.raises(PermissionDeniedError):
        fixture.work_lists.work_agenda_page(unscoped, WorkQuery())
    with pytest.raises(PermissionDeniedError):
        fixture.work_lists.work_today_page(unscoped, limit=10)


@pytest.mark.integration
def test_sort_and_group_orders() -> None:
    fixture = WorkFixture()
    project_id, beta, cesar, adam, step_id = (new_uuid7() for _ in range(5))
    # Hours before NOW: cesar changed last, then Beta, then Adam, whatever their versions.
    hours_ago = {cesar: 1, beta: 2, adam: 3}

    def task(
        identifier: UUID, title: str, status: str, priority: str, version: int, **extra: Any
    ) -> dict[str, Any]:
        return {
            "id": identifier,
            "owner_id": fixture.owner_id,
            "title": title,
            "status": status,
            "priority": priority,
            "created_at": NOW,
            "updated_at": NOW - timedelta(hours=hours_ago[identifier]),
            "version": version,
            "domain_id": fixture.domain_id,
            **extra,
        }

    with fixture.factory.begin() as session:
        session.execute(
            insert(ProjectRow),
            [
                {
                    "id": project_id,
                    "owner_id": fixture.owner_id,
                    "domain_id": fixture.domain_id,
                    "title": "Alfa",
                    "status": "active",
                    "created_at": NOW,
                    "updated_at": NOW,
                    "version": 3,
                }
            ],
        )
        session.execute(
            insert(TaskRow),
            [
                task(beta, "Beta", "blocked", "normal", 1, due_at=NOW),
                task(cesar, "cesar", "todo", "urgent", 2),
                task(adam, "Adam", "todo", "low", 4, due_at=NOW - timedelta(days=1)),
            ],
        )
        session.execute(
            insert(StepRow),
            [
                {
                    "id": step_id,
                    "owner_id": fixture.owner_id,
                    "task_id": beta,
                    "title": "Alpha",
                    "status": "todo",
                    "position": 0,
                    "created_at": NOW,
                    "updated_at": NOW,
                    "version": 2,
                }
            ],
        )

    def titles(**options: Any) -> list[str]:
        return [item.title for item in fixture.walk(WorkQuery(**options))]

    # Group by kind (code point order of the kind), then case-insensitive title.
    assert titles(sort="title_asc", group="kind") == [
        "Hem",
        "Alfa",
        "Alpha",
        "Adam",
        "Beta",
        "cesar",
    ]
    # A missing due date sorts last.
    assert titles(kind="task", sort="due_asc") == ["Adam", "Beta", "cesar"]
    assert titles(kind="task", sort="priority_desc") == ["cesar", "Beta", "Adam"]
    assert titles(kind="task", sort="title_asc", group="status") == ["Beta", "Adam", "cesar"]
    # `updated_desc` orders by the last change, newest first (not by version: Adam has the
    # highest version and the oldest change).
    assert titles(kind="task") == ["cesar", "Beta", "Adam"]
    assert titles(kind="task", sort="title_asc", group="context") == ["Adam", "Beta", "cesar"]


def _insert_projects(fixture: WorkFixture, titles: list[str]) -> None:
    with fixture.factory.begin() as session:
        session.execute(
            insert(ProjectRow),
            [
                {
                    "id": new_uuid7(),
                    "owner_id": fixture.owner_id,
                    "domain_id": fixture.domain_id,
                    "title": title,
                    "status": "active",
                    "created_at": NOW,
                    "updated_at": NOW,
                    "version": 1,
                }
                for title in titles
            ],
        )


@pytest.mark.integration
def test_text_query_folds_case_and_sharp_s_and_treats_wildcards_literally() -> None:
    fixture = WorkFixture()
    _insert_projects(fixture, ["Städa Straße", "100% klart", "snabb_väg", "Annat"])

    def found(q: str) -> list[str]:
        return [item.title for item in fixture.walk(WorkQuery(kind="project", q=q))]

    assert found("STRASSE") == ["Städa Straße"]
    assert found("städa") == ["Städa Straße"]
    assert found("100%") == ["100% klart"]
    assert found("_väg") == ["snabb_väg"]
    assert found("%") == ["100% klart"]


# Titles and the search that must find them, exactly as `str.casefold()` matched them before.
FOLDED_MATCHES = [
    ("Le \ufb00et", "ff"),  # ligature ff
    ("Of\ufb01ce", "FFI"),  # ligature fi: "offi" inside "Office"
    ("Gro\u1e9e", "gross"),  # capital sharp s
    ("\u039f\u0394\u039f\u03a3", "\u03bf\u03b4\u03bf\u03c2"),  # Greek final sigma
    ("\u03bf\u03b4\u03bf\u03c2", "\u039f\u0394\u039f\u03a3"),
    ("\u0130stanbul", "istanbul"),  # Turkish dotted capital I
    ("istanbul", "\u0130STANBUL"),
    ("\uff21bc", "abc"),  # fullwidth A (NFKC; casefold alone kept it)
]


# Characters whose full case folding expands: a title must still match itself.
EXPANDING = ["\u01f0", "\u0390", "\u1f88"]
SAME_TEXT = [(title, title) for title, _ in FOLDED_MATCHES] + [(c, c) for c in EXPANDING]


@pytest.mark.integration
@pytest.mark.parametrize(("title", "query"), [*FOLDED_MATCHES, *SAME_TEXT])
def test_text_query_matches_like_casefold_for_ligatures_sigma_and_turkish_i(
    title: str, query: str
) -> None:
    fixture = WorkFixture()
    _insert_projects(fixture, [title, "Orelaterat"])

    found = [item.title for item in fixture.walk(WorkQuery(kind="project", q=query))]

    assert found == [title]


@pytest.mark.integration
def test_title_order_matches_the_old_casefold_sort() -> None:
    titles = [
        "zebra",
        "\xc5ke",
        "\xe4pple",
        "Stra\xdfe",
        "strasse",
        "Of\ufb01ce",
        "office",
        "\u03c3a",
        "\u03a3b",
        "\u03c2c",
        "\xd6l",
        "Banan",
        "banan",
        "alfa",
    ]
    fixture = WorkFixture()
    _insert_projects(fixture, titles)

    listed = [
        item.title for item in fixture.walk(WorkQuery(kind="project", sort="title_asc", limit=100))
    ]

    # The old Python sort: casefolded title, then id (the ids here are inserted in list order).
    assert [title.casefold() for title in listed] == sorted(title.casefold() for title in titles)

"""Two list orders that must hold across page boundaries.

`updated_desc` is ordered by the last change, not by the version counter, and the status board's
manual `board_rank` order is applied by the database before the page is cut, so a page of any
size continues the same order as the whole list.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.dialects.postgresql import insert

from sidekick.shared.persistence.models import ProjectRow, TaskRow
from sidekick.shared.types import new_uuid7
from sidekick.work.application.service import WorkQuery
from tests.support.work_paging import NOW, WorkFixture

PAGE_SIZES = (1, 2, 3)


def _task(fixture: WorkFixture, title: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": new_uuid7(),
        "owner_id": fixture.owner_id,
        "title": title,
        "status": "todo",
        "priority": "normal",
        "created_at": NOW - timedelta(days=30),
        "updated_at": NOW - timedelta(days=30),
        "version": 1,
        "domain_id": fixture.domain_id,
        **extra,
    }


def _board_walk(fixture: WorkFixture, query: WorkQuery) -> dict[str, list[str]]:
    """Every page of the board, merged: the titles of each status column in the order served."""

    merged: dict[str, list[str]] = {}
    cursor: str | None = None
    for _ in range(100):
        columns, cursor = fixture.contexts.work_board_page(
            fixture.actor, replace(query, cursor=cursor)
        )
        for status, items in columns.items():
            merged.setdefault(status, []).extend(item["title"] for item in items)
        if cursor is None:
            return merged
    raise AssertionError("pagination did not end")


@pytest.mark.integration
@pytest.mark.parametrize("limit", PAGE_SIZES)
def test_updated_desc_orders_by_the_last_change_not_the_version(limit: int) -> None:
    fixture = WorkFixture()
    old_busy, just_edited, middle = (new_uuid7() for _ in range(3))
    with fixture.factory.begin() as session:
        session.execute(
            insert(TaskRow),
            [
                # Version 20 but untouched for a month; version 2 but edited a minute ago.
                _task(fixture, "Gammal", id=old_busy, version=20),
                _task(
                    fixture,
                    "Nyligen",
                    id=just_edited,
                    version=2,
                    updated_at=NOW - timedelta(minutes=1),
                ),
                _task(fixture, "Mitten", id=middle, version=9, updated_at=NOW - timedelta(days=3)),
            ],
        )
        session.execute(
            insert(ProjectRow),
            [
                {
                    "id": new_uuid7(),
                    "owner_id": fixture.owner_id,
                    "domain_id": fixture.domain_id,
                    "title": "Projekt",
                    "status": "active",
                    "created_at": NOW,
                    "updated_at": NOW - timedelta(days=3, hours=1),
                    "version": 50,
                }
            ],
        )
    query = WorkQuery(kind="all", limit=100)

    whole = [item["title"] for item in fixture.walk(query)]
    paged = [item["title"] for item in fixture.walk(replace(query, limit=limit))]

    # The Domain of the fixture was created 400 days ago, so it is last.
    assert whole == ["Nyligen", "Mitten", "Projekt", "Gammal", "Hem"]
    assert paged == whole


@pytest.mark.integration
@pytest.mark.parametrize("limit", PAGE_SIZES)
def test_updated_desc_breaks_equal_times_by_id_across_pages(limit: int) -> None:
    fixture = WorkFixture()
    with fixture.factory.begin() as session:
        session.execute(
            insert(TaskRow),
            [_task(fixture, f"Lika {n}", version=n + 1) for n in range(7)],
        )
    query = WorkQuery(kind="task", limit=100)

    whole = [(item["id"], item["title"]) for item in fixture.walk(query)]
    paged = [(item["id"], item["title"]) for item in fixture.walk(replace(query, limit=limit))]

    assert len(whole) == 7
    assert [identifier for identifier, _ in whole] == sorted(
        (identifier for identifier, _ in whole), reverse=True
    )
    assert paged == whole


def _seed_ranked_board(fixture: WorkFixture) -> None:
    """Todo: ranks 1 and 2 on the two oldest Tasks; blocked: rank 1 on its oldest Task."""

    def at(days: int) -> dict[str, Any]:
        return {"updated_at": NOW - timedelta(days=days)}

    with fixture.factory.begin() as session:
        session.execute(
            insert(TaskRow),
            [
                _task(fixture, "Todo ny", **at(1)),
                _task(fixture, "Todo mitten", **at(5)),
                _task(fixture, "Todo rank 2", board_rank=2, **at(40)),
                _task(fixture, "Todo rank 1", board_rank=1, **at(60)),
                _task(fixture, "Spärrad ny", status="blocked", **at(2)),
                _task(fixture, "Spärrad rank 1", status="blocked", board_rank=1, **at(70)),
            ],
        )


@pytest.mark.integration
@pytest.mark.parametrize("limit", [1, 2, 3, 100])
def test_board_pages_follow_the_manual_rank_order(limit: int) -> None:
    fixture = WorkFixture()
    _seed_ranked_board(fixture)

    columns = _board_walk(fixture, WorkQuery(kind="task", limit=limit))

    assert columns == {
        "todo": ["Todo rank 1", "Todo rank 2", "Todo ny", "Todo mitten"],
        "blocked": ["Spärrad rank 1", "Spärrad ny"],
    }


@pytest.mark.integration
def test_board_first_page_of_one_holds_the_top_ranked_task() -> None:
    fixture = WorkFixture()
    _seed_ranked_board(fixture)

    columns, cursor = fixture.contexts.work_board_page(
        fixture.actor, WorkQuery(kind="task", limit=1)
    )

    # Ranked first (ties between columns fall to the newer change), though it is old.
    assert [item["title"] for items in columns.values() for item in items] == ["Todo rank 1"]
    assert cursor is not None


@pytest.mark.integration
def test_board_cursor_is_not_interchangeable_with_the_list_cursor() -> None:
    fixture = WorkFixture()
    _seed_ranked_board(fixture)
    query = WorkQuery(kind="task", limit=1)

    _, board_cursor = fixture.contexts.work_board_page(fixture.actor, query)
    list_cursor = fixture.contexts.work_list_page(fixture.actor, query).next_cursor

    assert board_cursor is not None and list_cursor is not None
    for call, cursor in (
        (fixture.contexts.work_list_page, board_cursor),
        (fixture.contexts.work_board_page, list_cursor),
    ):
        with pytest.raises(ValueError, match="invalid pagination cursor"):
            call(fixture.actor, replace(query, cursor=cursor))


@pytest.mark.integration
def test_board_ignores_the_rank_of_an_archived_task() -> None:
    fixture = WorkFixture()
    with fixture.factory.begin() as session:
        session.execute(
            insert(TaskRow),
            [
                _task(fixture, "Arkiverad rank 1", board_rank=1, archived_at=NOW),
                _task(fixture, "Ny", updated_at=NOW - timedelta(days=1)),
                _task(fixture, "Rankad", board_rank=1, updated_at=NOW - timedelta(days=9)),
            ],
        )

    columns = _board_walk(fixture, WorkQuery(kind="task", archive="all", limit=2))

    assert columns == {"todo": ["Rankad", "Ny", "Arkiverad rank 1"]}

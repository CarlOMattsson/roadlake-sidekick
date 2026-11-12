"""MCP Work board and agenda reads: the same application use cases as the REST routes.

The board groups the owner's bounded Work page into status columns. The agenda returns the
owner's dated Work records grouped by `agenda_group`. Both require `tasks:read`, neither
exposes another owner's records, and neither returns the persistence owner key.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.text import (
    AGENDA_NOTE,
    AGENDA_ROW_LIMIT,
    BOARD_EMPTY_NOTE,
    CARD_NOTE,
    EMPTY_WORK_NOTE,
)
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

WRITE_SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
READ_SCOPES = frozenset({"tasks:read"})


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _in(days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


async def _seed(client: Client, prefix: str) -> dict[str, str]:
    """Five owned Tasks: overdue, started, upcoming, scheduled later, and undated."""

    async def create(title: str, key: str, **extra: Any) -> dict[str, Any]:
        created = await client.call_tool(
            "create_task", {"title": title, "idempotency_key": key, **extra}
        )
        return created.structured_content["task"]

    overdue = await create(f"{prefix} overdue", f"{prefix}-overdue", due_at=_in(-2))
    started = await create(f"{prefix} started", f"{prefix}-started", due_at=_in(1))
    started = (
        await client.call_tool(
            "update_task",
            {
                "task_id": started["id"],
                "version": started["version"],
                "idempotency_key": f"{prefix}-started-status",
                "changes": {"status": "in_progress"},
            },
        )
    ).structured_content["task"]
    upcoming = await create(f"{prefix} upcoming", f"{prefix}-upcoming", due_at=_in(5))
    scheduled = await create(
        f"{prefix} scheduled", f"{prefix}-scheduled", not_before=_in(10), due_at=_in(12)
    )
    undated = await create(f"{prefix} undated", f"{prefix}-undated")
    return {
        "overdue": overdue["id"],
        "started": started["id"],
        "upcoming": upcoming["id"],
        "scheduled": scheduled["id"],
        "undated": undated["id"],
    }


def _ids(columns: dict[str, list[dict[str, Any]]]) -> set[str]:
    return {item["id"] for items in columns.values() for item in items}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_board_groups_owned_records_by_status() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        ids = await _seed(client, "board")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        board = await client.call_tool("get_work_board", {"limit": 100})

    columns = board.structured_content["columns"]
    assert set(columns) == {"todo", "in_progress"}
    for status, items in columns.items():
        assert all(item["status"] == status for item in items), status
    assert _ids(columns) == set(ids.values())
    assert columns["in_progress"][0]["id"] == ids["started"]
    assert board.structured_content["next_cursor"] is None
    assert "owner_id" not in str(board.structured_content)
    # The model reads one short line; the full board stays in structuredContent for the card.
    assert len(board.content) == 1
    summary = board.content[0].text
    # Columns appear in the order of the first record served (newest change first), so the two
    # status phrases are checked without fixing which comes first.
    first_line, second_line = summary.split("\n")[:2]
    assert first_line.startswith("The Work board has 5 tasks: ")
    assert "1 in progress" in first_line and "4 to do" in first_line
    assert second_line.startswith("Work board card shown: 5 tasks (")
    assert "todo 4" in summary and "in_progress 1" in summary
    assert all(item_id in summary for item_id in ids.values())
    assert summary.endswith(CARD_NOTE)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_board_respects_the_page_limit_across_pages() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed(client, "limit")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        first = await client.call_tool("get_work_board", {"limit": 2})
        second = await client.call_tool(
            "get_work_board",
            {"limit": 2, "cursor": first.structured_content["next_cursor"]},
        )
        third = await client.call_tool(
            "get_work_board",
            {"limit": 2, "cursor": second.structured_content["next_cursor"]},
        )

    first_ids = _ids(first.structured_content["columns"])
    second_ids = _ids(second.structured_content["columns"])
    assert len(first_ids) == 2
    assert len(second_ids) == 2
    assert first_ids.isdisjoint(second_ids)
    assert first.structured_content["next_cursor"] is not None
    assert len(_ids(third.structured_content["columns"])) == 1
    assert third.structured_content["next_cursor"] is None
    next_cursor = first.structured_content["next_cursor"]
    assert f"More: next_cursor {next_cursor}." in first.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_board_filters_by_status_and_rejects_an_oversized_page() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        ids = await _seed(client, "filter")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        filtered = await client.call_tool("get_work_board", {"status": "in_progress", "limit": 100})
        with pytest.raises(ToolError):
            await client.call_tool("get_work_board", {"limit": 101})
        with pytest.raises(ToolError):
            await client.call_tool("get_work_board", {"status": "archived"})

    assert set(filtered.structured_content["columns"]) == {"in_progress"}
    assert _ids(filtered.structured_content["columns"]) == {ids["started"]}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_groups_dated_records_and_drops_undated_ones() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        ids = await _seed(client, "agenda")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})

    items = agenda.structured_content["items"]
    groups = {item["id"]: item["agenda_group"] for item in items}
    assert groups == {
        ids["overdue"]: "overdue",
        ids["started"]: "upcoming",
        ids["upcoming"]: "upcoming",
        ids["scheduled"]: "scheduled_later",
    }
    assert ids["undated"] not in groups
    # Default sort is due_asc: the earliest deadline first.
    assert [item["id"] for item in items] == [
        ids["overdue"],
        ids["started"],
        ids["upcoming"],
        ids["scheduled"],
    ]
    assert all(item["kind"] == "task" and item["task_id"] == item["id"] for item in items)
    assert all("owner_id" not in item for item in items)
    assert len(agenda.content) == 1
    summary = agenda.content[0].text
    assert summary.startswith(
        "4 agenda items: 1 overdue, 0 due today.\nWork agenda card shown: 4 items ("
    )
    assert "overdue 1" in summary and "today 0" in summary
    assert "upcoming 2" in summary and "scheduled_later 1" in summary
    # Overdue, today and upcoming within 7 days are named; a later start is only counted.
    assert ids["overdue"] in summary
    assert ids["started"] in summary and ids["upcoming"] in summary
    assert ids["scheduled"] not in summary
    assert "More:" not in summary
    assert summary.endswith(f"{CARD_NOTE} {AGENDA_NOTE}")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_lists_a_task_due_in_three_days_and_only_counts_one_due_in_twenty() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        near = await client.call_tool(
            "create_task",
            {"title": "agenda near", "due_at": _in(3), "idempotency_key": "agenda-near-0001"},
        )
        far = await client.call_tool(
            "create_task",
            {"title": "agenda far", "due_at": _in(20), "idempotency_key": "agenda-far-0001"},
        )
    near_id = near.structured_content["task"]["id"]
    far_id = far.structured_content["task"]["id"]

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})

    summary = agenda.content[0].text
    assert "upcoming 2" in summary
    assert f"- {near_id} v1 | agenda near | due " in summary
    assert far_id not in summary
    assert "agenda far" not in summary


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_card_lists_at_most_the_row_limit_in_total() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    total = AGENDA_ROW_LIMIT + 2
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        for index in range(total):
            await client.call_tool(
                "create_task",
                {
                    "title": f"soon {index}",
                    "due_at": _in(1 + index / 100),
                    "idempotency_key": f"agenda-soon-{index:04d}",
                },
            )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})

    summary = agenda.content[0].text
    assert f"upcoming {total}" in summary
    assert len([line for line in summary.splitlines() if line.startswith("- ")]) == AGENDA_ROW_LIMIT
    assert f"… {total - AGENDA_ROW_LIMIT} more" in summary


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_never_lists_completed_tasks_as_overdue_or_upcoming() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        ids = await _seed(client, "completed")
        for name in ("overdue", "upcoming"):
            current = await client.call_tool("get_task", {"task_id": ids[name]})
            await client.call_tool(
                "update_task",
                {
                    "task_id": ids[name],
                    "version": current.structured_content["task"]["version"],
                    "idempotency_key": f"completed-{name}-status",
                    "changes": {"status": "completed"},
                },
            )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})

    items = agenda.structured_content["items"]
    groups = {item["id"]: item["agenda_group"] for item in items}
    # Completed records are not listed at all; the open started Task and the scheduled Task remain.
    assert groups == {
        ids["started"]: "upcoming",
        ids["scheduled"]: "scheduled_later",
    }
    assert "overdue" not in {item["agenda_group"] for item in items}
    assert [item["id"] for item in items] == [ids["started"], ids["scheduled"]]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_rejects_an_oversized_page_and_an_unknown_sort() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed(client, "bounds")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        with pytest.raises(ToolError):
            await client.call_tool("get_work_agenda", {"limit": 101})
        with pytest.raises(ToolError):
            await client.call_tool("get_work_agenda", {"sort": "created_asc"})
        with pytest.raises(ToolError):
            await client.call_tool("get_work_agenda", {"from": _in(0), "to": _in(7)})


@pytest.mark.asyncio
@pytest.mark.integration
async def test_other_owners_records_never_appear_on_board_or_agenda() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    other = container.auth.provision_user("other-owner", "Other")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        owner_ids = await _seed(client, "mine")
    async with Client(_server_for(container, Actor(other, WRITE_SCOPES))) as client:
        other_task = await client.call_tool(
            "create_task",
            {
                "title": "Other owner secret",
                "idempotency_key": "other-owner-secret",
                "due_at": _in(-1),
            },
        )
    other_id = other_task.structured_content["task"]["id"]

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        board = await client.call_tool("get_work_board", {"limit": 100})
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})
    assert other_id not in _ids(board.structured_content["columns"])
    assert other_id not in {item["id"] for item in agenda.structured_content["items"]}
    assert _ids(board.structured_content["columns"]) == set(owner_ids.values())

    async with Client(_server_for(container, Actor(other, READ_SCOPES))) as client:
        other_board = await client.call_tool("get_work_board", {"limit": 100})
        other_agenda = await client.call_tool("get_work_agenda", {"limit": 100})
    assert _ids(other_board.structured_content["columns"]) == {other_id}
    assert [item["id"] for item in other_agenda.structured_content["items"]] == [other_id]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_board_and_agenda_are_forbidden_without_tasks_read() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed(client, "scope")

    stranger = Actor(owner, frozenset({"projects:read"}))
    async with Client(_server_for(container, stranger)) as client:
        for tool in ("get_work_board", "get_work_agenda"):
            denied = await client.call_tool(tool, {}, raise_on_error=False)
            assert denied.is_error, tool
            assert denied.structured_content["code"] == "forbidden", tool


@pytest.mark.asyncio
@pytest.mark.integration
async def test_board_filters_to_one_projects_tasks_and_pages_through_them() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Ekonomi", "idempotency_key": "pf-domain"}
        )
        domain_id = domain.structured_content["domain"]["id"]
        taxes = await client.call_tool(
            "create_project",
            {
                "title": "Bokslut och skatt",
                "domain_id": domain_id,
                "idempotency_key": "pf-project-a",
            },
        )
        other = await client.call_tool(
            "create_project",
            {"title": "Annat projekt", "domain_id": domain_id, "idempotency_key": "pf-project-b"},
        )
        taxes_id = taxes.structured_content["project"]["id"]
        other_id = other.structured_content["project"]["id"]

        async def create(title: str, key: str, **extra: Any) -> str:
            created = await client.call_tool(
                "create_task", {"title": title, "idempotency_key": key, **extra}
            )
            return created.structured_content["task"]["id"]

        first = await create("Lämna deklarationen", "pf-task-1", project_id=taxes_id)
        second = await create("Momsrapport", "pf-task-2", project_id=taxes_id)
        elsewhere = await create("Annat arbete", "pf-task-3", project_id=other_id)
        standalone = await create("Fristående", "pf-task-4")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        scoped = await client.call_tool("get_work_board", {"limit": 100, "project_id": taxes_id})
        whole = await client.call_tool("get_work_board", {"limit": 100})
        page_one = await client.call_tool("get_work_board", {"limit": 1, "project_id": taxes_id})
        page_two = await client.call_tool(
            "get_work_board",
            {
                "limit": 1,
                "project_id": taxes_id,
                "cursor": page_one.structured_content["next_cursor"],
            },
        )

    # Only the Project's Tasks: the other Project's Task, a standalone Task and the Project record
    # itself (kind project carries the same project_id) are left out.
    assert _ids(scoped.structured_content["columns"]) == {first, second}
    assert {first, second, elsewhere, standalone} <= _ids(whole.structured_content["columns"])
    assert _ids(page_one.structured_content["columns"]) | _ids(
        page_two.structured_content["columns"]
    ) == {first, second}
    assert page_two.structured_content["next_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_empty_unfiltered_board_says_how_to_start() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        board = await client.call_tool("get_work_board", {"limit": 100})

    assert board.content[0].text == (
        f"The Work board has no records.\nWork board card shown: 0 records.\n"
        f"{EMPTY_WORK_NOTE}\n{CARD_NOTE}"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_empty_board_card_says_no_tasks_match() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        board = await client.call_tool("get_work_board", {"limit": 100, "q": "zzz-inget-zzz"})

    assert board.structured_content["columns"] == {}
    assert board.content[0].text == (
        f"The Work board has no records.\nWork board card shown: 0 records.\n"
        f"{BOARD_EMPTY_NOTE}\n{CARD_NOTE}"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_board_and_agenda_name_the_project_of_a_task_only() -> None:
    """A Task in a Project carries the Project's title; a standalone Task and Project carry none."""

    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    long_title = "Bokslut och skatt " + "x" * 120
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Ekonomi", "idempotency_key": "title-domain-001"}
        )
        domain_id = domain.structured_content["domain"]["id"]
        project = await client.call_tool(
            "create_project",
            {
                "title": "Bokslut och skatt",
                "domain_id": domain_id,
                "idempotency_key": "title-project-001",
            },
        )
        long_project = await client.call_tool(
            "create_project",
            {
                "title": long_title,
                "domain_id": domain_id,
                "idempotency_key": "title-project-002",
            },
        )
        project_id = project.structured_content["project"]["id"]
        long_project_id = long_project.structured_content["project"]["id"]
        in_project = await client.call_tool(
            "create_task",
            {
                "title": "Lämna deklarationen",
                "project_id": project_id,
                "due_at": _in(-1),
                "idempotency_key": "title-task-in-project",
            },
        )
        in_long_project = await client.call_tool(
            "create_task",
            {
                "title": "Långt projekt",
                "project_id": long_project_id,
                "due_at": _in(3),
                "idempotency_key": "title-task-in-long-project",
            },
        )
        standalone = await client.call_tool(
            "create_task",
            {
                "title": "Fristående",
                "due_at": _in(2),
                "idempotency_key": "title-task-standalone",
            },
        )
        in_project_id = in_project.structured_content["task"]["id"]
        in_long_id = in_long_project.structured_content["task"]["id"]
        standalone_id = standalone.structured_content["task"]["id"]

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        board = await client.call_tool("get_work_board", {"limit": 100})
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})

    by_id = {
        item["id"]: item for items in board.structured_content["columns"].values() for item in items
    }
    assert by_id[in_project_id]["project_title"] == "Bokslut och skatt"
    assert by_id[standalone_id]["project_title"] is None
    assert by_id[project_id]["project_title"] is None
    assert by_id[long_project_id]["project_title"] is None
    # A Project title is clipped to 120 characters, the last one `…`, as other titles are.
    clipped = by_id[in_long_id]["project_title"]
    assert len(clipped) == 120
    assert clipped == long_title[:119] + "…"

    agenda_by_id = {item["id"]: item for item in agenda.structured_content["items"]}
    assert agenda_by_id[in_project_id]["project_title"] == "Bokslut och skatt"
    assert agenda_by_id[standalone_id]["project_title"] is None
    # The overdue Project Task is named in the card text with its due time and Project title.
    # The standalone Task is due within AGENDA_UPCOMING_DAYS, so its row is listed, but it names
    # no Project and the Project's id never appears in the card text.
    due = agenda_by_id[in_project_id]["due_at"]
    row = f"- {in_project_id} v1 | Lämna deklarationen | due {due} | project Bokslut och skatt"
    assert row in agenda.content[0].text
    standalone_due = agenda_by_id[standalone_id]["due_at"]
    lines = agenda.content[0].text.splitlines()
    assert f"- {standalone_id} v1 | Fristående | due {standalone_due}" in lines
    assert project_id not in agenda.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_board_echoes_the_filters_it_was_read_with_but_not_the_defaults() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Echo", "idempotency_key": "echo-domain"}
        )
        project = await client.call_tool(
            "create_project",
            {
                "title": "Ekoprojekt",
                "domain_id": domain.structured_content["domain"]["id"],
                "idempotency_key": "echo-project",
            },
        )
        project_id = project.structured_content["project"]["id"]

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        scoped = await client.call_tool("get_work_board", {"project_id": project_id})
        plain = await client.call_tool("get_work_board", {"limit": 100})
        searched = await client.call_tool("get_work_board", {"q": "zzz-inget-zzz"})

    assert scoped.structured_content["filters"] == {"project_id": project_id}
    assert plain.structured_content["filters"] == {}
    # q is echoed for the card's re-read, but never reaches the model-facing text.
    assert searched.structured_content["filters"] == {"q": "zzz-inget-zzz"}
    assert "zzz-inget-zzz" not in searched.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_echoes_its_filters_and_never_the_cursor() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed(client, "echo-agenda")

    args: dict[str, Any] = {"limit": 1, "sort": "title_asc", "q": "echo-agenda"}
    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        first = await client.call_tool("get_work_agenda", args)
        cursor = first.structured_content["next_cursor"]
        assert cursor is not None
        second = await client.call_tool("get_work_agenda", {**args, "cursor": cursor})
        plain = await client.call_tool("get_work_agenda", {"limit": 100})

    assert first.structured_content["filters"] == {"q": "echo-agenda", "sort": "title_asc"}
    assert second.structured_content["filters"] == {"q": "echo-agenda", "sort": "title_asc"}
    assert plain.structured_content["filters"] == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_board_and_agenda_carry_the_domain_accent_of_tasks_and_projects() -> None:
    """A Task or Project carries its Domain's colour; an uncoloured Domain gives null."""

    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    target = (datetime.now(UTC) + timedelta(days=10)).date().isoformat()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        teal = await client.call_tool(
            "create_domain",
            {"name": "Jobb", "accent": "teal", "idempotency_key": "accent-domain-teal"},
        )
        plain = await client.call_tool(
            "create_domain", {"name": "Hem", "idempotency_key": "accent-domain-plain"}
        )
        teal_id = teal.structured_content["domain"]["id"]
        plain_id = plain.structured_content["domain"]["id"]
        coloured_project = await client.call_tool(
            "create_project",
            {
                "domain_id": teal_id,
                "title": "Offert",
                "target_date": target,
                "idempotency_key": "accent-project-teal",
            },
        )
        plain_project = await client.call_tool(
            "create_project",
            {
                "domain_id": plain_id,
                "title": "Garden",
                "target_date": target,
                "idempotency_key": "accent-project-plain",
            },
        )
        coloured_project_id = coloured_project.structured_content["project"]["id"]
        plain_project_id = plain_project.structured_content["project"]["id"]
        coloured_task = await client.call_tool(
            "create_task",
            {
                "title": "Skicka offerten",
                "project_id": coloured_project_id,
                "due_at": _in(3),
                "idempotency_key": "accent-task-teal",
            },
        )
        plain_task = await client.call_tool(
            "create_task",
            {
                "title": "Vattna beten",
                "project_id": plain_project_id,
                "due_at": _in(4),
                "idempotency_key": "accent-task-plain",
            },
        )
        coloured_task_id = coloured_task.structured_content["task"]["id"]
        plain_task_id = plain_task.structured_content["task"]["id"]

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        board = await client.call_tool("get_work_board", {"limit": 100})
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})

    columns = board.structured_content["columns"]
    board_items = {item["id"]: item for items in columns.values() for item in items}
    agenda_items = {item["id"]: item for item in agenda.structured_content["items"]}
    for items in (board_items, agenda_items):
        assert items[coloured_task_id]["domain_accent"] == "teal"
        assert items[coloured_project_id]["domain_accent"] == "teal"
        assert items[plain_task_id]["domain_accent"] is None
        assert items[plain_project_id]["domain_accent"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_task_takes_the_domain_accent_of_its_process_or_its_own_domain() -> None:
    """A Task under a Process takes that Process's Domain colour; a Task with its own
    `domain_id` takes that Domain's colour. Both show on the board and the agenda."""

    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, WRITE_SCOPES)
    process_domain = container.contexts.create_domain(
        actor, name="Ekonomi", description=None, accent="teal", idempotency_key="derive-domain-a"
    )
    direct_domain = container.contexts.create_domain(
        actor, name="Hem", description=None, accent="rose", idempotency_key="derive-domain-b"
    )
    process = container.contexts.create_process(
        actor,
        domain_id=process_domain.id,
        name="Månadsbokslut",
        description=None,
        idempotency_key="derive-process",
    )
    due = datetime.now(UTC) + timedelta(days=3)
    via_process = container.tasks.create(
        actor,
        title="Stäng perioden",
        process_id=process.id,
        due_at=due,
        idempotency_key="derive-task-process",
    )
    direct = container.tasks.create(
        actor,
        title="Byt filter",
        domain_id=direct_domain.id,
        due_at=due,
        idempotency_key="derive-task-domain",
    )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        board = await client.call_tool("get_work_board", {"limit": 100})
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})

    columns = board.structured_content["columns"]
    board_items = {item["id"]: item for items in columns.values() for item in items}
    agenda_items = {item["id"]: item for item in agenda.structured_content["items"]}
    for items in (board_items, agenda_items):
        assert items[str(via_process.id)]["domain_accent"] == "teal"
        assert items[str(direct.id)]["domain_accent"] == "rose"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_finds_an_open_overdue_task_behind_completed_ones() -> None:
    """Filtering runs before paging: 30 completed Tasks due earlier than one open overdue Task
    must not push that Task past the default page of 25."""

    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        for index in range(30):
            created = await client.call_tool(
                "create_task",
                {
                    "title": f"done {index}",
                    "due_at": _in(-3),
                    "idempotency_key": f"page-done-{index}",
                },
            )
            await client.call_tool(
                "update_task",
                {
                    "task_id": created.structured_content["task"]["id"],
                    "version": created.structured_content["task"]["version"],
                    "idempotency_key": f"page-done-{index}-status",
                    "changes": {"status": "completed"},
                },
            )
        overdue = await client.call_tool(
            "create_task",
            {"title": "open overdue", "due_at": _in(-2), "idempotency_key": "page-open-overdue"},
        )
    overdue_id = overdue.structured_content["task"]["id"]

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        agenda = await client.call_tool("get_work_agenda", {})

    items = agenda.structured_content["items"]
    assert [(item["id"], item["agenda_group"]) for item in items] == [(overdue_id, "overdue")]
    assert agenda.structured_content["next_cursor"] is None

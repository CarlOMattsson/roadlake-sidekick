"""MCP Journal identity, date, relation, and authorization (the REST surface is gone, D-082)."""

import logging
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_app
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.persistence.models import StepRow, TaskRow
from sidekick.shared.types import Actor, new_uuid7
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_journal_identity_summary_state_and_owner_isolation() -> None:
    factory = database_factory()
    app = create_app(make_settings(), factory)
    user_id = app.state.container.auth.provision_user("cross-journal-owner", "Cross Journal")
    actor = Actor(
        user_id,
        frozenset(
            {
                "journal:read",
                "journal:write",
                "projects:read",
                "tasks:read",
                "contacts:read",
            }
        ),
    )

    server = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as mcp:
        source = await mcp.call_tool(
            "create_journal_source",
            {
                "source_type": "manual_text",
                "journal_date": "2026-07-21",
                "occurred_at": "2026-07-21T09:00:00Z",
                "source_recorded_at": "2026-07-24T08:00:00Z",
                "raw_text": "MCP-källa",
                "language": "sv",
                "idempotency_key": "cross-source",
            },
        )
        entry = await mcp.call_tool(
            "create_manual_journal_entry",
            {
                "source_id": source.structured_content["source"]["id"],
                "title": "MCP journalpost",
                "summary": "MCP innehåll",
                "key_points": [],
                "project_ids": [],
                "task_ids": [],
                "contact_ids": [],
                "idempotency_key": "cross-entry",
            },
        )
        entry_id = entry.structured_content["entry"]["id"]
        read = await mcp.call_tool("get_journal_entry", {"entry_id": entry_id})
        assert read.structured_content["entry"]["id"] == entry_id
        assert read.structured_content["entry"]["journal_date"] == "2026-07-21"
        assert read.structured_content["entry"]["summary"] == "MCP innehåll"

        detailed = await mcp.call_tool(
            "get_journal_entry", {"entry_id": entry_id, "include_content": True}
        )
        assert detailed.structured_content["entry"]["summary"] == "MCP innehåll"
        day = await mcp.call_tool("get_journal_day", {"journal_date": "2026-07-21"})
        assert day.structured_content["entries"][0]["id"] == entry_id
        summary = await mcp.call_tool("get_daily_journal_summary", {"journal_date": "2026-07-21"})
        assert summary.structured_content["summary"]["exists"] is False

    second = Actor(user_id, frozenset({"journal:read"}))
    other = Actor(
        app.state.container.auth.provision_user("cross-journal-other", "Other"),
        frozenset({"journal:read"}),
    )
    other_server = create_mcp_server(
        app.state.container, actor_provider=lambda: other, enable_auth=False
    )
    async with Client(other_server) as mcp:
        with pytest.raises(ToolError):
            await mcp.call_tool("get_journal_entry", {"entry_id": entry_id})
    assert second.user_id == user_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_returns_the_done_section_for_a_day_without_entries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = database_factory()
    app = create_app(make_settings(), factory)
    auth = app.state.container.auth
    user_id = auth.provision_user("cross-done-owner", "Cross Done")
    other_id = auth.provision_user("cross-done-other", "Cross Other")
    done_at = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
    sentinel = "DONE_REDACTION_SENTINEL"

    def task(owner: UUID, title: str) -> TaskRow:
        return TaskRow(
            id=new_uuid7(),
            owner_id=owner,
            title=title,
            status="completed",
            priority="normal",
            completed_at=done_at,
            created_at=done_at,
            updated_at=done_at,
            version=1,
        )

    own, foreign = task(user_id, f"{sentinel} egen"), task(other_id, f"{sentinel} annans")
    own_list = ShoppingListRow(
        id=new_uuid7(),
        owner_id=user_id,
        name=f"{sentinel} lista",
        archived=False,
        version=1,
        created_at=done_at,
        updated_at=done_at,
    )
    with factory.begin() as session:
        session.add_all([own, foreign, own_list])
        session.flush()
        session.add_all(
            [
                StepRow(
                    id=new_uuid7(),
                    owner_id=user_id,
                    task_id=own.id,
                    title=f"{sentinel} steg",
                    status="completed",
                    position=0,
                    completed_at=done_at,
                    created_at=done_at,
                    updated_at=done_at,
                    version=1,
                ),
                ShoppingItemRow(
                    id=new_uuid7(),
                    owner_id=user_id,
                    list_id=own_list.id,
                    name=f"{sentinel} vara",
                    quantity=1,
                    purchased=True,
                    purchased_at=done_at,
                    version=1,
                    created_at=done_at,
                    updated_at=done_at,
                ),
            ]
        )

    caplog.set_level(logging.DEBUG)
    actor = Actor(user_id, frozenset({"journal:read", "tasks:read", "shopping:read"}))
    server = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as mcp:
        mcp_day = await mcp.call_tool("get_journal_day", {"journal_date": "2026-07-21"})
    mcp_done = mcp_day.structured_content["done"]

    assert mcp_day.structured_content["entries"] == []
    assert mcp_done["counts"] == {"tasks": 1, "steps": 1, "purchases": 1}
    assert mcp_done["truncated"] is False
    assert [item["title"] for item in mcp_done["tasks"]] == [f"{sentinel} egen"]
    assert set(mcp_done["tasks"][0]) == {
        "id",
        "title",
        "completed_at",
        "project_title",
        "recurring",
    }
    assert set(mcp_done["steps"][0]) == {"id", "title", "task_id", "task_title", "completed_at"}
    assert set(mcp_done["purchases"][0]) == {
        "id",
        "title",
        "list_id",
        "list_title",
        "purchased_at",
    }

    # Another owner never sees the first owner's records, over MCP.
    other_actor = Actor(other_id, frozenset({"journal:read", "tasks:read", "shopping:read"}))
    other_server = create_mcp_server(
        app.state.container, actor_provider=lambda: other_actor, enable_auth=False
    )
    async with Client(other_server) as mcp:
        theirs = await mcp.call_tool("get_journal_day", {"journal_date": "2026-07-21"})
    assert [item["title"] for item in theirs.structured_content["done"]["tasks"]] == [
        f"{sentinel} annans"
    ]
    assert theirs.structured_content["done"]["counts"] == {"tasks": 1, "steps": 0, "purchases": 0}

    # Titles are user data and never reach a log record.
    logged = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert sentinel not in logged

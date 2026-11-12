"""Threat matrix for Journal probing and mutation boundaries (MCP, D-082)."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

JOURNAL_DATE = "2026-07-21"
MISSING_ID = "01910000-0000-7000-8000-000000000099"


def _server(container, actor: Actor):
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_journal_threat_matrix_denies_probing_and_unsafe_mutation() -> None:
    container = create_container(make_settings(), database_factory())
    owner_id = container.auth.provision_user("journal-security-owner", "Owner")
    other_id = container.auth.provision_user("journal-security-other", "Other")
    private_text = "JOURNAL_SECURITY_PRIVATE_SOURCE"
    private_title = "JOURNAL_SECURITY_PRIVATE_TITLE"

    owner = Actor(owner_id, frozenset({"journal:read", "journal:write"}))
    async with Client(_server(container, owner)) as client:
        source = await client.call_tool(
            "create_journal_source",
            {
                "source_type": "manual_text",
                "journal_date": JOURNAL_DATE,
                "occurred_at": "2026-07-21T09:00:00+00:00",
                "source_recorded_at": "2026-07-21T09:05:00+00:00",
                "raw_text": private_text,
                "language": "sv",
                "idempotency_key": "journal-security-source",
            },
        )
        source_id = source.structured_content["source"]["id"]
        entry = await client.call_tool(
            "create_manual_journal_entry",
            {
                "source_id": source_id,
                "title": private_title,
                "summary": "Private summary sentinel",
                "key_points": [{"kind": "decision", "text": "Private decision sentinel"}],
                "project_ids": [],
                "task_ids": [],
                "contact_ids": [],
                "idempotency_key": "journal-security-entry",
            },
        )
        entry_id = entry.structured_content["entry"]["id"]

        # A missing id and a malformed range or cursor are refused without echoing content.
        with pytest.raises(ToolError) as missing:
            await client.call_tool("get_journal_entry", {"entry_id": MISSING_ID})
        with pytest.raises(ToolError) as missing_source:
            await client.call_tool("get_journal_source", {"source_id": MISSING_ID})
        with pytest.raises(ToolError) as too_wide:
            await client.call_tool(
                "list_journal_entries", {"from_date": "2024-01-01", "to_date": "2025-01-01"}
            )
        with pytest.raises(ToolError) as bad_cursor:
            await client.call_tool(
                "list_journal_entries",
                {
                    "from_date": JOURNAL_DATE,
                    "to_date": JOURNAL_DATE,
                    "cursor": "not-a-valid-cursor",
                },
            )
        oversized = "JOURNAL_SECURITY_OVERSIZED" + ("x" * 100_000)
        with pytest.raises(ToolError) as overflow:
            await client.call_tool(
                "create_journal_source",
                {
                    "source_type": "manual_text",
                    "journal_date": JOURNAL_DATE,
                    "raw_text": oversized,
                    "idempotency_key": "journal-security-overflow",
                },
            )
        for refused in (missing, missing_source, too_wide, bad_cursor, overflow):
            assert private_title not in str(refused.value)
            assert private_text not in str(refused.value)
        assert JOURNAL_DATE not in str(too_wide.value)
        assert oversized not in str(overflow.value)

    # Another owner probing the same ids, or reading the same day, learns nothing.
    other = Actor(other_id, frozenset({"journal:read"}))
    async with Client(_server(container, other)) as client:
        for tool, arguments in (
            ("get_journal_entry", {"entry_id": entry_id}),
            ("get_journal_source", {"source_id": source_id}),
        ):
            with pytest.raises(ToolError) as denied:
                await client.call_tool(tool, arguments)
            assert private_title not in str(denied.value)
            assert private_text not in str(denied.value)

        # A day answers with an empty day for another owner.
        day = await client.call_tool("get_journal_day", {"journal_date": JOURNAL_DATE})
        assert day.structured_content["entries"] == []
        assert private_text not in str(day.content)
        assert private_title not in str(day.content)

        searched = await client.call_tool(
            "list_journal_entries", {"from_date": JOURNAL_DATE, "to_date": JOURNAL_DATE}
        )
        assert searched.structured_content["entries"] == []
        assert private_title not in str(searched.content)

    # Without the write scope the owner cannot create a source at all.
    reader = Actor(owner_id, frozenset({"journal:read"}))
    async with Client(_server(container, reader)) as client:
        with pytest.raises(ToolError) as no_scope:
            await client.call_tool(
                "create_journal_source",
                {
                    "source_type": "manual_text",
                    "journal_date": JOURNAL_DATE,
                    "raw_text": "JOURNAL_SECURITY_SCOPE_SENTINEL",
                    "idempotency_key": "journal-security-no-scope",
                },
            )
        assert "JOURNAL_SECURITY_SCOPE_SENTINEL" not in str(no_scope.value)

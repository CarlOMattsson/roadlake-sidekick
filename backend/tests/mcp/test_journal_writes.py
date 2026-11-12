"""Idempotent Journal source and manual-entry MCP writes, and the app-only entry edit."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import text

from sidekick.api.app import create_container
from sidekick.mcp.journal import JOURNAL_TOOL_NAMES
from sidekick.mcp.results import error_result
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.shared.errors import NotFoundError
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.fakes import JOURNAL_REDACTION_SENTINEL_ONE, JOURNAL_REDACTION_SENTINEL_TWO
from tests.support.settings import make_settings
from tests.support.telemetry import CaptureTelemetry


def make_container(telemetry: CaptureTelemetry | None = None) -> tuple[object, Actor]:
    container = create_container(make_settings(), database_factory(), telemetry)
    user_id = container.auth.provision_user("mcp-write-owner", "MCP Write Owner")
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
    return container, actor


@pytest.mark.asyncio
@pytest.mark.integration
async def test_source_and_manual_entry_writes_are_retry_safe_and_ai_independent() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        source_args = {
            "source_type": "manual_text",
            "journal_date": "2026-07-21",
            "occurred_at": "2026-07-21T09:00:00Z",
            "source_recorded_at": "2026-07-24T08:00:00Z",
            "raw_text": "En explicit MCP-källa.",
            "language": "sv",
            "idempotency_key": "mcp-source-retry-1",
        }
        first_source = await client.call_tool("create_journal_source", source_args)
        replay_source = await client.call_tool("create_journal_source", source_args)
        assert first_source.structured_content == replay_source.structured_content
        source_id = first_source.structured_content["source"]["id"]

        entry_args = {
            "source_id": source_id,
            "title": "MCP manuell post",
            "summary": "Ett explicit användarbeslut.",
            "key_points": [{"kind": "decision", "text": "Följ upp."}],
            "project_ids": [],
            "task_ids": [],
            "contact_ids": [],
            "idempotency_key": "mcp-entry-retry-1",
        }
        first_entry = await client.call_tool("create_manual_journal_entry", entry_args)
        replay_entry = await client.call_tool("create_manual_journal_entry", entry_args)
        assert first_entry.structured_content == replay_entry.structured_content
        assert first_entry.structured_content["entry"]["source_id"] == source_id
        assert first_entry.structured_content["entry"]["version"] == 1
        # Line 1 is what voice mode reads, with no version; the id and version are on line 2.
        entry_id = first_entry.structured_content["entry"]["id"]
        assert first_entry.content[0].text == (
            f"Created a manual entry from 21 July.\nEntry {entry_id} v1."
        )

        with pytest.raises(ToolError):
            await client.call_tool(
                "create_journal_source",
                {**source_args, "raw_text": "Ändrad payload"},
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_manual_journal_entry",
                {**entry_args, "title": "Ändrad payload"},
            )

    with container.session_factory() as session:
        assert session.execute(text("SELECT count(*) FROM sidekick.tasks")).scalar_one() == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_manual_entry_validates_closed_input_relations_and_aware_times() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        source = await client.call_tool(
            "create_journal_source",
            {
                "source_type": "manual_text",
                "journal_date": "2026-07-21",
                "occurred_at": datetime(2026, 7, 21, 9, tzinfo=UTC).isoformat(),
                "source_recorded_at": datetime(2026, 7, 24, 8, tzinfo=UTC).isoformat(),
                "raw_text": "Källa",
                "idempotency_key": "mcp-source-validation",
            },
        )
        source_id = source.structured_content["source"]["id"]
        base = {
            "source_id": source_id,
            "title": "Giltig post",
            "summary": None,
            "key_points": [],
            "project_ids": [],
            "task_ids": [],
            "contact_ids": [],
            "idempotency_key": "mcp-entry-validation",
        }
        with pytest.raises(ToolError):
            await client.call_tool("create_manual_journal_entry", {**base, "title": "   "})
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_manual_journal_entry",
                {**base, "project_ids": ["01910000-0000-7000-8000-000000000001"]},
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_journal_source",
                {
                    "source_type": "manual_text",
                    "journal_date": "2026-07-21",
                    "occurred_at": "2026-07-21T09:00:00",
                    "raw_text": "Naive tid",
                    "idempotency_key": "mcp-source-naive",
                },
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_manual_journal_entry",
                {**base, "project_ids": ["01910000-0000-7000-8000-000000000001"] * 2},
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_manual_entry_write_does_not_require_journal_read_scope() -> None:
    container, actor = make_container()
    write_actor = Actor(actor.user_id, frozenset({"journal:write"}))
    server = create_mcp_server(container, actor_provider=lambda: write_actor, enable_auth=False)

    async with Client(server) as client:
        source = await client.call_tool(
            "create_journal_source",
            {
                "source_type": "manual_text",
                "journal_date": "2026-07-21",
                "raw_text": "Scope-bound source",
                "idempotency_key": "mcp-write-only-source",
            },
        )
        entry = await client.call_tool(
            "create_manual_journal_entry",
            {
                "source_id": source.structured_content["source"]["id"],
                "title": "Scope-bound entry",
                "summary": None,
                "key_points": [],
                "project_ids": [],
                "task_ids": [],
                "contact_ids": [],
                "idempotency_key": "mcp-write-only-entry",
            },
        )

    assert entry.structured_content["entry"]["title"] == "Scope-bound entry"


def test_mcp_error_result_is_structured_and_redacted() -> None:
    response = error_result(NotFoundError("private source sentinel"))

    assert response.is_error is True
    assert response.structured_content is not None
    assert response.structured_content["code"] == "not_found"
    assert response.structured_content["message"] == (
        "I could not find that. Check the name or search again."
    )
    assert len(response.structured_content["correlation_id"]) <= 64
    assert "private source sentinel" not in str(response)


class _Collector(logging.Handler):
    """Keeps every record that reaches it, whatever the propagation flags say."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def rendered(self) -> str:
        formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
        parts = [formatter.format(record) for record in self.records]
        parts.extend(repr(record.__dict__) for record in self.records)
        return "\n".join(parts)


@pytest.fixture(name="all_logs")
def _all_logs() -> Iterator[_Collector]:
    """Attach to root and to every logger, as test_journal_review does."""

    collector = _Collector()
    loggers: list[logging.Logger] = [logging.getLogger()]
    loggers.extend(
        item
        for item in logging.root.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    )
    for logger in loggers:
        logger.addHandler(collector)
    try:
        yield collector
    finally:
        for logger in loggers:
            logger.removeHandler(collector)


def _update_args(
    entry_id: str, expected_version: int, key: str, **overrides: Any
) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "expected_version": expected_version,
        "title": "Ny titel",
        "summary": "Ny sammanfattning.",
        "key_points": [{"kind": "decision", "text": "Ny punkt."}],
        "idempotency_key": key,
        **overrides,
    }


async def _create_entry(client: Client, suffix: str) -> dict[str, Any]:
    source = await client.call_tool(
        "create_journal_source",
        {
            "source_type": "manual_text",
            "journal_date": "2026-07-21",
            "raw_text": f"Källa för {suffix}",
            "idempotency_key": f"{suffix}-source",
        },
    )
    entry = await client.call_tool(
        "create_manual_journal_entry",
        {
            "source_id": source.structured_content["source"]["id"],
            "title": "Ursprunglig titel",
            "summary": "Ursprunglig sammanfattning.",
            "key_points": [],
            "project_ids": [],
            "task_ids": [],
            "contact_ids": [],
            "idempotency_key": f"{suffix}-entry",
        },
    )
    return entry.structured_content["entry"]


@pytest.mark.asyncio
async def test_only_the_manual_entry_write_opens_the_journal_card() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}

    write_names = {
        "create_journal_source",
        "create_manual_journal_entry",
        "write_journal_entry",
        "update_journal_entry",
        "update_journal_draft",
        "reject_journal_draft",
        "finalize_journal_draft",
    }
    assert write_names <= set(JOURNAL_TOOL_NAMES)
    carded = {
        name
        for name in write_names
        if (tools[name].meta or {}).get("ui", {}).get("resourceUri") is not None
    }
    # update_journal_entry shows the same card as the creation does.
    assert carded == {"create_manual_journal_entry", "write_journal_entry", "update_journal_entry"}
    assert tools["create_manual_journal_entry"].meta["ui"]["resourceUri"] == SIDEKICK_APP_URI
    assert "resourceUri" not in (tools["create_journal_source"].meta or {}).get("ui", {})
    # The entry edit is model-visible (a deliberate choice) and shows the same card.
    assert tools["update_journal_entry"].meta["ui"]["resourceUri"] == SIDEKICK_APP_URI
    assert "visibility" not in tools["update_journal_entry"].meta["ui"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_journal_entry_is_versioned_and_returns_the_text_in_block_two() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _create_entry(client, "update-owner")
        arguments = _update_args(entry["id"], 1, "update-entry-1")

        updated = await client.call_tool("update_journal_entry", arguments, raise_on_error=False)
        assert not updated.is_error, updated.structured_content
        assert updated.structured_content["entry"]["title"] == "Ny titel"
        assert updated.structured_content["entry"]["version"] == 2
        # Line 1 names the day only; the version belongs on line 2, with the id.
        assert updated.content[0].text == (
            f"Updated the journal entry from 21 July.\nEntry {entry['id']} v2."
        )
        # Block 2 is the full structured result (D-060), so the model reads the saved owner text.
        assert entry["id"] in updated.content[1].text
        for owner_text in ("Ny titel", "Ny sammanfattning.", "Ny punkt."):
            assert owner_text in updated.content[1].text

        replay = await client.call_tool("update_journal_entry", arguments)
        assert replay.structured_content == updated.structured_content

        stale = await client.call_tool(
            "update_journal_entry",
            _update_args(entry["id"], 1, "update-entry-2"),
            raise_on_error=False,
        )
        assert stale.is_error and stale.structured_content["code"] == "conflict"

        changed = await client.call_tool(
            "update_journal_entry",
            {**arguments, "title": "Annan titel"},
            raise_on_error=False,
        )
        assert changed.is_error
        assert changed.structured_content["code"] in {"conflict", "idempotency_conflict"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_journal_entry_refuses_a_write_only_actor_before_writing() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        entry = await _create_entry(client, "update-scope-owner")

    write_only = Actor(actor.user_id, frozenset({"journal:write"}))
    server = create_mcp_server(container, actor_provider=lambda: write_only, enable_auth=False)
    async with Client(server) as client:
        refused = await client.call_tool(
            "update_journal_entry",
            _update_args(entry["id"], 1, "update-scope-1"),
            raise_on_error=False,
        )
    assert refused.is_error and refused.structured_content["code"] == "forbidden"

    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        current = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
    assert current.structured_content["entry"]["version"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_journal_entry_keeps_entry_text_out_of_logs_telemetry_and_errors(
    all_logs: _Collector,
) -> None:
    telemetry = CaptureTelemetry()
    container, actor = make_container(telemetry)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    title = f"{JOURNAL_REDACTION_SENTINEL_ONE} titel"
    summary = f"{JOURNAL_REDACTION_SENTINEL_TWO} sammanfattning"
    point = f"{JOURNAL_REDACTION_SENTINEL_ONE} punkt"
    edit = {
        "title": title,
        "summary": summary,
        "key_points": [{"kind": "decision", "text": point}],
    }

    async with Client(server) as client:
        entry = await _create_entry(client, "update-log-owner")
        ok = await client.call_tool(
            "update_journal_entry", _update_args(entry["id"], 1, "log-update-1", **edit)
        )
        assert not ok.is_error
        # Stale version: a conflict whose message must not carry the rejected text.
        stale = await client.call_tool(
            "update_journal_entry",
            _update_args(entry["id"], 1, "log-update-2", **edit),
            raise_on_error=False,
        )
        assert stale.is_error and stale.structured_content["code"] == "conflict"
        # Schema-invalid input: FastMCP logs the arguments on this path. Its argument-validation
        # text is FastMCP's own and echoes the rejected value for every tool, so it is pinned
        # only for logs here; the error text is not asserted.
        invalid = await client.call_tool(
            "update_journal_entry",
            _update_args(str(summary), 2, "log-update-3", **edit),
            raise_on_error=False,
        )
        assert invalid.is_error
        too_long = await client.call_tool(
            "update_journal_entry",
            _update_args(entry["id"], 2, "log-update-4", **{**edit, "title": title + "x" * 200}),
            raise_on_error=False,
        )
        assert too_long.is_error

    rendered = all_logs.rendered()
    # The pydantic-failure path above really logged, and logged without its content.
    assert "fastmcp tool warning record (content withheld)" in rendered
    for sentinel in (JOURNAL_REDACTION_SENTINEL_ONE, JOURNAL_REDACTION_SENTINEL_TWO):
        assert sentinel not in rendered
        assert sentinel not in str(telemetry.records)
        # The tool's own refusal carries no entry text.
        assert sentinel not in str(stale.structured_content)
        assert sentinel not in str(stale.content)
    assert all(not record.args for record in all_logs.records)
    assert all(record.exc_info is None for record in all_logs.records)

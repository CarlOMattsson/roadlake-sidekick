"""Bounded Journal MCP reads over authoritative PostgreSQL state."""

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.journal.domain.summary import SummaryContent, entry_fingerprint
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

JOURNAL_DATE = date(2026, 7, 21)


def make_state() -> tuple[object, Actor, UUID]:
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user("mcp-read-owner", "MCP Read Owner")
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
    source = container.journal_capture.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=JOURNAL_DATE,
        occurred_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        source_recorded_at=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        raw_text="Känslig journaltext som inte ska läcka implicit.",
        language="sv",
        replaces_source_id=None,
        idempotency_key="mcp-read-source",
    )
    entry = container.journal_capture.create_manual_entry(
        actor,
        source_id=source.id,
        title="MCP läsbar journalpost",
        summary="Ett manuellt beslut.",
        key_points=(KeyPoint(KeyPointKind.DECISION, "Följ upp beslutet."),),
        idempotency_key="mcp-read-entry",
    )
    content = SummaryContent(
        overview="Dagens översikt.",
        overview_entry_ids=[entry.id],
        themes=[],
        important_events=[],
        decisions=[],
        commitments=[],
        open_questions=[],
        unresolved_items=[],
        contradictions=[],
    )
    container.journal_day.put_manual_summary(
        actor,
        journal_date=JOURNAL_DATE,
        expected_entry_fingerprint=entry_fingerprint([entry]),
        expected_summary_version=None,
        content=content,
        idempotency_key="mcp-read-summary",
    )
    return container, actor, entry.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_journal_reads_are_bounded_ordered_and_return_content_by_default() -> None:
    container, actor, entry_id = make_state()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        listed = await client.call_tool(
            "list_journal_entries",
            {
                "from_date": "2026-07-21",
                "to_date": "2026-07-21",
                "limit": 10,
            },
        )
        listed_entry = listed.structured_content["entries"][0]
        assert listed_entry["id"] == str(entry_id)
        assert listed_entry["title"] == "MCP läsbar journalpost"
        assert listed_entry["summary"] == "Ett manuellt beslut."
        assert listed_entry["key_points"][0]["text"] == "Följ upp beslutet."
        assert listed_entry["archived"] is False
        assert listed.structured_content["next_cursor"] is None
        # Block 2 is the full structured result (D-060), so the host model reads the summary too.
        assert "Ett manuellt beslut." in listed.content[1].text
        # The raw source text is never part of an entry record.
        assert "Känslig" not in str(listed.structured_content)

        detailed = await client.call_tool(
            "get_journal_entry",
            {"entry_id": str(entry_id)},
        )
        entry = detailed.structured_content["entry"]
        assert entry["summary"] == "Ett manuellt beslut."
        assert entry["key_points"][0]["text"] == "Följ upp beslutet."

        # The gateways force include_content=False; the opt-out still leaves the summary out.
        hidden = await client.call_tool(
            "get_journal_entry",
            {"entry_id": str(entry_id), "include_content": False},
        )
        assert hidden.structured_content["entry"]["summary"] is None
        assert hidden.structured_content["entry"]["key_points"] == []
        assert "Ett manuellt beslut." not in hidden.content[1].text

        day = await client.call_tool(
            "get_journal_day",
            {
                "journal_date": "2026-07-21",
                "include_content": True,
                "limit": 10,
            },
        )
        assert day.structured_content["journal_date"] == "2026-07-21"
        assert day.structured_content["entries"][0]["id"] == str(entry_id)
        assert day.structured_content["summary"]["exists"] is True
        assert day.structured_content["summary"]["status"] == "current"

        summary = await client.call_tool(
            "get_daily_journal_summary", {"journal_date": "2026-07-21"}
        )
        assert summary.structured_content["summary"]["content"]["overview"] == ("Dagens översikt.")
        assert summary.structured_content["summary"]["entry_ids"] == [str(entry_id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_journal_reads_enforce_date_range_cursor_and_safe_missing_errors() -> None:
    container, actor, entry_id = make_state()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "list_journal_entries",
                {"from_date": "2025-01-01", "to_date": "2026-01-02"},
            )
        # A day nobody wrote on is an empty day with its done section, not an error.
        empty_day = await client.call_tool("get_journal_day", {"journal_date": "2026-07-22"})
        assert empty_day.structured_content["entries"] == []
        assert empty_day.structured_content["done"]["counts"] == {
            "tasks": 0,
            "steps": 0,
            "purchases": 0,
        }
        with pytest.raises(ToolError):
            await client.call_tool(
                "get_journal_entry",
                {"entry_id": str(UUID("01910000-0000-7000-8000-000000000099"))},
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "list_journal_entries",
                {
                    "from_date": "2026-07-21",
                    "to_date": "2026-07-21",
                    "limit": 0,
                },
            )

        assert entry_id


READ_SCOPES = frozenset({"journal:read", "journal:write"})
SOURCE_TEXT = "Känslig journaltext som inte ska läcka implicit."
PENDING_DAY = date(2026, 7, 22)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_journal_source_returns_provenance_and_text_by_default() -> None:
    container, actor, entry_id = make_state()
    source_id = container.journal.get_entry(actor, entry_id).source_id
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        plain = await client.call_tool("get_journal_source", {"source_id": str(source_id)})
        source = plain.structured_content["source"]
        assert source["id"] == str(source_id)
        assert source["source_type"] == "manual_text"
        assert source["journal_date"] == "2026-07-21"
        assert source["occurred_at"].startswith("2026-07-21T09:00:00")
        assert source["source_recorded_at"].startswith("2026-07-24T08:00:00")
        assert source["language"] == "sv"
        assert source["replaces_source_id"] is None
        assert len(source["content_fingerprint"]) == 64
        assert source["raw_text"] == SOURCE_TEXT
        assert plain.content[0].text == (
            f"The source text from 21 July (manual text).\nSource {source_id}."
        )
        assert SOURCE_TEXT in plain.content[1].text

        detailed = await client.call_tool(
            "get_journal_source",
            {"source_id": str(source_id), "include_content": True},
        )
        assert detailed.structured_content["source"]["raw_text"] == SOURCE_TEXT

        hidden = await client.call_tool(
            "get_journal_source",
            {"source_id": str(source_id), "include_content": False},
        )
        assert hidden.structured_content["source"]["raw_text"] is None
        assert "Känslig" not in str(hidden.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_journal_source_hides_another_owners_source_as_not_found() -> None:
    container, actor, entry_id = make_state()
    source_id = container.journal.get_entry(actor, entry_id).source_id
    other_id = container.auth.provision_user("mcp-source-other", "Other")
    other = Actor(other_id, READ_SCOPES)
    server = create_mcp_server(container, actor_provider=lambda: other, enable_auth=False)

    async with Client(server) as client:
        foreign = await client.call_tool(
            "get_journal_source",
            {"source_id": str(source_id), "include_content": True},
            raise_on_error=False,
        )
        missing = await client.call_tool(
            "get_journal_source",
            {"source_id": str(uuid4()), "include_content": True},
            raise_on_error=False,
        )

    assert foreign.is_error and missing.is_error
    assert foreign.structured_content["code"] == "not_found"
    assert missing.structured_content["code"] == "not_found"
    assert foreign.structured_content["message"] == missing.structured_content["message"]
    assert "Känslig" not in str(foreign.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_pending_journal_is_owner_scoped_bounded_and_text_free() -> None:
    container, actor, _entry_id = make_state()
    for index in range(2):
        container.journal_capture.create_source(
            actor,
            source_type=SourceType.MANUAL_TEXT,
            journal_date=PENDING_DAY,
            occurred_at=None,
            source_recorded_at=None,
            raw_text=f"Väntande källtext {index} som ska stanna i databasen.",
            language=None,
            replaces_source_id=None,
            idempotency_key=f"mcp-pending-owner-{index}",
        )
    other_id = container.auth.provision_user("mcp-pending-other", "Other")
    other = Actor(other_id, READ_SCOPES)
    container.journal_capture.create_source(
        other,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=PENDING_DAY,
        occurred_at=None,
        source_recorded_at=None,
        raw_text="Annan ägares väntande text.",
        language=None,
        replaces_source_id=None,
        idempotency_key="mcp-pending-other-1",
    )
    window = {"from_date": "2026-07-22", "to_date": "2026-07-22"}

    owner_server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(owner_server) as client:
        listed = await client.call_tool("list_pending_journal", window)
        items = listed.structured_content["items"]
        assert len(items) == 2
        assert {item["state"] for item in items} == {"source_saved"}
        assert {item["journal_date"] for item in items} == {"2026-07-22"}
        assert all(item["draft_id"] is None and item["draft_title"] is None for item in items)
        assert "Väntande" not in str(listed.structured_content)
        assert "Annan" not in str(listed.structured_content)

        limited = await client.call_tool("list_pending_journal", {**window, "limit": 1})
        assert len(limited.structured_content["items"]) == 1

        for bad in ({**window, "limit": 0}, {**window, "limit": 101}):
            with pytest.raises(ToolError):
                await client.call_tool("list_pending_journal", bad)
        with pytest.raises(ToolError):
            await client.call_tool("list_pending_journal", {"from_date": "2026-07-22"})
        with pytest.raises(ToolError):
            await client.call_tool(
                "list_pending_journal",
                {"from_date": "2025-01-01", "to_date": "2026-07-22"},
            )

    other_server = create_mcp_server(container, actor_provider=lambda: other, enable_auth=False)
    async with Client(other_server) as client:
        seen = await client.call_tool("list_pending_journal", window)
        assert len(seen.structured_content["items"]) == 1
        assert "Väntande" not in str(seen.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_source_and_pending_reads_are_forbidden_without_journal_read() -> None:
    container, actor, entry_id = make_state()
    source_id = container.journal.get_entry(actor, entry_id).source_id
    stranger = Actor(actor.user_id, frozenset({"projects:read"}))
    server = create_mcp_server(container, actor_provider=lambda: stranger, enable_auth=False)

    async with Client(server) as client:
        for tool, arguments in (
            ("get_journal_source", {"source_id": str(source_id)}),
            ("list_pending_journal", {"from_date": "2026-07-22", "to_date": "2026-07-22"}),
        ):
            denied = await client.call_tool(tool, arguments, raise_on_error=False)
            assert denied.is_error, tool
            assert denied.structured_content["code"] == "forbidden", tool


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
    """Attach to root and to every logger, as test_tool_argument_logging does."""

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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_source_reads_never_write_source_text_to_a_log(all_logs: _Collector) -> None:
    sentinel = "sentinel-journal-source-text-4c1e"
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user("mcp-source-log", "Log")
    actor = Actor(user_id, READ_SCOPES)
    source = container.journal_capture.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=PENDING_DAY,
        occurred_at=None,
        source_recorded_at=None,
        raw_text=sentinel,
        language=None,
        replaces_source_id=None,
        idempotency_key="mcp-source-log-1",
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        await client.call_tool("get_journal_source", {"source_id": str(source.id)})
        await client.call_tool(
            "get_journal_source",
            {"source_id": str(source.id), "include_content": True},
        )
        await client.call_tool(
            "list_pending_journal",
            {"from_date": "2026-07-22", "to_date": "2026-07-22"},
        )
        await client.call_tool(
            "get_journal_source",
            {"source_id": str(uuid4()), "include_content": True},
            raise_on_error=False,
        )

    assert sentinel not in all_logs.rendered()
    assert all(not record.args for record in all_logs.records)

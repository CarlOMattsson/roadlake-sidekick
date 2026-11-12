"""MCP behaviour of `recall_memory` over the fake provider and PostgreSQL.

The fake provider supplies facts, one per non-empty line of a document; Postgres decides which may
leave and supplies titles and dates. Rows are written with the ORM so that lifecycle state (trash,
archive, switched-off domains, missing settings) is explicit.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastmcp import Client
from sqlalchemy.orm import Session, sessionmaker

from sidekick.mcp import memory as mcp_memory
from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.domain import MemoryKind
from sidekick.memory.ports import RetainItem
from sidekick.shared.persistence.models import (
    ContactRow,
)
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.mcp_recall import (
    ALL_SCOPES,
    NOW,
    _contact,
    _container,
    _journal,
    _memory_row,
    _owner,
    _project,
    _server,
    _settings,
    _structured,
    _task,
)


def _retain(
    provider: FakeMemoryProvider,
    owner_id: UUID,
    doc_key: str,
    text: str,
    *,
    timestamp: str = "unset",
) -> None:
    provider.retain_batch(
        owner_id=owner_id,
        items=[
            RetainItem(
                document_id=doc_key,
                content=text,
                timestamp=timestamp,
                entities=(),
                tags=(),
            )
        ],
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_recall_memory_returns_titles_dates_and_archived_flags() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    _settings(factory, owner, journal=True, contacts=True, projects=True, tasks=True)
    provider = FakeMemoryProvider()
    container.memory = provider
    entry = _journal(factory, owner, "Morgonmöte")
    contact = _contact(factory, owner, "Sara Lind", archived=True)
    task = _task(
        factory,
        owner,
        "Skicka offert till Sara",
        completed_at=datetime(2026, 10, 19, 15, tzinfo=UTC),
    )
    project = _project(factory, owner, "Sara-projektet")
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, entry),
        "Sara bytte jobb till Volvo",
        timestamp="2026-10-12",
    )
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, contact), "Sara är kollega"
    )
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.TASK, task), "Sara väntar på offert"
    )
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.PROJECT, project),
        "Sara leder projektet",
    )

    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        call = await client.call_tool("recall_memory", {"query": "Sara"})

    assert not call.is_error
    structured = _structured(call.structured_content)
    assert structured["status"] == "ok"
    assert structured["truncated"] is False
    by_kind = {fact["source"]["kind"]: fact for fact in structured["facts"]}
    assert set(by_kind) == {"journal_entry", "contact", "task", "project"}

    journal_fact = by_kind["journal_entry"]
    assert journal_fact["text"] == "Sara bytte jobb till Volvo"
    assert journal_fact["occurred"] == "2026-10-12"
    assert journal_fact["source"] == {
        "kind": "journal_entry",
        "id": str(entry),
        "title": "Morgonmöte",
        "date": "2026-10-20",
        "archived": False,
    }
    contact_fact = by_kind["contact"]
    assert contact_fact["occurred"] is None
    assert contact_fact["source"]["title"] == "Sara Lind"
    assert contact_fact["source"]["date"] is None
    assert contact_fact["source"]["archived"] is True
    assert by_kind["task"]["source"]["title"] == "Skicka offert till Sara"
    assert by_kind["task"]["source"]["date"] == "2026-10-19"
    assert by_kind["project"]["source"]["title"] == "Sara-projektet"
    assert by_kind["project"]["source"]["date"] == "2026-09-01"

    assert call.content[0].text == "Found 4 facts in memory."
    assert "Morgonmöte" in call.content[1].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_explicit_kind_without_read_scope_is_forbidden() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    _settings(factory, owner, contacts=True, journal=True)
    container.memory = FakeMemoryProvider()

    async with Client(_server(container, Actor(owner, frozenset({"journal:read"})))) as client:
        denied = await client.call_tool(
            "recall_memory",
            {"query": "Sara", "kinds": ["journal_entry", "contact"]},
            raise_on_error=False,
        )

    assert denied.is_error
    assert _structured(denied.structured_content)["code"] == "forbidden"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_omitted_kinds_skip_unreadable_kinds_silently() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    _settings(factory, owner, journal=True, contacts=True)
    provider = FakeMemoryProvider()
    container.memory = provider
    entry = _journal(factory, owner, "Morgonmöte")
    contact = _contact(factory, owner, "Sara Lind")
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, entry),
        "Sara i dagboken",
        timestamp="2026-10-12",
    )
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.CONTACT, contact),
        "Sara i kontakter",
    )

    async with Client(_server(container, Actor(owner, frozenset({"journal:read"})))) as client:
        call = await client.call_tool("recall_memory", {"query": "Sara"})

    assert not call.is_error
    facts = _structured(call.structured_content)["facts"]
    assert [fact["source"]["kind"] for fact in facts] == ["journal_entry"]
    assert facts[0]["text"] == "Sara i dagboken"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_readable_kind_at_all_is_forbidden() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    _settings(factory, owner, journal=True)
    container.memory = FakeMemoryProvider()

    async with Client(_server(container, Actor(owner, frozenset({"contacts:write"})))) as client:
        denied = await client.call_tool("recall_memory", {"query": "Sara"}, raise_on_error=False)

    assert denied.is_error
    assert _structured(denied.structured_content)["code"] == "forbidden"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unavailable_provider_is_a_status_not_a_tool_error() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    _settings(factory, owner, journal=True)
    container.memory = FakeMemoryProvider(available=False)

    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        call = await client.call_tool("recall_memory", {"query": "Sara"})

    assert not call.is_error
    assert _structured(call.structured_content) == {
        "status": "unavailable",
        "facts": [],
        "truncated": False,
    }
    assert call.content[0].text == "Memory is unavailable; continue with search."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_trashed_records_never_appear_in_recall() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    _settings(factory, owner, contacts=True)
    provider = FakeMemoryProvider()
    container.memory = provider
    live = _contact(factory, owner, "Sara Lind")
    trashed = _contact(factory, owner, "Sara gammal", trashed=True)
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, live), "Sara är kollega"
    )
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, trashed), "Sara gammal vän"
    )

    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        call = await client.call_tool("recall_memory", {"query": "Sara"})

    structured = _structured(call.structured_content)
    assert [fact["text"] for fact in structured["facts"]] == ["Sara är kollega"]
    assert structured["facts"][0]["source"]["title"] == "Sara Lind"
    assert "Sara gammal" not in call.content[1].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_limit_marks_truncation_and_summary_says_so() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    _settings(factory, owner, contacts=True)
    provider = FakeMemoryProvider()
    container.memory = provider
    first = _contact(factory, owner, "Sara Lind")
    second = _contact(factory, owner, "Sara Berg")
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, first), "Sara är kollega"
    )
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, second), "Sara är granne"
    )

    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        call = await client.call_tool("recall_memory", {"query": "Sara", "limit": 1})

    structured = _structured(call.structured_content)
    assert len(structured["facts"]) == 1
    assert structured["truncated"] is True
    assert call.content[0].text.startswith("Found 1 fact in memory.")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_memory_off_answers_disabled_without_a_provider() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    assert container.memory is None

    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        call = await client.call_tool("recall_memory", {"query": "Sara"})

    assert not call.is_error
    assert _structured(call.structured_content) == {
        "status": "disabled",
        "facts": [],
        "truncated": False,
    }
    assert call.content[0].text == "Memory is off."


def _trash_before_enrichment(
    monkeypatch: pytest.MonkeyPatch,
    factory: sessionmaker[Session],
    trashed: UUID,
) -> None:
    """Trash one contact after recall verified it and before the titles are read (the race)."""

    original = mcp_memory.source_details

    def trash_then_enrich(
        store: Any, session: Session, owner_id: UUID, facts: Any
    ) -> dict[tuple[MemoryKind, UUID], Any]:
        with factory.begin() as tx:
            row = tx.get(ContactRow, trashed)
            assert row is not None
            row.trashed_at = NOW
        return original(store, session, owner_id, facts)

    monkeypatch.setattr(mcp_memory, "source_details", trash_then_enrich)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fact_whose_source_is_trashed_before_enrichment_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    _settings(factory, owner, contacts=True)
    provider = FakeMemoryProvider()
    container.memory = provider
    live = _contact(factory, owner, "Sara Lind")
    racing = _contact(factory, owner, "Sara Berg")
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, live), "Sara är kollega"
    )
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, racing), "Sara är granne"
    )
    _trash_before_enrichment(monkeypatch, factory, racing)

    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        call = await client.call_tool("recall_memory", {"query": "Sara"})

    assert not call.is_error
    structured = _structured(call.structured_content)
    assert structured["status"] == "ok"
    assert [fact["text"] for fact in structured["facts"]] == ["Sara är kollega"]
    assert "Sara är granne" not in call.content[1].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_facts_trashed_before_enrichment_report_empty_not_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = database_factory()
    container = _container(factory)
    owner = _owner(container)
    _settings(factory, owner, contacts=True)
    provider = FakeMemoryProvider()
    container.memory = provider
    racing = _contact(factory, owner, "Sara Berg")
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, racing), "Sara är granne"
    )
    _trash_before_enrichment(monkeypatch, factory, racing)

    async with Client(_server(container, Actor(owner, ALL_SCOPES))) as client:
        call = await client.call_tool("recall_memory", {"query": "Sara"})

    assert not call.is_error
    assert _structured(call.structured_content) == {
        "status": "empty",
        "facts": [],
        "truncated": False,
    }
    assert call.content[0].text == "No facts in memory for this query."

"""`write_journal_entry`: one source and one entry in a single, retry-safe transaction."""

import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client
from sqlalchemy import text

from sidekick.contacts.application.models import CreateContactCommand
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.support.fakes import JOURNAL_REDACTION_SENTINEL_ONE, JOURNAL_REDACTION_SENTINEL_TWO
from tests.support.mcp_journal_write import (
    SETUP,
    args,
    make_container,
    make_project,
)
from tests.support.telemetry import CaptureTelemetry


def counts(container: Any) -> tuple[int, int]:
    with container.session_factory() as session:
        sources = session.execute(
            text("SELECT count(*) FROM sidekick.journal_sources")
        ).scalar_one()
        entries = session.execute(
            text("SELECT count(*) FROM sidekick.journal_entries")
        ).scalar_one()
    return sources, entries


@pytest.mark.asyncio
@pytest.mark.integration
async def test_one_call_creates_a_source_and_an_entry_with_relations() -> None:
    container, actor = make_container()
    setup = Actor(actor.user_id, SETUP)
    project = make_project(container, actor.user_id, "we-project")
    task = container.tasks.create(setup, title="Uppgift", idempotency_key="we-task")
    contact = container.contacts.create(
        setup, CreateContactCommand(display_name="Anna"), "we-contact"
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        tool = {item.name: item for item in await client.list_tools()}["write_journal_entry"]
        assert tool.meta["ui"]["resourceUri"].startswith("ui://")
        assert {"journal_date", "title", "source_text", "idempotency_key"} == set(
            tool.inputSchema["required"]
        )
        response = await client.call_tool(
            "write_journal_entry",
            args(
                "we-relations-1",
                project_ids=[str(project.id)],
                task_ids=[str(task.id)],
                contact_ids=[str(contact.id)],
            ),
        )
        entry = response.structured_content["entry"]
        assert entry["title"] == "En bra dag"
        assert entry["version"] == 1
        assert entry["project_ids"] == [str(project.id)]
        assert entry["task_ids"] == [str(task.id)]
        assert entry["contact_ids"] == [str(contact.id)]
        # Block 1 opens with a sentence and carries the id on line 2; it holds no entry text.
        # The names of the links are in the text (D-060); the entry's own text is not.
        assert response.content[0].text == (
            f"Saved the journal entry from 28 October.\nEntry {entry['id']} v1.\n"
            "Linked to Projekt and Anna."
        )
        assert "En bra dag" not in response.content[0].text
        assert entry["links"] == [
            {"kind": "project", "id": str(project.id), "label": "Projekt"},
            {"kind": "contact", "id": str(contact.id), "label": "Anna"},
        ]

        source = await client.call_tool("get_journal_source", {"source_id": entry["source_id"]})
        assert source.structured_content["source"]["source_type"] == "transcript_text"
        assert source.structured_content["source"]["raw_text"].startswith("Jag pratade")
        stored = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
        assert stored.structured_content["entry"]["project_ids"] == [str(project.id)]

    assert counts(container) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_relations_are_optional_and_default_to_empty() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        response = await client.call_tool(
            "write_journal_entry",
            {
                "journal_date": "2026-10-28",
                "title": "Minimal",
                "source_text": "Kort.",
                "idempotency_key": "we-minimal-1",
            },
        )
    entry = response.structured_content["entry"]
    assert entry["summary"] is None
    assert entry["key_points"] == []
    assert (entry["project_ids"], entry["task_ids"], entry["contact_ids"]) == ([], [], [])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_retry_with_the_same_key_returns_the_same_entry() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        first = await client.call_tool("write_journal_entry", args("we-retry-1"))
        replay = await client.call_tool("write_journal_entry", args("we-retry-1"))
        assert first.structured_content == replay.structured_content
        changed = await client.call_tool(
            "write_journal_entry", args("we-retry-1", title="Annan"), raise_on_error=False
        )
        assert changed.is_error
        assert changed.structured_content["code"] in {"conflict", "idempotency_conflict"}
        changed_source = await client.call_tool(
            "write_journal_entry",
            args("we-retry-1", source_text="Annan källa."),
            raise_on_error=False,
        )
        assert changed_source.is_error

    assert counts(container) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("failure", ["unknown_task", "blank_title"])
async def test_a_failing_entry_leaves_no_source_behind(failure: str) -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    overrides: dict[str, Any] = (
        {"task_ids": [str(uuid4())]} if failure == "unknown_task" else {"title": "   "}
    )

    async with Client(server) as client:
        failed = await client.call_tool(
            "write_journal_entry", args("we-fail-1", **overrides), raise_on_error=False
        )
        assert failed.is_error
        assert counts(container) == (0, 0)
        with container.session_factory() as session:
            keys = session.execute(
                text("SELECT count(*) FROM sidekick.idempotency_operations")
            ).scalar_one()
        assert keys == 0
        # The same key is not poisoned: a corrected retry succeeds and creates exactly one pair.
        retry = await client.call_tool("write_journal_entry", args("we-fail-1"))
        assert not retry.is_error

    assert counts(container) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_scopes_are_refused_before_anything_is_written() -> None:
    container, actor = make_container()
    project = make_project(container, actor.user_id, "we-scope-project")
    for scopes, extra in (
        (frozenset({"journal:read"}), {}),
        (frozenset({"journal:write"}), {"project_ids": [str(project.id)]}),
    ):
        limited = Actor(actor.user_id, scopes)
        server = create_mcp_server(container, actor_provider=lambda a=limited: a, enable_auth=False)
        async with Client(server) as client:
            refused = await client.call_tool(
                "write_journal_entry", args("we-scope-1", **extra), raise_on_error=False
            )
        assert refused.is_error and refused.structured_content["code"] == "forbidden"

    assert counts(container) == (0, 0)

    write_only = Actor(actor.user_id, frozenset({"journal:write"}))
    server = create_mcp_server(container, actor_provider=lambda: write_only, enable_auth=False)
    async with Client(server) as client:
        ok = await client.call_tool("write_journal_entry", args("we-scope-2"))
    assert not ok.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_owner_cannot_attach_to_this_owners_records() -> None:
    container, actor = make_container()
    other_id = container.auth.provision_user("write-entry-other", "Other")
    other = Actor(other_id, SETUP)
    foreign = container.tasks.create(other, title="Annans", idempotency_key="we-foreign-task")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        refused = await client.call_tool(
            "write_journal_entry",
            args("we-foreign-1", task_ids=[str(foreign.id)]),
            raise_on_error=False,
        )
    assert refused.is_error and refused.structured_content["code"] == "not_found"
    assert counts(container) == (0, 0)


class _Collector(logging.Handler):
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
async def test_journal_text_stays_out_of_logs_telemetry_and_errors(all_logs: _Collector) -> None:
    telemetry = CaptureTelemetry()
    container, actor = make_container(telemetry)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    private = {
        "title": f"{JOURNAL_REDACTION_SENTINEL_ONE} titel",
        "summary": f"{JOURNAL_REDACTION_SENTINEL_TWO} sammanfattning",
        "source_text": f"{JOURNAL_REDACTION_SENTINEL_ONE} {JOURNAL_REDACTION_SENTINEL_TWO} källa",
        "key_points": [{"kind": "decision", "text": f"{JOURNAL_REDACTION_SENTINEL_TWO} punkt"}],
    }

    async with Client(server) as client:
        ok = await client.call_tool("write_journal_entry", args("we-log-1", **private))
        assert not ok.is_error
        conflict = await client.call_tool(
            "write_journal_entry",
            args("we-log-1", **{**private, "title": f"{JOURNAL_REDACTION_SENTINEL_ONE} ny"}),
            raise_on_error=False,
        )
        assert conflict.is_error
        unknown = await client.call_tool(
            "write_journal_entry",
            args("we-log-2", **private, task_ids=[str(uuid4())]),
            raise_on_error=False,
        )
        assert unknown.is_error
        too_long = await client.call_tool(
            "write_journal_entry",
            args("we-log-3", **{**private, "title": private["title"] + "x" * 300}),
            raise_on_error=False,
        )
        assert too_long.is_error

    rendered = all_logs.rendered()
    for sentinel in (JOURNAL_REDACTION_SENTINEL_ONE, JOURNAL_REDACTION_SENTINEL_TWO):
        assert sentinel not in rendered
        assert sentinel not in str(telemetry.records)
        for failed in (conflict, unknown):
            assert sentinel not in str(failed.structured_content)
            assert sentinel not in str(failed.content)
    assert all(not record.args for record in all_logs.records)
    assert all(record.exc_info is None for record in all_logs.records)

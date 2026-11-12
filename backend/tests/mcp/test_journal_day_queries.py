"""get_journal_day reads a day in a fixed number of SQL statements, however many entries it has."""

import time
from typing import Any

import pytest
from fastmcp import Client
from sqlalchemy import Engine, event

from sidekick.contacts.application.models import CreateContactCommand
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.support.mcp_journal_write import SETUP, args, make_container, make_project


async def _statements_for_day(entry_count: int, key: str) -> tuple[int, float, dict[str, Any]]:
    container, actor = make_container()
    setup = Actor(actor.user_id, SETUP)
    project = make_project(container, actor.user_id, f"{key}-project")
    anna = container.contacts.create(
        setup, CreateContactCommand(display_name="Anna Andersson"), f"{key}-anna"
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    engine: Engine = container.session_factory.kw["bind"]
    async with Client(server) as client:
        for index in range(entry_count):
            await client.call_tool(
                "write_journal_entry",
                args(
                    f"{key}-write-{index}",
                    title=f"Post {index}",
                    project_ids=[str(project.id)],
                    contact_ids=[str(anna.id)],
                ),
            )
        statements: list[str] = []

        def record(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            started = time.perf_counter()
            response = await client.call_tool(
                "get_journal_day", {"journal_date": "2026-10-28", "limit": 50}
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
        finally:
            event.remove(engine, "before_cursor_execute", record)
    assert response.structured_content is not None
    return len(statements), elapsed_ms, response.structured_content


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_journal_day_statement_count_does_not_grow_with_entries() -> None:
    few_count, few_ms, few = await _statements_for_day(2, "qd-few")
    many_count, many_ms, many = await _statements_for_day(6, "qd-many")

    print(f"get_journal_day statements: 2 entries={few_count}, 6 entries={many_count}")
    print(f"get_journal_day ms: 2 entries={few_ms:.1f}, 6 entries={many_ms:.1f}")
    assert len(few["entries"]) == 2
    assert len(many["entries"]) == 6
    # Links are still named for every entry.
    for entry in many["entries"]:
        assert [(link["kind"], link["label"]) for link in entry["links"]] == [
            ("project", "Projekt"),
            ("contact", "Anna Andersson"),
        ]
    assert many_count == few_count

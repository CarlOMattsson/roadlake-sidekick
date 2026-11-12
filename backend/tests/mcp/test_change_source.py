"""Who made a change: Claude through a model tool, the owner through an app-only tool or the app.

The audit trail records the source of the transport that made the change. `list_recent_changes`
reports it as `claude`, `you` or `unknown` (not recorded). Only the closed word is stored.
"""

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.companion import bearer, companion_app, create_task, owner, paired_token
from tests.support.settings import make_settings

COMPLETE = {"companion:tasks:complete"}


def _setup() -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    owner_id = container.auth.provision_user("source-owner", "Source Owner")
    return container, Actor(owner_id, frozenset(MCP_SCOPES))


def _client(container: Container, actor: Actor) -> Client[Any]:
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    return Client(server)


async def _changes(client: Client[Any]) -> list[dict[str, Any]]:
    result = await client.call_tool("list_recent_changes", {})
    assert result.structured_content is not None
    return list(result.structured_content["changes"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_model_tool_is_claude_and_an_app_only_tool_is_you() -> None:
    container, actor = _setup()
    async with _client(container, actor) as client:
        task = await client.call_tool(
            "create_task", {"title": "Bokat av Claude", "idempotency_key": f"src-{uuid4()}"}
        )
        assert task.structured_content is not None
        task_id = task.structured_content["task"]["id"]
        source = await client.call_tool(
            "create_journal_source",
            {
                "source_type": "manual_text",
                "journal_date": date(2026, 11, 1).isoformat(),
                "raw_text": "Skriven i appen",
                "idempotency_key": f"src-{uuid4()}",
            },
        )
        assert source.structured_content is not None
        entry = await client.call_tool(
            "create_manual_journal_entry",
            {
                "source_id": source.structured_content["source"]["id"],
                "title": "Skriven av dig",
                "summary": None,
                "key_points": [],
                "project_ids": [],
                "task_ids": [],
                "contact_ids": [],
                "idempotency_key": f"src-{uuid4()}",
            },
        )
        assert entry.structured_content is not None
        entry_id = entry.structured_content["entry"]["id"]
        by_id = {change["id"]: change["actor"] for change in await _changes(client)}
    assert by_id[task_id] == "claude"
    assert by_id[entry_id] == "you"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_change_written_outside_a_request_is_unknown() -> None:
    container, actor = _setup()
    task = container.tasks.create(actor, title="Utan källa", idempotency_key=f"src-{uuid4()}")
    async with _client(container, actor) as client:
        [change] = await _changes(client)
    assert change["id"] == str(task.id)
    assert change["actor"] == "unknown"


@pytest.mark.integration
def test_a_change_from_the_companion_app_is_you() -> None:
    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id, title="Klarmarkeras i appen")
    with TestClient(app) as http:
        token = paired_token(http, app, user_id, scopes=COMPLETE)
        done = http.post(
            f"/companion/v1/tasks/{task.id}/complete",
            headers={**bearer(token), "Idempotency-Key": f"src-{uuid4()}"},
            json={"version": task.version},
        )
        assert done.status_code == 200, done.text
    actor = Actor(user_id, frozenset(MCP_SCOPES))
    changes = app.state.container.lifecycle.list_recent_changes(actor, limit=5)
    completed = [change for change in changes if change.action == "completed"]
    assert [change.actor for change in completed] == ["you"]


@pytest.mark.integration
def test_the_stored_source_is_one_of_two_words_or_null() -> None:
    container, _ = _setup()
    store: Any = container.session_factory

    def insert(source: str | None) -> None:
        with store.begin() as session:
            session.execute(
                text(
                    "INSERT INTO sidekick.audit_events (id, event, outcome, source, occurred_at) "
                    "VALUES (:id, 'test.event', 'success', :source, now())"
                ),
                {"id": UUID(int=uuid4().int), "source": source},
            )

    insert(None)
    insert("you")
    insert("claude")
    with pytest.raises(IntegrityError):
        insert("someone else")

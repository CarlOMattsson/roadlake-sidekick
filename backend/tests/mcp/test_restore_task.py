"""restore_task: bring an archived Task back, the undo of archive (also of a review's archive).

Version-checked and retry-safe like the other single-Task writes, with its own activity entry.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.instrument import instrument_mcp
from sidekick.mcp.review import register_review_tools
from sidekick.mcp.task_tools import register_task_tools
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.types import Actor
from sidekick.tasks.domain import Task
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"tasks:read", "tasks:write", "projects:read"})
TITLE = "Hemlig arkiverad titel"


def _setup(username: str = "restore-owner") -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(username, "Restore Owner")
    return container, Actor(owner, SCOPES)


def _server(container: Container, actor: Actor) -> FastMCP:
    mcp = FastMCP("restore-task-test")
    ctx = ToolContext(container, lambda: actor, lambda name: instrument_mcp(container, name))
    register_task_tools(mcp, ctx)
    register_review_tools(mcp, ctx)
    return mcp


def _task(container: Container, actor: Actor) -> Task:
    return container.tasks.create(actor, title=TITLE, idempotency_key=f"restore-{uuid4().hex}")


async def _archive(client: Client[Any], task: Task) -> dict[str, Any]:
    saved = await client.call_tool(
        "review_tasks",
        {
            "items": [
                {"task_id": str(task.id), "expected_version": task.version, "decision": "archive"}
            ],
            "idempotency_key": f"archive-{uuid4().hex}",
        },
    )
    return saved.structured_content["tasks"][0]


async def _restore(client: Client[Any], task_id: object, version: int, key: str) -> Any:
    return await client.call_tool(
        "restore_task",
        {"task_id": str(task_id), "version": version, "idempotency_key": key},
        raise_on_error=False,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_archive_from_a_review_is_undone_and_a_retry_replays_it() -> None:
    container, actor = _setup()
    task = _task(container, actor)

    async with Client(_server(container, actor)) as client:
        archived = await _archive(client, task)
        restored = await _restore(client, task.id, archived["version"], "restore-once-1")
        replayed = await _restore(client, task.id, archived["version"], "restore-once-1")

    assert not restored.is_error, restored.structured_content
    record = restored.structured_content
    assert record["version"] == archived["version"] + 1
    assert record["archived"] is False
    assert record["title"] == TITLE
    assert replayed.structured_content == restored.structured_content
    stored = container.tasks.get(actor, task.id)
    assert stored.archived_at is None and stored.version == archived["version"] + 1
    # The review time stays, so the restored Task does not come straight back into the queue.
    assert stored.last_reviewed_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_version_is_a_conflict_and_the_task_stays_archived() -> None:
    container, actor = _setup()
    task = _task(container, actor)

    async with Client(_server(container, actor)) as client:
        archived = await _archive(client, task)
        stale = await _restore(client, task.id, task.version, "restore-stale-1")

    assert stale.is_error
    assert stale.structured_content["reason"] == "stale_version"
    still = container.tasks.store.transaction(
        lambda session: container.tasks.store.get_task(
            session, actor.user_id, task.id, include_archived=True
        )
    )
    assert still.archived_at is not None and still.version == archived["version"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_restoring_records_one_activity_entry_and_logs_no_title(
    caplog: pytest.LogCaptureFixture,
) -> None:
    container, actor = _setup()
    task = _task(container, actor)
    caplog.set_level(logging.DEBUG)

    async with Client(_server(container, actor)) as client:
        archived = await _archive(client, task)
        seen = {entry.id for entry in container.activity.list_activity(actor, limit=100).items}
        restored = await _restore(client, task.id, archived["version"], "restore-ledger-1")

    assert not restored.is_error
    entries = [
        entry
        for entry in container.activity.list_activity(actor, limit=100).items
        if entry.id not in seen
    ]
    assert [(entry.operation, entry.aggregate_id) for entry in entries] == [
        ("restore_task", task.id)
    ]
    assert TITLE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_without_tasks_write_or_for_another_owner_nothing_is_restored() -> None:
    container, actor = _setup()
    task = _task(container, actor)
    stranger = Actor(container.auth.provision_user("restore-stranger", "Stranger"), SCOPES)
    reader = Actor(actor.user_id, frozenset({"tasks:read"}))

    async with Client(_server(container, actor)) as client:
        archived = await _archive(client, task)
    async with Client(_server(container, reader)) as client:
        denied = await _restore(client, task.id, archived["version"], "restore-denied-1")
    async with Client(_server(container, stranger)) as client:
        foreign = await _restore(client, task.id, archived["version"], "restore-foreign-1")

    assert denied.structured_content["code"] == "forbidden"
    assert foreign.structured_content["code"] == "not_found"
    assert TITLE not in str(foreign.content)

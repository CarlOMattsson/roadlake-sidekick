"""`list_task_steps` reports how many active and how many done Actions each Step has."""

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.errors import PermissionDeniedError
from sidekick.shared.types import Actor
from sidekick.work.domain import ActionCounts
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_task_steps_counts_active_actions_and_reports_zero_without_any() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("count-owner", "Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    steps = container.steps
    task = container.tasks.create(actor, title="Counted", idempotency_key="count-task")
    busy = steps.create_step(actor, task.id, title="Busy", idempotency_key="count-s1")
    bare = steps.create_step(actor, task.id, title="Bare", idempotency_key="count-s2")
    emptied = steps.create_step(actor, task.id, title="Emptied", idempotency_key="count-s3")
    busy_actions = [
        steps.create_action(actor, busy.id, title=f"Action {n}", idempotency_key=f"count-a{n}")
        for n in range(4)
    ]
    # Done Actions count; an archived one counts as neither active nor done, done or not.
    steps.complete_action(
        actor, busy_actions[0].id, version=busy_actions[0].version, idempotency_key="count-done-0"
    )
    done_then_archived = steps.complete_action(
        actor, busy_actions[1].id, version=busy_actions[1].version, idempotency_key="count-done-1"
    )
    steps.archive_action(
        actor,
        done_then_archived.id,
        version=done_then_archived.version,
        idempotency_key="count-archive-done",
    )
    only = steps.create_action(actor, emptied.id, title="Gone", idempotency_key="count-gone")
    steps.archive_action(actor, only.id, version=only.version, idempotency_key="count-archive")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        listed = await client.call_tool("list_task_steps", {"task_id": str(task.id)})
        # A page that stops short counts only the Steps it returns.
        first = await client.call_tool("list_task_steps", {"task_id": str(task.id), "limit": 1})

    assert listed.structured_content is not None
    counts = {
        item["id"]: (item["action_count"], item["action_done_count"])
        for item in listed.structured_content["items"]
    }
    assert counts == {str(busy.id): (3, 1), str(bare.id): (0, 0), str(emptied.id): (0, 0)}
    assert first.structured_content is not None
    assert [
        (item["action_count"], item["action_done_count"])
        for item in first.structured_content["items"]
    ] == [(3, 1)]


@pytest.mark.integration
def test_action_counts_follow_the_read_scope_and_the_owner_of_the_steps() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("count-scope-owner", "Owner")
    stranger = container.auth.provision_user("count-scope-other", "Other")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    task = container.tasks.create(actor, title="Scoped", idempotency_key="scope-task")
    step = container.steps.create_step(actor, task.id, title="Step", idempotency_key="scope-step")
    container.steps.create_action(actor, step.id, title="Action", idempotency_key="scope-action")
    finished = container.steps.create_action(
        actor, step.id, title="Finished", idempotency_key="scope-finished"
    )
    container.steps.complete_action(
        actor, finished.id, version=finished.version, idempotency_key="scope-finish"
    )

    page, counts = container.steps.list_steps_with_action_counts(actor, task.id)
    assert [item.id for item in page.items] == [step.id]
    assert counts == {step.id: ActionCounts(active=2, completed=1)}

    # Another owner sees neither the Steps nor their counts.
    other_page, other_counts = container.steps.list_steps_with_action_counts(
        Actor(stranger, frozenset(MCP_SCOPES)), task.id
    )
    assert other_page.items == []
    assert other_counts == {}

    # Without tasks:read nothing is read at all, the counts included.
    with pytest.raises(PermissionDeniedError):
        container.steps.list_steps_with_action_counts(
            Actor(owner, frozenset({"tasks:write"})), task.id
        )

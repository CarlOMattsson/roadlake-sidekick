"""A completed Action is opened again with `update_step_action` and `status = open`."""

import pytest
from fastmcp import Client
from sqlalchemy import select

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.errors import ConflictError, NotFoundError, PermissionDeniedError
from sidekick.shared.persistence.models import AuditEventRow
from sidekick.shared.types import Actor
from sidekick.tasks.domain import TaskStatus
from sidekick.work.domain import ActionStatus
from tests.db import database_factory
from tests.support.settings import make_settings


def _completed_action(prefix: str):
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner = container.auth.provision_user(f"{prefix}-owner", "Owner")
    actor = Actor(owner, frozenset(MCP_SCOPES))
    task = container.tasks.create(actor, title="Parent", idempotency_key=f"{prefix}-task")
    step = container.steps.create_step(actor, task.id, title="Step", idempotency_key=f"{prefix}-s")
    created = container.steps.create_action(
        actor, step.id, title="Action", idempotency_key=f"{prefix}-a"
    )
    done = container.steps.complete_action(
        actor, created.id, version=created.version, idempotency_key=f"{prefix}-done"
    )
    return factory, container, actor, done


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_step_action_opens_a_completed_action_again_and_replays_by_key() -> None:
    factory, container, actor, done = _completed_action("reopen")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    arguments = {
        "action_id": str(done.id),
        "version": done.version,
        "idempotency_key": "reopen-action-open",
        "changes": {"status": "open"},
    }

    async with Client(server) as client:
        first = await client.call_tool("update_step_action", arguments)
        replay = await client.call_tool("update_step_action", arguments)

    assert first.structured_content is not None
    record = first.structured_content["action"]
    assert (record["status"], record["version"]) == ("open", done.version + 1)
    # The same key answers with the stored result and writes nothing a second time.
    assert replay.structured_content == first.structured_content
    stored = container.steps.list_actions(actor, done.step_id).items
    assert [(item.status, item.version) for item in stored] == [
        (ActionStatus.OPEN, done.version + 1)
    ]
    with factory() as session:
        events = session.scalars(
            select(AuditEventRow).where(AuditEventRow.target_id == done.id)
        ).all()
    reopened = [event for event in events if event.event == "action.reopened"]
    assert len(reopened) == 1
    assert reopened[0].target_type == "action"
    assert reopened[0].correlation_id
    assert [event.event for event in events].count("action.completed") == 1


@pytest.mark.integration
def test_a_status_change_is_recorded_as_complete_or_reopen_and_other_edits_are_not() -> None:
    factory, container, actor, done = _completed_action("status-audit")
    steps = container.steps
    opened = steps.update_action(
        actor,
        done.id,
        version=done.version,
        idempotency_key="status-audit-open",
        status=ActionStatus.OPEN,
    )
    renamed = steps.update_action(
        actor,
        done.id,
        version=opened.version,
        idempotency_key="status-audit-rename",
        title="Renamed",
    )
    ticked = steps.update_action(
        actor,
        done.id,
        version=renamed.version,
        idempotency_key="status-audit-tick",
        status=ActionStatus.COMPLETED,
    )

    assert ticked.status is ActionStatus.COMPLETED
    with factory() as session:
        events = session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.target_id == done.id)
            .order_by(AuditEventRow.occurred_at, AuditEventRow.id)
        ).all()
    assert [event.event for event in events] == [
        "action.created",
        "action.completed",
        "action.reopened",
        "action.updated",
        "action.completed",
    ]


@pytest.mark.integration
def test_reopening_follows_the_owner_the_scope_and_the_version() -> None:
    _factory, container, actor, done = _completed_action("reopen-guard")
    steps = container.steps
    stranger = Actor(
        container.auth.provision_user("reopen-guard-other", "Other"), frozenset(MCP_SCOPES)
    )

    with pytest.raises(NotFoundError):
        steps.update_action(
            stranger,
            done.id,
            version=done.version,
            idempotency_key="reopen-guard-stranger",
            status=ActionStatus.OPEN,
        )
    with pytest.raises(PermissionDeniedError):
        steps.update_action(
            Actor(actor.user_id, frozenset({"tasks:read"})),
            done.id,
            version=done.version,
            idempotency_key="reopen-guard-scope",
            status=ActionStatus.OPEN,
        )
    with pytest.raises(ConflictError):
        steps.update_action(
            actor,
            done.id,
            version=done.version - 1,
            idempotency_key="reopen-guard-stale",
            status=ActionStatus.OPEN,
        )

    # None of the refused writes changed the Action.
    stored = steps.list_actions(actor, done.step_id).items
    assert [(item.status, item.version) for item in stored] == [
        (ActionStatus.COMPLETED, done.version)
    ]


@pytest.mark.integration
def test_repeating_the_current_status_writes_no_version_and_no_event() -> None:
    factory, container, actor, done = _completed_action("status-noop")
    steps = container.steps

    again = steps.update_action(
        actor,
        done.id,
        version=done.version,
        idempotency_key="status-noop-tick",
        status=ActionStatus.COMPLETED,
    )
    open_action = steps.update_action(
        actor,
        done.id,
        version=done.version,
        idempotency_key="status-noop-open",
        status=ActionStatus.OPEN,
    )
    still_open = steps.update_action(
        actor,
        done.id,
        version=open_action.version,
        idempotency_key="status-noop-open-again",
        status=ActionStatus.OPEN,
    )

    assert (again.version, again.updated_at) == (done.version, done.updated_at)
    assert (still_open.version, still_open.updated_at) == (
        open_action.version,
        open_action.updated_at,
    )
    with pytest.raises(ConflictError):
        steps.update_action(
            actor,
            done.id,
            version=done.version - 1,
            idempotency_key="status-noop-stale",
            status=ActionStatus.OPEN,
        )
    with factory() as session:
        events = session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.target_id == done.id)
            .order_by(AuditEventRow.occurred_at, AuditEventRow.id)
        ).all()
    assert [event.event for event in events] == [
        "action.created",
        "action.completed",
        "action.reopened",
    ]


@pytest.mark.integration
def test_repeating_a_steps_current_status_writes_no_version_and_no_event() -> None:
    factory, container, actor, done = _completed_action("step-noop")
    steps = container.steps
    step = steps.get_step(actor, done.step_id)

    same = steps.update_step(
        actor,
        step.id,
        version=step.version,
        idempotency_key="step-noop-same",
        status=step.status,
    )
    ticked = steps.update_step(
        actor,
        step.id,
        version=step.version,
        idempotency_key="step-noop-tick",
        status=TaskStatus.COMPLETED,
    )
    ticked_again = steps.update_step(
        actor,
        step.id,
        version=ticked.version,
        idempotency_key="step-noop-tick-again",
        status=TaskStatus.COMPLETED,
    )

    assert (same.version, same.updated_at) == (step.version, step.updated_at)
    assert ticked.version == step.version + 1
    assert (ticked_again.version, ticked_again.updated_at) == (ticked.version, ticked.updated_at)
    with factory() as session:
        events = session.scalars(
            select(AuditEventRow).where(AuditEventRow.target_id == step.id)
        ).all()
    assert sorted(event.event for event in events) == ["step.created", "step.updated"]


@pytest.mark.integration
def test_completing_an_already_completed_action_writes_no_version_and_no_event() -> None:
    factory, container, actor, done = _completed_action("complete-action-twice")
    steps = container.steps

    again = steps.complete_action(
        actor, done.id, version=done.version, idempotency_key="complete-action-twice-again"
    )

    assert (again.version, again.updated_at) == (done.version, done.updated_at)
    with pytest.raises(ConflictError):
        steps.complete_action(
            actor, done.id, version=done.version - 1, idempotency_key="complete-action-twice-stale"
        )
    with factory() as session:
        events = session.scalars(
            select(AuditEventRow).where(AuditEventRow.target_id == done.id)
        ).all()
    assert sorted(event.event for event in events) == ["action.completed", "action.created"]


@pytest.mark.integration
def test_completing_an_already_completed_step_writes_no_version_and_no_event() -> None:
    factory, container, actor, done = _completed_action("complete-step-twice")
    steps = container.steps
    step = steps.get_step(actor, done.step_id)
    ticked = steps.complete_step(
        actor, step.id, version=step.version, idempotency_key="complete-step-twice-first"
    )

    again = steps.complete_step(
        actor, step.id, version=ticked.version, idempotency_key="complete-step-twice-again"
    )

    assert ticked.version == step.version + 1
    assert (again.version, again.updated_at) == (ticked.version, ticked.updated_at)
    with pytest.raises(ConflictError):
        steps.complete_step(
            actor, step.id, version=step.version, idempotency_key="complete-step-twice-stale"
        )
    with factory() as session:
        events = session.scalars(
            select(AuditEventRow).where(AuditEventRow.target_id == step.id)
        ).all()
    assert sorted(event.event for event in events) == ["step.completed", "step.created"]

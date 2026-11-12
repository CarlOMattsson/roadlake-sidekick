"""MCP `show_work_changes`: one read-only confirmation card for Work refs, owner-scoped and bounded.

The tool takes refs only (kind and id), reads each one through the same use cases as the `get_*`
tools, returns the `card` envelope, and leaves out unknown, foreign or trashed ids without saying
which of the three it was.
"""

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.shared.types import Actor, utc_now
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
FOREIGN_TITLE = "sentinel-foreign-work-title-5c2e"


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _seed_owner(container: Container, owner: UUID) -> dict[str, Any]:
    """One domain, project, task and step owned by `owner`."""

    actor = Actor(owner, SCOPES)
    domain = container.contexts.create_domain(
        actor, name="Cards domain", description=None, idempotency_key="cards-domain-0001"
    )
    project = container.projects.create(
        actor,
        title="Cards project",
        domain_id=domain.id,
        idempotency_key="cards-project-0001",
    )
    task = container.tasks.create(
        actor, title="Cards task", project_id=project.id, idempotency_key="cards-task-0001"
    )
    step = container.steps.create_step(
        actor, task.id, title="Cards step", idempotency_key="cards-step-0001"
    )
    return {
        "domain": (domain.id, domain.version, "Cards domain"),
        "project": (project.id, project.version, "Cards project"),
        "task": (task.id, task.version, "Cards task"),
        "step": (step.id, step.version, "Cards step"),
    }


async def _show(client: Client, refs: list[dict[str, str]]) -> Any:
    return await client.call_tool("show_work_changes", {"refs": refs}, raise_on_error=False)


def _ref(kind: str, record_id: UUID | str) -> dict[str, str]:
    return {"kind": kind, "id": str(record_id)}


@pytest.mark.asyncio
async def test_discovery_is_read_only_and_opens_the_sidekick_app() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}
    tool = tools["show_work_changes"]

    assert tool.meta["ui"]["resourceUri"] == SIDEKICK_APP_URI
    assert isinstance(tool.annotations, ToolAnnotations)
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.output_schema is not None
    assert tool.output_schema["additionalProperties"] is False
    # Model-facing guidance: one closing call after Work writes, not after shopping.
    assert "at most once" in tool.description
    assert "last" in tool.description
    assert "shopping" in tool.description
    # Closed input: refs only. Each ref is a closed {kind, id} pair, with no free text anywhere.
    assert set(tool.parameters["properties"]) == {"refs"}
    assert tool.parameters["additionalProperties"] is False
    refs_schema = tool.parameters["properties"]["refs"]
    assert refs_schema["maxItems"] == 25
    assert refs_schema["minItems"] == 1
    ref_schema = refs_schema["items"]
    assert set(ref_schema["properties"]) == {"kind", "id"}
    assert set(ref_schema["properties"]["kind"]["enum"]) == {"domain", "project", "task", "step"}
    assert ref_schema["additionalProperties"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_card_envelope_and_one_row_per_resolved_ref() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("cards-owner", "Owner")
    ids = _seed_owner(container, owner)

    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        response = await _show(client, [_ref(kind, rid) for kind, (rid, _, _) in ids.items()])

    assert not response.is_error, response.structured_content
    card = response.structured_content["card"]
    assert set(card) == {"kind", "total", "truncated", "issued_at", "items"}
    assert card["kind"] == "work_changes"
    assert card["total"] == 4
    assert card["truncated"] is False
    by_kind = {item["kind"]: item for item in card["items"]}
    assert [item["kind"] for item in card["items"]] == ["domain", "project", "task", "step"]
    for kind, (record_id, version, title) in ids.items():
        item = by_kind[kind]
        assert set(item) == {"kind", "id", "title", "status", "version", "due_at"}
        assert item["id"] == str(record_id)
        assert item["version"] == version
        assert item["title"] == title
        assert item["due_at"] is None
    assert by_kind["task"]["status"] == "todo"
    assert by_kind["domain"]["status"] == "active"
    assert "owner_id" not in str(response.structured_content)

    lines = response.content[0].text.splitlines()
    assert lines[0].startswith("Here is what changed: ")
    assert lines[1:] == [
        f"- {kind} {record_id} | {title} | v{version}"
        for kind, (record_id, version, title) in ids.items()
    ]
    assert str(owner) not in response.content[1].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_issued_at_is_server_utc_and_timezone_aware() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("cards-owner-e", "Owner")
    ids = _seed_owner(container, owner)
    task_id = ids["task"][0]

    before = utc_now()
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        response = await _show(client, [_ref("task", task_id)])
    after = utc_now()

    assert not response.is_error, response.structured_content
    issued_raw = response.structured_content["card"]["issued_at"]
    assert isinstance(issued_raw, str)
    issued = datetime.fromisoformat(issued_raw)
    # Timezone-aware and in UTC, stamped by the server during the call.
    assert issued.tzinfo is not None
    assert issued.utcoffset() == timedelta(0)
    assert before <= issued <= after


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unknown_foreign_and_duplicate_refs_are_left_out_without_a_hint() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("cards-owner-b", "Owner")
    other = container.auth.provision_user("cards-other", "Other")
    ids = _seed_owner(container, owner)
    foreign_task = container.tasks.create(
        Actor(other, SCOPES),
        title=FOREIGN_TITLE,
        idempotency_key="cards-foreign-task-0001",
    )
    unknown = uuid4()
    task_id = ids["task"][0]

    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        foreign = await _show(client, [_ref("task", foreign_task.id)])
        missing = await _show(client, [_ref("task", unknown)])
        mixed = await _show(
            client,
            [
                _ref("task", foreign_task.id),
                _ref("task", unknown),
                _ref("task", task_id),
                _ref("task", task_id),
                _ref("step", foreign_task.id),
            ],
        )

    # A foreign id and an unknown id look the same to the caller: both empty, same text.
    for response in (foreign, missing):
        assert not response.is_error
        assert response.structured_content["card"]["items"] == []
        assert response.structured_content["card"]["total"] == 0
    assert foreign.content[0].text == missing.content[0].text
    # issued_at is the server clock at each call, so it is the one field allowed to differ.
    foreign_json = json.loads(foreign.content[1].text)
    missing_json = json.loads(missing.content[1].text)
    foreign_json["card"].pop("issued_at")
    missing_json["card"].pop("issued_at")
    assert foreign_json == missing_json
    assert str(foreign_task.id) not in foreign.content[1].text
    assert FOREIGN_TITLE not in str(foreign.structured_content)
    assert FOREIGN_TITLE not in str(foreign.content)

    # Mixed: only the owned task appears, once, even though it was asked for twice.
    assert not mixed.is_error
    items = mixed.structured_content["card"]["items"]
    assert [(item["kind"], item["id"]) for item in items] == [("task", str(task_id))]
    assert mixed.content[0].text.splitlines()[1:] == [
        f"- task {task_id} | Cards task | v{ids['task'][1]}"
    ]
    assert FOREIGN_TITLE not in str(mixed.content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_refs_are_bounded_and_closed() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("cards-owner-c", "Owner")
    ids = _seed_owner(container, owner)
    task_id = ids["task"][0]

    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        at_limit = await _show(client, [_ref("task", task_id)] * 25)
        over_limit = await _show(client, [_ref("task", uuid4()) for _ in range(26)])
        empty = await _show(client, [])
        free_text = await client.call_tool(
            "show_work_changes",
            {"refs": [_ref("task", task_id)], "note": "write me a title"},
            raise_on_error=False,
        )
        bad_kind = await _show(client, [{"kind": "contact", "id": str(task_id)}])
        bad_id = await _show(client, [{"kind": "task", "id": "not-a-uuid"}])

    assert not at_limit.is_error
    assert len(at_limit.structured_content["card"]["items"]) == 1
    for rejected in (over_limit, empty, free_text, bad_kind, bad_id):
        assert rejected.is_error
        assert "write me a title" not in str(rejected.content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_task_ref_without_tasks_read_is_refused_not_silently_empty() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("cards-owner-d", "Owner")
    ids = _seed_owner(container, owner)
    task_id = ids["task"][0]

    # Without tasks:read the task read is refused by the use case, so the caller learns the scope
    # problem instead of an empty card that looks like a missing record.
    async with Client(_server_for(container, Actor(owner, frozenset({"projects:read"})))) as client:
        response = await _show(client, [_ref("task", task_id)])
    assert response.is_error
    assert "Cards task" not in str(response.content)

"""MCP write behaviour for the Work context updates: update_project, update_domain, update_process.

Each tool calls the same application use case as its REST PATCH route, so these tests pin
the MCP-visible behaviour: optimistic version checks, idempotent replay, owner-safe
not_found, scope-gated forbidden, and a closed `changes` object.
"""

from typing import NamedTuple

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor, new_uuid7
from tests.db import database_factory
from tests.support.settings import make_settings

WRITE_SCOPES = frozenset({"projects:read", "projects:write", "tasks:read"})


class Case(NamedTuple):
    tool: str
    read_tool: str
    id_arg: str
    record_key: str
    changes: dict[str, object]
    expected: dict[str, object]
    null_field: str


CASES = {
    "project": Case(
        tool="update_project",
        read_tool="get_project",
        id_arg="project_id",
        record_key="project",
        changes={"title": "Sidekick renamed", "status": "paused", "tags": ["Ekonomi"]},
        expected={"title": "Sidekick renamed", "status": "paused", "tags": ["ekonomi"]},
        null_field="title",
    ),
    "domain": Case(
        tool="update_domain",
        read_tool="get_domain",
        id_arg="domain_id",
        record_key="domain",
        changes={"description": "Reviewed", "review_cadence": "weekly", "tags": ["Ekonomi"]},
        expected={"description": "Reviewed", "review_cadence": "weekly", "tags": ["ekonomi"]},
        null_field="name",
    ),
    "process": Case(
        tool="update_process",
        read_tool="get_process",
        id_arg="process_id",
        record_key="process",
        changes={"name": "Monthly review", "cadence": "monthly", "tags": ["Ekonomi"]},
        expected={"name": "Monthly review", "cadence": "monthly", "tags": ["ekonomi"]},
        null_field="name",
    ),
}
KINDS = tuple(CASES)


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


async def _seed(client: Client) -> dict[str, dict[str, object]]:
    """One Domain with a Project and a Process under it, all created through MCP."""

    domain = await client.call_tool(
        "create_domain", {"name": "Operations", "idempotency_key": "update-seed-domain"}
    )
    domain_id = domain.structured_content["domain"]["id"]
    project = await client.call_tool(
        "create_project",
        {"title": "Sidekick", "domain_id": domain_id, "idempotency_key": "update-seed-project"},
    )
    process = await client.call_tool(
        "create_process",
        {"domain_id": domain_id, "name": "Weekly review", "idempotency_key": "update-seed-process"},
    )
    return {
        "domain": domain.structured_content["domain"],
        "project": project.structured_content["project"],
        "process": process.structured_content["process"],
    }


def _arguments(case: Case, record: dict[str, object], **extra: object) -> dict[str, object]:
    return {case.id_arg: record["id"], "version": 1, **extra}


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
async def test_update_applies_changes_bumps_version_and_reads_back(kind: str) -> None:
    case = CASES[kind]
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, WRITE_SCOPES))

    async with Client(server) as client:
        record = (await _seed(client))[kind]
        updated = await client.call_tool(
            case.tool,
            _arguments(
                case,
                record,
                idempotency_key="update-update-once",
                changes=case.changes,
            ),
        )
        read_back = await client.call_tool(case.read_tool, {case.id_arg: record["id"]})

    returned = updated.structured_content[case.record_key]
    assert returned["version"] == 2
    assert "owner_id" not in returned
    for field, value in case.expected.items():
        assert returned[field] == value, field
    # The update returns the record without derived estimate totals, as REST PATCH does.
    comparable = {field: value for field, value in returned.items() if field != "estimate_totals"}
    stored = read_back.structured_content[case.record_key]
    assert {field: stored[field] for field in comparable} == comparable
    assert updated.content[0].type == "text"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
async def test_stale_version_is_a_conflict_and_changes_nothing(kind: str) -> None:
    case = CASES[kind]
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, WRITE_SCOPES))

    async with Client(server) as client:
        record = (await _seed(client))[kind]
        await client.call_tool(
            case.tool,
            _arguments(case, record, idempotency_key="update-stale-first", changes=case.changes),
        )
        stale = await client.call_tool(
            case.tool,
            _arguments(
                case,
                record,
                idempotency_key="update-stale-second",
                changes={"description": "Too late"},
            ),
            raise_on_error=False,
        )
        read_back = await client.call_tool(case.read_tool, {case.id_arg: record["id"]})

    assert stale.is_error
    assert stale.structured_content["code"] == "conflict"
    assert read_back.structured_content[case.record_key]["version"] == 2


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
async def test_replaying_the_same_key_returns_the_same_result_without_a_second_bump(
    kind: str,
) -> None:
    case = CASES[kind]
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, WRITE_SCOPES))

    async with Client(server) as client:
        record = (await _seed(client))[kind]
        arguments = _arguments(case, record, idempotency_key="update-replay", changes=case.changes)
        first = await client.call_tool(case.tool, arguments)
        replay = await client.call_tool(case.tool, arguments)
        read_back = await client.call_tool(case.read_tool, {case.id_arg: record["id"]})

    assert first.structured_content == replay.structured_content
    assert read_back.structured_content[case.record_key]["version"] == 2


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
async def test_foreign_and_missing_records_are_the_same_not_found(kind: str) -> None:
    case = CASES[kind]
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    other = container.auth.provision_user("other-owner", "Other")
    owner_server = _server_for(container, Actor(owner, WRITE_SCOPES))
    other_server = _server_for(container, Actor(other, WRITE_SCOPES))

    async with Client(owner_server) as client:
        record = (await _seed(client))[kind]

    async with Client(other_server) as client:
        foreign = await client.call_tool(
            case.tool,
            _arguments(case, record, idempotency_key="update-foreign", changes=case.changes),
            raise_on_error=False,
        )
        missing = await client.call_tool(
            case.tool,
            {
                case.id_arg: str(new_uuid7()),
                "version": 1,
                "idempotency_key": "update-missing",
                "changes": case.changes,
            },
            raise_on_error=False,
        )

    assert foreign.is_error and missing.is_error
    assert foreign.structured_content["code"] == "not_found"
    assert foreign.structured_content["code"] == missing.structured_content["code"]
    assert foreign.structured_content["message"] == missing.structured_content["message"]
    assert record["id"] not in str(foreign.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
async def test_update_requires_projects_write_scope(kind: str) -> None:
    case = CASES[kind]
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    writer = _server_for(container, Actor(owner, WRITE_SCOPES))
    reader = _server_for(container, Actor(owner, frozenset({"projects:read", "tasks:read"})))

    async with Client(writer) as client:
        record = (await _seed(client))[kind]

    async with Client(reader) as client:
        denied = await client.call_tool(
            case.tool,
            _arguments(case, record, idempotency_key="update-scope", changes=case.changes),
            raise_on_error=False,
        )
        read_back = await client.call_tool(case.read_tool, {case.id_arg: record["id"]})

    assert denied.is_error
    assert denied.structured_content["code"] == "forbidden"
    assert read_back.structured_content[case.record_key]["version"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
async def test_changes_are_closed_and_refuse_nulling_required_fields(kind: str) -> None:
    case = CASES[kind]
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, WRITE_SCOPES))

    async with Client(server) as client:
        record = (await _seed(client))[kind]
        rejected_inputs = [
            {"owner_id": str(new_uuid7())},
            {"archived_at": None},
            {},
            {case.null_field: None},
        ]
        for changes in rejected_inputs:
            with pytest.raises(ToolError):
                await client.call_tool(
                    case.tool,
                    _arguments(case, record, idempotency_key="update-closed", changes=changes),
                )

        read_back = await client.call_tool(case.read_tool, {case.id_arg: record["id"]})

    assert read_back.structured_content[case.record_key]["version"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_project_and_process_domain_cannot_be_cleared_over_mcp() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, WRITE_SCOPES))

    async with Client(server) as client:
        seeded = await _seed(client)
        for kind in ("project", "process"):
            case = CASES[kind]
            with pytest.raises(ToolError):
                await client.call_tool(
                    case.tool,
                    _arguments(
                        case,
                        seeded[kind],
                        idempotency_key="update-clear-domain",
                        changes={"domain_id": None},
                    ),
                )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_domain_accent_is_set_listed_and_cleared_over_mcp() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, WRITE_SCOPES))

    async with Client(server) as client:
        created = await client.call_tool(
            "create_domain",
            {"name": "Hem", "idempotency_key": "accent-create", "accent": "green"},
        )
        domain_id = created.structured_content["domain"]["id"]
        assert created.structured_content["domain"]["accent"] == "green"

        set_amber = await client.call_tool(
            "update_domain",
            {
                "domain_id": domain_id,
                "version": 1,
                "idempotency_key": "accent-set",
                "changes": {"accent": "amber"},
            },
        )
        assert set_amber.structured_content["domain"]["accent"] == "amber"
        assert set_amber.structured_content["domain"]["version"] == 2

        listed = await client.call_tool("list_domains", {})
        listed_hem = next(
            item for item in listed.structured_content["domains"] if item["id"] == domain_id
        )
        assert listed_hem["accent"] == "amber"

        cleared = await client.call_tool(
            "update_domain",
            {
                "domain_id": domain_id,
                "version": 2,
                "idempotency_key": "accent-clear",
                "changes": {"accent": None},
            },
        )
        assert cleared.structured_content["domain"]["accent"] is None
        assert cleared.structured_content["domain"]["version"] == 3

        read_back = await client.call_tool("get_domain", {"domain_id": domain_id})

    assert read_back.structured_content["domain"]["accent"] is None
    assert read_back.structured_content["domain"]["version"] == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unknown_domain_accent_is_rejected_and_changes_nothing() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, WRITE_SCOPES))

    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_domain",
                {"name": "Hem", "idempotency_key": "accent-bad-create", "accent": "magenta"},
            )

        seeded = await client.call_tool(
            "create_domain", {"name": "Work", "idempotency_key": "accent-seed-work"}
        )
        domain_id = seeded.structured_content["domain"]["id"]
        with pytest.raises(ToolError):
            await client.call_tool(
                "update_domain",
                {
                    "domain_id": domain_id,
                    "version": 1,
                    "idempotency_key": "accent-bad-update",
                    "changes": {"accent": "magenta"},
                },
            )

        read_back = await client.call_tool("get_domain", {"domain_id": domain_id})

    assert read_back.structured_content["domain"]["accent"] is None
    assert read_back.structured_content["domain"]["version"] == 1


def test_mcp_accent_literal_matches_domain_palette() -> None:
    from typing import get_args

    from sidekick.structured.work_records import DomainAccent
    from sidekick.work.domain.context import DOMAIN_ACCENTS

    assert get_args(DomainAccent) == tuple(DOMAIN_ACCENTS)


async def _tags_only(
    client: Client, case: Case, record: dict[str, object], key: str, version: int, tags: list[str]
):
    return await client.call_tool(
        case.tool,
        {
            case.id_arg: record["id"],
            "version": version,
            "idempotency_key": key,
            "changes": {"tags": tags},
        },
        raise_on_error=False,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
async def test_tags_only_update_sets_replaces_and_clears_tags_and_bumps_version(kind: str) -> None:
    case = CASES[kind]
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, WRITE_SCOPES))

    async with Client(server) as client:
        record = (await _seed(client))[kind]
        first = await _tags_only(client, case, record, "tags-only-1", 1, ["Ekonomi", "Hem"])
        second = await _tags_only(client, case, record, "tags-only-2", 2, ["Hem"])
        cleared = await _tags_only(client, case, record, "tags-only-3", 3, [])
        read_back = await client.call_tool(case.read_tool, {case.id_arg: record["id"]})

    for result, version, tags in (
        (first, 2, ["ekonomi", "hem"]),
        (second, 3, ["hem"]),
        (cleared, 4, []),
    ):
        assert not result.is_error
        returned = result.structured_content[case.record_key]
        assert returned["version"] == version
        assert sorted(returned["tags"]) == tags
    stored = read_back.structured_content[case.record_key]
    assert stored["version"] == 4
    assert stored["tags"] == []


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
async def test_tags_only_update_replays_and_conflicts_on_stale_version(kind: str) -> None:
    case = CASES[kind]
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, WRITE_SCOPES))

    async with Client(server) as client:
        record = (await _seed(client))[kind]
        first = await _tags_only(client, case, record, "tags-only-replay", 1, ["Ekonomi"])
        replay = await _tags_only(client, case, record, "tags-only-replay", 1, ["Ekonomi"])
        stale = await _tags_only(client, case, record, "tags-only-stale", 1, ["Annat"])
        read_back = await client.call_tool(case.read_tool, {case.id_arg: record["id"]})

    assert not first.is_error
    assert first.structured_content == replay.structured_content
    assert stale.is_error
    assert stale.structured_content["code"] == "conflict"
    stored = read_back.structured_content[case.record_key]
    assert stored["version"] == 2
    assert stored["tags"] == ["ekonomi"]

"""Names on an entry's links, and fixing them with update_journal_entry."""

from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.contacts.application.models import CreateContactCommand
from sidekick.lifecycle import RecordKind
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.support.mcp_journal_write import (
    FULL,
    SETUP,
    args,
    make_container,
    make_project,
)


def _setup(container: Any, actor: Actor, key: str) -> tuple[Any, Any, Any]:
    setup = Actor(actor.user_id, SETUP)
    project = make_project(container, actor.user_id, f"{key}-project")
    anna = container.contacts.create(
        setup, CreateContactCommand(display_name="Anna Andersson"), f"{key}-anna"
    )
    bo = container.contacts.create(setup, CreateContactCommand(display_name="Bo Berg"), f"{key}-bo")
    return project, anna, bo


async def _write(client: Client, key: str, **relations: Any) -> dict[str, Any]:
    response = await client.call_tool("write_journal_entry", args(f"write-{key}", **relations))
    return response.structured_content["entry"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_links_name_the_contacts_and_projects_and_the_text_says_them() -> None:
    container, actor = make_container()
    project, anna, bo = _setup(container, actor, "ln")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _write(
            client, "ln-1", project_ids=[str(project.id)], contact_ids=[str(anna.id), str(bo.id)]
        )
        labels = {link["id"]: (link["kind"], link["label"]) for link in entry["links"]}
        assert labels[str(project.id)] == ("project", "Projekt")
        assert labels[str(anna.id)] == ("contact", "Anna Andersson")
        assert labels[str(bo.id)] == ("contact", "Bo Berg")

        read = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
        assert "Linked to Projekt, " in read.content[0].text
        assert "Anna Andersson" in read.content[0].text

        redacted = await client.call_tool(
            "get_journal_entry", {"entry_id": entry["id"], "include_content": False}
        )
        assert all(link["label"] is None for link in redacted.structured_content["entry"]["links"])
        assert "Anna" not in redacted.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_reader_without_the_contacts_scope_gets_no_contact_names() -> None:
    container, actor = make_container()
    _, anna, _ = _setup(container, actor, "sc")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        entry = await _write(client, "sc-1", contact_ids=[str(anna.id)])

    narrow = Actor(actor.user_id, frozenset({"journal:read", "journal:write"}))
    server = create_mcp_server(container, actor_provider=lambda: narrow, enable_auth=False)
    async with Client(server) as client:
        read = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
        links = read.structured_content["entry"]["links"]
        assert links == [{"kind": "contact", "id": str(anna.id), "label": None}]
        assert "Anna" not in read.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_removes_and_adds_links_with_a_new_version_and_undo() -> None:
    container, actor = make_container()
    project, anna, bo = _setup(container, actor, "ch")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert tools["update_journal_entry"].meta["ui"]["resourceUri"].startswith("ui://")
        entry = await _write(
            client, "ch-1", project_ids=[str(project.id)], contact_ids=[str(anna.id)]
        )

        removed = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "idempotency_key": "ch-remove-1",
                "remove_contact_ids": [str(anna.id)],
                "add_contact_ids": [str(bo.id)],
            },
        )
        after = removed.structured_content["entry"]
        assert after["version"] == 2
        assert after["contact_ids"] == [str(bo.id)]
        assert after["project_ids"] == [str(project.id)]
        assert after["title"] == entry["title"]
        assert after["summary"] == entry["summary"]
        assert after["key_points"] == entry["key_points"]
        text = removed.content[0].text
        assert "Added 1 link and removed 1 link." in text
        assert "Linked to Projekt and Bo Berg." in text

        # The undo is the opposite change on the new version.
        undone = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 2,
                "idempotency_key": "ch-undo-1",
                "add_contact_ids": [str(anna.id)],
                "remove_contact_ids": [str(bo.id)],
            },
        )
        assert undone.structured_content["entry"]["version"] == 3
        assert undone.structured_content["entry"]["contact_ids"] == [str(anna.id)]

        # The same key and request returns the same result without a new version.
        again = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 2,
                "idempotency_key": "ch-undo-1",
                "add_contact_ids": [str(anna.id)],
                "remove_contact_ids": [str(bo.id)],
            },
        )
        assert again.structured_content["entry"]["version"] == 3

        # A stale version conflicts and changes nothing.
        with pytest.raises(ToolError):
            await client.call_tool(
                "update_journal_entry",
                {
                    "entry_id": entry["id"],
                    "expected_version": 1,
                    "idempotency_key": "ch-stale-1",
                    "remove_project_ids": [str(project.id)],
                },
            )
        read = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
        assert read.structured_content["entry"]["project_ids"] == [str(project.id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_links_can_change_together_with_an_appended_text() -> None:
    container, actor = make_container()
    _, anna, _ = _setup(container, actor, "ap")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _write(client, "ap-1")
        response = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "idempotency_key": "ap-add-1",
                "append_key_points": [{"kind": "fact", "text": "Ringde Anna."}],
                "add_contact_ids": [str(anna.id)],
            },
        )
        after = response.structured_content["entry"]
        assert after["version"] == 2
        assert after["contact_ids"] == [str(anna.id)]
        assert len(after["key_points"]) == len(entry["key_points"]) + 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_link_changes_keep_the_creation_checks() -> None:
    container, actor = make_container()
    setup = Actor(actor.user_id, SETUP)
    _, anna, _ = _setup(container, actor, "ck")
    other_id = container.auth.provision_user("link-other-owner", "Other")
    foreign = container.contacts.create(
        Actor(other_id, SETUP), CreateContactCommand(display_name="Främling"), "ck-foreign"
    )
    archived = container.contacts.create(
        setup, CreateContactCommand(display_name="Gammal"), "ck-old"
    )
    container.contacts.archive(setup, archived.id, archived.version, "ck-old-archive")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _write(client, "ck-1", contact_ids=[str(anna.id)])

        def call(key: str, **fields: Any) -> Any:
            return client.call_tool(
                "update_journal_entry",
                {
                    "entry_id": entry["id"],
                    "expected_version": 1,
                    "idempotency_key": key,
                    **fields,
                },
            )

        # Another owner's contact and an archived one cannot be linked.
        with pytest.raises(ToolError):
            await call("ck-foreign-1", add_contact_ids=[str(foreign.id)])
        with pytest.raises(ToolError):
            await call("ck-archived-1", add_contact_ids=[str(archived.id)])
        # The same link cannot be added and removed in one call.
        with pytest.raises(ToolError):
            await call(
                "ck-both-1", add_contact_ids=[str(anna.id)], remove_contact_ids=[str(anna.id)]
            )
        # Nothing changed, so the version is still 1.
        read = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
        assert read.structured_content["entry"]["version"] == 1

    # Link changes need the read scope of the kind they name.
    narrow = Actor(actor.user_id, frozenset({"journal:read", "journal:write"}))
    server = create_mcp_server(container, actor_provider=lambda: narrow, enable_auth=False)
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "update_journal_entry",
                {
                    "entry_id": entry["id"],
                    "expected_version": 1,
                    "idempotency_key": "ck-scope-1",
                    "remove_contact_ids": [str(anna.id)],
                },
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_removed_link_to_an_archived_contact_is_allowed() -> None:
    container, actor = make_container()
    setup = Actor(actor.user_id, SETUP)
    _, anna, _ = _setup(container, actor, "ar")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        entry = await _write(client, "ar-1", contact_ids=[str(anna.id)])
        container.contacts.archive(setup, anna.id, anna.version, "ar-archive")
        response = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "idempotency_key": "ar-remove-1",
                "remove_contact_ids": [str(anna.id)],
            },
        )
        assert response.structured_content["entry"]["contact_ids"] == []


def test_full_scopes_cover_the_link_checks() -> None:
    assert {"projects:read", "contacts:read"} <= FULL


@pytest.mark.asyncio
@pytest.mark.integration
async def test_without_content_the_links_carry_no_names() -> None:
    container, actor = make_container()
    project, anna, _ = _setup(container, actor, "nc")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        entry = await _write(
            client, "nc-1", project_ids=[str(project.id)], contact_ids=[str(anna.id)]
        )
        read = await client.call_tool(
            "get_journal_entry", {"entry_id": entry["id"], "include_content": False}
        )
        links = read.structured_content["entry"]["links"]
        assert {link["id"] for link in links} == {str(project.id), str(anna.id)}
        assert all(link["label"] is None for link in links)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_trashed_project_or_contact_loses_its_name_but_stays_linked() -> None:
    container, actor = make_container()
    setup = Actor(actor.user_id, SETUP)
    project, anna, _ = _setup(container, actor, "tr")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        entry = await _write(
            client, "tr-1", project_ids=[str(project.id)], contact_ids=[str(anna.id)]
        )
        container.lifecycle.trash(
            setup,
            RecordKind.PROJECT,
            project.id,
            version=project.version,
            idempotency_key="tr-project-trash",
        )
        container.lifecycle.trash(
            setup,
            RecordKind.CONTACT,
            anna.id,
            version=anna.version,
            idempotency_key="tr-contact-trash",
        )
        read = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
        record = read.structured_content["entry"]
        labels = {link["id"]: link["label"] for link in record["links"]}
        assert labels == {str(project.id): None, str(anna.id): None}
        assert record["project_ids"] == [str(project.id)]
        assert record["contact_ids"] == [str(anna.id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_replayed_link_change_returns_the_same_entry_and_changes_nothing_twice() -> None:
    container, actor = make_container()
    _, anna, bo = _setup(container, actor, "rp")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        entry = await _write(client, "rp-1", contact_ids=[str(anna.id)])
        arguments = {
            "entry_id": entry["id"],
            "expected_version": 1,
            "idempotency_key": "rp-swap-1",
            "remove_contact_ids": [str(anna.id)],
            "add_contact_ids": [str(bo.id)],
        }
        first = await client.call_tool("update_journal_entry", arguments)
        replay = await client.call_tool("update_journal_entry", arguments)
        assert replay.structured_content == first.structured_content
        assert replay.structured_content["entry"]["version"] == 2
        read = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
        assert read.structured_content["entry"]["version"] == 2
        assert read.structured_content["entry"]["contact_ids"] == [str(bo.id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_link_change_that_changes_no_link_keeps_the_version_and_the_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, actor = make_container()
    project, anna, bo = _setup(container, actor, "nop")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        entry = await _write(
            client, "nop-1", project_ids=[str(project.id)], contact_ids=[str(anna.id)]
        )
        store = container.journal.store
        marked: list[Any] = []
        mark = store.mark_daily_journal_summary_stale

        def record(session: Any, owner_id: Any, journal_date: Any) -> None:
            marked.append(journal_date)
            mark(session, owner_id, journal_date)

        monkeypatch.setattr(store, "mark_daily_journal_summary_stale", record)

        # Adds a link that is there already and removes one that is not: nothing changes.
        noop = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "idempotency_key": "nop-noop-1",
                "add_project_ids": [str(project.id)],
                "add_contact_ids": [str(anna.id)],
                "remove_contact_ids": [str(bo.id)],
            },
        )
        assert noop.structured_content["entry"]["version"] == 1
        assert "No link changed." in noop.content[0].text
        assert marked == []

        # A real link change still versions the entry and marks the day.
        real = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "idempotency_key": "nop-real-1",
                "remove_contact_ids": [str(anna.id)],
            },
        )
        assert real.structured_content["entry"]["version"] == 2
        assert len(marked) == 1

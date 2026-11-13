"""Trash list, move and restore over MCP: reversible only, owner-scoped, versioned, replayable."""

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastmcp import Client
from mcp.types import ToolAnnotations
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.journal.domain.source import SourceType
from sidekick.lifecycle import RecordKind
from sidekick.lifecycle.application.service import _READ_SCOPE
from sidekick.mcp.lifecycle import (
    _READ_SCOPE_BY_KIND,
    LIFECYCLE_TOOL_NAMES,
    KindValue,
    TrashItemRecord,
    _trash_summary,
)
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.errors import NotFoundError, ValidationError
from sidekick.shared.types import MAX_CURSOR_LENGTH, Actor
from sidekick.shopping.application.schemas import BatchItem
from tests.db import create_test_session_factory, database_factory, require_test_database_url
from tests.mcp.harness import SwitchableServer
from tests.support.settings import make_settings

JOURNAL_TITLE = "sentinel-trash-journal-title-3e91"
SOURCE_TEXT = "sentinel-trash-journal-source-text-77aa"
FULL = frozenset(
    {
        "projects:read",
        "projects:write",
        "tasks:read",
        "tasks:write",
        "contacts:read",
        "contacts:write",
        "journal:read",
        "journal:write",
        "shopping:read",
        "shopping:write",
    }
)
KINDS = ("task", "project", "contact", "journal_entry", "shopping_item")


@dataclass(frozen=True, slots=True)
class Harness:
    container: Container
    actor: Actor
    records: dict[str, tuple[UUID, int]]
    mcp: SwitchableServer

    def client(self, scopes: frozenset[str] = FULL, user_id: UUID | None = None) -> Client:
        return self.mcp.client(Actor(user_id or self.actor.user_id, scopes))


def make_harness(username: str) -> Harness:
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user(username, "Trash Owner")
    actor = Actor(user_id, FULL)
    domain = container.contexts.create_domain(
        actor, name="Ops", description=None, idempotency_key=f"{username}-domain"
    )
    project = container.projects.create(
        actor, title="Trash project", domain_id=domain.id, idempotency_key=f"{username}-project"
    )
    task = container.tasks.create(actor, title="Trash task", idempotency_key=f"{username}-task")
    contact = container.contacts.create(
        actor, CreateContactCommand(display_name="Trash contact"), f"{username}-contact"
    )
    source = container.journal_capture.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=date(2026, 7, 21),
        occurred_at=None,
        source_recorded_at=None,
        raw_text=SOURCE_TEXT,
        language="sv",
        replaces_source_id=None,
        idempotency_key=f"{username}-source",
    )
    entry = container.journal_capture.create_manual_entry(
        actor,
        source_id=source.id,
        title=JOURNAL_TITLE,
        summary=None,
        key_points=(),
        idempotency_key=f"{username}-entry",
    )
    shopping_list = container.shopping.create_list(
        actor, "Trash shopping", idempotency_key=f"{username}-shopping-list"
    ).shopping_list
    added = container.shopping.add_items(
        actor,
        shopping_list.id,
        [BatchItem(name="Trash item", client_ref="trash")],
        idempotency_key=f"{username}-shopping-item",
    )
    shopping_item = added.items[0].item
    return Harness(
        container,
        actor,
        {
            "task": (task.id, task.version),
            "project": (project.id, project.version),
            "contact": (contact.id, contact.version),
            "journal_entry": (entry.id, int(getattr(entry, "version", 1))),
            "shopping_item": (shopping_item.id, shopping_item.version),
        },
        SwitchableServer.build(container, actor),
    )


async def call(client: Client, tool: str, arguments: dict[str, Any]) -> Any:
    return await client.call_tool(tool, arguments, raise_on_error=False)


def args(harness: Harness, kind: str, key: str, version: int | None = None) -> dict[str, Any]:
    record_id, base = harness.records[kind]
    return {
        "kind": kind,
        "record_id": str(record_id),
        "version": version if version is not None else base,
        "idempotency_key": key,
    }


def audit_count(container: Container, owner: UUID, event: str) -> int:
    with container.session_factory() as session:
        return session.execute(
            text(
                "SELECT count(*) FROM sidekick.audit_events "
                "WHERE actor_id = :owner AND event = :event"
            ),
            {"owner": owner, "event": event},
        ).scalar_one()


@pytest.mark.asyncio
async def test_discovery_exposes_exactly_the_three_reversible_tools() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(LIFECYCLE_TOOL_NAMES) <= set(tools)
    assert LIFECYCLE_TOOL_NAMES == ("list_trash", "move_to_trash", "restore_from_trash")
    for name in LIFECYCLE_TOOL_NAMES:
        tool = tools[name]
        assert tool.output_schema is not None
        assert tool.parameters["additionalProperties"] is False
        assert isinstance(tool.annotations, ToolAnnotations)
        assert tool.annotations.openWorldHint is False
        assert tool.annotations.idempotentHint is True
    assert tools["list_trash"].annotations.readOnlyHint is True  # pyright: ignore[reportOptionalMemberAccess]
    assert tools["move_to_trash"].annotations.destructiveHint is True  # pyright: ignore[reportOptionalMemberAccess]
    assert tools["restore_from_trash"].annotations.destructiveHint is False  # pyright: ignore[reportOptionalMemberAccess]
    assert tools["list_trash"].parameters["properties"]["limit"]["maximum"] == 100
    cursor_schema = tools["list_trash"].parameters["properties"]["cursor"]
    assert {"type": "string", "maxLength": MAX_CURSOR_LENGTH} in cursor_schema["anyOf"]
    assert "next_cursor" in tools["list_trash"].output_schema["properties"]  # pyright: ignore[reportOptionalSubscript]
    for name in ("move_to_trash", "restore_from_trash"):
        properties = tools[name].parameters["properties"]
        assert set(properties) == {"kind", "record_id", "version", "idempotency_key"}
        assert properties["idempotency_key"]["minLength"] == 8
        assert set(properties["kind"]["enum"]) == {kind.value for kind in RecordKind} - {
            "journal_source"
        }


@pytest.mark.asyncio
async def test_restore_is_listed_for_the_model_and_list_trash_names_the_path() -> None:
    """Restoring is not destructive and no app calls it, so the model must see it."""

    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}

    visibility = (tools["restore_from_trash"].meta or {}).get("ui", {}).get("visibility", [])
    assert "app" not in visibility
    move_visibility = (tools["move_to_trash"].meta or {}).get("ui", {}).get("visibility", [])
    assert "app" not in move_visibility
    move_description = tools["move_to_trash"].description or ""
    assert move_description.startswith(
        "Use this only after asking the user and getting an explicit yes in this turn to "
        "move this record to the trash."
    )
    assert "restore_from_trash" in move_description
    assert "restore_from_trash" in (tools["list_trash"].description or "")
    assert "something back from the trash" in (tools["restore_from_trash"].description or "")


@pytest.mark.asyncio
async def test_no_mcp_tool_can_remove_permanently() -> None:
    """D-031: permanent removal is HTTP-only, nothing over MCP may delete for good."""

    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = await server.list_tools()
    forbidden = ("permanent", "purge", "empty_trash", "hard_delete", "destroy")
    for tool in tools:
        haystack = " ".join(
            [tool.name, json.dumps(tool.parameters), json.dumps(tool.output_schema or {})]
        ).lower()
        assert not any(word in haystack for word in forbidden), tool.name
    assert not any(
        word in tool.name for tool in tools for word in ("delete", "remove_record", "wipe")
    )
    # The lifecycle adapter never touches the destructive use case, even by attribute access.
    import ast

    import sidekick.mcp.lifecycle as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    touched = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert touched.isdisjoint({"permanently_remove", "set_trashed"})
    assert {"trash", "restore", "list_trash"} <= touched


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
async def test_move_list_restore_round_trip_per_kind(kind: str) -> None:
    harness = make_harness(f"trash-roundtrip-{kind}")
    record_id, _ = harness.records[kind]
    async with harness.client() as client:
        trashed = await call(client, "move_to_trash", args(harness, kind, f"move-{kind}-0001"))
        assert not trashed.is_error, trashed.structured_content
        item = trashed.structured_content
        assert item["kind"] == kind and item["id"] == str(record_id)
        assert item["trashed_at"] is not None

        listed = await call(client, "list_trash", {})
        assert [row["id"] for row in listed.structured_content["items"]] == [str(record_id)]
        assert listed.structured_content["has_more"] is False
        filtered = await call(client, "list_trash", {"kind": kind})
        assert len(filtered.structured_content["items"]) == 1
        other = "contact" if kind != "contact" else "task"
        empty = await call(client, "list_trash", {"kind": other})
        assert empty.structured_content["items"] == []

        restored = await call(
            client,
            "restore_from_trash",
            {**args(harness, kind, f"restore-{kind}-001"), "version": item["version"]},
        )
        assert not restored.is_error, restored.structured_content
        assert restored.structured_content["trashed_at"] is None
        assert restored.structured_content["version"] == item["version"] + 1
        again = await call(client, "list_trash", {})
        assert again.structured_content["items"] == []

    owner = harness.actor.user_id
    assert audit_count(harness.container, owner, f"{kind}.trashed") == 1
    assert audit_count(harness.container, owner, f"{kind}.restored") == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_journal_sources_are_not_part_of_the_mcp_surface() -> None:
    """Sources are immutable (no UPDATE grant), so trash cannot move them."""

    harness = make_harness("trash-journal-source")
    source_id = harness.container.journal_capture.create_source(
        harness.actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=date(2026, 7, 22),
        occurred_at=None,
        source_recorded_at=None,
        raw_text=SOURCE_TEXT,
        language="sv",
        replaces_source_id=None,
        idempotency_key="trash-journal-source-2",
    ).id
    async with harness.client() as client:
        for tool in ("move_to_trash", "restore_from_trash"):
            refused = await call(
                client,
                tool,
                {
                    "kind": "journal_source",
                    "record_id": str(source_id),
                    "version": 1,
                    "idempotency_key": "journal-src-001",
                },
            )
            assert refused.is_error and SOURCE_TEXT not in str(refused.structured_content)
        listing = await call(client, "list_trash", {"kind": "journal_source"})
        assert listing.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_trashed_shopping_item_leaves_the_list_until_restored() -> None:
    """D-068: a trashed shopping item is hidden from reads and edits, and comes back on restore."""

    harness = make_harness("trash-shopping-list")
    item_id, _ = harness.records["shopping_item"]
    list_id = harness.container.shopping.list_lists(harness.actor).lists[0].id
    async with harness.client() as client:
        shown = harness.container.shopping.get_list(harness.actor, list_id)
        assert [row.id for row in shown.items] == [item_id]

        trashed = await call(
            client, "move_to_trash", args(harness, "shopping_item", "shop-trash-0001")
        )
        assert not trashed.is_error, trashed.structured_content
        version = trashed.structured_content["version"]
        assert harness.container.shopping.get_list(harness.actor, list_id).items == []

        with pytest.raises(NotFoundError):
            harness.container.shopping.set_purchased(
                harness.actor,
                item_id,
                purchased=True,
                version=version,
                idempotency_key="shop-edit-trashed-01",
            )
        with pytest.raises(ValidationError):
            harness.container.lifecycle.permanently_remove(
                harness.actor,
                RecordKind.SHOPPING_ITEM,
                item_id,
                version=version,
                idempotency_key="shop-purge-trashed-01",
            )
        edited = await call(
            client,
            "update_shopping_item",
            {
                "item_id": str(item_id),
                "item": {"name": "Trash item renamed"},
                "version": version,
                "idempotency_key": "shop-mcp-edit-trashed",
            },
        )
        assert edited.is_error and edited.structured_content["code"] == "not_found"
        listed = await call(client, "list_trash", {"kind": "shopping_item"})
        assert not listed.is_error, listed.structured_content
        assert [row["id"] for row in listed.structured_content["items"]] == [str(item_id)]

        restored = await call(
            client,
            "restore_from_trash",
            {**args(harness, "shopping_item", "shop-restore-0001"), "version": version},
        )
        assert not restored.is_error, restored.structured_content
    shown_again = harness.container.shopping.get_list(harness.actor, list_id)
    assert [row.id for row in shown_again.items] == [item_id]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_owner_gets_not_found_and_nothing_changes() -> None:
    harness = make_harness("trash-owner-a")
    other_id = harness.container.auth.provision_user("trash-owner-b", "Other")
    async with harness.client(user_id=other_id) as client:
        for kind in KINDS:
            foreign = await call(client, "move_to_trash", args(harness, kind, f"foreign-{kind}-01"))
            absent = await call(
                client,
                "move_to_trash",
                {**args(harness, kind, f"absent-{kind}-001"), "record_id": str(uuid4())},
            )
            assert foreign.is_error and absent.is_error, kind
            assert foreign.structured_content["code"] == "not_found", kind
            assert foreign.structured_content["message"] == absent.structured_content["message"]
            restore = await call(
                client, "restore_from_trash", args(harness, kind, f"foreign-r-{kind}-01")
            )
            assert restore.is_error and restore.structured_content["code"] == "not_found", kind
        assert (await call(client, "list_trash", {})).structured_content["items"] == []

    async with harness.client() as client:
        assert (await call(client, "list_trash", {})).structured_content["items"] == []
    for kind in KINDS:
        assert audit_count(harness.container, harness.actor.user_id, f"{kind}.trashed") == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_each_kind_requires_its_own_write_scope() -> None:
    harness = make_harness("trash-scopes")
    needed = {
        "task": "tasks:write",
        "project": "projects:write",
        "contact": "contacts:write",
        "journal_entry": "journal:write",
        "shopping_item": "shopping:write",
    }
    async with harness.client() as client:
        for kind in KINDS:
            moved = await call(client, "move_to_trash", args(harness, kind, f"scope-set-{kind}"))
            assert not moved.is_error, kind
    for kind, scope in needed.items():
        weaker = frozenset(FULL - {scope})
        async with harness.client(scopes=weaker) as client:
            denied = await call(
                client, "restore_from_trash", args(harness, kind, f"scope-{kind}-001", version=2)
            )
            assert denied.is_error, kind
            assert denied.structured_content["code"] == "forbidden", kind
    read_only = frozenset(scope for scope in FULL if scope.endswith(":read"))
    async with harness.client(scopes=read_only) as client:
        for kind in KINDS:
            denied = await call(
                client, "move_to_trash", args(harness, kind, f"readonly-{kind}-01", version=2)
            )
            assert denied.structured_content["code"] == "forbidden", kind
    # Nothing was restored by any denied call.
    async with harness.client() as client:
        listed = await call(client, "list_trash", {})
    assert len(listed.structured_content["items"]) == len(KINDS)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_requires_read_scope_and_hides_kinds_the_caller_cannot_read() -> None:
    harness = make_harness("trash-list-scopes")
    async with harness.client() as client:
        for kind in KINDS:
            await call(client, "move_to_trash", args(harness, kind, f"list-set-{kind}-1"))

    async with harness.client(scopes=frozenset({"tasks:write"})) as client:
        denied = await call(client, "list_trash", {})
        assert denied.is_error and denied.structured_content["code"] == "forbidden"
        denied_kind = await call(client, "list_trash", {"kind": "contact"})
        assert denied_kind.is_error and denied_kind.structured_content["code"] == "forbidden"

    async with harness.client(scopes=frozenset({"projects:read"})) as client:
        listed = await call(client, "list_trash", {})
    assert {row["kind"] for row in listed.structured_content["items"]} == {"project"}
    assert JOURNAL_TITLE not in str(listed)

    async with harness.client(scopes=frozenset({"projects:read", "tasks:read"})) as client:
        listed = await call(client, "list_trash", {})
    assert {row["kind"] for row in listed.structured_content["items"]} == {"task", "project"}
    assert JOURNAL_TITLE not in str(listed) and SOURCE_TEXT not in str(listed)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stale_version_conflicts_and_wrong_state_conflicts() -> None:
    harness = make_harness("trash-conflicts")
    async with harness.client() as client:
        stale = await call(client, "move_to_trash", args(harness, "task", "stale-key-001", 99))
        assert stale.is_error and stale.structured_content["code"] == "conflict"
        moved = await call(client, "move_to_trash", args(harness, "task", "fresh-key-001"))
        assert not moved.is_error
        # The old version is stale after the transition, and a second trash is a conflict.
        again = await call(client, "move_to_trash", args(harness, "task", "fresh-key-002"))
        assert again.is_error and again.structured_content["code"] == "conflict"
        old_restore = await call(
            client, "restore_from_trash", args(harness, "task", "restore-k-01")
        )
        assert old_restore.is_error and old_restore.structured_content["code"] == "conflict"
        current = moved.structured_content["version"]
        ok = await call(
            client, "restore_from_trash", args(harness, "task", "restore-k-02", current)
        )
        assert not ok.is_error
        not_trashed = await call(
            client,
            "restore_from_trash",
            args(harness, "task", "restore-k-03", ok.structured_content["version"]),
        )
        assert not_trashed.is_error and not_trashed.structured_content["code"] == "conflict"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_replay_returns_the_same_result_and_a_changed_payload_conflicts() -> None:
    harness = make_harness("trash-replay")
    async with harness.client() as client:
        first = await call(client, "move_to_trash", args(harness, "project", "replay-key-01"))
        replay = await call(client, "move_to_trash", args(harness, "project", "replay-key-01"))
        assert not first.is_error and not replay.is_error
        assert first.structured_content == replay.structured_content
        reused = await call(client, "move_to_trash", args(harness, "task", "replay-key-01"))
        assert reused.is_error
        assert reused.structured_content["code"] in {"conflict", "idempotency_conflict"}

        restore_args = args(
            harness, "project", "replay-key-02", first.structured_content["version"]
        )
        restored = await call(client, "restore_from_trash", restore_args)
        restore_replay = await call(client, "restore_from_trash", restore_args)
        assert restored.structured_content == restore_replay.structured_content
    owner = harness.actor.user_id
    assert audit_count(harness.container, owner, "project.trashed") == 1
    assert audit_count(harness.container, owner, "project.restored") == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_errors_and_logs_carry_no_record_content(caplog: pytest.LogCaptureFixture) -> None:
    harness = make_harness("trash-redaction")
    caplog.set_level(logging.DEBUG)
    async with harness.client() as client:
        moved = await call(client, "move_to_trash", args(harness, "journal_entry", "redact-key-01"))
        assert not moved.is_error and moved.structured_content["label"] == JOURNAL_TITLE
        stale = await call(client, "move_to_trash", args(harness, "task", "redact-key-02", 99))
        invalid = await call(
            client,
            "move_to_trash",
            {**args(harness, "task", "redact-key-03"), "record_id": "sentinel-bad-uuid-5d1c"},
        )
    async with harness.client(scopes=frozenset()) as client:
        forbidden = await call(client, "list_trash", {})
    for denied in (stale, invalid, forbidden):
        assert denied.is_error
    for denied in (stale, forbidden):
        assert denied.structured_content["correlation_id"]
        assert JOURNAL_TITLE not in str(denied.structured_content)
    assert "sentinel-bad-uuid-5d1c" not in caplog.text
    assert JOURNAL_TITLE not in caplog.text and SOURCE_TEXT not in caplog.text
    assert "redact-key-0" not in caplog.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_journal_entry_labels_are_in_the_text_blocks() -> None:
    """D-060: the host model may read all tool results, so Journal labels reach the text blocks."""
    harness = make_harness("trash-text-blocks")
    async with harness.client() as client:
        moved = await call(client, "move_to_trash", args(harness, "journal_entry", "text-key-01"))
        listing = await call(client, "list_trash", {"kind": "journal_entry"})
        restored = await call(
            client,
            "restore_from_trash",
            args(harness, "journal_entry", "text-key-02", moved.structured_content["version"]),
        )
    for outcome in (moved, listing, restored):
        assert not outcome.is_error
        assert JOURNAL_TITLE in str(outcome.structured_content)
        text = " ".join(block.text for block in outcome.content)
        assert JOURNAL_TITLE in text
        assert str(harness.records["journal_entry"][0]) in text
    # The summary line names the record by kind words and title, never by storage kind or id.
    assert moved.content[0].text == f'Moved journal entry "{JOURNAL_TITLE}" to the trash.'
    assert restored.content[0].text == f'Restored journal entry "{JOURNAL_TITLE}" from the trash.'
    assert listing.content[0].text.startswith("1 trashed item, latest a journal entry: ")


def test_mcp_read_scope_map_matches_the_use_case() -> None:
    """The MCP label rule must name exactly the kinds the use case lets an actor read."""

    assert _READ_SCOPE_BY_KIND == _READ_SCOPE


@pytest.mark.asyncio
@pytest.mark.integration
async def test_label_is_returned_only_with_the_kinds_read_scope() -> None:
    harness = make_harness("trash-label-scope")
    write_only = frozenset({"tasks:write"})
    async with harness.client(scopes=write_only) as client:
        moved = await call(client, "move_to_trash", args(harness, "task", "label-scope-01"))
        assert not moved.is_error, moved.structured_content
        assert moved.structured_content["label"] is None
        assert "Trash task" not in str(moved)
        restored = await call(
            client,
            "restore_from_trash",
            args(harness, "task", "label-scope-02", moved.structured_content["version"]),
        )
        assert not restored.is_error, restored.structured_content
        assert restored.structured_content["label"] is None
        assert "Trash task" not in str(restored)

    readable = frozenset({"tasks:write", "tasks:read"})
    async with harness.client(scopes=readable) as client:
        moved = await call(
            client,
            "move_to_trash",
            args(harness, "task", "label-scope-03", restored.structured_content["version"]),
        )
        assert not moved.is_error, moved.structured_content
        assert moved.structured_content["label"] == "Trash task"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_trashed_journal_sources_do_not_take_the_page_from_readable_records() -> None:
    """Journal sources are excluded by the query, so they never fill a limited page."""

    harness = make_harness("trash-paging")
    readable_ids: list[str] = []
    async with harness.client() as client:
        for index in range(2):
            task = harness.container.tasks.create(
                harness.actor, title=f"Paging task {index}", idempotency_key=f"paging-task-{index}"
            )
            moved = await call(
                client,
                "move_to_trash",
                {
                    "kind": "task",
                    "record_id": str(task.id),
                    "version": task.version,
                    "idempotency_key": f"paging-move-{index:02d}",
                },
            )
            assert not moved.is_error, moved.structured_content
            readable_ids.append(str(task.id))

    # Journal sources cannot be trashed through the application role (no UPDATE grant), so the
    # fixture sets trashed_at as the test admin role, newer than the Tasks, so they fill the top.
    admin_url = require_test_database_url("SIDEKICK_TEST_ADMIN_DATABASE_URL")
    admin = create_test_session_factory(admin_url)
    source_ids = []
    for index in range(3):
        source = harness.container.journal_capture.create_source(
            harness.actor,
            source_type=SourceType.MANUAL_TEXT,
            journal_date=date(2026, 7, 25 + index),
            occurred_at=None,
            source_recorded_at=None,
            raw_text=f"{SOURCE_TEXT}-{index}",
            language="sv",
            replaces_source_id=None,
            idempotency_key=f"paging-source-{index}",
        )
        source_ids.append(source.id)
    with admin() as session:
        for source_id in source_ids:
            session.execute(
                text(
                    "UPDATE sidekick.journal_sources SET trashed_at = now() + interval '1 hour' "
                    "WHERE id = :id AND owner_id = :owner"
                ),
                {"id": source_id, "owner": harness.actor.user_id},
            )
        session.commit()

    async with harness.client() as client:
        listed = await call(client, "list_trash", {"limit": 2})
    assert not listed.is_error, listed.structured_content
    assert {row["kind"] for row in listed.structured_content["items"]} == {"task"}
    assert {row["id"] for row in listed.structured_content["items"]} == set(readable_ids)
    assert listed.structured_content["has_more"] is False
    assert SOURCE_TEXT not in str(listed)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_trash_pages_by_cursor_are_total_owner_bound_and_reject_bad_cursors() -> None:
    """Two records of different kinds share one trash time; every page is complete and in order."""

    harness = make_harness("trash-cursor")
    tasks = [
        harness.container.tasks.create(
            harness.actor, title=f"Cursor task {i}", idempotency_key=f"cursor-task-{i}"
        )
        for i in range(4)
    ]
    async with harness.client() as client:
        for index, task in enumerate(tasks):
            moved = await call(
                client,
                "move_to_trash",
                {
                    "kind": "task",
                    "record_id": str(task.id),
                    "version": task.version,
                    "idempotency_key": f"cursor-move-{index:02d}",
                },
            )
            assert not moved.is_error, moved.structured_content
        moved = await call(client, "move_to_trash", args(harness, "project", "cursor-move-project"))
        assert not moved.is_error, moved.structured_content

    # Force identical trash times across the kinds so only the (kind, id) tiebreak orders them.
    with harness.container.session_factory() as session:
        for table in ("tasks", "projects"):
            session.execute(
                text(
                    f"UPDATE sidekick.{table} SET trashed_at = :at "
                    "WHERE owner_id = :owner AND trashed_at IS NOT NULL"
                ),
                {"at": "2026-08-01T10:00:00+00:00", "owner": harness.actor.user_id},
            )
        session.commit()

    served: list[tuple[str, str]] = []
    cursor: str | None = None
    page_sizes: list[int] = []
    async with harness.client() as client:
        while True:
            arguments: dict[str, Any] = {"limit": 2}
            if cursor:
                arguments["cursor"] = cursor
            listed = await call(client, "list_trash", arguments)
            assert not listed.is_error, listed.structured_content
            content = listed.structured_content
            page_sizes.append(len(content["items"]))
            served.extend((row["kind"], row["id"]) for row in content["items"])
            assert content["has_more"] is (content["next_cursor"] is not None)
            cursor = content["next_cursor"]
            if cursor is None:
                break
            assert len(cursor) <= MAX_CURSOR_LENGTH

        assert page_sizes == [2, 2, 1]
        assert len(set(served)) == 5
        # Total order: kind descending, then id descending, for the shared trash time.
        assert served == sorted(served, reverse=True)

        # Bad, foreign and narrowed cursors are the same validation error as other lists.
        first = (await call(client, "list_trash", {"limit": 1})).structured_content
        for bad in ("not-a-cursor", first["next_cursor"][:-2] + "AA"):
            failed = await call(client, "list_trash", {"cursor": bad})
            assert failed.is_error and failed.structured_content["code"] == "validation_error"
        narrowed = await call(
            client, "list_trash", {"kind": "task", "cursor": first["next_cursor"]}
        )
        assert narrowed.is_error and narrowed.structured_content["code"] == "validation_error"
        too_long = await call(client, "list_trash", {"cursor": "a" * (MAX_CURSOR_LENGTH + 1)})
        assert too_long.is_error

    other_id = harness.container.auth.provision_user("trash-cursor-b", "Other")
    async with harness.client(user_id=other_id) as client:
        foreign = await call(client, "list_trash", {"cursor": first["next_cursor"]})
        assert foreign.is_error and foreign.structured_content["code"] == "validation_error"


def test_count_line_names_the_newest_kind_and_leads_the_labels() -> None:
    """Pure check of the count line: the newest item's kind leads, then up to three labels."""

    def item(kind: KindValue, label: str | None) -> TrashItemRecord:
        return TrashItemRecord(kind=kind, id=uuid4(), label=label, trashed_at=None, version=1)

    seven = [item("task", "A"), *(item("task", name) for name in "BCDEFG")]
    assert _trash_summary(seven, has_more=False) == (
        "7 trashed items, latest a task: A, B, C and 4 more."
    )
    assert _trash_summary([item("action", "Byt lampa")], has_more=False) == (
        "1 trashed item, latest an action: Byt lampa."
    )
    assert _trash_summary([item("contact", None), item("task", "B")], has_more=True) == (
        "at least 2 trashed items, latest a contact (name hidden): B and 1 more."
    )

"""The Contact and Journal tools carry the owner's tags: write, read, filter and count them."""

from __future__ import annotations

import os
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from fastmcp import Client
from sqlalchemy import select, text

from sidekick.api.app import Container, create_container
from sidekick.journal.domain.source import SourceType
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.persistence.models import AuditEventRow
from sidekick.shared.types import Actor
from tests.db import _cleanup_factory_for, database_factory
from tests.support.mcp_scope_gate import _code, _digests
from tests.support.settings import make_settings
from tests.support.telemetry import CaptureTelemetry

ALL = frozenset(
    {
        "contacts:read",
        "contacts:write",
        "journal:read",
        "journal:write",
        "projects:read",
        "tasks:read",
        "tasks:write",
    }
)
DAY = "2026-07-21"
SENSITIVE_TAG = "hemlig-diagnos-xyzzy"


def _server(container: Container, owner: Any, scopes: frozenset[str] = ALL) -> Any:
    return create_mcp_server(
        container, actor_provider=lambda: Actor(owner, scopes), enable_auth=False
    )


@pytest.fixture
def setup() -> tuple[Container, Any]:
    container = create_container(make_settings(), database_factory())
    return container, container.auth.provision_user("owner", "Owner")


async def _call(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    async with Client(server) as client:
        return await client.call_tool(name, arguments)


# --- Contacts ---------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_and_update_contact_carry_tags(setup: tuple[Container, Any]) -> None:
    container, owner = setup
    server = _server(container, owner)

    created = await _call(
        server,
        "create_contact",
        {
            "display_name": "Anna",
            "tags": ["Viktig", "familj"],
            "idempotency_key": "test-key-c-create",
        },
    )
    contact = created.structured_content["contact"]
    assert sorted(contact["tags"]) == ["familj", "viktig"]
    assert "Tags: familj, viktig." in created.content[0].text

    # Tags alone are a valid update; the complete set replaces the old one.
    retagged = await _call(
        server,
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": contact["version"],
            "idempotency_key": "test-key-c-retag",
            "changes": {"tags": ["vänta"]},
        },
    )
    updated = retagged.structured_content["contact"]
    assert updated["tags"] == ["vänta"]
    assert updated["version"] == contact["version"] + 1
    assert updated["display_name"] == "Anna"

    # An update that names no tags keeps them; null is refused; [] removes them all.
    renamed = await _call(
        server,
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": updated["version"],
            "idempotency_key": "test-key-c-rename",
            "changes": {"display_name": "Anna Lind"},
        },
    )
    assert renamed.structured_content["contact"]["tags"] == ["vänta"]
    version = renamed.structured_content["contact"]["version"]
    async with Client(server) as client:
        refused = await client.call_tool(
            "update_contact",
            {
                "contact_id": contact["id"],
                "expected_version": version,
                "idempotency_key": "test-key-c-null",
                "changes": {"tags": None},
            },
            raise_on_error=False,
        )
    assert refused.is_error
    kept = await _call(
        server,
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": version,
            "idempotency_key": "test-key-c-keep",
            "changes": {"role": "Neighbour"},
        },
    )
    assert kept.structured_content["contact"]["tags"] == ["vänta"]
    cleared = await _call(
        server,
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": kept.structured_content["contact"]["version"],
            "idempotency_key": "test-key-c-clear",
            "changes": {"tags": []},
        },
    )
    assert cleared.structured_content["contact"]["tags"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_contacts_filters_by_tag_and_shows_tags(setup: tuple[Container, Any]) -> None:
    container, owner = setup
    server = _server(container, owner)
    for name, tags in (("Anna", ["viktig", "familj"]), ("Bo", ["viktig"]), ("Cia", [])):
        await _call(
            server,
            "create_contact",
            {"display_name": name, "tags": tags, "idempotency_key": f"test-key-c-{name}"},
        )

    plain = await _call(server, "list_contacts", {})
    assert [c["tags"] for c in plain.structured_content["contacts"]] == [
        ["familj", "viktig"],
        ["viktig"],
        [],
    ]
    assert "tags: familj, viktig" in plain.content[0].text

    any_match = await _call(server, "list_contacts", {"tags": ["viktig"]})
    assert [c["display_name"] for c in any_match.structured_content["contacts"]] == ["Anna", "Bo"]
    assert any_match.structured_content["tags"] == ["viktig"]
    assert any_match.structured_content["tag_match"] == "any"

    all_match = await _call(
        server, "list_contacts", {"tags": ["viktig", "familj"], "tag_match": "all"}
    )
    assert [c["display_name"] for c in all_match.structured_content["contacts"]] == ["Anna"]
    assert all_match.structured_content["tag_match"] == "all"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_contact_context_lists_the_contacts_tags(setup: tuple[Container, Any]) -> None:
    container, owner = setup
    server = _server(container, owner)
    created = await _call(
        server,
        "create_contact",
        {"display_name": "Anna", "tags": ["familj"], "idempotency_key": "test-key-c-ctx"},
    )
    contact_id = created.structured_content["contact"]["id"]

    context = await _call(server, "get_contact_context", {"contact_id": contact_id})

    assert context.structured_content["contact"]["tags"] == ["familj"]
    assert "Tags: familj" in context.content[0].text


# --- Journal ----------------------------------------------------------------------------------


async def _write_entry(server: Any, title: str, tags: list[str] | None, key: str) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "journal_date": DAY,
        "title": title,
        "source_text": f"Words for {title}",
        "idempotency_key": key,
    }
    if tags is not None:
        arguments["tags"] = tags
    result = await _call(server, "write_journal_entry", arguments)
    return result.structured_content["entry"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_write_and_update_journal_entry_carry_tags(setup: tuple[Container, Any]) -> None:
    container, owner = setup
    server = _server(container, owner)

    entry = await _write_entry(server, "Dag", ["Viktig", "familj"], "test-key-j-write")
    assert sorted(entry["tags"]) == ["familj", "viktig"]

    # Tags alone are a valid update: content stays, the version moves.
    retagged = await _call(
        server,
        "update_journal_entry",
        {
            "entry_id": entry["id"],
            "expected_version": entry["version"],
            "idempotency_key": "test-key-j-retag",
            "tags": ["vänta"],
        },
    )
    updated = retagged.structured_content["entry"]
    assert updated["tags"] == ["vänta"]
    assert updated["title"] == "Dag"
    assert updated["version"] == entry["version"] + 1
    assert "Tags: vänta." in retagged.content[0].text

    # Appending without naming tags keeps them; an explicit empty set removes them all.
    appended = await _call(
        server,
        "update_journal_entry",
        {
            "entry_id": entry["id"],
            "expected_version": updated["version"],
            "idempotency_key": "test-key-j-append",
            "append_key_points": [{"kind": "fact", "text": "More"}],
        },
    )
    assert appended.structured_content["entry"]["tags"] == ["vänta"]
    cleared = await _call(
        server,
        "update_journal_entry",
        {
            "entry_id": entry["id"],
            "expected_version": appended.structured_content["entry"]["version"],
            "idempotency_key": "test-key-j-clear",
            "tags": [],
        },
    )
    assert cleared.structured_content["entry"]["tags"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_journal_reads_show_tags_and_filter_by_them(setup: tuple[Container, Any]) -> None:
    container, owner = setup
    server = _server(container, owner)
    first = await _write_entry(server, "Ett", ["viktig", "familj"], "test-key-j-1")
    await _write_entry(server, "Två", ["viktig"], "test-key-j-2")
    await _write_entry(server, "Tre", None, "test-key-j-3")

    listed = await _call(
        server, "list_journal_entries", {"from_date": DAY, "to_date": DAY, "limit": 50}
    )
    assert {e["title"]: e["tags"] for e in listed.structured_content["entries"]} == {
        "Ett": ["familj", "viktig"],
        "Två": ["viktig"],
        "Tre": [],
    }
    assert "tags: familj, viktig" in listed.content[0].text

    wanted = await _call(
        server,
        "list_journal_entries",
        {"from_date": DAY, "to_date": DAY, "tags": ["viktig", "familj"], "tag_match": "all"},
    )
    assert [e["title"] for e in wanted.structured_content["entries"]] == ["Ett"]
    either = await _call(
        server, "list_journal_entries", {"from_date": DAY, "to_date": DAY, "tags": ["viktig"]}
    )
    assert sorted(e["title"] for e in either.structured_content["entries"]) == ["Ett", "Två"]

    day = await _call(server, "get_journal_day", {"journal_date": DAY})
    assert {e["title"]: e["tags"] for e in day.structured_content["entries"]}["Ett"] == [
        "familj",
        "viktig",
    ]
    single = await _call(server, "get_journal_entry", {"entry_id": first["id"]})
    assert single.structured_content["entry"]["tags"] == ["familj", "viktig"]
    assert "Tags: familj, viktig." in single.content[0].text
    # Tags are shown even when the owner's text is left out.
    bare = await _call(
        server, "get_journal_entry", {"entry_id": first["id"], "include_content": False}
    )
    assert bare.structured_content["entry"]["summary"] is None
    assert bare.structured_content["entry"]["tags"] == ["familj", "viktig"]


# --- The shared vocabulary --------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_tags_counts_use_across_every_kind(setup: tuple[Container, Any]) -> None:
    container, owner = setup
    server = _server(container, owner)
    await _call(
        server,
        "create_contact",
        {"display_name": "Anna", "tags": ["viktig"], "idempotency_key": "test-key-v-contact"},
    )
    await _write_entry(server, "Dag", ["viktig", "familj"], "test-key-v-entry")
    await _call(
        server,
        "create_task",
        {"title": "Task", "tags": ["viktig"], "idempotency_key": "test-key-v-task"},
    )

    listed = await _call(server, "list_tags", {})

    usage = {tag["slug"]: tag["usage"] for tag in listed.structured_content["tags"]}
    assert usage["viktig"] == {
        "domain": 0,
        "process": 0,
        "project": 0,
        "task": 1,
        "contact": 1,
        "journal_entry": 1,
    }
    assert usage["familj"]["journal_entry"] == 1
    assert sum(usage["familj"].values()) == 1


# --- Authorization and redaction --------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_caller_who_cannot_read_the_reply_writes_no_tags(
    setup: tuple[Container, Any],
) -> None:
    container, owner = setup
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    anna = (
        await _call(
            _server(container, owner),
            "create_contact",
            {"display_name": "Anna", "idempotency_key": "test-key-a-seed"},
        )
    ).structured_content["contact"]
    entry = await _write_entry(_server(container, owner), "Dag", None, "test-key-a-seed-entry")
    before = _digests(admin)

    write_only = _server(container, owner, frozenset({"contacts:write", "journal:write"}))
    async with Client(write_only) as client:
        refused = {
            "create_contact": await client.call_tool(
                "create_contact",
                {"display_name": "Bo", "tags": ["viktig"], "idempotency_key": "test-key-a-1"},
                raise_on_error=False,
            ),
            "update_contact": await client.call_tool(
                "update_contact",
                {
                    "contact_id": anna["id"],
                    "expected_version": anna["version"],
                    "idempotency_key": "test-key-a-2",
                    "changes": {"tags": ["viktig"]},
                },
                raise_on_error=False,
            ),
            "update_journal_entry": await client.call_tool(
                "update_journal_entry",
                {
                    "entry_id": entry["id"],
                    "expected_version": entry["version"],
                    "idempotency_key": "test-key-a-3",
                    "tags": ["viktig"],
                },
                raise_on_error=False,
            ),
        }

    assert {name: _code(result) for name, result in refused.items()} == dict.fromkeys(
        refused, "forbidden"
    )
    assert _digests(admin) == before


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_write_only_journal_caller_can_tag_a_new_entry_and_sees_only_what_it_wrote(
    setup: tuple[Container, Any],
) -> None:
    container, owner = setup
    write_only = _server(container, owner, frozenset({"journal:write"}))

    entry = await _write_entry(write_only, "Dag", ["Viktig"], "test-key-w-only")

    assert entry["tags"] == ["viktig"]
    stored = await _call(_server(container, owner), "get_journal_entry", {"entry_id": entry["id"]})
    assert stored.structured_content["entry"]["tags"] == ["viktig"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tag_values_stay_out_of_telemetry_and_audit() -> None:
    telemetry = CaptureTelemetry()
    factory = database_factory()
    container = create_container(make_settings(), factory, telemetry)
    owner = container.auth.provision_user("telemetry-owner", "Owner")
    server = _server(container, owner)

    contact = (
        await _call(
            server,
            "create_contact",
            {
                "display_name": "Anna",
                "tags": [SENSITIVE_TAG],
                "idempotency_key": "test-key-t-contact",
            },
        )
    ).structured_content["contact"]
    await _call(
        server,
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": contact["version"],
            "idempotency_key": "test-key-t-retag",
            "changes": {"tags": [SENSITIVE_TAG, "annan"]},
        },
    )
    await _call(server, "list_contacts", {"tags": [SENSITIVE_TAG]})
    entry = await _write_entry(server, "Dag", [SENSITIVE_TAG], "test-key-t-entry")
    await _call(
        server,
        "update_journal_entry",
        {
            "entry_id": entry["id"],
            "expected_version": entry["version"],
            "idempotency_key": "test-key-t-entry-retag",
            "tags": [SENSITIVE_TAG, "annan"],
        },
    )
    await _call(
        server, "list_journal_entries", {"from_date": DAY, "to_date": DAY, "tags": [SENSITIVE_TAG]}
    )

    with factory() as session:
        audit = session.scalars(select(AuditEventRow)).all()
    assert SENSITIVE_TAG not in str(telemetry.records) + str(audit)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_tags_counts_only_the_kinds_the_caller_may_read(
    setup: tuple[Container, Any],
) -> None:
    container, owner = setup
    server = _server(container, owner)
    await _call(
        server,
        "create_contact",
        {"display_name": "Anna", "tags": ["viktig"], "idempotency_key": "test-key-s-contact"},
    )
    await _write_entry(server, "Dag", ["viktig"], "test-key-s-entry")
    await _call(
        server,
        "create_task",
        {"title": "Task", "tags": ["viktig"], "idempotency_key": "test-key-s-task"},
    )

    async def usage_with(scopes: frozenset[str]) -> dict[str, int]:
        listed = await _call(_server(container, owner, scopes), "list_tags", {})
        (tag,) = listed.structured_content["tags"]
        return tag["usage"]

    work_only = await usage_with(frozenset({"projects:read"}))
    assert work_only == {"domain": 0, "process": 0, "project": 0, "task": 1}
    with_contacts = await usage_with(frozenset({"projects:read", "contacts:read"}))
    assert with_contacts["contact"] == 1 and "journal_entry" not in with_contacts
    with_journal = await usage_with(frozenset({"projects:read", "journal:read"}))
    assert with_journal["journal_entry"] == 1 and "contact" not in with_journal
    everything = await usage_with(ALL)
    assert everything["contact"] == 1 and everything["journal_entry"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_tags_counts_what_the_lists_show_not_archived_or_trashed(
    setup: tuple[Container, Any],
) -> None:
    container, owner = setup
    server = _server(container, owner)
    contacts = [
        (
            await _call(
                server,
                "create_contact",
                {"display_name": name, "tags": ["viktig"], "idempotency_key": f"test-key-l-{name}"},
            )
        ).structured_content["contact"]
        for name in ("Anna", "Bo")
    ]
    await _write_entry(server, "Kvar", ["viktig"], "test-key-l-kept")
    archived = await _write_entry(server, "Arkiverad", ["viktig"], "test-key-l-archived")
    trashed = await _write_entry(server, "Papperskorg", ["viktig"], "test-key-l-trashed")
    await _call(
        server,
        "archive_contact",
        {
            "contact_id": contacts[1]["id"],
            "expected_version": contacts[1]["version"],
            "idempotency_key": "test-key-l-archive-contact",
        },
    )
    container.journal.archive_entry(
        Actor(owner, ALL),
        entry_id=UUID(archived["id"]),
        expected_version=archived["version"],
        idempotency_key="test-key-l-archive-entry",
    )
    with container.session_factory.begin() as session:
        session.execute(
            text("UPDATE sidekick.journal_entries SET trashed_at = now() WHERE id = :id"),
            {"id": trashed["id"]},
        )

    listed = await _call(server, "list_tags", {})

    (tag,) = listed.structured_content["tags"]
    assert tag["usage"]["contact"] == 1
    assert tag["usage"]["journal_entry"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_manual_journal_entry_carries_tags(setup: tuple[Container, Any]) -> None:
    container, owner = setup
    server = _server(container, owner)
    source = container.journal_capture.create_source(
        Actor(owner, ALL),
        source_type=SourceType.MANUAL_TEXT,
        journal_date=date(2026, 7, 21),
        occurred_at=None,
        source_recorded_at=None,
        raw_text="Words",
        language=None,
        replaces_source_id=None,
        idempotency_key="test-key-m-source",
    )

    created = await _call(
        server,
        "create_manual_journal_entry",
        {
            "source_id": str(source.id),
            "title": "Dag",
            "summary": None,
            "key_points": [],
            "project_ids": [],
            "task_ids": [],
            "contact_ids": [],
            "tags": ["Viktig", "familj"],
            "idempotency_key": "test-key-m-entry",
        },
    )

    entry = created.structured_content["entry"]
    assert sorted(entry["tags"]) == ["familj", "viktig"]
    assert "Tags:" in created.content[0].text
    read_back = await _call(server, "get_journal_entry", {"entry_id": entry["id"]})
    assert sorted(read_back.structured_content["entry"]["tags"]) == ["familj", "viktig"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_tags_hides_a_tag_used_only_on_kinds_the_caller_may_not_read(
    setup: tuple[Container, Any],
) -> None:
    container, owner = setup
    server = _server(container, owner)
    await _call(
        server,
        "create_contact",
        {"display_name": "Anna", "tags": ["anna-diagnos"], "idempotency_key": "test-key-h-contact"},
    )
    await _write_entry(server, "Dag", ["dagbok-hemlig"], "test-key-h-entry")
    await _call(
        server,
        "create_task",
        {"title": "Task", "tags": ["viktig", "gemensam"], "idempotency_key": "test-key-h-task"},
    )
    await _call(
        server,
        "create_contact",
        {"display_name": "Bo", "tags": ["gemensam"], "idempotency_key": "test-key-h-contact-2"},
    )
    container.work_tags.create(
        Actor(owner, ALL | {"projects:write"}), label="tom", idempotency_key="test-key-h-empty"
    )

    async def slugs_with(scopes: frozenset[str]) -> set[str]:
        listed = await _call(_server(container, owner, scopes), "list_tags", {})
        return {tag["slug"] for tag in listed.structured_content["tags"]}

    work_only = await slugs_with(frozenset({"projects:read"}))
    # A tag on a task is shown, a tag nobody uses is shown, a tag only on Contacts or Journal
    # entries is not, and a tag shared with a task is shown but its Contact count is not.
    assert work_only == {"viktig", "gemensam", "tom"}
    with_contacts = await slugs_with(frozenset({"projects:read", "contacts:read"}))
    assert with_contacts == {"viktig", "gemensam", "tom", "anna-diagnos"}
    with_journal = await slugs_with(frozenset({"projects:read", "journal:read"}))
    assert with_journal == {"viktig", "gemensam", "tom", "dagbok-hemlig"}
    assert await slugs_with(ALL) == {
        "viktig",
        "gemensam",
        "tom",
        "anna-diagnos",
        "dagbok-hemlig",
    }
    listed = await _call(_server(container, owner, frozenset({"projects:read"})), "list_tags", {})
    shared = next(tag for tag in listed.structured_content["tags"] if tag["slug"] == "gemensam")
    assert "contact" not in shared["usage"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_hidden_tags_do_not_change_the_paging_of_the_visible_ones(
    setup: tuple[Container, Any],
) -> None:
    container, owner = setup
    server = _server(container, owner)
    for index in range(3):
        await _call(
            server,
            "create_contact",
            {
                "display_name": f"Kontakt {index}",
                "tags": [f"a-hidden-{index}"],
                "idempotency_key": f"test-key-p-contact-{index}",
            },
        )
        await _call(
            server,
            "create_task",
            {
                "title": f"Task {index}",
                "tags": [f"b-shown-{index}"],
                "idempotency_key": f"test-key-p-task-{index}",
            },
        )
    work_only = _server(container, owner, frozenset({"projects:read"}))

    first = await _call(work_only, "list_tags", {"limit": 2})
    second = await _call(
        work_only, "list_tags", {"limit": 2, "cursor": first.structured_content["next_cursor"]}
    )

    shown = [tag["slug"] for tag in first.structured_content["tags"]]
    shown += [tag["slug"] for tag in second.structured_content["tags"]]
    assert shown == ["b-shown-0", "b-shown-1", "b-shown-2"]
    assert not second.structured_content.get("next_cursor")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_tags_does_not_count_archived_or_trashed_work_records(
    setup: tuple[Container, Any],
) -> None:
    container, owner = setup
    server = _server(container, owner)
    tasks = [
        (
            await _call(
                server,
                "create_task",
                {"title": name, "tags": ["viktig"], "idempotency_key": f"test-key-w-{name}"},
            )
        ).structured_content["task"]
        for name in ("kvar", "arkiverad", "papperskorg")
    ]
    with container.session_factory.begin() as session:
        session.execute(
            text("UPDATE sidekick.tasks SET archived_at = now() WHERE id = :id"),
            {"id": tasks[1]["id"]},
        )
        session.execute(
            text("UPDATE sidekick.tasks SET trashed_at = now() WHERE id = :id"),
            {"id": tasks[2]["id"]},
        )

    listed = await _call(server, "list_tags", {})

    (tag,) = listed.structured_content["tags"]
    assert tag["usage"]["task"] == 1

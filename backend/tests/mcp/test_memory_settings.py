"""MCP behaviour of `get_memory_status`, `set_memory_settings` and `exclude_from_memory`.

Scopes, the confirmation gate for switching a domain off, optimistic locking, and per-record
exclusion over PostgreSQL. The sync interplay (what the worker does with these rows) is in
`tests/memory/test_settings_sync.py`.
"""

from typing import Any
from uuid import UUID

import pytest
from fastmcp import Client
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container
from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.domain import MemoryKind
from sidekick.shared.persistence.models import MemorySettingsRow, MemorySourceRow, UserRow
from sidekick.shared.types import Actor, new_uuid7, utc_now
from tests.db import database_factory
from tests.support.mcp_recall import (
    ALL_SCOPES,
    _contact,
    _container,
    _journal,
    _memory_row,
    _owner,
    _project,
    _server,
    _settings,
    _structured,
    _task,
)

READ_ALL = ALL_SCOPES
WRITE_ALL = frozenset({"journal:write", "contacts:write", "projects:write", "tasks:write"})
READ_AND_WRITE = READ_ALL | WRITE_ALL
DOMAIN_SCOPE = {
    "journal": "journal:write",
    "contacts": "contacts:write",
    "projects": "projects:write",
    "tasks": "tasks:write",
}


def _setup() -> tuple[sessionmaker[Session], Container, UUID]:
    factory = database_factory()
    container = _container(factory)
    return factory, container, _owner(container)


def _settings_row(factory: sessionmaker[Session], owner: UUID) -> MemorySettingsRow | None:
    with factory() as session:
        return session.get(MemorySettingsRow, owner)


def _owner_without_settings(factory: sessionmaker[Session]) -> UUID:
    """An owner with no memory settings row. The app role may not delete one, so none is made."""
    owner_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            UserRow(
                id=owner_id,
                username=f"bare-{owner_id.hex}",
                display_name="Bare",
                active=True,
                created_at=utc_now(),
            )
        )
    return owner_id


def _source_rows(factory: sessionmaker[Session], owner: UUID) -> list[MemorySourceRow]:
    with factory() as session:
        return list(
            session.scalars(select(MemorySourceRow).where(MemorySourceRow.owner_id == owner))
        )


async def _call(container: Container, actor: Actor, name: str, arguments: dict[str, Any]) -> Any:
    async with Client(_server(container, actor)) as client:
        return await client.call_tool(name, arguments, raise_on_error=False)


def _is_forbidden(call: Any) -> bool:
    return bool(call.is_error) and _structured(call.structured_content)["code"] == "forbidden"


# --- get_memory_status ---------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_new_owner_has_all_four_domains_on_at_version_one() -> None:
    factory, container, owner = _setup()
    container.memory = None

    call = await _call(container, Actor(owner, READ_ALL), "get_memory_status", {})

    assert not call.is_error
    data = _structured(call.structured_content)
    assert data["settings"] == {
        "journal": True,
        "contacts": True,
        "projects": True,
        "tasks": True,
        "paused": False,
        "version": 1,
    }
    row = _settings_row(factory, owner)
    assert row is not None and (row.journal, row.contacts, row.projects, row.tasks) == (
        True,
        True,
        True,
        True,
    )
    assert data["provider"] == "off"
    assert call.content[0].text.startswith(
        "Memory is on for journal, contacts, projects and tasks, but the memory service is off"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_status_without_a_settings_row_reads_the_defaults_at_version_zero() -> None:
    factory, container, _owner = _setup()
    owner = _owner_without_settings(factory)
    container.memory = None

    call = await _call(container, Actor(owner, READ_ALL), "get_memory_status", {})

    assert not call.is_error
    data = _structured(call.structured_content)
    assert data["settings"] == {
        "journal": True,
        "contacts": True,
        "projects": True,
        "tasks": True,
        "paused": False,
        "version": 0,
    }
    assert {source["kind"] for source in data["sources"]} == {
        "journal_entry",
        "contact",
        "project",
        "task",
    }
    assert all(source["retained"] == 0 for source in data["sources"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_status_with_every_domain_switched_off_says_so() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner)
    container.memory = None

    call = await _call(container, Actor(owner, READ_ALL), "get_memory_status", {})

    data = _structured(call.structured_content)
    assert data["settings"]["version"] == 1
    assert call.content[0].text == "Memory is off for every domain."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_status_counts_per_kind_and_status_and_names_the_fake_provider() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True, contacts=True)
    container.memory = FakeMemoryProvider()
    journal = _journal(factory, owner, "Dag")
    contact = _contact(factory, owner, "Sara")
    other_contact = _contact(factory, owner, "Per")
    _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, journal)
    _memory_row(factory, owner, MemoryKind.CONTACT, contact)
    _memory_row(factory, owner, MemoryKind.CONTACT, other_contact)
    with factory.begin() as session:
        rows = session.scalars(
            select(MemorySourceRow).where(
                MemorySourceRow.owner_id == owner, MemorySourceRow.source_id == other_contact
            )
        ).all()
        rows[0].excluded = True

    call = await _call(container, Actor(owner, READ_ALL), "get_memory_status", {})

    data = _structured(call.structured_content)
    assert data["provider"] == "fake"
    counts = {source["kind"]: source for source in data["sources"]}
    assert counts["journal_entry"]["retained"] == 1
    assert counts["contact"]["retained"] == 1
    assert counts["contact"]["excluded"] == 1
    assert (
        call.content[0].text
        == "Memory is on for journal and contacts: 2 records stored, 1 excluded. "
        "Memory uses a test provider; nothing reaches the real memory."
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_status_counts_only_kinds_the_caller_may_read() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True, contacts=True)
    container.memory = FakeMemoryProvider()
    _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, _journal(factory, owner, "Dag"))
    _memory_row(factory, owner, MemoryKind.CONTACT, _contact(factory, owner, "Sara"))

    call = await _call(
        container, Actor(owner, frozenset({"journal:read"})), "get_memory_status", {}
    )

    data = _structured(call.structured_content)
    assert [source["kind"] for source in data["sources"]] == ["journal_entry"]
    assert data["sources"][0]["retained"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_status_without_any_read_scope_is_forbidden() -> None:
    _factory, container, owner = _setup()

    call = await _call(container, Actor(owner, WRITE_ALL), "get_memory_status", {})

    assert _is_forbidden(call)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_status_reports_pending_failed_and_parked_but_not_removed_markers() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, tasks=True)
    container.memory = FakeMemoryProvider()
    for status, category in (
        ("pending", None),
        ("submitted", None),
        ("failed", "timeout"),
        ("parked", "rejected"),
        ("parked", "removed"),
    ):
        task = _task(factory, owner, f"Uppgift {status} {category}", completed_at=None)
        _memory_row(factory, owner, MemoryKind.TASK, task)
        with factory.begin() as session:
            row = session.scalars(
                select(MemorySourceRow).where(MemorySourceRow.source_id == task)
            ).one()
            row.status = status
            row.failure_category = category
            row.operation_id = "op" if status == "submitted" else None

    call = await _call(container, Actor(owner, frozenset({"tasks:read"})), "get_memory_status", {})

    counts = _structured(call.structured_content)["sources"][0]
    assert (counts["retained"], counts["pending"], counts["failed"], counts["parked"]) == (
        0,
        2,
        1,
        1,
    )


# --- set_memory_settings: scopes -----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("domain", ["journal", "contacts", "projects", "tasks"])
async def test_each_domain_needs_its_own_write_scope(domain: str) -> None:
    factory, container, owner = _setup()
    _settings(factory, owner)
    others = WRITE_ALL - {DOMAIN_SCOPE[domain]}

    refused = await _call(
        container,
        Actor(owner, others | READ_ALL),
        "set_memory_settings",
        {"expected_version": 1, domain: True},
    )
    allowed = await _call(
        container,
        Actor(owner, frozenset({DOMAIN_SCOPE[domain]})),
        "set_memory_settings",
        {"expected_version": 1, domain: True},
    )

    assert _is_forbidden(refused)
    assert not allowed.is_error
    row = _settings_row(factory, owner)
    assert row is not None and getattr(row, domain) is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_refused_domain_blocks_the_whole_call_even_beside_an_allowed_one() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner)

    call = await _call(
        container,
        Actor(owner, frozenset({"journal:write"})),
        "set_memory_settings",
        {"expected_version": 1, "journal": True, "tasks": True},
    )

    assert _is_forbidden(call)
    row = _settings_row(factory, owner)
    assert row is not None and (row.journal, row.tasks, row.version) == (False, False, 1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pausing_needs_some_write_scope_and_read_scopes_do_not_count() -> None:
    factory, container, owner = _setup()

    refused = await _call(
        container,
        Actor(owner, READ_ALL),
        "set_memory_settings",
        {"expected_version": 1, "paused": True},
    )
    allowed = await _call(
        container,
        Actor(owner, frozenset({"contacts:write"})),
        "set_memory_settings",
        {"expected_version": 1, "paused": True},
    )

    assert _is_forbidden(refused)
    assert not allowed.is_error
    row = _settings_row(factory, owner)
    assert row is not None and row.paused is True and row.version == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_setting_at_all_is_a_validation_error() -> None:
    _factory, container, owner = _setup()

    call = await _call(
        container, Actor(owner, WRITE_ALL), "set_memory_settings", {"expected_version": 0}
    )

    assert call.is_error
    assert _structured(call.structured_content)["code"] == "validation_error"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_setting_at_all_without_a_write_scope_is_forbidden() -> None:
    _factory, container, owner = _setup()

    call = await _call(
        container, Actor(owner, READ_ALL), "set_memory_settings", {"expected_version": 0}
    )

    assert _is_forbidden(call)


# --- set_memory_settings: create, turn on, confirmation gate --------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_turning_domains_on_again_without_confirm_bumps_the_version() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner)

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "set_memory_settings",
        {"expected_version": 1, "journal": True, "tasks": True},
    )

    assert not call.is_error
    data = _structured(call.structured_content)
    assert data["status"] == "updated"
    assert data["turning_off"] == []
    assert data["settings"]["version"] == 2
    row = _settings_row(factory, owner)
    assert row is not None
    assert (row.journal, row.contacts, row.projects, row.tasks, row.paused) == (
        True,
        False,
        False,
        True,
        False,
    )
    assert row.version == 2
    assert call.content[0].text == "Memory settings saved."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_turning_on_a_domain_that_is_on_by_default_changes_nothing() -> None:
    factory, container, owner = _setup()

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "set_memory_settings",
        {"expected_version": 1, "journal": True},
    )

    assert not call.is_error
    data = _structured(call.structured_content)
    assert data["status"] == "unchanged"
    assert data["settings"]["version"] == 1
    row = _settings_row(factory, owner)
    assert row is not None and (row.journal, row.version) == (True, 1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_turning_a_domain_off_without_confirm_changes_nothing_and_previews() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True, contacts=True)
    for index in range(8):
        entry = _journal(factory, owner, f"Dag {index}")
        _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, entry)
    _memory_row(factory, owner, MemoryKind.CONTACT, _contact(factory, owner, "Sara"))

    call = await _call(
        container,
        Actor(owner, READ_AND_WRITE),
        "set_memory_settings",
        {"expected_version": 1, "journal": False, "paused": True},
    )

    assert not call.is_error
    data = _structured(call.structured_content)
    assert data["status"] == "needs_confirmation"
    assert data["turning_off"] == [{"domain": "journal", "documents": 8}]
    assert data["settings"]["journal"] is True
    assert data["settings"]["paused"] is False
    assert data["settings"]["version"] == 1
    assert call.content[0].text == (
        "Turning off journal removes 8 journal entries from memory. "
        "Turning it on again costs a new import. Call again with confirm true."
    )
    row = _settings_row(factory, owner)
    assert row is not None
    assert (row.journal, row.paused, row.version) == (True, False, 1)
    assert len(_source_rows(factory, owner)) == 9


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_preview_names_every_domain_and_uses_singular_for_one() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, contacts=True, projects=True)
    _memory_row(factory, owner, MemoryKind.CONTACT, _contact(factory, owner, "Sara"))
    _memory_row(factory, owner, MemoryKind.PROJECT, _project(factory, owner, "Bygge"))
    _memory_row(factory, owner, MemoryKind.PROJECT, _project(factory, owner, "Resa"))

    call = await _call(
        container,
        Actor(owner, READ_AND_WRITE),
        "set_memory_settings",
        {"expected_version": 1, "contacts": False, "projects": False},
    )

    assert call.content[0].text == (
        "Turning off contacts and projects removes 1 contact and 2 projects from memory. "
        "Turning them on again costs a new import. Call again with confirm true."
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_confirm_writes_the_change_and_raises_the_version() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True, tasks=True)
    _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, _journal(factory, owner, "Dag"))

    call = await _call(
        container,
        Actor(owner, READ_AND_WRITE),
        "set_memory_settings",
        {"expected_version": 1, "journal": False, "confirm": True},
    )

    assert not call.is_error
    data = _structured(call.structured_content)
    assert data["status"] == "updated"
    assert data["settings"]["version"] == 2
    assert data["turning_off"] == [{"domain": "journal", "documents": 1}]
    row = _settings_row(factory, owner)
    assert row is not None
    assert (row.journal, row.tasks, row.version) == (False, True, 2)
    # The documents stay until the sync pass removes them; no memory row is touched here.
    assert len(_source_rows(factory, owner)) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_write_only_caller_sees_that_the_domain_goes_but_not_how_many() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True)
    for index in range(3):
        entry = _journal(factory, owner, f"Dag {index}")
        _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, entry)

    call = await _call(
        container,
        Actor(owner, frozenset({"journal:write"})),
        "set_memory_settings",
        {"expected_version": 1, "journal": False},
    )

    assert not call.is_error
    data = _structured(call.structured_content)
    assert data["status"] == "needs_confirmation"
    assert data["turning_off"] == [{"domain": "journal", "documents": None}]
    assert call.content[0].text == (
        "Turning off journal removes all journal entry facts from memory. "
        "Turning it on again costs a new import. Call again with confirm true."
    )
    row = _settings_row(factory, owner)
    assert row is not None and (row.journal, row.version) == (True, 1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_count_is_given_only_for_the_domains_the_caller_can_read() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True, contacts=True)
    _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, _journal(factory, owner, "Dag"))
    _memory_row(factory, owner, MemoryKind.CONTACT, _contact(factory, owner, "Sara"))
    scopes = frozenset({"contacts:read", "journal:write", "contacts:write"})

    call = await _call(
        container,
        Actor(owner, scopes),
        "set_memory_settings",
        {"expected_version": 1, "journal": False, "contacts": False},
    )

    data = _structured(call.structured_content)
    assert data["status"] == "needs_confirmation"
    assert data["turning_off"] == [
        {"domain": "journal", "documents": None},
        {"domain": "contacts", "documents": 1},
    ]
    assert call.content[0].text == (
        "Turning off journal and contacts removes all journal entry facts and 1 contact "
        "from memory. Turning them on again costs a new import. Call again with confirm true."
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_repeating_a_successful_change_with_the_same_version_is_unchanged() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True, tasks=True)
    _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, _journal(factory, owner, "Dag"))
    actor = Actor(owner, READ_AND_WRITE)
    arguments: dict[str, Any] = {"expected_version": 1, "journal": False, "confirm": True}

    first = await _call(container, actor, "set_memory_settings", arguments)
    again = await _call(container, actor, "set_memory_settings", arguments)

    assert _structured(first.structured_content)["status"] == "updated"
    assert not again.is_error
    data = _structured(again.structured_content)
    assert data["status"] == "unchanged"
    assert data["turning_off"] == []
    assert data["settings"] == {
        "journal": False,
        "contacts": False,
        "projects": False,
        "tasks": True,
        "paused": False,
        "version": 2,
    }
    assert again.content[0].text.startswith("Memory settings were already like that")
    row = _settings_row(factory, owner)
    assert row is not None and (row.journal, row.tasks, row.version) == (False, True, 2)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_different_change_with_an_old_version_is_still_a_conflict() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True)
    actor = Actor(owner, WRITE_ALL)

    first = await _call(
        container, actor, "set_memory_settings", {"expected_version": 1, "paused": True}
    )
    stale = await _call(
        container, actor, "set_memory_settings", {"expected_version": 1, "paused": False}
    )

    assert _structured(first.structured_content)["status"] == "updated"
    assert stale.is_error
    data = _structured(stale.structured_content)
    assert data["code"] == "conflict"
    assert data["reason"] == "stale_version"
    row = _settings_row(factory, owner)
    assert row is not None and (row.paused, row.version) == (True, 2)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_turning_off_a_domain_that_is_already_off_needs_no_confirm() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True)

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "set_memory_settings",
        {"expected_version": 1, "tasks": False},
    )

    data = _structured(call.structured_content)
    assert data["status"] == "unchanged"
    row = _settings_row(factory, owner)
    assert row is not None and row.version == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pausing_and_resuming_need_no_confirm_and_count_as_versions() -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True)

    paused = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "set_memory_settings",
        {"expected_version": 1, "paused": True},
    )
    resumed = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "set_memory_settings",
        {"expected_version": 2, "paused": False},
    )

    assert _structured(paused.structured_content)["status"] == "updated"
    assert _structured(resumed.structured_content)["settings"]["version"] == 3
    row = _settings_row(factory, owner)
    assert row is not None and (row.paused, row.version) == (False, 3)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("stored_version, sent", [(1, 0), (1, 2), (3, 1)])
async def test_a_wrong_expected_version_is_a_stale_conflict_and_changes_nothing(
    stored_version: int, sent: int
) -> None:
    factory, container, owner = _setup()
    _settings(factory, owner, journal=True)
    with factory.begin() as session:
        row = session.get(MemorySettingsRow, owner)
        assert row is not None
        row.version = stored_version

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "set_memory_settings",
        {"expected_version": sent, "journal": False, "confirm": True},
    )

    assert call.is_error
    data = _structured(call.structured_content)
    assert data["code"] == "conflict"
    assert data["reason"] == "stale_version"
    row = _settings_row(factory, owner)
    assert row is not None and (row.journal, row.version) == (True, stored_version)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creating_the_row_with_a_nonzero_expected_version_conflicts() -> None:
    factory, container, _owner = _setup()
    owner = _owner_without_settings(factory)

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "set_memory_settings",
        {"expected_version": 1, "journal": False},
    )

    assert _structured(call.structured_content)["code"] == "conflict"
    assert _settings_row(factory, owner) is None


# --- exclude_from_memory -----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "kind, scope",
    [
        (MemoryKind.JOURNAL_ENTRY, "journal:write"),
        (MemoryKind.CONTACT, "contacts:write"),
        (MemoryKind.PROJECT, "projects:write"),
        (MemoryKind.TASK, "tasks:write"),
    ],
)
async def test_exclude_needs_the_kinds_write_scope(kind: MemoryKind, scope: str) -> None:
    factory, container, owner = _setup()
    record = _record_of(factory, owner, kind)

    refused = await _call(
        container,
        Actor(owner, (WRITE_ALL - {scope}) | READ_ALL),
        "exclude_from_memory",
        {"kind": kind.value, "id": str(record)},
    )

    assert _is_forbidden(refused)
    assert _source_rows(factory, owner) == []


def _record_of(factory: sessionmaker[Session], owner: UUID, kind: MemoryKind) -> UUID:
    if kind is MemoryKind.JOURNAL_ENTRY:
        return _journal(factory, owner, "Morgonmöte")
    if kind is MemoryKind.CONTACT:
        return _contact(factory, owner, "Sara Lind")
    if kind is MemoryKind.PROJECT:
        return _project(factory, owner, "Bygge")
    return _task(factory, owner, "Ring Sara", completed_at=None)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", list(MemoryKind))
async def test_excluding_a_record_without_a_row_creates_a_removed_marker(
    kind: MemoryKind,
) -> None:
    factory, container, owner = _setup()
    record = _record_of(factory, owner, kind)

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "exclude_from_memory",
        {"kind": kind.value, "id": str(record)},
    )

    assert not call.is_error
    data = _structured(call.structured_content)
    assert data == {"kind": kind.value, "id": str(record), "excluded": True, "changed": True}
    rows = _source_rows(factory, owner)
    assert len(rows) == 1
    row = rows[0]
    assert (row.source_kind, row.source_id, row.excluded) == (kind.value, record, True)
    assert (row.status, row.failure_category, row.retained_at) == ("parked", "removed", None)
    assert row.doc_key.startswith("d1_") and len(row.doc_key) == 67
    assert "is now kept out of memory" in call.content[0].text
    assert str(record) not in call.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_excluding_an_existing_row_flips_the_flag_and_including_reverses_it() -> None:
    factory, container, owner = _setup()
    contact = _contact(factory, owner, "Sara Lind")
    doc_key = _memory_row(factory, owner, MemoryKind.CONTACT, contact)
    actor = Actor(owner, WRITE_ALL)
    arguments: dict[str, Any] = {"kind": "contact", "id": str(contact)}

    excluded = await _call(container, actor, "exclude_from_memory", arguments)
    again = await _call(container, actor, "exclude_from_memory", arguments)
    included = await _call(
        container, actor, "exclude_from_memory", {**arguments, "excluded": False}
    )

    assert _structured(excluded.structured_content)["changed"] is True
    assert _structured(again.structured_content)["changed"] is False
    assert _structured(included.structured_content) == {
        "kind": "contact",
        "id": str(contact),
        "excluded": False,
        "changed": True,
    }
    assert "Sara Lind is back in memory" in included.content[0].text
    rows = _source_rows(factory, owner)
    assert len(rows) == 1
    assert (rows[0].doc_key, rows[0].excluded, rows[0].status) == (doc_key, False, "retained")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_including_a_never_synced_marker_without_a_key_removes_the_marker() -> None:
    factory, container, owner = _setup()
    contact = _contact(factory, owner, "Sara Lind")
    actor = Actor(owner, WRITE_ALL)
    arguments: dict[str, Any] = {"kind": "contact", "id": str(contact)}

    excluded = await _call(container, actor, "exclude_from_memory", arguments)
    assert _structured(excluded.structured_content)["changed"] is True
    marker = _source_rows(factory, owner)
    assert len(marker) == 1 and marker[0].doc_key.startswith("d1_")

    included = await _call(
        container, actor, "exclude_from_memory", {**arguments, "excluded": False}
    )

    assert not included.is_error
    assert _structured(included.structured_content) == {
        "kind": "contact",
        "id": str(contact),
        "excluded": False,
        "changed": True,
    }
    assert _source_rows(factory, owner) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_including_a_record_that_has_no_row_creates_nothing() -> None:
    factory, container, owner = _setup()
    task = _task(factory, owner, "Ring Sara", completed_at=None)

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "exclude_from_memory",
        {"kind": "task", "id": str(task), "excluded": False},
    )

    assert not call.is_error
    assert _structured(call.structured_content)["changed"] is False
    assert _source_rows(factory, owner) == []


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", list(MemoryKind))
async def test_another_owners_record_is_not_found(kind: MemoryKind) -> None:
    factory, container, owner = _setup()
    stranger = container.auth.provision_user("stranger", "Stranger")
    record = _record_of(factory, stranger, kind)

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "exclude_from_memory",
        {"kind": kind.value, "id": str(record)},
    )

    assert call.is_error
    assert _structured(call.structured_content)["code"] == "not_found"
    assert _source_rows(factory, owner) == []
    assert _source_rows(factory, stranger) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_missing_record_is_not_found() -> None:
    _factory, container, owner = _setup()

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "exclude_from_memory",
        {"kind": "project", "id": str(new_uuid7())},
    )

    assert _structured(call.structured_content)["code"] == "not_found"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("kind", list(MemoryKind))
async def test_a_trashed_record_is_not_found(kind: MemoryKind) -> None:
    factory, container, owner = _setup()
    record = _record_of(factory, owner, kind)
    _trash(factory, kind, record)

    call = await _call(
        container,
        Actor(owner, WRITE_ALL),
        "exclude_from_memory",
        {"kind": kind.value, "id": str(record)},
    )

    assert call.is_error
    assert _structured(call.structured_content)["code"] == "not_found"
    assert _source_rows(factory, owner) == []


def _trash(factory: sessionmaker[Session], kind: MemoryKind, record: UUID) -> None:
    from datetime import UTC, datetime

    from sidekick.shared.persistence.models import (
        ContactRow,
        JournalEntryRow,
        ProjectRow,
        TaskRow,
    )

    model = {
        MemoryKind.JOURNAL_ENTRY: JournalEntryRow,
        MemoryKind.CONTACT: ContactRow,
        MemoryKind.PROJECT: ProjectRow,
        MemoryKind.TASK: TaskRow,
    }[kind]
    with factory.begin() as session:
        row = session.get(model, record)
        assert row is not None
        row.trashed_at = datetime(2026, 10, 21, tzinfo=UTC)

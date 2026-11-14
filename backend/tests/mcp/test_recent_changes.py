"""list_recent_changes: the owner's newest changes over MCP, bounded, scope-aware, from records.

The tool sits on the audit trail and reads each title, version and trash state from the record
itself. Trashed records stay visible as "trashed". A kind without its read scope is left out
silently, and the journal source text never reaches the answer.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client, FastMCP
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.journal.domain.source import SourceType
from sidekick.lifecycle import RecordKind
from sidekick.lifecycle.domain import RecentChange
from sidekick.mcp.changes import _text as change_text
from sidekick.mcp.changes import register_change_tools
from sidekick.mcp.tool_context import ToolContext
from sidekick.references.domain import ExternalReferenceDetails
from sidekick.shared.types import Actor
from sidekick.shopping.application.schemas import BatchItem
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.application import UpdateTaskCommand
from tests.db import database_factory
from tests.mcp.harness import ActorSwitch
from tests.support.settings import make_settings

JOURNAL_TITLE = "Dagbok för ändringstestet"
SOURCE_TEXT = "Källtext-som-aldrig-ska-synas-i-svaret"
NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
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


def _seed(container: Container, actor: Actor) -> dict[str, UUID]:
    """Seven owner changes, in this order: task created and updated, contact created, journal
    entry created, shopping list created, shopping item added, contact trashed."""

    task = container.tasks.create(actor, title="Första uppgiften", idempotency_key="recent-task")
    container.tasks.update(
        actor,
        task.id,
        version=task.version,
        idempotency_key="recent-task-update",
        command=UpdateTaskCommand(title="Uppgift ändrad"),
    )
    contact = container.contacts.create(
        actor, CreateContactCommand(display_name="Sara Test"), "recent-contact"
    )
    source = container.journal_capture.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=date(2026, 10, 29),
        occurred_at=None,
        source_recorded_at=None,
        raw_text=SOURCE_TEXT,
        language="sv",
        replaces_source_id=None,
        idempotency_key="recent-source",
    )
    entry = container.journal_capture.create_manual_entry(
        actor,
        source_id=source.id,
        title=JOURNAL_TITLE,
        summary=None,
        key_points=(),
        idempotency_key="recent-entry",
    )
    shopping_list = container.shopping.create_list(
        actor, "Veckohandel", idempotency_key="recent-list"
    ).shopping_list
    added = container.shopping.add_items(
        actor,
        shopping_list.id,
        [BatchItem(name="Mjölk", client_ref="milk")],
        idempotency_key="recent-items",
    )
    item = added.items[0].item
    container.lifecycle.trash(
        actor,
        RecordKind.CONTACT,
        contact.id,
        version=contact.version,
        idempotency_key="recent-trash",
    )
    return {"task": task.id, "contact": contact.id, "entry": entry.id, "item": item.id}


def _build(username: str) -> tuple[ActorSwitch, FastMCP, UUID, dict[str, UUID]]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(username, "Change Owner")
    actor = Actor(owner, FULL)
    ids = _seed(container, actor)
    switch = ActorSwitch(actor)
    mcp = FastMCP("recent-changes-test")
    register_change_tools(mcp, ToolContext(container, switch, lambda _name: lambda fn: fn))
    return switch, mcp, owner, ids


async def _call(client: Client[Any], arguments: dict[str, Any]) -> Any:
    return await client.call_tool("list_recent_changes", arguments, raise_on_error=False)


def _changes(call_result: Any) -> list[dict[str, Any]]:
    assert not call_result.is_error, call_result.content
    assert call_result.structured_content is not None
    return list(call_result.structured_content["changes"])


def test_first_line_uses_spoken_kind_words_and_one_line_titles() -> None:
    """Pure check of the text builder: no database, so it runs without fixtures."""

    link = RecentChange(
        kind="contact_task_link",
        id=uuid4(),
        title="Lina\nLänk ↔ Länkad uppgift",
        version=2,
        action="created",
        state="active",
        occurred_at=datetime(2026, 10, 30, tzinfo=UTC),
        related_id=uuid4(),
    )
    shopping = RecentChange(
        kind="shopping_item",
        id=uuid4(),
        title="Mjölk",
        version=1,
        action="created",
        state="active",
        occurred_at=datetime(2026, 10, 30, tzinfo=UTC),
    )

    text = change_text([link, shopping], now=NOW, zone=UTC)
    first_line, *rest = text.splitlines()
    assert first_line == (
        "Your last 2 changes: created link between contact and task "
        '"Lina Länk ↔ Länkad uppgift" today, created shopping item "Mjölk" today.'
    )
    assert "contact_task_link" not in first_line
    assert str(link.id) not in first_line
    assert any("contact_task_link" in line for line in rest)


def test_first_line_names_at_most_three_changes_then_counts_the_rest() -> None:
    def change(number: int) -> RecentChange:
        return RecentChange(
            kind="task",
            id=uuid4(),
            title=f"Uppgift {number}",
            version=number,
            action="updated",
            state="active",
            occurred_at=datetime(2026, 10, 30, tzinfo=UTC),
        )

    five = change_text([change(number) for number in range(1, 6)], now=NOW, zone=UTC)
    first_line, *rest = five.splitlines()
    assert first_line == (
        'Your last 5 changes: updated task "Uppgift 1" today, updated task "Uppgift 2" today, '
        'updated task "Uppgift 3" today and 2 more.'
    )
    assert len(rest) == 5
    three = change_text([change(number) for number in range(1, 4)], now=NOW, zone=UTC)
    first_three = three.splitlines()[0]
    assert "more" not in first_three
    assert first_three.count("updated task") == 3


def test_first_line_says_today_yesterday_or_the_day_on_the_owner_calendar() -> None:
    """Pure check: 31 October 20:00 UTC is 31 October in Stockholm, so it reads "yesterday"."""

    def change(occurred_at: datetime) -> RecentChange:
        return RecentChange(
            kind="task",
            id=uuid4(),
            title="Uppgift",
            version=1,
            action="updated",
            state="active",
            occurred_at=occurred_at,
        )

    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    changes = [
        change(datetime(2026, 11, 1, 9, tzinfo=UTC)),
        change(datetime(2026, 10, 31, 20, tzinfo=UTC)),
        change(datetime(2026, 10, 2, 9, tzinfo=UTC)),
    ]
    first_line = change_text(changes, now=now, zone=ZoneInfo("Europe/Stockholm")).splitlines()[0]
    assert first_line == (
        'Your last 3 changes: updated task "Uppgift" today, updated task "Uppgift" yesterday, '
        'updated task "Uppgift" 2 October.'
    )


def test_purchase_and_put_back_are_spoken_with_their_own_verbs_and_name_the_undo() -> None:
    bought = RecentChange(
        kind="shopping_item",
        id=uuid4(),
        title="Mjölk",
        version=3,
        action="purchased",
        state="active",
        occurred_at=datetime(2026, 10, 30, tzinfo=UTC),
        undo_tool="set_shopping_item_purchased",
    )
    put_back = RecentChange(
        kind="shopping_item",
        id=uuid4(),
        title="Smör",
        version=4,
        action="reopened",
        state="active",
        occurred_at=datetime(2026, 10, 30, tzinfo=UTC),
        undo_tool="set_shopping_item_purchased",
    )

    text = change_text([bought, put_back], now=NOW, zone=UTC)
    first_line, bought_row, put_back_row = text.splitlines()
    assert first_line == (
        'Your last 2 changes: bought shopping item "Mjölk" today, '
        'reopened shopping item "Smör" today.'
    )
    assert "version 3" in bought_row
    assert bought_row.endswith("undo with set_shopping_item_purchased purchased=false")
    assert "version 4" in put_back_row
    assert put_back_row.endswith("undo with set_shopping_item_purchased purchased=true")
    assert "move_to_trash" not in bought_row + put_back_row


def _text(call_result: Any) -> str:
    block = call_result.content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.mark.asyncio
async def test_newest_first_with_default_limit_of_twenty() -> None:
    _switch, mcp, _owner, _ids = _build("recent-order-owner")
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert tools["list_recent_changes"].parameters["properties"]["limit"]["default"] == 20
    async with Client(mcp) as client:
        changes = _changes(await _call(client, {}))
    # The contact's created event is older than its trashed event, so only the trashed one shows.
    assert [(change["kind"], change["action"]) for change in changes] == [
        ("contact", "trashed"),
        ("shopping_item", "created"),
        ("shopping_list", "created"),
        ("journal_entry", "created"),
        ("task", "updated"),
    ]


@pytest.mark.asyncio
async def test_limit_is_bounded_between_one_and_twenty() -> None:
    _switch, mcp, _owner, _ids = _build("recent-limit-owner")
    async with Client(mcp) as client:
        two = _changes(await _call(client, {"limit": 2}))
        everything = _changes(await _call(client, {"limit": 20}))
        too_many = await _call(client, {"limit": 21})
        too_few = await _call(client, {"limit": 0})
    assert len(two) == 2
    # Seven audit events over five records: each record is listed once, with its newest event.
    assert len(everything) == 5
    assert too_many.is_error
    assert too_few.is_error


@pytest.mark.asyncio
async def test_kinds_without_read_scope_are_left_out_silently() -> None:
    switch, mcp, owner, _ids = _build("recent-scope-owner")
    async with Client(mcp) as client:
        switch.use(Actor(owner, frozenset({"tasks:read"})))
        tasks_only = _changes(await _call(client, {"limit": 20}))
        switch.use(Actor(owner, frozenset({"contacts:read"})))
        contacts_only = _changes(await _call(client, {"limit": 20}))
        switch.use(Actor(owner, frozenset()))
        nothing = _changes(await _call(client, {"limit": 20}))
    assert [change["kind"] for change in tasks_only] == ["task"]
    assert [change["action"] for change in tasks_only] == ["updated"]
    assert [change["kind"] for change in contacts_only] == ["contact"]
    assert nothing == []


@pytest.mark.asyncio
async def test_titles_come_from_the_record_and_trashed_records_show_trashed() -> None:
    _switch, mcp, _owner, ids = _build("recent-title-owner")
    async with Client(mcp) as client:
        call_result = await _call(client, {"limit": 20})
    changes = _changes(call_result)
    by_id = {change["id"]: change for change in changes}
    # Each task event carries the record's current title, not a title stored at the time.
    task_rows = [change for change in changes if change["kind"] == "task"]
    assert [change["title"] for change in task_rows] == ["Uppgift ändrad"]
    assert [change["version"] for change in task_rows] == [2]
    assert by_id[str(ids["entry"])]["title"] == JOURNAL_TITLE
    assert by_id[str(ids["item"])]["title"] == "Mjölk"
    # The trashed contact reads as trashed, on its newest event (the trash), not the created one.
    contact_rows = [change for change in changes if change["kind"] == "contact"]
    assert [change["state"] for change in contact_rows] == ["trashed"]
    assert contact_rows[0]["action"] == "trashed"
    assert all(change["title"] == "Sara Test" for change in contact_rows)
    # Answer text: the first line is speakable without ids; ids and versions follow on later lines.
    text = _text(call_result)
    first_line, *rest = text.splitlines()
    assert str(ids["task"]) not in first_line
    assert 'trashed contact "Sara Test"' in first_line
    assert any(str(ids["task"]) in line for line in rest)
    assert SOURCE_TEXT not in text


@pytest.mark.asyncio
async def test_another_owners_changes_are_never_listed() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("recent-isolation-owner", "Change Owner")
    other = container.auth.provision_user("recent-isolation-other", "Other Owner")
    actor = Actor(owner, FULL)
    other_actor = Actor(other, FULL)
    _seed(container, actor)
    foreign_task = container.tasks.create(
        other_actor, title="Främmande uppgift", idempotency_key="foreign-task"
    )
    foreign_contact = container.contacts.create(
        other_actor, CreateContactCommand(display_name="Främmande kontakt"), "foreign-contact"
    )
    switch = ActorSwitch(actor)
    mcp = FastMCP("recent-isolation-test")
    register_change_tools(mcp, ToolContext(container, switch, lambda _name: lambda fn: fn))
    async with Client(mcp) as client:
        call_result = await _call(client, {"limit": 20})
    changes = _changes(call_result)
    ids = {change["id"] for change in changes}
    assert str(foreign_task.id) not in ids
    assert str(foreign_contact.id) not in ids
    assert len(changes) == 5
    assert "Främmande" not in _text(call_result)


@pytest.mark.asyncio
async def test_repeated_edits_of_one_record_are_listed_once_with_the_newest_event() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("recent-dedup-owner", "Change Owner")
    actor = Actor(owner, FULL)
    contact = container.contacts.create(
        actor, CreateContactCommand(display_name="Äldst i listan"), "dedup-contact"
    )
    task = container.tasks.create(actor, title="Redigeras tre gånger", idempotency_key="dedup-task")
    for number in range(3):
        version = container.tasks.get(actor, task.id).version
        container.tasks.update(
            actor,
            task.id,
            version=version,
            idempotency_key=f"dedup-update-{number}",
            command=UpdateTaskCommand(title=f"Redigering {number}"),
        )
    switch = ActorSwitch(actor)
    mcp = FastMCP("recent-dedup-test")
    register_change_tools(mcp, ToolContext(container, switch, lambda _name: lambda fn: fn))
    async with Client(mcp) as client:
        # Without dedup, the three task edits would fill this limit of two and hide the contact.
        changes = _changes(await _call(client, {"limit": 2}))
    assert [(change["kind"], change["id"]) for change in changes] == [
        ("task", str(task.id)),
        ("contact", str(contact.id)),
    ]
    assert changes[0]["action"] == "updated"
    assert changes[0]["title"] == "Redigering 2"
    assert changes[0]["version"] == 4


@pytest.mark.asyncio
async def test_journal_source_text_never_appears_in_the_answer() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("recent-source-owner", "Change Owner")
    actor = Actor(owner, FULL)
    _seed(container, actor)
    switch = ActorSwitch(actor)
    mcp = FastMCP("recent-source-test")
    register_change_tools(mcp, ToolContext(container, switch, lambda _name: lambda fn: fn))
    async with Client(mcp) as client:
        call_result = await _call(client, {"limit": 20})
    assert SOURCE_TEXT not in _text(call_result)
    assert SOURCE_TEXT not in str(call_result.structured_content)
    # Only three changes are spoken on the first line; the full list is in the structured content.
    assert JOURNAL_TITLE in str(call_result.structured_content)


@pytest.mark.asyncio
async def test_alias_and_unlink_changes_are_named_and_unlinks_keep_their_text() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("recent-link-owner", "Change Owner")
    actor = Actor(owner, FULL)
    contact = container.contacts.create(
        actor, CreateContactCommand(display_name="Kopplad Kontakt"), "link-contact"
    )
    contact = container.contacts.add_alias(
        actor, contact.id, "Shell", expected_version=contact.version, idempotency_key="link-alias"
    )
    alias_id = contact.aliases[-1].id
    task = container.tasks.create(actor, title="Offertuppgift", idempotency_key="link-task")
    container.contact_relations.link_task(actor, contact.id, task.id, "link-task-link")
    container.contact_relations.unlink_task(actor, contact.id, task.id, "link-task-unlink")
    linked = container.references.link(
        actor,
        task.id,
        ExternalReferenceDetails(
            kind="mail",
            provider="google_gmail",
            account_ref="link-account",
            external_id="link-message",
            title="Mejl om offerten",
        ),
        source="manual",
        idempotency_key="link-reference",
    )
    reference_id = linked.reference.id
    # A second task shares the reference, so removing it from the first task keeps the row.
    other_task = container.tasks.create(
        actor, title="Andra uppgiften", idempotency_key="link-task-2"
    )
    shared = container.references.link(
        actor,
        other_task.id,
        ExternalReferenceDetails(
            kind="mail",
            provider="google_gmail",
            account_ref="link-account",
            external_id="link-message",
            title="Mejl om offerten",
        ),
        source="manual",
        idempotency_key="link-reference-2",
    )
    assert shared.reference.id == reference_id
    container.references.unlink(actor, task.id, reference_id, idempotency_key="link-ref-unlink")
    switch = ActorSwitch(actor)
    mcp = FastMCP("recent-link-test")
    register_change_tools(mcp, ToolContext(container, switch, lambda _name: lambda fn: fn))
    async with Client(mcp) as client:
        call_result = await _call(client, {"limit": 20})
        # Removing the last relation also removes the pointer row, so its unlink is skipped.
        container.references.unlink(
            actor, other_task.id, reference_id, idempotency_key="link-ref-unlink-2"
        )
        after_last = _changes(await _call(client, {"limit": 20}))
    assert "external_reference" not in [change["kind"] for change in after_last]
    changes = _changes(call_result)
    by_kind = {change["kind"]: change for change in changes}
    # Alias added: named by alias value and contact; the version is the contact's version.
    assert by_kind["contact_alias"]["id"] == str(alias_id)
    assert by_kind["contact_alias"]["title"] == "Alias 'Shell' för Kopplad Kontakt"
    assert by_kind["contact_alias"]["action"] == "created"
    assert by_kind["contact_alias"]["version"] == contact.version
    # Unlink: names only the contact or the reference, never the other party.
    assert by_kind["contact_link"]["id"] == str(contact.id)
    assert by_kind["contact_link"]["title"] == "Kontakt Kopplad Kontakt: koppling borttagen"
    assert by_kind["contact_link"]["action"] == "updated"
    assert by_kind["external_reference"]["id"] == str(reference_id)
    assert by_kind["external_reference"]["title"] == (
        "Referens 'Mejl om offerten': koppling borttagen"
    )
    # Each unlink keeps the unlink kind and text; its link has its own kind (see the linked test).
    assert [change["kind"] for change in changes].count("contact_link") == 1
    assert by_kind["contact_link"]["related_id"] == str(task.id)
    assert by_kind["contact_link"]["undo_tool"] is None


@pytest.mark.asyncio
async def test_linked_changes_name_both_sides_and_send_the_undo_to_the_app() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("recent-linked-owner", "Change Owner")
    actor = Actor(owner, FULL)
    domain = container.contexts.create_domain(
        actor, name="Länkdomän", description=None, idempotency_key="linked-domain"
    )
    project = container.projects.create(
        actor, title="Länkprojekt", domain_id=domain.id, idempotency_key="linked-project"
    )
    contact = container.contacts.create(
        actor, CreateContactCommand(display_name="Lina Länk"), "linked-contact"
    )
    task = container.tasks.create(actor, title="Länkad uppgift", idempotency_key="linked-task")
    container.contact_relations.link_task(actor, contact.id, task.id, "linked-task-link")
    container.contact_relations.link_project(actor, contact.id, project.id, "linked-project-link")
    linked = container.references.link(
        actor,
        task.id,
        ExternalReferenceDetails(
            kind="mail",
            provider="google_gmail",
            account_ref="linked-account",
            external_id="linked-message",
            title="Mejl om länken",
        ),
        source="manual",
        idempotency_key="linked-reference",
    )
    reference_id = linked.reference.id
    switch = ActorSwitch(actor)
    mcp = FastMCP("recent-linked-test")
    register_change_tools(mcp, ToolContext(container, switch, lambda _name: lambda fn: fn))
    async with Client(mcp) as client:
        call_result = await _call(client, {"limit": 20})
    changes = _changes(call_result)
    by_kind = {change["kind"]: change for change in changes}
    # A task link: the contact is the record, the task is the related id.
    assert by_kind["contact_task_link"]["id"] == str(contact.id)
    assert by_kind["contact_task_link"]["related_id"] == str(task.id)
    assert by_kind["contact_task_link"]["title"] == "Lina Länk ↔ Länkad uppgift"
    assert by_kind["contact_task_link"]["action"] == "created"
    assert by_kind["contact_task_link"]["undo_tool"] is None
    # A project link names the project.
    assert by_kind["contact_project_link"]["id"] == str(contact.id)
    assert by_kind["contact_project_link"]["related_id"] == str(project.id)
    assert by_kind["contact_project_link"]["title"] == "Lina Länk ↔ Länkprojekt"
    assert by_kind["contact_project_link"]["undo_tool"] is None
    # A reference link: the reference is the record, the task is the related id.
    assert by_kind["external_reference_link"]["id"] == str(reference_id)
    assert by_kind["external_reference_link"]["related_id"] == str(task.id)
    assert (
        by_kind["external_reference_link"]["title"] == "Referens 'Mejl om länken' ↔ Länkad uppgift"
    )
    assert by_kind["external_reference_link"]["undo_tool"] is None
    text = _text(call_result)
    # The unlink tools are app-only: no row and no field names one, the text sends the owner there.
    assert "unlink" not in text
    assert "unlink" not in str(call_result.structured_content)
    assert text.count("undo in the app") == 3
    assert "linked-message" not in text


@pytest.mark.asyncio
async def test_link_changes_need_the_read_scope_of_both_sides() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("recent-linked-scope-owner", "Change Owner")
    actor = Actor(owner, FULL)
    domain = container.contexts.create_domain(
        actor, name="Scopedomän", description=None, idempotency_key="scope-domain"
    )
    project = container.projects.create(
        actor, title="Scopeprojekt", domain_id=domain.id, idempotency_key="scope-project"
    )
    contact = container.contacts.create(
        actor, CreateContactCommand(display_name="Scope Kontakt"), "scope-contact"
    )
    task = container.tasks.create(actor, title="Scopeuppgift", idempotency_key="scope-task")
    container.contact_relations.link_task(actor, contact.id, task.id, "scope-task-link")
    container.contact_relations.link_project(actor, contact.id, project.id, "scope-project-link")
    switch = ActorSwitch(actor)
    mcp = FastMCP("recent-linked-scope-test")
    register_change_tools(mcp, ToolContext(container, switch, lambda _name: lambda fn: fn))
    async with Client(mcp) as client:
        switch.use(Actor(owner, frozenset({"contacts:read"})))
        contacts_only = _changes(await _call(client, {"limit": 20}))
        switch.use(Actor(owner, frozenset({"contacts:read", "tasks:read"})))
        with_tasks = _changes(await _call(client, {"limit": 20}))
    # Without the task read, the task side is never named; without the project read, neither is
    # the project. The contact read alone shows no link at all (the contact's own creation stays).
    link_kinds = ("contact_task_link", "contact_project_link")
    assert [change["kind"] for change in contacts_only if change["kind"] in link_kinds] == []
    assert [change["kind"] for change in with_tasks if change["kind"] in link_kinds] == [
        "contact_task_link"
    ]
    task_link = next(change for change in with_tasks if change["kind"] == "contact_task_link")
    assert task_link["title"] == "Scope Kontakt ↔ Scopeuppgift"


@pytest.mark.asyncio
async def test_alias_removal_names_the_contact_and_legacy_rows_keep_their_text() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("recent-alias-owner", "Change Owner")
    actor = Actor(owner, FULL)
    contact = container.contacts.create(
        actor, CreateContactCommand(display_name="Alias Kontakt"), "alias-removal-contact"
    )
    contact = container.contacts.add_alias(
        actor,
        contact.id,
        "Gamla namnet",
        expected_version=contact.version,
        idempotency_key="alias-removal-add",
    )
    alias_id = contact.aliases[-1].id
    # Rows written before related ids existed: an unlink without one, and an alias removal without
    # one. The first keeps its old text; the second names no contact, so it is left out.
    with container.session_factory() as session:
        SqlAlchemyStore.append_audit(
            session,
            actor_id=owner,
            event="contact.task_unlinked",
            outcome="success",
            target_type="task_contact",
            target_id=contact.id,
        )
        SqlAlchemyStore.append_audit(
            session,
            actor_id=owner,
            event="contact.alias_removed",
            outcome="success",
            target_type="contact_alias",
            target_id=uuid4(),
        )
        session.commit()
    container.contacts.remove_alias(
        actor,
        contact.id,
        alias_id,
        expected_version=contact.version,
        idempotency_key="alias-removal-remove",
    )
    switch = ActorSwitch(actor)
    mcp = FastMCP("recent-alias-test")
    register_change_tools(mcp, ToolContext(container, switch, lambda _name: lambda fn: fn))
    async with Client(mcp) as client:
        call_result = await _call(client, {"limit": 20})
    changes = _changes(call_result)
    # Only the new removal is listed; the legacy alias removal (no related id) is left out.
    assert [change["id"] for change in changes if change["kind"] == "contact_alias_removed"] == [
        str(alias_id)
    ]
    legacy = next(change for change in changes if change["kind"] == "contact_link")
    assert legacy["title"] == "Kontakt Alias Kontakt: koppling borttagen"
    assert legacy["related_id"] is None
    assert legacy["undo_tool"] is None
    # The service's own removal row carries the contact as the related id: named by the contact.
    removal = next(change for change in changes if change["kind"] == "contact_alias_removed")
    assert removal["id"] == str(alias_id)
    assert removal["related_id"] == str(contact.id)
    assert removal["title"] == "Alias borttaget för Alias Kontakt"
    assert removal["action"] == "updated"
    assert removal["undo_tool"] is None
    assert "Gamla namnet" not in _text(call_result)


@pytest.mark.asyncio
async def test_purchase_and_put_back_show_with_the_version_the_undo_needs() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("recent-buy-owner", "Change Owner")
    actor = Actor(owner, FULL)
    shopping_list = container.shopping.create_list(
        actor, "Handla", idempotency_key="buy-list"
    ).shopping_list
    added = container.shopping.add_items(
        actor,
        shopping_list.id,
        [BatchItem(name="Mjölk", client_ref="milk"), BatchItem(name="Smör", client_ref="butter")],
        idempotency_key="buy-items",
    )
    milk = added.items[0].item
    butter = added.items[1].item
    bought = container.shopping.set_purchased(
        actor,
        milk.id,
        purchased=True,
        version=milk.version,
        idempotency_key="buy-milk-1",
    )
    container.shopping.set_purchased(
        actor,
        butter.id,
        purchased=True,
        version=butter.version,
        idempotency_key="butter-buy-2",
    )
    container.shopping.set_purchased(
        actor,
        butter.id,
        purchased=False,
        version=butter.version + 1,
        idempotency_key="butter-back-3",
    )
    switch = ActorSwitch(actor)
    mcp = FastMCP("recent-buy-test")
    register_change_tools(mcp, ToolContext(container, switch, lambda _name: lambda fn: fn))
    async with Client(mcp) as client:
        call_result = await _call(client, {"limit": 20})
        # The undo the row names must work at the version the row shows.
        changes = _changes(call_result)
        milk_row = next(change for change in changes if change["id"] == str(milk.id))
        container.shopping.set_purchased(
            actor,
            UUID(milk_row["id"]),
            purchased=False,
            version=milk_row["version"],
            idempotency_key="buy-milk-undo",
        )
        after_undo = _changes(await _call(client, {"limit": 20}))
    by_id = {change["id"]: change for change in changes}
    assert [change["kind"] for change in changes[:2]] == ["shopping_item", "shopping_item"]
    # Newest first: butter was put back last, and its row shows its newest event only.
    assert changes[0]["id"] == str(butter.id)
    assert changes[0]["action"] == "reopened"
    assert changes[0]["version"] == butter.version + 2
    assert changes[0]["undo_tool"] == "set_shopping_item_purchased"
    assert by_id[str(milk.id)]["action"] == "purchased"
    assert by_id[str(milk.id)]["version"] == bought.item.version
    assert by_id[str(milk.id)]["undo_tool"] == "set_shopping_item_purchased"
    text = _text(call_result)
    first_line = text.splitlines()[0]
    assert 'reopened shopping item "Smör"' in first_line
    assert 'bought shopping item "Mjölk"' in first_line
    assert "move_to_trash" not in text
    assert "unlink" not in text
    # After the undo the item reads as put back, one version later.
    undone = next(change for change in after_undo if change["id"] == str(milk.id))
    assert undone["action"] == "reopened"
    assert undone["version"] == milk_row["version"] + 1


@pytest.mark.asyncio
async def test_change_titles_follow_the_app_language_when_the_feed_is_read() -> None:
    english = make_settings().model_copy(update={"mcp_app_locale": "en"})
    container = create_container(english, database_factory())
    owner = container.auth.provision_user("recent-locale-owner", "Change Owner")
    actor = Actor(owner, FULL)
    contact = container.contacts.create(
        actor, CreateContactCommand(display_name="Anna Berg"), "locale-contact"
    )
    contact = container.contacts.add_alias(
        actor, contact.id, "Shell", expected_version=contact.version, idempotency_key="locale-alias"
    )
    alias_id = contact.aliases[-1].id
    container.contacts.remove_alias(
        actor,
        contact.id,
        alias_id,
        expected_version=contact.version,
        idempotency_key="locale-alias-remove",
    )
    task = container.tasks.create(actor, title="Offertuppgift", idempotency_key="locale-task")
    container.contact_relations.link_task(actor, contact.id, task.id, "locale-link")
    container.contact_relations.unlink_task(actor, contact.id, task.id, "locale-unlink")
    titles = {
        change.kind: change.title for change in container.lifecycle.list_recent_changes(actor)
    }
    assert titles["contact_alias_removed"] == "Nickname removed for Anna Berg"
    assert titles["contact_link"] == "Contact Anna Berg: link removed"
    # The same audit rows read in Swedish under the default: nothing is stored per language.
    swedish = create_container(make_settings(), container.session_factory)
    sv_titles = {
        change.kind: change.title for change in swedish.lifecycle.list_recent_changes(actor)
    }
    assert sv_titles["contact_alias_removed"] == "Alias borttaget för Anna Berg"
    assert sv_titles["contact_link"] == "Kontakt Anna Berg: koppling borttagen"

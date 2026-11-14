"""External reference MCP tools: ownership, scopes, idempotency, redaction and lifecycle."""

import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastmcp import Client
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.lifecycle.domain import RecordKind
from sidekick.mcp.server import create_mcp_server
from sidekick.references.service import LOGGER as REFERENCE_LOGGER
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

OWNER_SCOPES = frozenset({"tasks:read", "tasks:write"})
SENTINEL_TITLE = "sentinel-reference-title-4c1e"
SENTINEL_ACCOUNT = "sentinel-account-9b7a@example.com"
SENTINEL_EXTERNAL_ID = "sentinel-external-id-2f6d"
SENTINEL_PATH = "sentinel-link-path-71aa"
SENTINEL_URL = f"https://mail.google.com/mail/u/0/#inbox/{SENTINEL_PATH}"


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(name="reference_logs")
def _reference_logs() -> Iterator[_Collector]:
    collector = _Collector()
    REFERENCE_LOGGER.addHandler(collector)
    previous = REFERENCE_LOGGER.level
    REFERENCE_LOGGER.setLevel(logging.INFO)
    try:
        yield collector
    finally:
        REFERENCE_LOGGER.removeHandler(collector)
        REFERENCE_LOGGER.setLevel(previous)


@dataclass(frozen=True, slots=True)
class Harness:
    container: Container
    factory: Any
    owner: Actor
    other: Actor

    def server(self, actor: Actor | None = None) -> Any:
        chosen = actor or self.owner
        return create_mcp_server(self.container, actor_provider=lambda: chosen, enable_auth=False)

    def task(self, actor: Actor | None = None, title: str = "Task") -> UUID:
        chosen = actor or self.owner
        return self.container.tasks.create(chosen, title=title, idempotency_key=uuid4().hex).id

    def count(self, table: str) -> int:
        with self.factory() as session:
            return int(session.scalar(text(f"SELECT count(*) FROM sidekick.{table}")) or 0)


def make_harness(prefix: str) -> Harness:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner_id = container.auth.provision_user(f"{prefix}-owner", "Owner")
    other_id = container.auth.provision_user(f"{prefix}-other", "Other")
    return Harness(container, factory, Actor(owner_id, OWNER_SCOPES), Actor(other_id, OWNER_SCOPES))


def link_args(task_id: UUID, key: str, **overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "task_id": str(task_id),
        "kind": "mail",
        "provider": "google_gmail",
        "account_ref": SENTINEL_ACCOUNT,
        "external_id": SENTINEL_EXTERNAL_ID,
        "title": SENTINEL_TITLE,
        "url": SENTINEL_URL,
        "idempotency_key": key,
    }
    arguments.update(overrides)
    return arguments


async def call(client: Client, tool: str, arguments: dict[str, Any]) -> Any:
    return await client.call_tool(tool, arguments, raise_on_error=False)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_link_list_replay_refresh_and_unlink_remove_the_last_pointer() -> None:
    harness = make_harness("ref-flow")
    task_id = harness.task()
    async with Client(harness.server()) as client:
        linked = await call(
            client, "link_external_reference_to_task", link_args(task_id, "ref-link-0001")
        )
        assert not linked.is_error, linked.structured_content
        body = linked.structured_content
        assert body["linked"] is True and body["relation_created"] is True
        reference = body["reference"]
        assert reference["source"] == "claude_connector"
        assert reference["account_ref"] == SENTINEL_ACCOUNT  # already lowercase
        assert reference["version"] == 1

        replay = await call(
            client, "link_external_reference_to_task", link_args(task_id, "ref-link-0001")
        )
        assert replay.structured_content == body
        assert harness.count("external_references") == 1

        conflict = await call(
            client,
            "link_external_reference_to_task",
            link_args(task_id, "ref-link-0001", title="A different title"),
        )
        assert conflict.is_error and conflict.structured_content["code"] == "conflict"

        refreshed = await call(
            client,
            "link_external_reference_to_task",
            link_args(task_id, "ref-link-0002", title="Updated title"),
        )
        again = refreshed.structured_content
        assert again["reference"]["id"] == reference["id"]
        assert again["relation_created"] is False
        assert again["reference"]["version"] == 2
        assert again["reference"]["title"] == "Updated title"
        assert harness.count("external_references") == 1
        assert harness.count("task_external_references") == 1

        listed = await call(client, "list_task_external_references", {"task_id": str(task_id)})
        assert [item["id"] for item in listed.structured_content["items"]] == [reference["id"]]
        assert listed.structured_content["next_cursor"] is None

        unlink_args = {
            "task_id": str(task_id),
            "reference_id": reference["id"],
            "idempotency_key": "ref-unlink-0001",
        }
        removed = await call(client, "unlink_external_reference_from_task", unlink_args)
        assert removed.structured_content["linked"] is False
        assert removed.structured_content["reference_removed"] is True
        replayed = await call(client, "unlink_external_reference_from_task", unlink_args)
        assert replayed.structured_content == removed.structured_content
        assert harness.count("external_references") == 0

        later = await call(
            client,
            "unlink_external_reference_from_task",
            {**unlink_args, "idempotency_key": "ref-unlink-0002"},
        )
        assert later.is_error and later.structured_content["code"] == "not_found"
        empty = await call(client, "list_task_external_references", {"task_id": str(task_id)})
        assert empty.structured_content["items"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_pointer_shared_by_two_tasks_survives_until_the_last_unlink() -> None:
    harness = make_harness("ref-shared")
    first, second = harness.task(title="First"), harness.task(title="Second")
    async with Client(harness.server()) as client:
        a = await call(client, "link_external_reference_to_task", link_args(first, "shared-link-a"))
        b = await call(
            client, "link_external_reference_to_task", link_args(second, "shared-link-b")
        )
        assert a.structured_content["reference"]["id"] == b.structured_content["reference"]["id"]
        assert b.structured_content["relation_created"] is True
        reference_id = a.structured_content["reference"]["id"]
        assert harness.count("external_references") == 1
        assert harness.count("task_external_references") == 2

        partial = await call(
            client,
            "unlink_external_reference_from_task",
            {
                "task_id": str(first),
                "reference_id": reference_id,
                "idempotency_key": "shared-unlink-a",
            },
        )
        assert partial.structured_content["reference_removed"] is False
        assert harness.count("external_references") == 1
        final = await call(
            client,
            "unlink_external_reference_from_task",
            {
                "task_id": str(second),
                "reference_id": reference_id,
                "idempotency_key": "shared-unlink-b",
            },
        )
        assert final.structured_content["reference_removed"] is True
        assert harness.count("external_references") == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_account_and_instance_make_distinct_pointers() -> None:
    harness = make_harness("ref-identity")
    task_id = harness.task()
    async with Client(harness.server()) as client:
        ids = set()
        for index, overrides in enumerate(
            (
                {},
                {"account_ref": "second@example.com"},
                {
                    "kind": "calendar_event",
                    "provider": "google_calendar",
                    "url": None,
                    "external_id": "series-1",
                },
                {
                    "kind": "calendar_event",
                    "provider": "google_calendar",
                    "url": None,
                    "external_id": "series-1",
                    "instance_ref": "2026-11-01",
                },
            )
        ):
            response = await call(
                client,
                "link_external_reference_to_task",
                link_args(task_id, f"identity-key-{index}", **overrides),
            )
            assert not response.is_error, response.structured_content
            ids.add(response.structured_content["reference"]["id"])
        assert len(ids) == 4


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_owner_gets_not_found_and_nothing_changes() -> None:
    harness = make_harness("ref-foreign")
    mine = harness.task()
    async with Client(harness.server()) as client:
        linked = await call(
            client, "link_external_reference_to_task", link_args(mine, "foreign-link-1")
        )
        reference_id = linked.structured_content["reference"]["id"]
    foreign_task = harness.task(harness.other, "Theirs")

    async with Client(harness.server(harness.other)) as client:
        for tool, arguments in (
            ("link_external_reference_to_task", link_args(mine, "foreign-link-2")),
            ("list_task_external_references", {"task_id": str(mine)}),
            (
                "unlink_external_reference_from_task",
                {
                    "task_id": str(mine),
                    "reference_id": reference_id,
                    "idempotency_key": "foreign-unlink-1",
                },
            ),
            # Their own Task with my reference id: the pointer is invisible to them.
            (
                "unlink_external_reference_from_task",
                {
                    "task_id": str(foreign_task),
                    "reference_id": reference_id,
                    "idempotency_key": "foreign-unlink-2",
                },
            ),
        ):
            denied = await call(client, tool, arguments)
            assert denied.is_error and denied.structured_content["code"] == "not_found", tool
            assert "sentinel" not in str(denied.structured_content)
    assert harness.count("external_references") == 1
    assert harness.count("task_external_references") == 1

    # The same external object may be linked independently by each owner.
    async with Client(harness.server(harness.other)) as client:
        theirs = await call(
            client, "link_external_reference_to_task", link_args(foreign_task, "foreign-link-3")
        )
        assert theirs.structured_content["reference"]["id"] != reference_id
    assert harness.count("external_references") == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tools_are_forbidden_without_scope_and_authorization_precedes_validation() -> None:
    harness = make_harness("ref-scope")
    task_id = harness.task()
    async with Client(harness.server()) as client:
        linked = await call(
            client, "link_external_reference_to_task", link_args(task_id, "scope-link-01")
        )
        reference_id = linked.structured_content["reference"]["id"]

    read_only = Actor(harness.owner.user_id, frozenset({"tasks:read"}))
    write_only = Actor(harness.owner.user_id, frozenset({"tasks:write"}))
    unrelated = Actor(harness.owner.user_id, frozenset({"contacts:read", "contacts:write"}))
    async with Client(harness.server(read_only)) as client:
        for tool, arguments in (
            ("link_external_reference_to_task", link_args(task_id, "scope-link-02")),
            # An invalid link must not leak validation rules to a caller without the scope.
            (
                "link_external_reference_to_task",
                link_args(task_id, "scope-link-03", url="http://evil.example/x"),
            ),
            (
                "unlink_external_reference_from_task",
                {
                    "task_id": str(task_id),
                    "reference_id": reference_id,
                    "idempotency_key": "scope-unlink-1",
                },
            ),
        ):
            denied = await call(client, tool, arguments)
            assert denied.is_error and denied.structured_content["code"] == "forbidden", tool
        allowed = await call(client, "list_task_external_references", {"task_id": str(task_id)})
        assert not allowed.is_error
    async with Client(harness.server(write_only)) as client:
        denied = await call(client, "list_task_external_references", {"task_id": str(task_id)})
        assert denied.is_error and denied.structured_content["code"] == "forbidden"
    async with Client(harness.server(unrelated)) as client:
        for tool, arguments in (
            ("link_external_reference_to_task", link_args(task_id, "scope-link-04")),
            ("list_task_external_references", {"task_id": str(task_id)}),
        ):
            denied = await call(client, tool, arguments)
            assert denied.structured_content["code"] == "forbidden", tool
    assert harness.count("task_external_references") == 1


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "http://mail.google.com/mail/u/0/#inbox/x"},
        {"url": "https://evil.example/x"},
        {"url": "javascript:alert(1)"},
        {"url": "https://user:secret@mail.google.com/x"},
        {"url": "https://mail.google.com/x?access_token=abc"},
        {"provider": "google_calendar"},
        {"provider": "other", "kind": "mail", "url": "https://example.org/a\\b"},
        {"occurs_at": "2026-10-25T12:00:00"},
    ],
)
async def test_unacceptable_links_and_identities_are_validation_errors(
    overrides: dict[str, Any],
) -> None:
    harness = make_harness("ref-invalid")
    task_id = harness.task()
    async with Client(harness.server()) as client:
        refused = await call(
            client,
            "link_external_reference_to_task",
            link_args(task_id, "invalid-link-1", **overrides),
        )
    assert refused.is_error and refused.structured_content["code"] == "validation_error"
    assert "secret" not in str(refused.structured_content)
    assert harness.count("external_references") == 0
    assert harness.count("task_external_references") == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_trashed_and_archived_tasks_cannot_receive_or_list_pointers() -> None:
    harness = make_harness("ref-trashed")
    trashed, archived = harness.task(title="Trashed"), harness.task(title="Archived")
    async with Client(harness.server()) as client:
        kept = harness.task(title="Kept")
        linked = await call(
            client, "link_external_reference_to_task", link_args(kept, "trash-link-00")
        )
        reference_id = linked.structured_content["reference"]["id"]
    with harness.factory.begin() as session:
        session.execute(
            text("UPDATE sidekick.tasks SET trashed_at = now() WHERE id = :id"), {"id": trashed}
        )
        session.execute(
            text("UPDATE sidekick.tasks SET archived_at = now() WHERE id = :id"), {"id": archived}
        )
    async with Client(harness.server()) as client:
        for task_id in (trashed, archived):
            denied = await call(
                client,
                "link_external_reference_to_task",
                link_args(task_id, f"trash-link-{task_id}"),
            )
            assert denied.is_error and denied.structured_content["code"] == "not_found"
            listed = await call(client, "list_task_external_references", {"task_id": str(task_id)})
            assert listed.structured_content["code"] == "not_found"
        unlinked = await call(
            client,
            "unlink_external_reference_from_task",
            {
                "task_id": str(trashed),
                "reference_id": reference_id,
                "idempotency_key": "trash-unlink-1",
            },
        )
        assert unlinked.structured_content["code"] == "not_found"
    assert harness.count("external_references") == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_task_holds_at_most_fifty_pointers_but_existing_ones_still_refresh() -> None:
    harness = make_harness("ref-limit")
    task_id = harness.task()
    service = harness.container.references
    from sidekick.references.domain import ExternalReferenceDetails

    def details(number: int) -> ExternalReferenceDetails:
        return ExternalReferenceDetails(
            kind="document",
            provider="other",
            account_ref="me@example.com",
            external_id=f"doc-{number}",
            title=f"Document {number}",
        )

    for number in range(50):
        service.link(
            harness.owner,
            task_id,
            details(number),
            source="manual",
            idempotency_key=f"limit-key-{number:02d}",
        )
    async with Client(harness.server()) as client:
        full = await call(
            client,
            "link_external_reference_to_task",
            link_args(
                task_id,
                "limit-key-over",
                kind="document",
                provider="other",
                external_id="doc-51",
                url=None,
            ),
        )
        assert full.is_error and full.structured_content["code"] == "conflict"
        refreshed = await call(
            client,
            "link_external_reference_to_task",
            link_args(
                task_id,
                "limit-key-refresh",
                kind="document",
                provider="other",
                account_ref="me@example.com",
                external_id="doc-3",
                title="Renamed",
                url=None,
            ),
        )
        assert not refreshed.is_error and refreshed.structured_content["relation_created"] is False
        first_page = await call(
            client, "list_task_external_references", {"task_id": str(task_id), "limit": 20}
        )
        second_page = await call(
            client,
            "list_task_external_references",
            {
                "task_id": str(task_id),
                "limit": 20,
                "cursor": first_page.structured_content["next_cursor"],
            },
        )
        last_page = await call(
            client,
            "list_task_external_references",
            {
                "task_id": str(task_id),
                "limit": 20,
                "cursor": second_page.structured_content["next_cursor"],
            },
        )
    seen = [
        item["id"]
        for page in (first_page, second_page, last_page)
        for item in page.structured_content["items"]
    ]
    assert len(seen) == len(set(seen)) == 50
    assert last_page.structured_content["next_cursor"] is None
    assert harness.count("task_external_references") == 50


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_cursor_cannot_be_replayed_by_another_owner_or_task() -> None:
    harness = make_harness("ref-cursor")
    first, second = harness.task(title="One"), harness.task(title="Two")
    async with Client(harness.server()) as client:
        for number in range(3):
            await call(
                client,
                "link_external_reference_to_task",
                link_args(first, f"cursor-key-{number}", external_id=f"id-{number}", url=None),
            )
        page = await call(
            client, "list_task_external_references", {"task_id": str(first), "limit": 2}
        )
        cursor = page.structured_content["next_cursor"]
        assert cursor
        replay = await call(
            client,
            "list_task_external_references",
            {"task_id": str(second), "limit": 2, "cursor": cursor},
        )
        assert replay.is_error


@pytest.mark.integration
def test_concurrent_links_of_one_object_create_one_pointer() -> None:
    harness = make_harness("ref-parallel")
    tasks = [harness.task(title=f"Parallel {number}") for number in range(4)]
    service = harness.container.references
    from sidekick.references.domain import ExternalReferenceDetails

    details = ExternalReferenceDetails(
        kind="mail",
        provider="google_gmail",
        account_ref="me@example.com",
        external_id="thread-parallel",
        title="Parallel",
    )

    def link(index: int) -> str:
        data = service.link(
            harness.owner,
            tasks[index % len(tasks)],
            details,
            source="claude_connector",
            idempotency_key=f"parallel-key-{index:02d}",
        )
        return str(data.reference.id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(link, range(8)))
    assert len(set(ids)) == 1
    assert harness.count("external_references") == 1
    assert harness.count("task_external_references") == 4


@pytest.mark.integration
def test_permanent_task_removal_releases_pointers_only_that_task_used() -> None:
    harness = make_harness("ref-purge")
    container = harness.container
    solo, shared_a, shared_b = (harness.task(title=name) for name in ("solo", "a", "b"))
    from sidekick.references.domain import ExternalReferenceDetails

    def details(name: str) -> ExternalReferenceDetails:
        return ExternalReferenceDetails(
            kind="document",
            provider="other",
            account_ref="me@example.com",
            external_id=name,
            title=name,
        )

    container.references.link(
        harness.owner, solo, details("only-solo"), source="manual", idempotency_key="purge-key-01"
    )
    for index, task in enumerate((shared_a, shared_b)):
        container.references.link(
            harness.owner,
            task,
            details("shared"),
            source="manual",
            idempotency_key=f"purge-key-1{index}",
        )
    assert harness.count("external_references") == 2

    for task_id, version in ((solo, 1), (shared_a, 1)):
        trashed = container.lifecycle.trash(
            harness.owner,
            RecordKind.TASK,
            task_id,
            version=version,
            idempotency_key=f"purge-trash-{task_id}",
        )
        container.lifecycle.permanently_remove(
            harness.owner,
            RecordKind.TASK,
            task_id,
            version=trashed.version,
            idempotency_key=f"purge-remove-{task_id}",
        )
    # The solo pointer is gone, the shared one remains for the surviving Task.
    assert harness.count("external_references") == 1
    assert harness.count("task_external_references") == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_discovery_declares_annotations_and_idempotency() -> None:
    harness = make_harness("ref-discovery")
    async with Client(harness.server()) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    link = tools["link_external_reference_to_task"]
    unlink = tools["unlink_external_reference_from_task"]
    listing = tools["list_task_external_references"]
    assert link.annotations.destructiveHint is False and link.annotations.idempotentHint is True
    assert link.annotations.openWorldHint is False
    assert unlink.annotations.destructiveHint is True
    assert listing.annotations.readOnlyHint is True
    for tool in (link, unlink):
        assert "idempotency_key" in tool.inputSchema["required"]
    assert "content" not in link.inputSchema["properties"]
    assert set(link.inputSchema["properties"]) == {
        "task_id",
        "kind",
        "provider",
        "account_ref",
        "external_id",
        "title",
        "idempotency_key",
        "instance_ref",
        "url",
        "occurs_at",
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_logs_audit_and_errors_never_carry_reference_content(
    reference_logs: _Collector,
) -> None:
    harness = make_harness("ref-redaction")
    task_id = harness.task()
    async with Client(harness.server()) as client:
        linked = await call(
            client, "link_external_reference_to_task", link_args(task_id, "redact-link-01")
        )
        refused = await call(
            client,
            "link_external_reference_to_task",
            link_args(task_id, "redact-link-02", url=f"http://evil.example/{SENTINEL_PATH}"),
        )
        reference_id = linked.structured_content["reference"]["id"]
        await call(
            client,
            "unlink_external_reference_from_task",
            {
                "task_id": str(task_id),
                "reference_id": reference_id,
                "idempotency_key": "redact-unlink-1",
            },
        )
    assert refused.is_error
    assert reference_logs.records, "operations are logged"
    sentinels = (
        SENTINEL_TITLE,
        SENTINEL_ACCOUNT,
        SENTINEL_EXTERNAL_ID,
        SENTINEL_PATH,
        "mail.google.com",
    )
    for record in reference_logs.records:
        rendered = f"{record.getMessage()} {record.__dict__}"
        assert not any(value in rendered for value in sentinels), rendered
    for text_value in (str(refused.structured_content), str(refused.content)):
        assert not any(value in text_value for value in sentinels)
    with harness.factory() as session:
        audit_rows = session.execute(text("SELECT * FROM sidekick.audit_events")).mappings().all()
    audit_text = " ".join(str(dict(row)) for row in audit_rows)
    assert "external_reference.linked" in audit_text
    assert not any(value in audit_text for value in sentinels)

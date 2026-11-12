"""`list_assistant_activity`: the Activity Center read over MCP, owner-scoped and redacted.

It calls the `automation.list_activity` use case and needs `tasks:read`. Content (summary,
before/after values, evidence) is returned by default and withheld with `include_content=false`;
no argument or record content reaches a log sink; the session-only automation settings read is
not exposed.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.automation.application.service import ActivityLedger
from sidekick.automation.domain import AutomationCategory
from sidekick.mcp.control import CONTROL_TOOL_NAMES, CONTROL_TOOL_SCOPES
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import TOKEN_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

WRITE_SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
READ_SCOPES = frozenset({"tasks:read"})
PROJECTS_READ_SCOPES = frozenset({"tasks:read", "projects:read"})
TITLE_SENTINEL = "sentinel-activity-title-5d1e"
CURSOR_SENTINEL = "sentinel-cursor-value-83ac"
PROCESS_RUN_SENTINEL = "sentinel-process-run-name-7b2f"
AUTOMATION_RUN_SENTINEL = "sentinel-automation-run-summary-4c9a"


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


async def _create_tasks(client: Client, count: int, prefix: str) -> None:
    for index in range(count):
        await client.call_tool(
            "create_task",
            {"title": f"{prefix} {index}", "idempotency_key": f"{prefix}-key-{index:03d}"},
        )


def _record_activity(container: Container, owner: Any, aggregate_type: str, summary: str) -> None:
    """Write a ledger row the way the owning domain service does, for one aggregate type."""
    ledger = ActivityLedger(container.automation.store)

    def operation(session: Any) -> None:
        ledger.append(
            session,
            owner_id=owner,
            aggregate_type=aggregate_type,
            aggregate_id=uuid4(),
            aggregate_version=1,
            event_type=f"{aggregate_type}.recorded",
            actor_type="user",
            actor_id=owner,
            operation="record",
            category=AutomationCategory.TASK_MAINTENANCE,
            summary=summary,
            occurred_at=datetime.now(UTC),
        )

    container.automation.store.transaction(operation)


def _record_process_run_activity(container: Container, owner: Any) -> None:
    """Write the ledger row `ProcessRunService` writes when a process run materializes."""
    _record_activity(
        container, owner, "process_run", f"Process run created: {PROCESS_RUN_SENTINEL}"
    )


def test_the_tool_needs_only_a_token_holdable_scope() -> None:
    assert CONTROL_TOOL_NAMES == ("list_assistant_activity",)
    needed = set().union(*CONTROL_TOOL_SCOPES.values())
    assert needed == {"tasks:read"}
    assert needed <= TOKEN_SCOPES


@pytest.mark.asyncio
async def test_the_session_only_automation_read_is_not_a_tool() -> None:
    container = create_container(make_settings())
    actor = Actor(uuid4(), frozenset({"tasks:read", "tasks:write"}))
    names = {tool.name for tool in await _server_for(container, actor).list_tools()}
    assert "list_assistant_activity" in names
    assert not {name for name in names if "automation" in name}
    assert not {name for name in names if name.startswith("get_automation")}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_returns_owned_entries_newest_first_with_content_by_default() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _create_tasks(client, 1, TITLE_SENTINEL)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        default = await client.call_tool("list_assistant_activity", {})
        withheld = await client.call_tool("list_assistant_activity", {"include_content": False})

    [entry] = withheld.structured_content["items"]
    assert entry["operation"] == "create_task"
    assert entry["source"] == "user"
    assert entry["state"] == "applied"
    assert entry["before_values"] == {} and entry["after_values"] == {}
    assert entry["evidence"] == {}
    assert withheld.structured_content["next_cursor"] is None
    assert "owner_id" not in str(withheld.structured_content)

    [full] = default.structured_content["items"]
    assert full["id"] == entry["id"]
    assert full["after_values"]["title"] == f"{TITLE_SENTINEL} 0"
    assert default.structured_content["next_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_carries_a_title_by_default() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _create_tasks(client, 1, TITLE_SENTINEL)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        default = await client.call_tool("list_assistant_activity", {})
        withheld = await client.call_tool("list_assistant_activity", {"include_content": False})

    [entry] = withheld.structured_content["items"]
    [full] = default.structured_content["items"]
    assert TITLE_SENTINEL not in str(withheld.structured_content)
    assert TITLE_SENTINEL not in str(withheld.content)
    assert entry["summary"] == "task_create: task.create_task"
    assert TITLE_SENTINEL in full["summary"]
    assert TITLE_SENTINEL in str(default.content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pages_with_a_cursor_and_filters_by_state() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _create_tasks(client, 3, "paged")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        first = await client.call_tool("list_assistant_activity", {"limit": 2})
        second = await client.call_tool(
            "list_assistant_activity",
            {"limit": 2, "cursor": first.structured_content["next_cursor"]},
        )
        failed = await client.call_tool("list_assistant_activity", {"state": "failed"})
        bad_state = await client.call_tool(
            "list_assistant_activity", {"state": "bogus"}, raise_on_error=False
        )
        too_many = await client.call_tool(
            "list_assistant_activity", {"limit": 101}, raise_on_error=False
        )

    first_ids = [item["id"] for item in first.structured_content["items"]]
    second_ids = [item["id"] for item in second.structured_content["items"]]
    assert len(first_ids) == 2 and len(second_ids) == 1
    assert set(first_ids).isdisjoint(second_ids)
    assert first.structured_content["next_cursor"] is not None
    assert second.structured_content["next_cursor"] is None
    assert failed.structured_content["items"] == []
    assert bad_state.is_error
    assert too_many.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_never_returns_another_owners_entries() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    other = container.auth.provision_user("other-owner", "Other")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _create_tasks(client, 2, "mine")
    async with Client(_server_for(container, Actor(other, WRITE_SCOPES))) as client:
        await _create_tasks(client, 1, "theirs")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        mine = await client.call_tool("list_assistant_activity", {"include_content": True})
    async with Client(_server_for(container, Actor(other, READ_SCOPES))) as client:
        theirs = await client.call_tool("list_assistant_activity", {"include_content": True})

    assert len(mine.structured_content["items"]) == 2
    assert len(theirs.structured_content["items"]) == 1
    assert "theirs" not in str(mine.structured_content)
    assert "mine" not in str(theirs.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_cursor_from_another_owner_is_refused() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    other = container.auth.provision_user("other-owner", "Other")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _create_tasks(client, 2, "cursor")
    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        page = await client.call_tool("list_assistant_activity", {"limit": 1})

    async with Client(_server_for(container, Actor(other, READ_SCOPES))) as client:
        denied = await client.call_tool(
            "list_assistant_activity",
            {"limit": 1, "cursor": page.structured_content["next_cursor"]},
            raise_on_error=False,
        )
    assert denied.is_error


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "scopes", [frozenset(), frozenset({"projects:read"}), frozenset({"preferences:read"})]
)
async def test_forbidden_without_tasks_read(scopes: frozenset[str]) -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, scopes))) as client:
        denied = await client.call_tool("list_assistant_activity", {}, raise_on_error=False)
    assert denied.is_error
    assert denied.structured_content["code"] == "forbidden"
    assert denied.structured_content["correlation_id"]


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def rendered(self) -> str:
        formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
        parts = [formatter.format(record) for record in self.records]
        parts.extend(repr(record.__dict__) for record in self.records)
        return "\n".join(parts)


@pytest.fixture(name="all_logs")
def _all_logs() -> Iterator[_Collector]:
    collector = _Collector()
    loggers: list[logging.Logger] = [logging.getLogger()]
    loggers.extend(
        item
        for item in logging.root.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    )
    for logger in loggers:
        logger.addHandler(collector)
    try:
        yield collector
    finally:
        for logger in loggers:
            logger.removeHandler(collector)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_record_content_or_argument_value_reaches_a_log_sink(
    all_logs: _Collector,
) -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _create_tasks(client, 1, TITLE_SENTINEL)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        ok: Any = await client.call_tool("list_assistant_activity", {"include_content": True})
        bad_cursor = await client.call_tool_mcp(
            "list_assistant_activity", {"cursor": CURSOR_SENTINEL}
        )
        bad_arguments = await client.call_tool_mcp(
            "list_assistant_activity", {"category": CURSOR_SENTINEL * 20}
        )

    assert TITLE_SENTINEL in str(ok.structured_content)  # the owner asked for content
    assert bad_cursor.isError and bad_arguments.isError
    rendered = all_logs.rendered()
    assert TITLE_SENTINEL not in rendered
    assert CURSOR_SENTINEL not in rendered
    assert CURSOR_SENTINEL not in str(bad_cursor.structuredContent)
    assert all(not record.args for record in all_logs.records)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_run_entries_need_projects_read() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _create_tasks(client, 1, TITLE_SENTINEL)
    _record_process_run_activity(container, owner)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        tasks_only: Any = await client.call_tool(
            "list_assistant_activity", {"include_content": True}
        )
    async with Client(_server_for(container, Actor(owner, PROJECTS_READ_SCOPES))) as client:
        with_projects: Any = await client.call_tool(
            "list_assistant_activity", {"include_content": True}
        )

    assert {item["aggregate_type"] for item in tasks_only.structured_content["items"]} == {"task"}
    assert PROCESS_RUN_SENTINEL not in str(tasks_only.structured_content)
    assert {item["aggregate_type"] for item in with_projects.structured_content["items"]} == {
        "task",
        "process_run",
    }
    assert PROCESS_RUN_SENTINEL in str(with_projects.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pages_skip_hidden_process_run_entries() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _create_tasks(client, 2, "visible")
    _record_process_run_activity(container, owner)
    _record_process_run_activity(container, owner)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        seen: list[str] = []
        cursor: str | None = None
        for _ in range(5):
            page: Any = await client.call_tool(
                "list_assistant_activity", {"limit": 1, "cursor": cursor}
            )
            seen.extend(item["aggregate_type"] for item in page.structured_content["items"])
            cursor = page.structured_content["next_cursor"]
            if cursor is None:
                break

    assert seen == ["task", "task"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cursor_from_wider_scope_is_refused_for_narrower_scope() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _create_tasks(client, 2, "scoped")
    async with Client(_server_for(container, Actor(owner, PROJECTS_READ_SCOPES))) as client:
        page: Any = await client.call_tool("list_assistant_activity", {"limit": 1})

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        replay: Any = await client.call_tool(
            "list_assistant_activity",
            {"limit": 1, "cursor": page.structured_content["next_cursor"]},
            raise_on_error=False,
        )
    assert replay.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_automation_run_entries_are_task_scoped() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    _record_activity(container, owner, "automation_run", f"Review run: {AUTOMATION_RUN_SENTINEL}")
    _record_process_run_activity(container, owner)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        tasks_only: Any = await client.call_tool(
            "list_assistant_activity", {"include_content": True}
        )

    assert [item["aggregate_type"] for item in tasks_only.structured_content["items"]] == [
        "automation_run"
    ]
    assert AUTOMATION_RUN_SENTINEL in str(tasks_only.structured_content)
    assert PROCESS_RUN_SENTINEL not in str(tasks_only.structured_content)

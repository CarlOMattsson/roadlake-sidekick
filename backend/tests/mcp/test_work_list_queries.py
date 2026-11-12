"""The Work agenda and board read in a fixed number of SQL statements, however many Tasks exist."""

import time
from datetime import UTC, datetime
from typing import Any

import pytest
from fastmcp import Client
from sqlalchemy import Engine, event

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset(
    {"contacts:read", "contacts:write", "projects:read", "tasks:read", "tasks:write"}
)


async def _statements_for(task_count: int, key: str) -> dict[str, Any]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, SCOPES)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    engine: Engine = container.session_factory.kw["bind"]
    async with Client(server) as client:
        contacts: list[str] = []
        for index in range(3):
            created = await client.call_tool(
                "create_contact",
                {"display_name": f"Kontakt {index}", "idempotency_key": f"{key}-contact-{index}"},
            )
            assert created.structured_content is not None
            contacts.append(str(created.structured_content["contact"]["id"]))
        for index in range(task_count):
            created_task = await client.call_tool(
                "create_task",
                {"title": f"Uppgift {index}", "idempotency_key": f"{key}-task-{index}"},
            )
            assert created_task.structured_content is not None
            task: dict[str, Any] = created_task.structured_content["task"]
            await client.call_tool(
                "update_task",
                {
                    "task_id": task["id"],
                    "version": task["version"],
                    "idempotency_key": f"{key}-wait-{index}",
                    "changes": {
                        "waiting_since": datetime.now(UTC).isoformat(),
                        "waiting_on_contact_id": contacts[index % 3],
                    },
                },
            )
            for step_index in range(2):
                created_step = await client.call_tool(
                    "create_task_step",
                    {
                        "task_id": task["id"],
                        "title": f"Steg {step_index}",
                        "idempotency_key": f"{key}-step-{index}-{step_index}",
                    },
                )
                assert created_step.structured_content is not None
                step: dict[str, Any] = created_step.structured_content["step"]
                await client.call_tool(
                    "create_step_action",
                    {
                        "step_id": step["id"],
                        "title": "Åtgärd",
                        "idempotency_key": f"{key}-action-{index}-{step_index}",
                    },
                )

        statements: list[str] = []

        def record(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
            statements.append(statement)

        counts: dict[str, Any] = {}
        event.listen(engine, "before_cursor_execute", record)
        try:
            for tool, arguments in (
                ("get_work_agenda", {"waiting": "waiting", "limit": 100}),
                ("get_work_board", {"limit": 100}),
            ):
                statements.clear()
                started = time.perf_counter()
                response = await client.call_tool(tool, arguments)
                elapsed_ms = (time.perf_counter() - started) * 1000
                counts[tool] = (len(statements), elapsed_ms, response.structured_content)
        finally:
            event.remove(engine, "before_cursor_execute", record)
    return counts


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_and_board_statement_count_does_not_grow_with_tasks() -> None:
    few = await _statements_for(2, "wq-few")
    many = await _statements_for(6, "wq-many")

    for tool in ("get_work_agenda", "get_work_board"):
        print(
            f"{tool} statements/ms: 2 tasks={few[tool][0]}/{few[tool][1]:.1f}, "
            f"6 tasks={many[tool][0]}/{many[tool][1]:.1f}"
        )
    agenda = many["get_work_agenda"][2]["items"]
    assert {item["waiting_on_contact_name"] for item in agenda} == {
        "Kontakt 0",
        "Kontakt 1",
        "Kontakt 2",
    }
    for tool in ("get_work_agenda", "get_work_board"):
        assert many[tool][0] == few[tool][0], tool

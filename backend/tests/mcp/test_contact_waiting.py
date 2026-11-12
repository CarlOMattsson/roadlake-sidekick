"""A Task that waits on a Contact shows in that Contact's context and in the meeting brief.

The brief tests are pure (the text builder takes the structured result); the last test runs the
real tools to show an unlinked waiting Task is found and named.
"""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.contacts import _contact_context_text  # pyright: ignore[reportPrivateUsage]
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.mcp_contact_brief import (  # pyright: ignore[reportPrivateUsage]
    _structured,
    _task,
)
from tests.support.settings import make_settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
ZONE = ZoneInfo("Europe/Stockholm")


def _brief(structured: dict[str, Any]) -> str:
    return _contact_context_text(structured, now=NOW, zone=ZONE).split("\n", 1)[0]


def _waiting(title: str, since: str, **overrides: Any) -> dict[str, Any]:
    return _task(title, None, waiting_on_contact=True, waiting_since=since, **overrides)


def test_brief_says_who_you_wait_on_and_for_how_long_instead_of_no_open_tasks() -> None:
    structured = _structured(
        role="Projektledare",
        organization="Nordvik AB",
        tasks=[_waiting("Förbered demo", "2026-10-18T09:00:00+02:00")],
    )

    brief = _brief(structured)

    assert brief == (
        "Sara Lind (Projektledare, Nordvik AB). "
        "You are waiting on Sara Lind for 9 days: Förbered demo."
    )
    assert "No open tasks" not in brief


def test_brief_names_the_longest_wait_counts_the_rest_and_keeps_other_tasks_apart() -> None:
    structured = _structured(
        tasks=[
            _waiting("Ny väntan", "2026-10-26T09:00:00+01:00"),
            _waiting("Gammal väntan", "2026-10-20T09:00:00+02:00", follow_up_due=True),
            _task("Skicka offert", "2026-10-30T09:00:00+01:00"),
        ],
    )

    brief = _brief(structured)

    assert brief == (
        "Sara Lind. You are waiting on Sara Lind for 7 days: Gammal väntan (follow-up overdue), "
        "and 1 more. 1 other open task, most urgent: Skicka offert (due 2026-10-30)."
    )


def test_a_completed_waiting_task_is_not_waited_on_any_more() -> None:
    structured = _structured(
        tasks=[_waiting("Klar väntan", "2026-10-18T09:00:00+02:00", status="completed")],
    )

    assert _brief(structured) == "Sara Lind. No open tasks."


def test_brief_has_no_id_or_version_on_line_one_when_waiting() -> None:
    structured = _structured(tasks=[_waiting("Förbered demo", "2026-10-18T09:00:00+02:00")])

    first = _brief(structured)

    assert "11111111-1111" not in first
    assert " v3" not in first


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unlinked_task_that_waits_on_the_contact_is_in_its_context() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    scopes = frozenset(
        {"contacts:read", "contacts:write", "projects:read", "tasks:read", "tasks:write"}
    )
    actor = Actor(owner, scopes)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        contact = await client.call_tool(
            "create_contact", {"display_name": "Anna Berg", "idempotency_key": "waiting-ctx-anna"}
        )
        contact_id = contact.structured_content["contact"]["id"]
        task = await client.call_tool(
            "create_task", {"title": "Förbered demo", "idempotency_key": "waiting-ctx-task"}
        )
        record = task.structured_content["task"]
        # The Task is not linked to Anna; it only waits on her.
        await client.call_tool(
            "update_task",
            {
                "task_id": record["id"],
                "version": record["version"],
                "idempotency_key": "waiting-ctx-wait",
                "changes": {
                    "waiting_since": datetime.now(UTC).isoformat(),
                    "waiting_on_contact_id": contact_id,
                },
            },
        )

        context = await client.call_tool("get_contact_context", {"contact_id": contact_id})
        agenda = await client.call_tool("get_work_agenda", {"waiting": "waiting"})

    tasks = context.structured_content["tasks"]["items"]
    assert [t["title"] for t in tasks] == ["Förbered demo"]
    assert tasks[0]["waiting_on_contact"] is True
    first_line = context.content[0].text.splitlines()[0]
    assert "You are waiting on Anna Berg since today: Förbered demo." in first_line
    assert "No open tasks" not in first_line
    assert agenda.structured_content["items"][0]["waiting_on_contact_name"] == "Anna Berg"
    assert agenda.content[0].text.splitlines()[0] == (
        "You are waiting on Anna Berg since today: Förbered demo."
    )

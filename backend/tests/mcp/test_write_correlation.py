"""Every MCP write tool hands the request's correlation id to its use case, so the audit event
it commits can be matched with the request log lines (and with the reply's `correlation_id`).

The matrix is derived from the tool registry: every tool annotated `readOnlyHint: false` must
either be exercised below, with its own correlation id, and leave an audit row carrying exactly
that id, or be named in an explicit exception list with its reason. Both lists may only shrink:
a new write tool fails the test until it is exercised, and a listed tool that starts to be
exercised or audited fails it until it is removed from the list.

The HTTP request is stood in for by a fixed scope: `request_correlation_id` reads
`sidekick.correlation_id` from it, exactly as the correlation middleware sets it.
"""

import os
from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastmcp import Client
from sqlalchemy import text

from sidekick.api.app import create_container
from sidekick.mcp import correlation
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import _cleanup_factory_for, database_factory
from tests.support.journal_drafts import seed_entry_draft
from tests.support.settings import make_settings

#: Write tools the scenario exercises that commit no audit row, each with the reason. Only shrinks:
#: a tool that starts to audit fails the test until it is removed here. Empty: every write tool
#: audits.
NO_AUDIT: dict[str, str] = {}

#: Tools whose audit event is also checked for replay: the same request again records no second
#: event. They were the unaudited ones of n116; the board reorder is checked separately.
REPLAYED: tuple[str, ...] = (
    "update_domain",
    "update_process",
    "create_task_step",
    "update_task_step",
    "complete_task_step",
    "reorder_task_steps",
    "create_step_action",
    "update_step_action",
    "complete_step_action",
    "reorder_step_actions",
    "create_saved_work_view",
    "update_saved_work_view",
    "archive_saved_work_view",
    "restore_saved_work_view",
    "update_journal_draft",
    "reject_journal_draft",
    "set_daily_journal_summary",
    "set_memory_settings",
    "exclude_from_memory",
)

#: Write tools the scenario does not exercise yet. Only shrinks; remove a name when it is covered.
NOT_EXERCISED: frozenset[str] = frozenset()


def _write_tool_names(tools: list[Any]) -> set[str]:
    return {
        tool.name
        for tool in tools
        if tool.annotations is not None and tool.annotations.readOnlyHint is False
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_every_write_tool_audits_its_requests_correlation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("corr_owner", "Corr Owner")
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    with admin() as session:
        known = set(session.execute(text("SELECT id FROM sidekick.audit_events")).scalars())

    current = {"id": "corr-unset"}
    monkeypatch.setattr(
        correlation,
        "get_http_request",
        lambda: SimpleNamespace(scope={"sidekick.correlation_id": current["id"]}),
    )
    server = create_mcp_server(
        container,
        actor_provider=lambda: Actor(owner, frozenset(MCP_SCOPES)),
        enable_auth=False,
    )
    write_tools = _write_tool_names(list(await server.list_tools()))
    calls: dict[str, str] = {}  # tool name -> correlation id of its (first) call
    first_args: dict[str, dict[str, Any]] = {}
    call_counts: dict[str, int] = {}

    async with Client(server) as client:

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            current["id"] = f"corr-{name}-0123456789"
            calls.setdefault(name, current["id"])
            first_args.setdefault(name, arguments)
            call_counts[name] = call_counts.get(name, 0) + 1
            result = await client.call_tool(name, arguments)
            return result.structured_content or {}

        key = "corr-key-"
        domain = (await call("create_domain", {"name": "Home", "idempotency_key": key + "dom"}))[
            "domain"
        ]
        await call(
            "update_domain",
            {
                "domain_id": domain["id"],
                "version": domain["version"],
                "idempotency_key": key + "udom",
                "changes": {"name": "House"},
            },
        )
        project = (
            await call(
                "create_project",
                {"domain_id": domain["id"], "title": "Garden", "idempotency_key": key + "prj"},
            )
        )["project"]
        await call(
            "update_project",
            {
                "project_id": project["id"],
                "version": project["version"],
                "idempotency_key": key + "uprj",
                "changes": {"title": "Allotment"},
            },
        )
        task = (await call("create_task", {"title": "Rake", "idempotency_key": key + "tsk"}))[
            "task"
        ]
        await call("create_task", {"title": "Weed", "idempotency_key": key + "tsk2"})
        await call("create_tasks", {"tasks": [{"title": "Mow"}], "idempotency_key": key + "tsks"})
        updated = (
            await call(
                "update_task",
                {
                    "task_id": task["id"],
                    "version": task["version"],
                    "idempotency_key": key + "utsk",
                    "changes": {"title": "Rake leaves"},
                },
            )
        )["task"]
        rescheduled = await call(
            "reschedule_tasks",
            {
                "items": [
                    {
                        "task_id": task["id"],
                        "expected_version": updated["version"],
                        "when": "tomorrow",
                    }
                ],
                "idempotency_key": key + "resched",
            },
        )
        await call(
            "complete_task",
            {
                "task_id": task["id"],
                "version": rescheduled["tasks"][0]["version"],
                "idempotency_key": key + "ctsk",
            },
        )
        contact = (
            await call("create_contact", {"display_name": "Sam", "idempotency_key": key + "con"})
        )["contact"]
        await call(
            "link_contact_to_project",
            {
                "contact_id": contact["id"],
                "project_id": project["id"],
                "idempotency_key": key + "link",
            },
        )
        await call(
            "archive_contact",
            {
                "contact_id": contact["id"],
                "expected_version": contact["version"],
                "idempotency_key": key + "acon",
            },
        )
        shopping = (
            await call("create_shopping_list", {"name": "Weekly", "idempotency_key": key + "list"})
        )["shopping_list"]

        # The board reorder: the complete todo column, replayed with the same key.
        column = (await client.call_tool("get_work_board", {"limit": 100})).structured_content
        assert column is not None
        todo = column["columns"]["todo"]
        assert len(todo) >= 2
        reorder_args = {
            "status": "todo",
            "items": [
                {"task_id": item["id"], "version": item["version"]} for item in reversed(todo)
            ],
            "idempotency_key": key + "reorder",
        }
        await call("reorder_work_board_column", reorder_args)
        await call("reorder_work_board_column", reorder_args)

        # Steps and actions under a task, then their reorder, archive and restore.
        live = (await call("create_task", {"title": "Steps", "idempotency_key": key + "tsk3"}))[
            "task"
        ]
        step = (
            await call(
                "create_task_step",
                {"task_id": live["id"], "title": "One", "idempotency_key": key + "step1"},
            )
        )["step"]
        step2 = (
            await call(
                "create_task_step",
                {"task_id": live["id"], "title": "Two", "idempotency_key": key + "step2"},
            )
        )["step"]
        await call(
            "reorder_task_steps",
            {
                "task_id": live["id"],
                "items": [
                    {"id": step2["id"], "version": step2["version"]},
                    {"id": step["id"], "version": step["version"]},
                ],
                "idempotency_key": key + "rsteps",
            },
        )
        step = (
            await call(
                "update_task_step",
                {
                    "step_id": step["id"],
                    "version": step["version"] + 1,
                    "changes": {"title": "One again"},
                    "idempotency_key": key + "ustep",
                },
            )
        )["step"]
        action = (
            await call(
                "create_step_action",
                {"step_id": step["id"], "title": "Act", "idempotency_key": key + "act1"},
            )
        )["action"]
        action2 = (
            await call(
                "create_step_action",
                {"step_id": step["id"], "title": "Act two", "idempotency_key": key + "act2"},
            )
        )["action"]
        await call(
            "reorder_step_actions",
            {
                "step_id": step["id"],
                "items": [
                    {"id": action2["id"], "version": action2["version"]},
                    {"id": action["id"], "version": action["version"]},
                ],
                "idempotency_key": key + "ract",
            },
        )
        await call(
            "update_step_action",
            {
                "action_id": action["id"],
                "version": action["version"] + 1,
                "changes": {"title": "Act again"},
                "idempotency_key": key + "uact",
            },
        )
        await call(
            "complete_step_action",
            {
                "action_id": action2["id"],
                "version": action2["version"] + 1,
                "idempotency_key": key + "cact",
            },
        )
        await call(
            "complete_task_step",
            {
                "step_id": step2["id"],
                "version": step2["version"] + 1,
                "idempotency_key": key + "cstep",
            },
        )
        await call(
            "archive_step_action",
            {
                "action_id": action["id"],
                "version": action["version"] + 2,
                "idempotency_key": key + "aact",
            },
        )
        await call(
            "restore_step_action",
            {
                "action_id": action["id"],
                "version": action["version"] + 3,
                "idempotency_key": key + "ract2",
            },
        )

        # Contacts: fields, aliases, links to a task, and archive then restore.
        sam = (await call("create_contact", {"display_name": "Kim", "idempotency_key": key + "k"}))[
            "contact"
        ]
        sam = (
            await call(
                "update_contact",
                {
                    "contact_id": sam["id"],
                    "expected_version": sam["version"],
                    "changes": {"display_name": "Kim L"},
                    "idempotency_key": key + "ucon",
                },
            )
        )["contact"]
        sam = (
            await call(
                "add_contact_alias",
                {
                    "contact_id": sam["id"],
                    "value": "K",
                    "expected_version": sam["version"],
                    "idempotency_key": key + "alias",
                },
            )
        )["contact"]
        await call(
            "remove_contact_alias",
            {
                "contact_id": sam["id"],
                "alias_id": sam["aliases"][0]["id"],
                "expected_version": sam["version"],
                "idempotency_key": key + "ralias",
            },
        )
        link_args = {
            "contact_id": sam["id"],
            "task_id": live["id"],
            "idempotency_key": key + "ltask",
        }
        await call("link_contact_to_task", link_args)
        await call("unlink_contact_from_task", {**link_args, "idempotency_key": key + "utask"})
        project_link = {"contact_id": sam["id"], "project_id": project["id"]}
        await call("link_contact_to_project", {**project_link, "idempotency_key": key + "lprj2"})
        await call(
            "unlink_contact_from_project", {**project_link, "idempotency_key": key + "uprj2"}
        )

        await call(
            "restore_contact",
            {
                "contact_id": contact["id"],
                "expected_version": contact["version"] + 1,
                "idempotency_key": key + "rcon",
            },
        )

        # Processes, saved views, step archive and the trash.
        process = (
            await call(
                "create_process",
                {"domain_id": domain["id"], "name": "Weekly", "idempotency_key": key + "proc"},
            )
        )["process"]
        await call(
            "update_process",
            {
                "process_id": process["id"],
                "version": process["version"],
                "changes": {"name": "Fortnightly"},
                "idempotency_key": key + "uproc",
            },
        )
        view_def = {"view": "agenda", "context": "all", "sort": "due_asc", "tags": ["home"]}
        view = (
            await call(
                "create_saved_work_view",
                {"name": "Mine", "definition": view_def, "idempotency_key": key + "view"},
            )
        )["saved_view"]
        view = (
            await call(
                "update_saved_work_view",
                {
                    "view_id": view["id"],
                    "version": view["version"],
                    "name": "Mine too",
                    "idempotency_key": key + "uview",
                },
            )
        )["saved_view"]
        archived_view = (
            await call(
                "archive_saved_work_view",
                {
                    "view_id": view["id"],
                    "version": view["version"],
                    "idempotency_key": key + "aview",
                },
            )
        )["saved_view"]
        await call(
            "restore_saved_work_view",
            {
                "view_id": view["id"],
                "version": archived_view["version"],
                "idempotency_key": key + "rview",
            },
        )
        step3 = (
            await call(
                "create_task_step",
                {"task_id": live["id"], "title": "Three", "idempotency_key": key + "step3"},
            )
        )["step"]
        archived_step = (
            await call(
                "archive_task_step",
                {
                    "step_id": step3["id"],
                    "version": step3["version"],
                    "idempotency_key": key + "astep",
                },
            )
        )["step"]
        await call(
            "restore_task_step",
            {
                "step_id": step3["id"],
                "version": archived_step["version"],
                "idempotency_key": key + "rstep",
            },
        )
        trashed = (await call("create_task", {"title": "Bin", "idempotency_key": key + "tsk4"}))[
            "task"
        ]
        moved = await call(
            "move_to_trash",
            {
                "kind": "task",
                "record_id": trashed["id"],
                "version": trashed["version"],
                "idempotency_key": key + "trash",
            },
        )
        await call(
            "restore_from_trash",
            {
                "kind": "task",
                "record_id": trashed["id"],
                "version": moved["version"],
                "idempotency_key": key + "untrash",
            },
        )

        # Shopping: items, patch, purchase one and a batch, rename the list.
        added = await call(
            "add_shopping_items",
            {
                "list_id": shopping["id"],
                "items": [{"client_ref": "a", "name": "Milk"}, {"client_ref": "b", "name": "Eggs"}],
                "idempotency_key": key + "shop",
            },
        )
        first, second = (entry["item"] for entry in added["items"])
        await call(
            "update_shopping_item",
            {
                "item_id": first["id"],
                "item": {"name": "Oat milk"},
                "version": first["version"],
                "idempotency_key": key + "ushop",
            },
        )
        await call(
            "set_shopping_item_purchased",
            {
                "item_id": first["id"],
                "purchased": True,
                "version": first["version"] + 1,
                "idempotency_key": key + "bought",
            },
        )
        await call(
            "set_shopping_items_purchased",
            {
                "items": [{"item_id": second["id"], "version": second["version"]}],
                "purchased": True,
                "idempotency_key": key + "bought2",
            },
        )
        await call(
            "update_shopping_list",
            {
                "list_id": shopping["id"],
                "name": "Weekly shop",
                "archived": False,
                "version": shopping["version"],
                "idempotency_key": key + "ulist",
            },
        )

        # An external reference on a task, then removed; and a journal entry.
        reference = (
            await call(
                "link_external_reference_to_task",
                {
                    "task_id": live["id"],
                    "kind": "mail",
                    "provider": "google_gmail",
                    "account_ref": "corr@example.com",
                    "external_id": "corr-external-1",
                    "title": "Thread",
                    "idempotency_key": key + "xref",
                },
            )
        )["reference"]
        await call(
            "unlink_external_reference_from_task",
            {
                "task_id": live["id"],
                "reference_id": reference["id"],
                "idempotency_key": key + "uxref",
            },
        )
        await call(
            "write_journal_entry",
            {
                "journal_date": "2026-07-25",
                "title": "A day",
                "source_text": "Raked the leaves.",
                "idempotency_key": key + "jrnl",
            },
        )

        # Journal: a source and a manual entry, an edit, the day summary, and two reviewed drafts.
        day = "2026-07-21"
        source = (
            await call(
                "create_journal_source",
                {
                    "source_type": "manual_text",
                    "journal_date": day,
                    "raw_text": "Cleared the shed.",
                    "idempotency_key": key + "jsrc",
                },
            )
        )["source"]
        manual = (
            await call(
                "create_manual_journal_entry",
                {
                    "source_id": source["id"],
                    "title": "Shed",
                    "summary": None,
                    "key_points": [],
                    "project_ids": [],
                    "task_ids": [],
                    "contact_ids": [],
                    "idempotency_key": key + "jman",
                },
            )
        )["entry"]
        await call(
            "update_journal_entry",
            {
                "entry_id": manual["id"],
                "expected_version": manual["version"],
                "title": "Shed cleared",
                "summary": "Tidier.",
                "key_points": [{"kind": "decision", "text": "Keep it tidy."}],
                "idempotency_key": key + "ujrnl",
            },
        )
        fingerprint = (
            await client.call_tool("get_journal_day", {"journal_date": day})
        ).structured_content
        assert fingerprint is not None
        await call(
            "set_daily_journal_summary",
            {
                "journal_date": day,
                "summary_text": "A tidy day.",
                "expected_entry_fingerprint": fingerprint["entry_fingerprint"],
                "idempotency_key": key + "jsum",
            },
        )
        owner_actor = Actor(owner, frozenset(MCP_SCOPES))
        drafts: list[dict[str, Any]] = []
        for suffix in ("a", "b"):
            draft_source = (
                await call(
                    "create_journal_source",
                    {
                        "source_type": "manual_text",
                        "journal_date": day,
                        "raw_text": f"Draft source {suffix}.",
                        "idempotency_key": key + f"jdsrc{suffix}",
                    },
                )
            )["source"]
            draft_id = seed_entry_draft(
                container, owner_actor, UUID(draft_source["id"]), date.fromisoformat(day)
            )
            read = await client.call_tool("get_journal_draft", {"draft_id": str(draft_id)})
            assert read.structured_content is not None
            drafts.append(read.structured_content["draft"])
        keep, drop = drafts
        review = {
            "title": "Reviewed",
            "summary": None,
            "key_points": [],
            "task_proposals": keep["task_proposals"],
        }
        kept = (
            await call(
                "update_journal_draft",
                {
                    "draft_id": keep["id"],
                    "expected_version": keep["version"],
                    **review,
                    "idempotency_key": key + "udraft",
                },
            )
        )["draft"]
        await call(
            "finalize_journal_draft",
            {
                "draft_id": kept["id"],
                "expected_version": kept["version"],
                **review,
                "relation_selection": {"project_ids": [], "task_ids": [], "contact_ids": []},
                "idempotency_key": key + "fdraft",
            },
        )
        await call(
            "reject_journal_draft",
            {
                "draft_id": drop["id"],
                "expected_version": drop["version"],
                "idempotency_key": key + "rdraft",
            },
        )

        # Licence and memory settings. The test instance has no licence public key, so the key is
        # refused and the refusal is audited (closed reason, no key text) under the request's id.
        await call("set_license_key", {"key": "not-a-real-licence-key"})
        await call("set_memory_settings", {"expected_version": 1, "paused": True})
        await call("exclude_from_memory", {"kind": "task", "id": live["id"], "excluded": True})

    async with Client(server) as client:
        for name in REPLAYED:
            current["id"] = calls[name]
            await client.call_tool(name, first_args[name])

    exercised = set(calls)
    with admin() as session:
        rows = session.execute(
            text("SELECT id, event, correlation_id FROM sidekick.audit_events")
        ).all()
    written = [(event, corr) for row_id, event, corr in rows if row_id not in known]
    by_corr: dict[str, list[str]] = {}
    for event, corr in written:
        by_corr.setdefault(corr, []).append(event)

    assert exercised <= write_tools
    # Every row written by this scenario carries the correlation id of exactly one of its calls.
    assert [(event, corr) for event, corr in written if corr not in calls.values()] == []
    for name, corr in calls.items():
        if name in NO_AUDIT:
            assert corr not in by_corr, f"{name} is listed as unaudited but audits"
        else:
            assert corr in by_corr, f"{name} wrote no audit row with its correlation id"
    # The matrix is complete: every registry write tool is exercised or explicitly excepted.
    assert write_tools - exercised == NOT_EXERCISED
    assert set(NO_AUDIT) <= exercised
    # Replaying the reorder with the same key records the audit event once.
    assert by_corr[calls["reorder_work_board_column"]] == ["task.board_reordered"]
    # A replayed request adds no event: each tool left one event per distinct call it made.
    for name in REPLAYED:
        assert len(by_corr[calls[name]]) == call_counts[name], f"{name} audited a replay"

    # The events are content-free: no title, name or text the scenario wrote is in any row.
    with admin() as session:
        dumps = session.execute(
            text("SELECT id, to_jsonb(a)::text FROM sidekick.audit_events a")
        ).all()
    written_rows = " ".join(dump for row_id, dump in dumps if row_id not in known)
    for content in (
        "Garden",
        "Allotment",
        "Fortnightly",
        "Mine too",
        "One again",
        "Act again",
        "Reviewed",
        "Shed",
        "A tidy day",
        "Steps",
        "not-a-real-licence-key",
    ):
        assert content not in written_rows, f"audit rows carry {content!r}"

"""No MCP tool and no companion route reads or changes another owner's data.

Owner isolation is a hand-written `owner_id` filter in every query (there is no row-level security),
so this is the test that notices a query, a new tool or a nested identifier that forgot it. Two
owners are seeded with a record of every kind. The tools come from the running server
(`list_tools`) and the companion routes from the app (`app.routes`), never from a handwritten
list, so a new one is covered the moment it is registered.

For every tool, every place in its arguments that names a record (`task_id`, `project_ids`, the
`id` inside `items`, `changes.project_id`, `kind` + `record_id`, ...) is tried in turn with owner
A's record while owner B calls and every other place names B's own record. Then:

- a write tool must answer `not_found` and leave every row of the instance as it was;
- a read tool must answer `not_found` or an answer that holds nothing of A (no A marker, no A id
  that the call did not hand it);
- in all cases none of A's rows change.

A tool with no such place cannot be pointed at another owner's record; it is listed in
`NO_REFERENCE_TOOLS` with the reason, so a tool that gains a reference, or a new tool, fails here
until it is looked at. The same holds for the companion routes.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from sidekick.api.app import create_container
from sidekick.api.companion import create_companion_router
from sidekick.mcp.server import create_mcp_server
from tests.db import _cleanup_factory_for, database_factory
from tests.mcp.harness import ActorSwitch
from tests.support.companion import bearer, companion_app, paired_token
from tests.support.cross_owner_support import (
    JOURNAL_DATE,
    MARKER_A,
    MARKER_B,
    NAME_KIND,
    TRASHED_TOOLS,
    OwnerSeed,
    Slot,
    ToolShape,
    leaked,
    owner_digest,
    owner_tables,
    seed_owner,
    whole_digest,
)
from tests.support.settings import make_settings

# Tools whose input names no record at all. Each one reads or writes only the caller's own rows,
# so there is nothing to point at another owner's record; the baseline call still runs for B and
# is checked for leaks and for changes to A.
NO_REFERENCE_TOOLS: dict[str, str] = {
    "create_contact": "creates the caller's own Contact from text fields",
    "create_domain": "creates the caller's own Domain from text fields",
    "create_saved_work_view": "creates the caller's own view; the definition holds filters, no ids",
    "create_shopping_list": "creates the caller's own list from a name",
    "get_daily_journal_summary": "addressed by a date inside the caller's own journal",
    "get_journal_day": "addressed by a date inside the caller's own journal",
    "get_memory_status": "reads the caller's own memory settings and counts",
    "get_today_brief": "assembled from the caller's own parts, no input",
    "get_work_agenda": "filters are text and enums; reads the caller's own work",
    "list_assistant_activity": "pages the caller's own activity (the cursor is owner-bound)",
    "list_contacts": "pages the caller's own Contacts by text search",
    "list_domains": "pages the caller's own Domains",
    "list_journal_entries": "pages the caller's own entries by date range",
    "list_pending_journal": "lists the caller's own pending sources by date range",
    "list_projects": "pages the caller's own Projects",
    "list_recent_changes": "reads the caller's own change feed",
    "list_saved_work_views": "lists the caller's own views",
    "list_shopping_lists": "pages the caller's own lists",
    "list_tags": "pages the caller's own tags",
    "list_trash": "pages the caller's own trash",
    "recall_memory": "a text query over the caller's own memory",
    "search": "a text query over the caller's own records",
    "set_daily_journal_summary": "writes the caller's own day, addressed by date and fingerprint",
    "set_license_key": "an instance-wide setting; no owner data is read or written",
    "set_memory_settings": "writes the caller's own memory settings",
}

# A write that names a record inside a set the use case checks as a whole answers
# `validation_error` for a foreign record, as it does for any record outside the set. Still a
# refusal that changes nothing; the reason says which set.
REFUSES_WITH_VALIDATION: dict[str, str] = {
    "finalize_journal_draft": "relation ids must come from the draft's own candidate catalog",
    "reorder_work_board_column": "the items must be exactly the column's own active tasks",
    "reorder_task_steps": "the items must be exactly the task's own steps",
    "reorder_step_actions": "the items must be exactly the step's own actions",
}

# The same for one reference slot, where the other optional fields are left out: an entry update
# that names no link must name a change.
EXTRA_FOR_SLOT: dict[tuple[str, str], dict[str, Any]] = {
    ("update_journal_entry", "entry_id"): {"title": "Renamed entry", "key_points": []},
}

# Removing a link that is not there is a defined no-op ("No link changed"): it reads nothing of the
# record it names, changes nothing and answers with the caller's own entry.
NOOP_SUCCESS: dict[tuple[str, str], str] = {
    ("update_journal_entry", "remove_contact_ids"): "unlinking an absent Contact is a no-op",
    ("update_journal_entry", "remove_project_ids"): "unlinking an absent Project is a no-op",
}

# Tools with no reference whose generic sample is refused for a reason of the sample, not of
# ownership: the call is still made for B and checked for leaks and for changes to A.
BASELINE_MAY_BE_REFUSED: dict[str, str] = {
    "set_daily_journal_summary": "the sample fingerprint is not the day's current one (conflict)",
    "set_memory_settings": "the sample is not a complete settings change (validation_error)",
    "set_license_key": "an instance-wide setting no owner's scopes reach (forbidden)",
}

# Extra fields that make a generated call well formed (the generic sample is minimal).
EXTRA_ARGUMENTS: dict[str, dict[str, Any]] = {
    # The Process filter only means something together with include_tasks.
    "get_work_hierarchy": {"include_tasks": True},
    "update_saved_work_view": {"name": "Renamed view"},
    "update_shopping_item": {"item": {"name": "Milk"}},
}


def _code(result: CallToolResult) -> str | None:
    return (result.structured_content or {}).get("code") if result.is_error else None


def _detail(result: CallToolResult) -> str:
    return " ".join(getattr(part, "text", "") for part in result.content)[:300]


def _output(result: CallToolResult) -> Any:
    return [result.structured_content, [getattr(part, "text", "") for part in result.content]]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_mcp_tool_reads_or_changes_another_owners_data() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner_a = await seed_owner(container, "owner_a", MARKER_A)
    owner_b = await seed_owner(container, "owner_b", MARKER_B)
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    tables = owner_tables(admin)
    switch = ActorSwitch(owner_b.actor)
    server = create_mcp_server(container, actor_provider=switch, enable_auth=False)

    violations: list[str] = []
    no_reference: set[str] = set()
    covered: set[str] = set()
    scenarios = 0
    a_sees: set[str] = set()
    unseeded: set[str] = set()

    async def run(
        client: Client,
        tool: str,
        read_only: bool,
        shape: ToolShape,
        choice: dict[Any, str],
        foreign: Slot | None,
        caller: OwnerSeed,
        other: OwnerSeed,
    ) -> CallToolResult | None:
        def reference(slot: Slot) -> tuple[str, int | None]:
            owner = other if slot == foreign else caller
            key = ("trashed_" if tool in TRASHED_TOOLS else "") + slot.kind
            if key not in owner.records:
                unseeded.add(f"{tool}:{slot.label}")
                return "00000000-0000-0000-0000-000000000000", 1
            record = owner.records[key]
            return record.id, record.version

        extra = EXTRA_ARGUMENTS.get(tool, {}) | EXTRA_FOR_SLOT.get(
            (tool, str(foreign.path[0]) if foreign else ""), {}
        )
        arguments = shape.arguments(choice, reference, foreign, extra)
        if "idempotency_key" in arguments:
            arguments["idempotency_key"] = f"sweep-{scenarios}-{caller.name}-{os.urandom(4).hex()}"
        switch.use(caller.actor)
        before_a = owner_digest(admin, tables, owner_a.user_id)
        before_all = whole_digest(admin) if not read_only else {}
        result = await client.call_tool(tool, arguments, raise_on_error=False)
        label = f"{tool}@{foreign.label if foreign else 'own'}"
        if caller is owner_b:
            if owner_digest(admin, tables, owner_a.user_id) != before_a:
                violations.append(f"{label}: a row of owner A changed")
            found = leaked(_output(result), owner_a, arguments)
            if found:
                violations.append(f"{label}: the answer holds owner A's data {found}")
            accepted = {"not_found"}
            if tool in REFUSES_WITH_VALIDATION:
                accepted.add("validation_error")
            if foreign is not None:
                if read_only:
                    if result.is_error and _code(result) not in accepted:
                        violations.append(f"{label}: read refused with {_code(result)}")
                elif (tool, str(foreign.path[0])) in NOOP_SUCCESS and not result.is_error:
                    pass
                elif _code(result) not in accepted:
                    violations.append(
                        f"{label}: write answered {_code(result) or 'success'}: {_detail(result)}"
                    )
            if (
                foreign is not None
                and result.is_error
                and not read_only
                and whole_digest(admin) != before_all
            ):
                violations.append(f"{label}: a refused write still changed rows")
        return result

    async with Client(server) as client:
        for tool in await client.list_tools():
            read_only = bool(tool.annotations and tool.annotations.readOnlyHint)
            shape = ToolShape(tool.name, tool.inputSchema)
            reachable = False
            for choice in shape.kind_choices():
                slots = shape.slots(choice)
                reachable = reachable or bool(slots)
                for slot in slots:
                    scenarios += 1
                    await run(client, tool.name, read_only, shape, choice, slot, owner_b, owner_a)
                if read_only or not slots:
                    scenarios += 1
                    baseline = await run(
                        client, tool.name, read_only, shape, choice, None, owner_b, owner_a
                    )
                    assert baseline is not None
                    if baseline.is_error and tool.name not in BASELINE_MAY_BE_REFUSED:
                        violations.append(
                            f"{tool.name}@own: baseline refused with {_code(baseline)}: "
                            f"{_detail(baseline)}"
                        )
                if read_only:
                    control = await run(
                        client, tool.name, read_only, shape, choice, None, owner_a, owner_b
                    )
                    assert control is not None
                    if control.is_error:
                        violations.append(f"{tool.name}@control: owner A's own read refused")
                    elif any(needle in str(_output(control)) for needle in owner_a.needles):
                        a_sees.add(tool.name)
            (covered if reachable else no_reference).add(tool.name)

    assert unseeded == set(), f"slots with no seeded record: {sorted(unseeded)}"
    assert violations == [], "\n".join(violations)
    assert set(NO_REFERENCE_TOOLS) == no_reference, (
        f"unlisted: {sorted(no_reference - set(NO_REFERENCE_TOOLS))}, "
        f"stale: {sorted(set(NO_REFERENCE_TOOLS) - no_reference)}"
    )
    assert len(covered) > 50 and scenarios > 100
    # The leak check is only as good as its eyes: where A itself reads its data back, the markers
    # and ids are the ones it looks for.
    must_show = {
        "search",
        "list_contacts",
        "list_projects",
        "list_domains",
        "list_tags",
        "get_task",
    }
    assert must_show <= a_sees, f"A's own reads do not show its data: {sorted(must_show - a_sees)}"
    assert len(a_sees) > 15


# --- the companion routes ----------------------------------------------------------------------

COMPANION_PREFIX = "/companion/v1"

# Routes that are not called by the sweep, with the reason. They act on the calling device itself
# (its pairing, credential, push endpoint or licence view) and take no record of an owner.
COMPANION_NOT_CALLED: dict[str, str] = {
    "POST /pair": "exchanges a pairing secret; no owner credential, no record id",
    "GET /device": "the calling device's own status",
    "DELETE /device": "unpairs the calling device itself",
    "POST /device/renew": "renews the calling device's own credential",
    "PUT /push/subscription": "the calling device's own push endpoint",
    "DELETE /push/subscription": "the calling device's own push endpoint",
    "POST /push/test": "queues a notification to the calling device itself",
    "GET /reminders/pending": "the caller's own reminders; takes no id",
    "POST /reminders/ack": "acknowledges the caller's own reminders; its ids are reminder ids",
    "GET /license": "the instance's licence display state; no owner data",
    "PUT /license": "an instance-wide setting; no owner data",
}


# The body fields that make a route's generated call a change.
COMPANION_EXTRA: dict[str, dict[str, Any]] = {
    "POST /journal/entries/{entry_id}/update": {"title": "Renamed entry", "key_points": []},
}

# Routes with no record id in the path or the body: the owner is the credential's, so there is
# nothing to point at another owner. The baseline call still runs for B and is checked for leaks.
COMPANION_NO_REFERENCE: dict[str, str] = {
    "GET /journal/days/{journal_date}": "addressed by a date inside the caller's own journal",
    "GET /journal/entries": "pages the caller's own entries by date range",
    "GET /shopping/lists": "pages the caller's own lists",
    "POST /shopping/lists": "creates the caller's own list from a name",
    "GET /work/agenda": "filters are text and enums; reads the caller's own work",
    "GET /work/hierarchy": "reads the caller's own work; its Process filter has own tests",
    "GET /work/today": "reads the caller's own Idag, a limit only",
}


def _route_key(method: str, path: str) -> str:
    return f"{method} {path.removeprefix(COMPANION_PREFIX)}"


def test_no_companion_route_reads_or_changes_another_owners_data() -> None:
    app = companion_app()
    container = app.state.container
    owner_a = asyncio.run(seed_owner(container, "owner_a", MARKER_A))
    owner_b = asyncio.run(seed_owner(container, "owner_b", MARKER_B))
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    tables = owner_tables(admin)
    violations: list[str] = []
    seen_routes: set[str] = set()
    no_reference_routes: set[str] = set()
    scenarios = 0
    a_sees: set[str] = set()
    unseeded: set[str] = set()
    companion_router = create_companion_router()

    def body_of(route: Any) -> Any:
        spec = companion_router.spec_for(route)
        return spec.body if spec is not None else None

    with TestClient(app) as client:
        tokens = {
            owner.name: paired_token(client, app, owner.user_id) for owner in (owner_a, owner_b)
        }

        def call(
            route: Any,
            method: str,
            foreign: tuple[str, Slot] | None,
            caller: OwnerSeed,
            other: OwnerSeed,
        ) -> Any:
            def reference(slot: Slot, where: str = "body") -> tuple[str, int | None]:
                owner = other if foreign == (where, slot) else caller
                if slot.kind not in owner.records:
                    unseeded.add(f"{method} {route.path}:{slot.label}")
                    return str(uuid4()), 1
                record = owner.records[slot.kind]
                return record.id, record.version

            path = route.path
            versions: list[int] = []
            for name in route.param_convertors:
                if name == "journal_date":
                    path = path.replace("{journal_date}", JOURNAL_DATE)
                    continue
                kind = NAME_KIND.get(name, "")
                slot = Slot((name,), kind)
                record_id, version = reference(slot, "path")
                path = path.replace("{" + name + "}", record_id)
                if version is not None:
                    versions.append(version)
            body_spec = body_of(route)
            kwargs: dict[str, Any] = {"headers": bearer(tokens[caller.name])}
            if method != "GET":
                kwargs["headers"] |= {"Idempotency-Key": f"sweep-{uuid4().hex}"}
                if body_spec is not None:
                    shape = ToolShape("route", body_spec.model.model_json_schema())
                    body_choice = shape.kind_choices()[0]
                    body_slot = foreign[1] if foreign and foreign[0] == "body" else None
                    body = shape.arguments(
                        body_choice,
                        reference,
                        body_slot,
                        COMPANION_EXTRA.get(_route_key(method, route.path), {}),
                    )
                    if "version" in body:
                        body["version"] = versions[0] if versions else 1
                    kwargs["json"] = body
            query_names = {field.name for field in route.dependant.query_params}
            query = {name: MARKER_A for name in ("q",) if name in query_names}
            return client.request(method, path, params=query, **kwargs), kwargs.get("json", {})

        for route in companion_router.routes:
            path = route.path  # type: ignore[attr-defined]
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                key = _route_key(method, path)
                seen_routes.add(key)
                if key in COMPANION_NOT_CALLED:
                    continue
                body_spec = body_of(route)
                body_slots = (
                    ToolShape("route", body_spec.model.model_json_schema()).slots({})
                    if body_spec is not None and method != "GET"
                    else []
                )
                path_slots = [
                    Slot((name,), NAME_KIND[name])
                    for name in route.param_convertors
                    if name in NAME_KIND
                ]
                if not (path_slots or body_slots):
                    no_reference_routes.add(key)
                for where, slot in [
                    *(("path", slot) for slot in path_slots),
                    *(("body", slot) for slot in body_slots),
                ]:
                    scenarios += 1
                    before_a = owner_digest(admin, tables, owner_a.user_id)
                    before_all = whole_digest(admin)
                    response, sent = call(route, method, (where, slot), owner_b, owner_a)
                    label = f"{key}@{where}:{slot.label}"
                    if owner_digest(admin, tables, owner_a.user_id) != before_a:
                        violations.append(f"{label}: a row of owner A changed")
                    found = leaked(response.text, owner_a, sent)
                    if found:
                        violations.append(f"{label}: the answer holds owner A's data {found}")
                    if method == "GET":
                        if response.status_code not in (200, 404):
                            violations.append(f"{label}: read answered {response.status_code}")
                    elif response.status_code != 404:
                        violations.append(
                            f"{label}: write answered {response.status_code} {response.text[:160]}"
                        )
                    elif whole_digest(admin) != before_all:
                        violations.append(f"{label}: a refused write still changed rows")
                if method == "GET" or not (path_slots or body_slots):
                    scenarios += 1
                    response, sent = call(route, method, None, owner_b, owner_a)
                    if not 200 <= response.status_code < 300 or leaked(
                        response.text, owner_a, sent
                    ):
                        violations.append(f"{key}@own: {response.status_code} or a leak")
                    if method != "GET":
                        continue
                    control, _ = call(route, method, None, owner_a, owner_b)
                    if control.status_code != 200:
                        violations.append(
                            f"{key}@control: A's own read answered {control.status_code}"
                        )
                    elif any(needle in control.text for needle in owner_a.needles):
                        a_sees.add(key)

    assert unseeded == set(), f"slots with no seeded record: {sorted(unseeded)}"
    assert violations == [], "\n".join(violations)
    assert set(COMPANION_NOT_CALLED) <= seen_routes, "a listed route is gone"
    assert no_reference_routes == set(COMPANION_NO_REFERENCE), (
        f"unlisted: {sorted(no_reference_routes - set(COMPANION_NO_REFERENCE))}, "
        f"stale: {sorted(set(COMPANION_NO_REFERENCE) - no_reference_routes)}"
    )
    assert len(seen_routes) > 25 and scenarios > 25
    assert len(a_sees) > 5, f"A's own reads show nothing of A: {sorted(a_sees)}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_owner_cannot_use_another_owners_page_cursor() -> None:
    """A cursor A got from a page is no key to A's data for B: B's answer holds none of A's."""

    container = create_container(make_settings(), database_factory())
    owner_a = await seed_owner(container, "owner_a", MARKER_A)
    owner_b = await seed_owner(container, "owner_b", MARKER_B)
    switch = ActorSwitch(owner_a.actor)
    server = create_mcp_server(container, actor_provider=switch, enable_auth=False)
    leaks: list[str] = []
    paged: set[str] = set()

    async with Client(server) as client:
        for tool in await client.list_tools():
            properties = tool.inputSchema.get("properties", {})
            read_only = bool(tool.annotations and tool.annotations.readOnlyHint)
            if not read_only or "cursor" not in properties:
                continue
            shape = ToolShape(tool.name, tool.inputSchema)
            for choice in shape.kind_choices():

                def by(owner: OwnerSeed, tool_name: str = tool.name) -> Any:
                    def reference(slot: Slot) -> tuple[str, int | None]:
                        record = owner.records[
                            ("trashed_" if tool_name in TRASHED_TOOLS else "") + slot.kind
                        ]
                        return record.id, record.version

                    return reference

                switch.use(owner_a.actor)
                arguments = shape.arguments(choice, by(owner_a))
                if "limit" in properties:
                    arguments["limit"] = 1
                first = await client.call_tool(tool.name, arguments, raise_on_error=False)
                cursor = (first.structured_content or {}).get("next_cursor")
                if first.is_error or not cursor:
                    continue
                paged.add(tool.name)
                switch.use(owner_b.actor)
                stolen = shape.arguments(choice, by(owner_b)) | {"cursor": cursor}
                if "limit" in properties:
                    stolen["limit"] = 1
                answer = await client.call_tool(tool.name, stolen, raise_on_error=False)
                found = leaked(_output(answer), owner_a, stolen)
                if found:
                    leaks.append(f"{tool.name}: {found}")

    assert leaks == []
    assert len(paged) >= 4, f"too few paged tools to mean anything: {sorted(paged)}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_owners_idempotency_key_replays_nothing() -> None:
    """The same key and the same arguments from two owners make two records, never A's reply."""

    container = create_container(make_settings(), database_factory())
    owner_a = await seed_owner(container, "owner_a", MARKER_A)
    owner_b = await seed_owner(container, "owner_b", MARKER_B)
    switch = ActorSwitch(owner_a.actor)
    server = create_mcp_server(container, actor_provider=switch, enable_auth=False)
    calls = {
        "create_domain": ("domain", {"name": "Shared name"}),
        "create_task": ("task", {"title": "Shared title"}),
        "create_contact": ("contact", {"display_name": "Shared name"}),
        "create_shopping_list": ("shopping_list", {"name": "Shared name"}),
    }
    async with Client(server) as client:
        for tool, (key, arguments) in calls.items():
            arguments = {**arguments, "idempotency_key": f"shared-key-{tool}"}
            switch.use(owner_a.actor)
            first = await client.call_tool(tool, arguments)
            switch.use(owner_b.actor)
            second = await client.call_tool(tool, arguments)
            assert first.structured_content and second.structured_content
            assert first.structured_content[key]["id"] != second.structured_content[key]["id"], tool

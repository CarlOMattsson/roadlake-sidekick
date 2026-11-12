"""The companion adapter's public surface and argument parity, without a database (ADR-005)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import create_model

from sidekick.api.companion import create_companion_router
from sidekick.api.public_surface import COMPANION_ROUTES, is_companion_route, is_public_path
from sidekick.companion.operations import OPERATIONS
from sidekick.shared.auth import (
    ALL_SCOPES,
    COMPANION_SCOPES,
    MCP_SCOPES,
    OPT_IN_SCOPES,
    TOKEN_SCOPES,
)
from sidekick.shared.types import MAX_CURSOR_LENGTH

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
TASK = "0192f0e0-1234-7abc-8def-0123456789ab"
PROJECT = "0192f0e0-1234-7abc-8def-0123456789ac"
DOMAIN = "0192f0e0-1234-7abc-8def-0123456789ad"
PROCESS = "0192f0e0-1234-7abc-8def-0123456789ae"
STEP = "0192f0e0-1234-7abc-8def-0123456789af"
PATH_PARAMETERS = {
    "{task_id}": TASK,
    "{project_id}": PROJECT,
    "{domain_id}": DOMAIN,
    "{process_id}": PROCESS,
    "{step_id}": STEP,
    # Inköp and Dagbok (sidekick.api.companion_rooms)
    "{list_id}": TASK,
    "{item_id}": TASK,
    "{entry_id}": TASK,
    "{source_id}": TASK,
    "{journal_date}": "2026-11-09",
}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/companion/v1/pair"),
        ("GET", "/companion/v1/device"),
        ("DELETE", "/companion/v1/device"),
        ("POST", "/companion/v1/device/renew"),
        ("PUT", "/companion/v1/push/subscription"),
        ("DELETE", "/companion/v1/push/subscription"),
        ("POST", "/companion/v1/push/test"),
        ("GET", "/companion/v1/reminders/pending"),
        ("POST", "/companion/v1/reminders/ack"),
        ("GET", "/companion/v1/work/agenda"),
        ("GET", "/companion/v1/work/today"),
        ("GET", f"/companion/v1/tasks/{TASK}"),
        ("GET", f"/companion/v1/tasks/{TASK}/steps"),
        ("GET", f"/companion/v1/tasks/{TASK}/contacts"),
        ("GET", f"/companion/v1/tasks/{TASK}/external-references"),
        ("POST", f"/companion/v1/tasks/{TASK}/complete"),
        ("POST", f"/companion/v1/tasks/{TASK}/reopen"),
        ("GET", "/companion/v1/work/hierarchy"),
        ("GET", f"/companion/v1/projects/{PROJECT}"),
        ("GET", f"/companion/v1/projects/{PROJECT}/tasks"),
        ("GET", f"/companion/v1/domains/{DOMAIN}"),
        ("GET", f"/companion/v1/processes/{PROCESS}"),
        ("POST", f"/companion/v1/steps/{STEP}/complete"),
        ("POST", f"/companion/v1/steps/{STEP}/reopen"),
        ("GET", "/companion/v1/shopping/lists"),
        ("GET", f"/companion/v1/shopping/lists/{TASK}"),
        ("POST", "/companion/v1/shopping/lists"),
        ("POST", f"/companion/v1/shopping/lists/{TASK}/update"),
        ("POST", f"/companion/v1/shopping/lists/{TASK}/items"),
        ("POST", f"/companion/v1/shopping/items/{TASK}/update"),
        ("POST", f"/companion/v1/shopping/items/{TASK}/purchased"),
        ("GET", "/companion/v1/journal/days/2026-11-09"),
        ("GET", "/companion/v1/journal/entries"),
        ("GET", f"/companion/v1/journal/entries/{TASK}"),
        ("GET", f"/companion/v1/journal/sources/{TASK}"),
        ("POST", "/companion/v1/journal/entries"),
        ("POST", f"/companion/v1/journal/entries/{TASK}/update"),
        ("GET", "/companion/v1/license"),
        ("PUT", "/companion/v1/license"),
    ],
)
def test_the_companion_routes_are_public_by_method_and_path(method: str, path: str) -> None:
    assert is_companion_route(method, path)
    # Never by the ordinary path allowlist: only with the companion switch.
    assert not is_public_path(path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/companion/v1/pair"),
        ("PUT", "/companion/v1/device"),
        ("GET", "/companion/v1/device/renew"),
        ("PUT", "/companion/v1/device/renew"),
        ("POST", "/companion/v1/device/renew/"),
        ("GET", "/companion/v1/push/subscription"),
        ("POST", "/companion/v1/push/subscription"),
        ("PATCH", "/companion/v1/push/subscription"),
        ("PUT", "/companion/v1/push/subscription/"),
        ("PUT", "/companion/v1/push"),
        ("PUT", "/companion/v1/push/test"),
        ("GET", "/companion/v1/push/test"),
        ("POST", "/companion/v1/reminders/pending"),
        ("GET", "/companion/v1/reminders/ack"),
        ("DELETE", "/companion/v1/reminders/ack"),
        ("GET", "/companion/v1/reminders"),
        ("POST", "/companion/v1/work/agenda"),
        ("POST", "/companion/v1/work/today"),
        ("GET", "/companion/v1/work/today/"),
        ("GET", "/companion/v1/work/todays"),
        ("GET", "/companion/v1/work/Today"),
        ("DELETE", f"/companion/v1/tasks/{TASK}"),
        ("GET", f"/companion/v1/tasks/{TASK}/complete"),
        ("POST", f"/companion/v1/tasks/{TASK.upper()}/complete"),
        ("POST", f"/companion/v1/tasks/{TASK}/complete/"),
        ("POST", f"/companion/v1/tasks/{TASK}/update"),
        ("POST", f"/companion/v1/tasks/{TASK}/contacts"),
        ("DELETE", f"/companion/v1/tasks/{TASK}/external-references"),
        ("GET", f"/companion/v1/tasks/{TASK}/contacts/"),
        ("GET", f"/companion/v1/tasks/{TASK}/contacts/{TASK}"),
        ("GET", f"/companion/v1/tasks/{TASK.upper()}/external-references"),
        ("GET", "/companion/v1/tasks/../../api/v1/tasks"),
        ("GET", f"/companion/v1/tasks/{TASK}/../../work/agenda"),
        ("GET", "/companion/v1/"),
        ("GET", "/companion/v2/work/agenda"),
        ("GET", "//companion/v1/work/agenda"),
        ("GET", "/companion/v1/work/agenda/"),
        ("GET", "/companion/v1/devices"),
        ("POST", "/api/v1/tasks"),
        # Arbete: one verb and one exact path each.
        ("POST", "/companion/v1/work/hierarchy"),
        ("GET", "/companion/v1/work/hierarchy/"),
        ("GET", "/companion/v1/work/Hierarchy"),
        ("GET", "/companion/v1/work/hierarchy/nodes"),
        ("GET", "/companion/v1/projects"),
        ("GET", "/companion/v1/projects/"),
        ("POST", "/companion/v1/projects"),
        ("DELETE", f"/companion/v1/projects/{PROJECT}"),
        ("PUT", f"/companion/v1/projects/{PROJECT}"),
        ("POST", f"/companion/v1/projects/{PROJECT}"),
        ("GET", f"/companion/v1/projects/{PROJECT.upper()}"),
        ("GET", f"/companion/v1/projects/{PROJECT}/"),
        ("GET", f"/companion/v1/projects/{PROJECT}/tasks/"),
        ("POST", f"/companion/v1/projects/{PROJECT}/tasks"),
        ("GET", f"/companion/v1/projects/{PROJECT.upper()}/tasks"),
        ("GET", f"/companion/v1/projects/{PROJECT}/tasks/{TASK}"),
        ("GET", f"/companion/v1/projects/{PROJECT}/steps"),
        ("GET", f"/companion/v1/projects/{PROJECT}/../../api/v1/tasks"),
        ("GET", "/companion/v1/domains"),
        ("POST", f"/companion/v1/domains/{DOMAIN}"),
        ("DELETE", f"/companion/v1/domains/{DOMAIN}"),
        ("GET", f"/companion/v1/domains/{DOMAIN.upper()}"),
        ("GET", f"/companion/v1/domains/{DOMAIN}/"),
        ("GET", f"/companion/v1/domains/{DOMAIN}/projects"),
        ("GET", "/companion/v1/processes"),
        ("POST", f"/companion/v1/processes/{PROCESS}"),
        ("DELETE", f"/companion/v1/processes/{PROCESS}"),
        ("GET", f"/companion/v1/processes/{PROCESS.upper()}"),
        ("GET", f"/companion/v1/processes/{PROCESS}/"),
        ("GET", f"/companion/v1/processes/{PROCESS}/tasks"),
        ("GET", f"/companion/v1/steps/{STEP}"),
        ("GET", f"/companion/v1/steps/{STEP}/complete"),
        ("GET", f"/companion/v1/steps/{STEP}/reopen"),
        ("PUT", f"/companion/v1/steps/{STEP}/complete"),
        ("DELETE", f"/companion/v1/steps/{STEP}"),
        ("POST", f"/companion/v1/steps/{STEP}"),
        ("POST", f"/companion/v1/steps/{STEP.upper()}/complete"),
        ("POST", f"/companion/v1/steps/{STEP.upper()}/reopen"),
        ("POST", f"/companion/v1/steps/{STEP}/complete/"),
        ("POST", f"/companion/v1/steps/{STEP}/reopen/"),
        ("POST", f"/companion/v1/steps/{STEP}/update"),
        ("POST", f"/companion/v1/steps/{STEP}/actions"),
        ("POST", f"/companion/v1/steps/{STEP}/complete/extra"),
        ("POST", "/companion/v1/steps/complete"),
        ("POST", f"/companion/v1/steps/{STEP}/../../tasks/{TASK}/complete"),
        # Singular resource names are not the plural ones.
        ("POST", f"/companion/v1/step/{STEP}/complete"),
        ("GET", f"/companion/v1/project/{PROJECT}"),
        ("PUT", "/companion/v1/shopping/lists"),
        ("DELETE", f"/companion/v1/shopping/lists/{TASK}"),
        ("POST", f"/companion/v1/shopping/lists/{TASK}"),
        ("GET", f"/companion/v1/shopping/lists/{TASK}/items"),
        ("GET", f"/companion/v1/shopping/items/{TASK}"),
        ("POST", f"/companion/v1/shopping/items/{TASK}/delete"),
        ("POST", f"/companion/v1/shopping/items/{TASK.upper()}/purchased"),
        ("POST", "/companion/v1/shopping/lists/"),
        ("GET", "/companion/v1/shopping"),
        ("GET", "/companion/v1/journal/days"),
        ("GET", "/companion/v1/journal/days/today"),
        ("GET", "/companion/v1/journal/days/2026-11-09/"),
        ("POST", "/companion/v1/journal/days/2026-11-09"),
        ("DELETE", f"/companion/v1/journal/entries/{TASK}"),
        ("PUT", f"/companion/v1/journal/entries/{TASK}"),
        ("POST", f"/companion/v1/journal/entries/{TASK}"),
        ("GET", f"/companion/v1/journal/entries/{TASK}/update"),
        ("GET", f"/companion/v1/journal/entries/{TASK}/source"),
        ("POST", f"/companion/v1/journal/sources/{TASK}"),
        ("GET", f"/companion/v1/journal/sources/{TASK}/raw"),
        ("GET", "/companion/v1/journal/sources"),
        ("GET", "/companion/v1/journal/drafts"),
        ("GET", "/companion/v1/journal/pending"),
        ("POST", f"/companion/v1/journal/drafts/{TASK}/finalize"),
        ("GET", "/companion/v1/journal/summary"),
        # The license key: one path, two verbs, nothing else (D-081).
        ("POST", "/companion/v1/license"),
        ("DELETE", "/companion/v1/license"),
        ("PATCH", "/companion/v1/license"),
        ("GET", "/companion/v1/license/"),
        ("PUT", "/companion/v1/license/"),
        ("PUT", "/companion/v1/License"),
        ("GET", "/companion/v1/licenses"),
        ("GET", "/companion/v1/license/key"),
        ("PUT", f"/companion/v1/license/{TASK}"),
    ],
)
def test_everything_else_under_companion_is_not_public(method: str, path: str) -> None:
    assert not is_companion_route(method, path)


def _concrete(path: str) -> str:
    for placeholder, value in PATH_PARAMETERS.items():
        path = path.replace(placeholder, value)
    return path


def test_every_registered_route_is_on_the_allowlist_and_nothing_more() -> None:
    router = create_companion_router()
    registered = {
        (method, route.path)
        for route in router.routes
        for method in route.methods  # type: ignore[attr-defined]
    }
    concrete = {(method, _concrete(path)) for method, path in registered}
    assert all(is_companion_route(method, path) for method, path in concrete)
    assert len(concrete) == len(COMPANION_ROUTES)
    # No path parameter is left unreplaced, so every route was checked against its pattern.
    assert not any("{" in path for _method, path in concrete)


def test_companion_scopes_are_opt_in_device_capabilities_only() -> None:
    assert {
        "companion:tasks:read",
        "companion:tasks:complete",
        "companion:push",
        "companion:shopping:read",
        "companion:shopping:write",
        "companion:journal:read",
        "companion:journal:write",
        "companion:license",
    } == COMPANION_SCOPES
    for application_scopes in (ALL_SCOPES, TOKEN_SCOPES, OPT_IN_SCOPES, frozenset(MCP_SCOPES)):
        assert not COMPANION_SCOPES & application_scopes
    for operation in OPERATIONS:
        assert operation.capability in COMPANION_SCOPES
        assert operation.also is None or operation.also in COMPANION_SCOPES
        # The fixed application scopes never include administration or Contact writes.
        assert operation.application_scopes <= {
            "tasks:read",
            "tasks:write",
            "projects:read",
            "contacts:read",
            "shopping:read",
            "shopping:write",
            "journal:read",
            "journal:write",
        }
    # The push registration reaches no use case at all: it holds no application scope.
    by_name = {item.name: item for item in OPERATIONS}
    assert by_name["push.subscription"].application_scopes == frozenset()
    assert by_name["push.subscription"].capability == "companion:push"
    assert by_name["push.reminders"].application_scopes == frozenset()
    assert by_name["push.reminders"].capability == "companion:push"
    writers = {item.name for item in OPERATIONS if "tasks:write" in item.application_scopes}
    assert writers == {"task.complete", "task.reopen", "step.complete", "step.reopen"}
    assert all(
        item.capability == "companion:tasks:complete" for item in OPERATIONS if item.name in writers
    )


def test_a_room_write_needs_its_write_and_its_read_capability_and_nothing_else_writes() -> None:
    by_name = {item.name: item for item in OPERATIONS}
    for name, operation in by_name.items():
        scopes = operation.application_scopes
        writes = {"shopping:write", "journal:write"} & scopes
        if not writes:
            continue
        room = "shopping" if "shopping:write" in scopes else "journal"
        assert name.startswith(f"{room}.")
        assert operation.capability == f"companion:{room}:write"
        assert operation.also == f"companion:{room}:read"
    reads = [item for item in OPERATIONS if item.capability.endswith(":read")]
    assert all(item.also is None for item in reads)
    # No operation reaches a Journal draft, summary or pending-list use case (D-076); the one source
    # operation only reads the text of a source back (the hand-written entry has no summary).
    assert not {name for name in by_name if "draft" in name or "summary" in name}
    assert [name for name in by_name if "source" in name] == ["journal.source"]
    assert by_name["journal.source"].application_scopes == {"journal:read"}


def test_the_journal_operations_hold_exactly_the_scopes_of_their_mcp_tools() -> None:
    from sidekick.mcp.journal import JOURNAL_TOOL_SCOPES

    by_name = {item.name: item for item in OPERATIONS}
    pairs = {
        "journal.day": "get_journal_day",
        "journal.entries": "list_journal_entries",
        "journal.entry": "get_journal_entry",
        "journal.source": "get_journal_source",
        "journal.entry_write": "write_journal_entry",
        "journal.entry_update": "update_journal_entry",
    }
    for operation, tool in pairs.items():
        assert by_name[operation].application_scopes == frozenset(JOURNAL_TOOL_SCOPES[tool])


def _plain(schema: Any, defs: dict[str, Any]) -> Any:
    """The schema with refs resolved and the cosmetic title/description keys dropped."""

    if isinstance(schema, dict):
        if "$ref" in schema:
            return _plain(defs[schema["$ref"].rsplit("/", 1)[1]], defs)
        return {
            key: _plain(value, defs)
            for key, value in schema.items()
            if key not in {"title", "description"}
        }
    if isinstance(schema, list):
        return [_plain(item, defs) for item in schema]
    return schema


def _companion_query_schema(path_suffix: str) -> dict[str, Any]:
    router = create_companion_router()
    route = next(item for item in router.routes if item.path.endswith(path_suffix))  # type: ignore[attr-defined]
    fields = {
        field.name: (field.field_info.annotation, field.field_info)
        for field in route.dependant.query_params  # type: ignore[attr-defined]
    }
    model = create_model("CompanionQuery", **fields)  # type: ignore[call-overload]
    schema = model.model_json_schema()
    return _plain(schema["properties"], schema.get("$defs", {}))


def _mcp_input_schema(tool: str, *, without: frozenset[str] = frozenset()) -> dict[str, Any]:
    snapshot = json.loads((CONTRACTS / "mcp-tools.generated.json").read_text(encoding="utf-8"))
    schema = next(item for item in snapshot if item["name"] == tool)["inputSchema"]
    properties = {key: value for key, value in schema["properties"].items() if key not in without}
    return _plain(properties, schema.get("$defs", {}))


def test_the_agenda_query_takes_exactly_the_mcp_arguments_and_bounds() -> None:
    assert _companion_query_schema("/work/agenda") == _mcp_input_schema("get_work_agenda")


def test_the_today_route_is_a_read_of_the_task_capability_with_a_bounded_query() -> None:
    by_name = {item.name: item for item in OPERATIONS}
    assert by_name["work.today"].capability == "companion:tasks:read"
    assert by_name["work.today"].application_scopes == {"tasks:read", "projects:read"}
    query = _companion_query_schema("/work/today")
    assert set(query) == {"limit", "cursor"}
    assert (query["limit"]["minimum"], query["limit"]["maximum"], query["limit"]["default"]) == (
        1,
        50,
        20,
    )
    assert query["cursor"]["anyOf"][0]["maxLength"] == MAX_CURSOR_LENGTH


def test_the_companion_envelope_treats_only_rejected_client_values_as_bad_requests() -> None:
    from sidekick.api.companion import _translate
    from sidekick.shared.errors import InvalidInputError

    rejected = _translate(InvalidInputError("invalid pagination cursor"))
    assert rejected is not None and (rejected.status, rejected.code) == (400, "bad_request")
    # A stray ValueError is a defect: no envelope here, so it becomes an internal error.
    assert _translate(ValueError("invalid pagination cursor")) is None


def test_the_caddy_example_forwards_exactly_the_allowlisted_get_paths() -> None:
    caddy = (CONTRACTS.parent / "deploy/selfhost/Caddyfile.example").read_text(encoding="utf-8")
    assert "(device|reminders/pending|work/agenda|work/today|tasks/" in caddy


def test_the_step_ticks_hold_only_the_task_write_scope_and_the_complete_capability() -> None:
    by_name = {item.name: item for item in OPERATIONS}
    for name in ("step.complete", "step.reopen"):
        assert by_name[name].application_scopes == {"tasks:write"}
        assert by_name[name].capability == "companion:tasks:complete"


def test_the_work_reads_hold_the_read_capability_and_no_write_scope() -> None:
    by_name = {item.name: item for item in OPERATIONS}
    reads = ("work.hierarchy", "project.get", "project.tasks", "domain.get", "process.get")
    for name in reads:
        assert by_name[name].capability == "companion:tasks:read"
        assert by_name[name].application_scopes
        assert not {scope for scope in by_name[name].application_scopes if scope.endswith(":write")}
    # The Project reads and the hierarchy (include_tasks) open Tasks; Domain and Process never do.
    assert by_name["work.hierarchy"].application_scopes == {"projects:read", "tasks:read"}
    assert by_name["domain.get"].application_scopes == {"projects:read"}
    assert by_name["process.get"].application_scopes == {"projects:read"}
    assert by_name["project.get"].application_scopes == {"projects:read", "tasks:read"}
    assert by_name["project.tasks"].application_scopes == {"projects:read", "tasks:read"}


def test_every_operation_marks_exactly_one_registered_route() -> None:
    names = [item.name for item in OPERATIONS]
    assert len(names) == len(set(names))
    router = create_companion_router()
    marked = [spec.operation for spec in router.specs]
    # The pairing, device and reminder routes carry marks of their own; every Task and Arbete
    # operation marks exactly one route, so each route is checked against one capability.
    assert len(marked) == len(set(marked))
    arbete = {name for name in names if name.split(".")[0] != "push"}
    assert arbete <= set(marked)


def test_the_caddy_example_forwards_the_push_subscription_by_exact_method_and_path() -> None:
    caddy = (CONTRACTS.parent / "deploy/selfhost/Caddyfile.example").read_text(encoding="utf-8")
    assert "method PUT\n\t\tpath /companion/v1/push/subscription\n" in caddy
    assert "path /companion/v1/device /companion/v1/push/subscription\n" in caddy
    # No pattern lets anything else under push/ through.
    assert "push/*" not in caddy and "push/(" not in caddy


def test_the_caddy_example_forwards_the_push_test_and_the_reminder_ack_as_exact_posts() -> None:
    caddy = (CONTRACTS.parent / "deploy/selfhost/Caddyfile.example").read_text(encoding="utf-8")
    assert "/companion/v1/(pair|device/renew|push/test|reminders/ack|tasks/" in caddy
    assert "reminders/*" not in caddy and "reminders/(" not in caddy


def test_the_caddy_example_forwards_the_work_routes_by_exact_method_and_path() -> None:
    caddy = (CONTRACTS.parent / "deploy/selfhost/Caddyfile.example").read_text(encoding="utf-8")
    uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    get_matcher = (
        "@companion_get_work {\n\t\tmethod GET\n"
        f"\t\tpath_regexp ^/companion/v1/(work/hierarchy|projects/{uuid}(/tasks)?"
        f"|(domains|processes)/{uuid})$\n\t}}\n"
    )
    post_matcher = (
        "@companion_post_work {\n\t\tmethod POST\n"
        f"\t\tpath_regexp ^/companion/v1/steps/{uuid}/(complete|reopen)$\n\t}}\n"
    )
    assert get_matcher in caddy
    assert post_matcher in caddy
    # Each matcher is used by a handler; the POST one caps the body like the other POSTs.
    assert "handle @companion_get_work {\n\t\treverse_proxy api:8000\n\t}" in caddy
    assert (
        "handle @companion_post_work {\n\t\trequest_body {\n\t\t\tmax_size 4KB\n\t\t}\n"
        "\t\treverse_proxy api:8000\n\t}"
    ) in caddy
    # Anchored on both ends, with no wildcard or prefix match anywhere in the two matchers.
    for matcher in (get_matcher, post_matcher):
        regexp = matcher.split("path_regexp ", 1)[1]
        assert regexp.startswith("^/companion/v1/") and regexp.split("\n", 1)[0].endswith("$")
        for forbidden in ("*", ".*", ".+", "(.*)", "[^/]"):
            assert forbidden not in regexp
    # No UUID segment reaches the access log: it logs a fixed route class, never the path.
    assert "log_append route {route_class}" in caddy
    assert "log_append path" not in caddy


def test_the_steps_query_takes_the_mcp_limit() -> None:
    assert _companion_query_schema("/steps") == _mcp_input_schema(
        "list_task_steps", without=frozenset({"task_id"})
    )


def _companion_route_query_schema(path: str) -> dict[str, Any]:
    """The query schema of the route registered at exactly `path` (not by its ending)."""

    router = create_companion_router()
    route = next(item for item in router.routes if item.path == path)  # type: ignore[attr-defined]
    fields = {
        field.name: (field.field_info.annotation, field.field_info)
        for field in route.dependant.query_params  # type: ignore[attr-defined]
    }
    model = create_model("CompanionQuery", **fields)  # type: ignore[call-overload]
    schema = model.model_json_schema()
    return _plain(schema["properties"], schema.get("$defs", {}))


def test_the_project_tasks_query_takes_the_mcp_limit_and_cursor_only() -> None:
    query = _companion_route_query_schema("/companion/v1/projects/{project_id}/tasks")
    mcp = _mcp_input_schema("list_tasks")
    # `project_id` comes from the path; the other list_tasks filters are deliberately not taken.
    assert set(query) == {"limit", "cursor"}
    assert {"project_id", "process_id", "status", "unsorted"} <= set(mcp)
    assert query == {key: mcp[key] for key in ("limit", "cursor")}


def test_the_hierarchy_query_takes_the_mcp_arguments() -> None:
    query = _companion_route_query_schema("/companion/v1/work/hierarchy")
    mcp = _mcp_input_schema("get_work_hierarchy")
    assert set(query) == {"limit", "cursor", "include_tasks", "process_id"}
    assert query == {key: mcp[key] for key in query}


def test_the_single_record_reads_and_step_ticks_take_no_query() -> None:
    for path in (
        "/companion/v1/projects/{project_id}",
        "/companion/v1/domains/{domain_id}",
        "/companion/v1/processes/{process_id}",
        "/companion/v1/steps/{step_id}/complete",
        "/companion/v1/steps/{step_id}/reopen",
    ):
        assert _companion_route_query_schema(path) == {}, path


def test_the_contacts_and_references_queries_take_the_mcp_arguments_and_bounds() -> None:
    assert _companion_query_schema("/contacts") == _mcp_input_schema(
        "list_task_contacts", without=frozenset({"task_id"})
    )
    assert _companion_query_schema("/external-references") == _mcp_input_schema(
        "list_task_external_references", without=frozenset({"task_id"})
    )


def test_the_linked_record_reads_hold_only_the_scopes_their_use_cases_need() -> None:
    by_name = {item.name: item for item in OPERATIONS}
    assert by_name["task.contacts"].application_scopes == {"tasks:read", "contacts:read"}
    assert by_name["task.external_references"].application_scopes == {"tasks:read"}
    assert by_name["task.contacts"].capability == "companion:tasks:read"
    assert by_name["task.external_references"].capability == "companion:tasks:read"


def test_a_reused_idempotency_key_maps_by_type_not_by_message_text() -> None:
    from sidekick.api.companion import _translate
    from sidekick.mcp.results import error_result
    from sidekick.shared.errors import ConflictError, IdempotencyKeyReusedError

    reused = _translate(IdempotencyKeyReusedError())
    assert reused is not None and (reused.status, reused.reason) == (409, "idempotency_key_reused")
    # The same message on a plain ConflictError is not the idempotency conflict.
    lookalike = _translate(ConflictError(str(IdempotencyKeyReusedError())))
    assert lookalike is not None and lookalike.reason is None
    stale = _translate(ConflictError("x", reason="stale_version"))
    assert stale is not None and stale.reason == "stale_version"

    # REST and MCP see the same conflict as before: code, text, and no reason.
    error = IdempotencyKeyReusedError()
    assert isinstance(error, ConflictError)
    assert (error.code, error.reason) == ("conflict", None)
    assert str(error) == "idempotency key was already used with another payload"
    structured = error_result(error).structured_content
    assert structured is not None
    assert structured["code"] == "conflict" and "reason" not in structured


def test_the_caddy_example_forwards_the_room_routes_by_exact_method_and_path() -> None:
    caddy = (CONTRACTS.parent / "deploy/selfhost/Caddyfile.example").read_text(encoding="utf-8")
    uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    start = "path_regexp ^/companion/v1/"
    # Reads: the GET routes only; writes: the POST routes only, with a body cap for long entries.
    assert f"@companion_rooms_get {{\n\t\tmethod GET\n\t\t{start}(shopping/lists(/{uuid})?" in caddy
    assert "journal/days/[0-9]{4}-[0-9]{2}-[0-9]{2})$" in caddy
    assert f"journal/sources/{uuid}|journal/days" in caddy
    post = "@companion_rooms_post {\n\t\tmethod POST\n\t\t" + start
    assert post + "(shopping/lists|journal/entries|" in caddy
    assert "handle @companion_rooms_post {" in caddy and "max_size 256KiB" in caddy
    # Ids and the journal day never reach the access log: only the fixed route class is logged.
    assert "log_append route {route_class}" in caddy
    assert "log_append path" not in caddy


def test_the_caddy_example_forwards_the_license_route_by_exact_method_and_path() -> None:
    caddy = (CONTRACTS.parent / "deploy/selfhost/Caddyfile.example").read_text(encoding="utf-8")
    assert "@companion_license {\n\t\tmethod GET PUT\n\t\tpath /companion/v1/license\n\t}" in caddy
    # The body is one key: capped. The path holds no id, so the access log has nothing to mask.
    handler = caddy.split("handle @companion_license {", 1)[1].split("\n\t}", 1)[0]
    assert "max_size 4KB" in handler and "reverse_proxy api:8000" in handler
    assert "license/" not in caddy and "license*" not in caddy


def test_the_license_operations_hold_a_capability_of_their_own_and_no_application_scope() -> None:
    by_name = {item.name: item for item in OPERATIONS}
    for name in ("license.show", "license.set"):
        assert by_name[name].capability == "companion:license"
        assert by_name[name].application_scopes == frozenset()
        assert by_name[name].also is None
    # Nothing else can be done with the capability.
    assert {item.name for item in OPERATIONS if item.capability == "companion:license"} == {
        "license.show",
        "license.set",
    }

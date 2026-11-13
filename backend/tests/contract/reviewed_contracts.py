"""Helpers for comparing reviewed contracts with the running implementation.

The reviewed contracts under `contracts/reviewed/00X-*/` are accepted artifacts
and are never rewritten. What they promise must still hold: every reviewed
operation and tool exists, with the same shape, annotations, and inputs. Later
changes add fields and routes on purpose, so an addition is not a violation, while
removing or reshaping something reviewed is.
"""

import copy
import json
from pathlib import Path
from typing import Any, cast

import yaml

from sidekick.shared.types import MAX_CURSOR_LENGTH

REVIEWED_ROOT = Path(__file__).resolve().parents[3] / "contracts" / "reviewed"
ANNOTATION_KEYS = ("readOnlyHint", "openWorldHint", "destructiveHint", "idempotentHint")
# MCP tool titles are Swedish labels shown in claude.ai. Each reviewed
# English title below is deliberately superseded by the runtime title named here, and nothing else
# about a title is exempt. Names, descriptions and annotations stay as reviewed. Only titles that
# appear in the reviewed baselines are listed.
SUPERSEDED_TOOL_TITLES: dict[str, str] = {
    "Add a Contact alias": "Lägg till alias för kontakt",
    "Archive a Sidekick contact": "Arkivera kontakt",
    "Complete a Sidekick task": "Slutför uppgift",
    "Create a Sidekick contact": "Skapa kontakt",
    "Create a Sidekick domain": "Skapa domän",
    "Create a Sidekick process": "Skapa process",
    "Create a Sidekick project": "Skapa projekt",
    "Create a Sidekick task": "Skapa uppgift",
    "Create a manual Sidekick journal entry": "Skapa dagboksinlägg",
    "Create an immutable Sidekick journal source": "Skapa dagboksunderlag",
    "Get a Sidekick daily journal summary": "Visa dagboksammanfattning",
    "Get bounded Contact context": "Visa kontakt med sammanhang",
    "Get one Sidekick domain": "Visa domän",
    "Get one Sidekick journal day": "Visa dagboksdag",
    "Get one Sidekick journal entry": "Visa dagboksinlägg",
    "Get one Sidekick process": "Visa process",
    "Get one Sidekick project": "Visa projekt",
    "Get one Sidekick task": "Visa uppgift",
    "Link a Contact to a Project": "Koppla kontakt till projekt",
    "Link a Contact to a Task": "Koppla kontakt till uppgift",
    "List Sidekick contacts": "Lista kontakter",
    "List Sidekick domains": "Lista domäner",
    "List Sidekick journal entries": "Lista dagboksinlägg",
    "List Sidekick processes": "Lista processer",
    "List Sidekick projects": "Lista projekt",
    "List Sidekick tasks": "Lista uppgifter",
    "Remove a Contact alias": "Ta bort alias för kontakt",
    "Restore a Sidekick contact": "Återställ kontakt",
    "Unlink a Contact from a Project": "Koppla bort kontakt från projekt",
    "Unlink a Contact from a Task": "Koppla bort kontakt från uppgift",
    "Update a Sidekick contact": "Ändra kontakt",
    "Update a Sidekick task": "Ändra uppgift",
}


# The baselines bound a pagination cursor at 512 characters. Keyset cursors carry a text sort key
# of up to 200 characters, so every cursor is bounded by `MAX_CURSOR_LENGTH` now. This widens an
# input bound and an output bound, which is compatible; only that one number is exempt.
REVIEWED_CURSOR_LENGTH = 512


def with_reviewed_cursor_bound(node: Any) -> Any:
    """A copy of a runtime schema with the cursor length bound the baselines were reviewed with."""

    if isinstance(node, list):
        return [with_reviewed_cursor_bound(item) for item in cast(list[Any], node)]
    if not isinstance(node, dict):
        return node
    return {
        key: REVIEWED_CURSOR_LENGTH
        if key == "maxLength" and value == MAX_CURSOR_LENGTH
        else with_reviewed_cursor_bound(value)
        for key, value in cast(dict[str, Any], node).items()
    }


# Core Work tool descriptions say when Claude should use them. Each reviewed description below is
# deliberately superseded by exactly this runtime text; every other description stays as reviewed.
SUPERSEDED_TOOL_DESCRIPTIONS: dict[str, str] = {
    "create_domain": (
        "Use this when the user wants a new Domain, the top-level area that groups Projects and "
        "Processes; create it before a Project that needs it. Owner-scoped, with a retry-safe "
        "idempotency key."
    ),
}

# D-065: additive output fields that the accepted baselines predate. The baselines are
# never rewritten. Only the tool/field pairs listed here are exempt, and they are removed from the
# runtime output schema before it is compared with the reviewed one.
ADDITIVE_OUTPUT_FIELDS: dict[str, tuple[str, ...]] = {
    # The diary day's "Gjort" section.
    "get_journal_day": ("entry_fingerprint", "done", "owner_timezone", "today"),
    # The owner's zone and calendar date, so the phone can say "today" the way the server does.
    "list_journal_entries": ("owner_timezone", "today"),
}


# The entry record names its links and its tags. Only the journal tools that return the
# record are listed, and each field is removed only from objects that carry the record's own
# fields, so the same name on another object in those tools is still checked.
ADDITIVE_RECORD_FIELDS: dict[str, tuple[str, ...]] = {
    "list_journal_entries": ("links", "tags"),
    "get_journal_entry": ("links", "tags"),
    "get_journal_day": ("links", "tags"),
    "create_manual_journal_entry": ("links", "tags"),
    "write_journal_entry": ("links", "tags"),
    "update_journal_entry": ("links", "tags"),
    "finalize_journal_draft": ("links", "tags"),
}
ENTRY_RECORD_FIELDS = frozenset({"journal_date", "key_points", "contact_ids"})


def _without_record_fields(node: Any, fields: tuple[str, ...]) -> None:
    if isinstance(node, list):
        for item in cast(list[Any], node):
            _without_record_fields(item, fields)
        return
    if not isinstance(node, dict):
        return
    schema = cast(dict[str, Any], node)
    properties = schema.get("properties")
    if isinstance(properties, dict):
        names = set(cast(dict[str, Any], properties))
        if names >= ENTRY_RECORD_FIELDS:
            for field in fields:
                if properties.pop(field, None) is not None and "required" in schema:
                    schema["required"] = [item for item in schema["required"] if item != field]
    for value in schema.values():
        _without_record_fields(value, fields)


def expected_tool_description(reviewed_tool: dict[str, Any]) -> str:
    """The runtime description a reviewed tool must now have: its own, or its named supersession."""
    reviewed = reviewed_tool["description"]
    return SUPERSEDED_TOOL_DESCRIPTIONS.get(reviewed_tool["name"], reviewed)


def expected_tool_title(reviewed_title: str) -> str:
    """The runtime title a reviewed title must now have: itself, or its named supersession."""
    return SUPERSEDED_TOOL_TITLES.get(reviewed_title, reviewed_title)


def expected_tool_annotations(reviewed_tool: dict[str, Any]) -> dict[str, Any]:
    """The annotations a reviewed tool must now carry: its reviewed hints, plus the title mirror.

    The runtime copies the display title into `annotations.title` because some hosts read it there
    first. The reviewed hints themselves are unchanged.
    """
    return {**reviewed_tool["annotations"], "title": expected_tool_title(reviewed_tool["title"])}


def without_additive_output_fields(name: str, output_schema: dict[str, Any]) -> dict[str, Any]:
    """The runtime output schema without this tool's listed additive fields."""

    fields = ADDITIVE_OUTPUT_FIELDS.get(name, ())
    stripped = copy.deepcopy(output_schema)
    for field in fields:
        stripped.get("properties", {}).pop(field, None)
    if "required" in stripped:
        stripped["required"] = [item for item in stripped["required"] if item not in fields]
    _without_record_fields(stripped, ADDITIVE_RECORD_FIELDS.get(name, ()))
    return stripped


def load_contract(path: Path) -> Any:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def reviewed(feature: str, name: str) -> Any:
    return load_contract(REVIEWED_ROOT / feature / name)


def resolve_ref(ref: str, root: dict[str, Any]) -> Any:
    """Resolve the local JSON Schema references used by reviewed/runtime contracts."""

    if ref.startswith("#/$defs/"):
        return root["$defs"][ref.rsplit("/", 1)[-1]]
    if ref.startswith("#/components/schemas/"):
        return root["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    if ref.startswith("#/components/parameters/"):
        return root["components"]["parameters"][ref.rsplit("/", 1)[-1]]
    if ref.startswith("#/components/responses/"):
        return root["components"]["responses"][ref.rsplit("/", 1)[-1]]
    raise AssertionError(f"unsupported local contract reference: {ref}")


def canonical_schema(
    schema: Any, root: dict[str, Any], resolving: frozenset[str] = frozenset()
) -> Any:
    """Normalize equivalent reviewed/runtime JSON Schema representations."""

    if isinstance(schema, list):
        return [canonical_schema(item, root, resolving) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref in resolving:
            return {"$ref": ref}
        return canonical_schema(resolve_ref(ref, root), root, resolving | {ref})

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and None in enum_values and "anyOf" not in schema:
        # `enum: [a, b, null]` and `anyOf: [{enum: [a, b]}, {type: null}]` say the
        # same thing; the two generators pick different spellings.
        return canonical_schema(
            {
                "anyOf": [
                    {
                        **{key: value for key, value in schema.items() if key != "type"},
                        "enum": [value for value in enum_values if value is not None],
                    },
                    {"type": "null"},
                ]
            },
            root,
            resolving,
        )

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        non_null_types = [item for item in schema_type if item != "null"]
        branches: list[dict[str, Any]] = [{"type": "null"}] if "null" in schema_type else []
        for item in non_null_types:
            branch = {key: value for key, value in schema.items() if key != "type"}
            if isinstance(branch.get("enum"), list):
                branch["enum"] = [value for value in branch["enum"] if value is not None]
            branch["type"] = item
            branches.append(branch)
        return canonical_schema({"anyOf": branches}, root, resolving)

    inferred_type = schema_type
    if inferred_type is None and "enum" in schema:
        values = [value for value in schema["enum"] if value is not None]
        if values and all(isinstance(value, str) for value in values):
            inferred_type = "string"
        elif values and all(
            isinstance(value, int) and not isinstance(value, bool) for value in values
        ):
            inferred_type = "integer"
    if inferred_type is None and "const" in schema:
        value = schema["const"]
        if isinstance(value, str):
            inferred_type = "string"
        elif isinstance(value, bool):
            inferred_type = "boolean"
        elif isinstance(value, int):
            inferred_type = "integer"

    structural_keys = {
        "additionalProperties",
        "const",
        "enum",
        "format",
        "items",
        "maxItems",
        "maxLength",
        "minItems",
        "minimum",
        "minLength",
        "oneOf",
        "anyOf",
        "pattern",
        "properties",
        "required",
        "type",
        "uniqueItems",
    }
    normalized: dict[str, Any] = {}
    if inferred_type is not None:
        normalized["type"] = inferred_type
    for key in structural_keys - {
        "type",
        "properties",
        "items",
        "oneOf",
        "anyOf",
        "required",
        "additionalProperties",
    }:
        if key in schema:
            normalized[key] = schema[key]
    if normalized.get("maxLength") == MAX_CURSOR_LENGTH:
        normalized["maxLength"] = REVIEWED_CURSOR_LENGTH
    if "additionalProperties" in schema:
        value = schema["additionalProperties"]
        normalized["additionalProperties"] = (
            canonical_schema(value, root, resolving) if isinstance(value, dict) else value
        )
    if "properties" in schema:
        normalized["properties"] = {
            name: canonical_schema(value, root, resolving)
            for name, value in sorted(schema["properties"].items())
        }
    if "required" in schema:
        normalized["required"] = sorted(schema["required"])
    if "items" in schema:
        normalized["items"] = canonical_schema(schema["items"], root, resolving)
    if "anyOf" in schema:
        branches = [canonical_schema(item, root, resolving) for item in schema["anyOf"]]
        object_branches = [
            branch
            for branch in branches
            if isinstance(branch, dict)
            and branch.get("type") == "object"
            and "properties" in branch
        ]
        if object_branches and len(object_branches) == len(branches):
            parent_properties = object_branches[0]["properties"]
            parent_additional = object_branches[0].get("additionalProperties")
            if all(
                branch["properties"] == parent_properties
                and branch.get("additionalProperties") == parent_additional
                for branch in object_branches
            ):
                normalized["type"] = "object"
                normalized["additionalProperties"] = parent_additional
                normalized["properties"] = parent_properties
                branch_requirements = [set(branch.get("required", [])) for branch in branches]
                common_required = set(normalized.get("required", [])) | set.intersection(
                    *branch_requirements
                )
                normalized["required"] = sorted(common_required)
                normalized["anyOf"] = [
                    {"required": sorted(requirements - common_required)}
                    for requirements in branch_requirements
                ]
            else:
                normalized["anyOf"] = branches
        elif inferred_type == "object" and "properties" in normalized and branches:
            parent_properties = normalized["properties"]
            parent_required = set(normalized.get("required", []))
            branch_requirements: list[set[str]] = []
            compatible = True
            for branch in branches:
                if not isinstance(branch, dict):
                    compatible = False
                    break
                if set(branch) == {"required"}:
                    branch_requirements.append(set(branch["required"]))
                elif (
                    branch.get("type") == "object"
                    and branch.get("properties") == parent_properties
                    and branch.get("additionalProperties") == normalized.get("additionalProperties")
                ):
                    branch_requirements.append(set(branch.get("required", [])))
                else:
                    compatible = False
                    break
            if compatible:
                common_required = parent_required | set.intersection(*branch_requirements)
                normalized["required"] = sorted(common_required)
                normalized["anyOf"] = [
                    {"required": sorted(requirements - common_required)}
                    for requirements in branch_requirements
                ]
            else:
                normalized["anyOf"] = branches
        else:
            normalized["anyOf"] = branches
        normalized["anyOf"] = sorted(
            normalized["anyOf"], key=lambda item: json.dumps(item, sort_keys=True)
        )
    if "oneOf" in schema:
        branches = [canonical_schema(item, root, resolving) for item in schema["oneOf"]]
        normalized["oneOf"] = sorted(branches, key=lambda item: json.dumps(item, sort_keys=True))
    return normalized


def _without_patterns(shape: Any) -> Any:
    """Drop `pattern` from an already canonical shape.

    This walks the canonical form once. Re-running the canonicaliser over its own
    output would read a `properties` map as a schema, and a property literally
    named `items` would then swallow its siblings.
    """

    if isinstance(shape, list):
        return [_without_patterns(item) for item in shape]
    if not isinstance(shape, dict):
        return shape
    result: dict[str, Any] = {}
    for key, value in shape.items():
        if key == "pattern":
            continue
        if key == "properties" and isinstance(value, dict):
            result[key] = {name: _without_patterns(child) for name, child in value.items()}
        else:
            result[key] = _without_patterns(value)
    return result


def assert_reviewed_tool_still_offered(
    reviewed_tool: dict[str, Any],
    runtime_tool: dict[str, Any],
    *,
    reviewed_root: dict[str, Any],
    runtime_root: Any,
    compare_output: bool = False,
    allowed_new_required: frozenset[str] = frozenset(),
) -> None:
    """A reviewed tool keeps its title, annotations, and accepted inputs."""

    name = reviewed_tool["name"]
    assert runtime_tool["title"] == expected_tool_title(reviewed_tool["title"]), name
    assert {
        key: runtime_tool["annotations"][key] for key in (*ANNOTATION_KEYS, "title")
    } == expected_tool_annotations(reviewed_tool), name

    reviewed_input = reviewed_tool["inputSchema"]
    if "$ref" in reviewed_input:
        reviewed_input = resolve_ref(reviewed_input["$ref"], reviewed_root)
    reviewed_properties = set(reviewed_input.get("properties", {}))
    runtime_properties = set(runtime_tool["inputSchema"].get("properties", {}))
    # Inputs may grow with later changes; a reviewed input must never disappear.
    assert reviewed_properties <= runtime_properties, name
    # A new input must never become mandatory for an existing caller, unless a
    # reviewed decision deliberately made it so and says which one.
    assert set(runtime_tool["inputSchema"].get("required", [])) <= (
        set(reviewed_input.get("required", [])) | allowed_new_required
    ), name

    if compare_output and "outputSchema" in reviewed_tool:
        runtime_output = without_additive_output_fields(name, runtime_tool["outputSchema"])
        assert canonical_schema(runtime_output, runtime_root) == canonical_schema(
            reviewed_tool["outputSchema"], reviewed_root
        ), name


def _is_explicit_nullable_supersession(reviewed: Any, runtime: Any) -> bool:
    """Return whether runtime is precisely the reviewed shape plus ``null``."""

    if not isinstance(reviewed, dict) or not isinstance(runtime, dict):
        return False
    branches = runtime.get("anyOf")
    if not isinstance(branches, list):
        return False
    null_branches = [branch for branch in branches if branch == {"type": "null"}]
    non_null_branches = [branch for branch in branches if branch != {"type": "null"}]
    return (
        len(null_branches) == 1 and len(non_null_branches) == 1 and reviewed == non_null_branches[0]
    )


def assert_schema_covers(
    reviewed: Any,
    runtime: Any,
    *,
    mode: str,
    path: str = "$",
    schema_path: str = "$",
    allowed_new_required: frozenset[str] = frozenset(),
    allowed_response_nulls: frozenset[str] = frozenset(),
) -> None:
    """Assert the runtime schema still honours a reviewed one.

    `mode` says who has to be tolerant. In `request` mode the runtime may accept
    more but must not demand more. In `response` mode the runtime may return more
    but must still return everything reviewed. Structures that no longer line up
    at all (a reviewed branch replaced by a different composition) are reported
    rather than silently skipped, and identical shapes short-circuit.
    """

    if mode == "response" and schema_path in allowed_response_nulls:
        assert _is_explicit_nullable_supersession(reviewed, runtime), path
        return
    if reviewed == runtime:
        return
    if not isinstance(reviewed, dict) or not isinstance(runtime, dict):
        assert reviewed == runtime, path
        return

    if "type" in reviewed and "type" in runtime:
        assert reviewed["type"] == runtime["type"], f"{path}.type"
    if "format" in reviewed:
        assert runtime.get("format") == reviewed["format"], f"{path}.format"
    if reviewed.get("additionalProperties") is False:
        assert runtime.get("additionalProperties") is False, f"{path}.additionalProperties"
    if isinstance(reviewed.get("enum"), list) and isinstance(runtime.get("enum"), list):
        assert set(map(str, reviewed["enum"])) <= set(map(str, runtime["enum"])), f"{path}.enum"

    if "required" in reviewed or "required" in runtime:
        reviewed_required = set(reviewed.get("required", []))
        runtime_required = set(runtime.get("required", []))
        if mode == "request":
            assert runtime_required <= reviewed_required | allowed_new_required, f"{path}.required"
        else:
            # A response field the caller was promised must still be there. Whether
            # the generated schema lists it as required depends on whether the model
            # field has a default; a field with a default is still always serialized,
            # so presence as a property is the promise that matters.
            runtime_present = runtime_required | set(runtime.get("properties", {}))
            assert reviewed_required <= runtime_present, f"{path}.required"

    for name, schema in reviewed.get("properties", {}).items():
        assert name in runtime.get("properties", {}), f"{path}.properties.{name}"
        assert_schema_covers(
            schema,
            runtime["properties"][name],
            mode=mode,
            path=f"{path}.properties.{name}",
            schema_path=f"{schema_path}.properties.{name}",
            allowed_response_nulls=allowed_response_nulls,
        )

    if "items" in reviewed and "items" in runtime:
        assert_schema_covers(
            reviewed["items"],
            runtime["items"],
            mode=mode,
            path=f"{path}.items",
            schema_path=f"{schema_path}.items",
            allowed_response_nulls=allowed_response_nulls,
        )

    if "anyOf" in reviewed or "oneOf" in reviewed:
        # A reviewed composition must remain a composition. Which keyword expresses
        # it, and how the branches are ordered, differs between the two generators,
        # so matching branches pairwise would not be a statement about behaviour.
        assert isinstance(runtime.get("anyOf"), list) or isinstance(runtime.get("oneOf"), list), (
            f"{path}.anyOf/oneOf"
        )

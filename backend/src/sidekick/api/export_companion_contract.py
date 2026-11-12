"""Export the companion (Android) API contract deterministically.

The companion routes under `/companion/v1/` are kept out of the browser OpenAPI document
(`contracts/openapi.generated.json`), so the paired app's client had no machine-readable
description of them. This module builds one from the registered routes themselves, as an
OpenAPI 3.1 document: every route with its operation name, path, query and header parameters,
JSON request body and size cap, whether it needs a device credential and which device capability
it checks, and the closed vocabulary of refusals (`PROBLEMS`) as the shared error schema.

What a successful call returns is the structured content of the MCP tool of the same name; those
shapes are the output schemas of `contracts/mcp-tools.generated.json` and are not repeated here.

CI regenerates the file and fails on a diff, like the other contract snapshots.
"""

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from sidekick.api.companion import (
    API_VERSION,
    PROBLEMS,
    CompanionRouteSpec,
    RequestBody,
    create_companion_router,
)
from sidekick.companion.operations import OPERATIONS, CompanionOperation

PROBLEM_SCHEMA = "Problem"
BEARER_SCHEME = "companionBearer"
JSON = "application/json"
PROBLEM_JSON = "application/problem+json"
# FastAPI adds its own 422 and validation schemas to every route with input; the companion
# answers its closed envelope instead.
_FASTAPI_VALIDATION_SCHEMAS = ("HTTPValidationError", "ValidationError")


def _capability(operation: str) -> CompanionOperation | None:
    """The capability entry for a route's operation name: the name itself, or the entry whose
    name it extends (`push.reminders.ack` is checked as `push.reminders`)."""

    matching = (
        candidate
        for candidate in OPERATIONS
        if operation == candidate.name or operation.startswith(candidate.name + ".")
    )
    return max(matching, key=lambda candidate: len(candidate.name), default=None)


def _documented(route: APIRoute, spec: CompanionRouteSpec) -> APIRoute:
    """A copy of the route that the OpenAPI generator will include, named by its operation."""

    shown = copy.copy(route)
    shown.include_in_schema = True
    shown.operation_id = spec.operation
    shown.summary = shown.operation_id
    return shown


def _problem_schema() -> dict[str, Any]:
    reasons = sorted({reason for kind in PROBLEMS for reason in kind.reasons})
    extras = sorted({field for kind in PROBLEMS for field in kind.extra_fields})
    return {
        "type": "object",
        "title": "Companion problem",
        "description": (
            "The one envelope of every refusal. `code` is closed; the text of the server's own "
            "message and any input is never echoed."
        ),
        "required": ["type", "title", "status", "code", "api_version", "correlation_id"],
        "properties": {
            "type": {"type": "string", "description": "urn:sidekick:companion:v1:error:{code}"},
            "title": {"type": "string"},
            "status": {"type": "integer"},
            "code": {"type": "string", "enum": sorted({kind.code for kind in PROBLEMS})},
            "reason": {"type": "string", "enum": reasons},
            "api_version": {"type": "string", "const": API_VERSION},
            "correlation_id": {"type": "string"},
            **{field: {"type": "string"} for field in extras},
        },
    }


def _problems() -> list[dict[str, Any]]:
    return [
        {
            "status": kind.status,
            "code": kind.code,
            "title": kind.title,
            **({"reasons": list(kind.reasons)} if kind.reasons else {}),
            **({"headers": list(kind.headers)} if kind.headers else {}),
            **({"extra_fields": list(kind.extra_fields)} if kind.extra_fields else {}),
        }
        for kind in sorted(PROBLEMS, key=lambda kind: (kind.status, kind.code))
    ]


def _request_body(body: RequestBody[Any], schemas: dict[str, Any]) -> dict[str, Any]:
    """The operation's `requestBody`; the model and the schemas it names go into `components`."""

    schema = body.model.model_json_schema(ref_template="#/components/schemas/{model}")
    schemas.update(schema.pop("$defs", {}))
    schemas[body.model.__name__] = schema
    return {
        "required": body.required,
        "content": {JSON: {"schema": {"$ref": f"#/components/schemas/{body.model.__name__}"}}},
        "x-sidekick-max-bytes": body.max_bytes,
    }


def build_contract() -> dict[str, Any]:
    """The contract of every companion route, whatever rooms an instance enables."""

    router = create_companion_router()
    specs = {spec.operation: spec for spec in router.specs}
    routes = [
        _documented(route, specs[str(route.operation_id)])
        for route in router.routes
        if isinstance(route, APIRoute)
    ]
    document = get_openapi(
        title="Sidekick companion API",
        version=API_VERSION,
        openapi_version="3.1.0",
        description=(
            "The routes the paired companion app calls, under /companion/v1/. Every route except "
            "the pairing exchange needs the device credential as a bearer token and a device "
            "capability (`x-sidekick-capability`). A successful answer is the structured content "
            "of the MCP tool of the same name (contracts/mcp-tools.generated.json). Instances "
            "may leave rooms out (SIDEKICK_ENABLED_ROOMS); a route of a room that is switched off "
            "answers 404."
        ),
        routes=routes,
    )
    schemas: dict[str, Any] = document.setdefault("components", {}).setdefault("schemas", {})
    for name in _FASTAPI_VALIDATION_SCHEMAS:
        schemas.pop(name, None)
    schemas[PROBLEM_SCHEMA] = _problem_schema()
    problem_response = {
        "description": "A refusal: one of the closed codes of `x-sidekick-problems`.",
        "content": {PROBLEM_JSON: {"schema": {"$ref": f"#/components/schemas/{PROBLEM_SCHEMA}"}}},
    }
    document["components"]["securitySchemes"] = {
        BEARER_SCHEME: {"type": "http", "scheme": "bearer", "description": "The device credential."}
    }
    document["x-sidekick-problems"] = _problems()

    for path_item in document["paths"].values():
        for operation in path_item.values():
            spec = specs[operation["operationId"]]
            operation["responses"].pop("422", None)
            operation["responses"]["default"] = problem_response
            operation["security"] = [] if spec.unauthenticated else [{BEARER_SCHEME: []}]
            capability = _capability(operation["operationId"])
            if capability is not None:
                operation["x-sidekick-capability"] = capability.capability
                if capability.also is not None:
                    operation["x-sidekick-also-capability"] = capability.also
            if spec.body is not None:
                operation["requestBody"] = _request_body(spec.body, schemas)
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(build_contract(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()

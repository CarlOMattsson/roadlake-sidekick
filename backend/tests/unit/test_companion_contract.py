"""The published companion API contract matches the routes and the refusal vocabulary (no database).

`contracts/companion-api.generated.json` is generated from the registered routes by
`sidekick.api.export_companion_contract`; CI regenerates it and fails on a diff. These tests catch
the same drift in a local run, and check the pieces the generator trusts: the declared request
bodies, the capability marks and the closed vocabulary of refusals.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from sidekick.api.companion import (
    PROBLEMS,
    CompanionProblem,
    CompanionRouter,
    CompanionRouteSpec,
    RequestBody,
    create_companion_router,
)
from sidekick.api.export_companion_contract import build_contract
from sidekick.companion.operations import OPERATIONS
from sidekick.shared.rooms import ROOMS

REPO = Path(__file__).resolve().parents[3]
SNAPSHOT = REPO / "contracts" / "companion-api.generated.json"
API_SOURCES = sorted((REPO / "backend" / "src" / "sidekick" / "api").glob("companion*.py"))
REGENERATE = (
    "uv run --project backend python -m sidekick.api.export_companion_contract "
    "--output contracts/companion-api.generated.json"
)
METHODS = ("get", "post", "put", "delete")


def _operations(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        operation["operationId"]: operation
        for path_item in contract["paths"].values()
        for operation in path_item.values()
    }


def test_the_committed_contract_is_what_the_routes_generate() -> None:
    rendered = json.dumps(build_contract(), indent=2, sort_keys=True) + "\n"
    current = SNAPSHOT.read_text(encoding="utf-8") == rendered
    assert current, (
        f"{SNAPSHOT.name} is stale against the companion routes. Regenerate it with: {REGENERATE}"
    )


def test_every_companion_route_is_registered_once_and_none_lacks_a_spec() -> None:
    router = create_companion_router(rooms=ROOMS)
    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    assert len(routes) == len(router.routes)
    specs = [router.spec_for(route) for route in routes]
    assert None not in specs
    assert len({spec.operation for spec in router.specs if spec}) == len(router.specs)
    assert specs == router.specs
    keys = [(spec.method, router.prefix + spec.path) for spec in router.specs]
    assert keys == [(next(iter(route.methods)), route.path) for route in routes]
    assert len(set(keys)) == len(keys)
    for route in routes:
        # Handlers are plain functions: nothing is attached to them.
        assert not [name for name in vars(route.endpoint) if name.startswith("companion_")]


def test_a_route_or_operation_cannot_be_registered_twice() -> None:
    router = CompanionRouter()

    async def handler() -> None: ...

    router.add(CompanionRouteSpec("GET", "/a", "a.get"), handler)
    with pytest.raises(ValueError, match="registered twice"):
        router.add(CompanionRouteSpec("GET", "/a", "a.other"), handler)
    with pytest.raises(ValueError, match="registered twice"):
        router.add(CompanionRouteSpec("GET", "/b", "a.get"), handler)


def test_every_registered_route_is_in_the_contract_once() -> None:
    contract = build_contract()
    documented = {
        (method.upper(), path) for path, item in contract["paths"].items() for method in item
    }
    registered = {
        (method, route.path)  # type: ignore[attr-defined]
        for route in create_companion_router().routes
        for method in route.methods  # type: ignore[attr-defined]
    }
    assert documented == registered
    names = [
        operation["operationId"]
        for item in contract["paths"].values()
        for operation in item.values()
    ]
    assert len(names) == len(set(names))


def test_only_the_pairing_exchange_is_open_to_a_caller_without_a_credential() -> None:
    open_operations = {
        name
        for name, operation in _operations(build_contract()).items()
        if operation["security"] == []
    }
    assert open_operations == {"device.pair"}


def test_a_route_carries_the_capability_its_operation_checks() -> None:
    operations = _operations(build_contract())
    for entry in OPERATIONS:
        operation = operations.get(entry.name)
        if operation is None:
            continue  # `push.*` operations name several routes, checked below.
        assert operation["x-sidekick-capability"] == entry.capability
        assert operation.get("x-sidekick-also-capability") == entry.also
    # A room write also needs the room's read capability.
    assert operations["shopping.item_purchased"]["x-sidekick-also-capability"] == (
        "companion:shopping:read"
    )
    assert operations["push.reminders.ack"]["x-sidekick-capability"] == "companion:push"
    assert operations["push.subscription.remove"]["x-sidekick-capability"] == "companion:push"
    assert "x-sidekick-capability" not in operations["device.status"]


def test_a_declared_body_is_a_closed_schema_with_a_size_cap() -> None:
    contract = build_contract()
    schemas = contract["components"]["schemas"]
    with_body = {
        name: operation
        for name, operation in _operations(contract).items()
        if "requestBody" in operation
    }
    assert {"device.pair", "task.complete", "shopping.list_create", "license.set"} <= set(with_body)
    for operation in with_body.values():
        body = operation["requestBody"]
        assert body["x-sidekick-max-bytes"] > 0
        ref = body["content"]["application/json"]["schema"]["$ref"]
        assert schemas[ref.rsplit("/", 1)[1]]["additionalProperties"] is False
    # The renewal takes no input: the body may be left out.
    assert with_body["device.renew"]["requestBody"]["required"] is False
    # A route with no body declares none.
    assert "requestBody" not in _operations(contract)["work.agenda"]


def test_a_write_names_its_idempotency_key_header() -> None:
    operation = _operations(build_contract())["task.complete"]
    header = next(item for item in operation["parameters"] if item["in"] == "header")
    assert header["name"] == "Idempotency-Key"
    assert header["required"] is True


def test_the_error_vocabulary_is_one_envelope_with_closed_codes() -> None:
    contract = build_contract()
    problem = contract["components"]["schemas"]["Problem"]
    assert problem["properties"]["code"]["enum"] == sorted({kind.code for kind in PROBLEMS})
    assert [entry["status"] for entry in contract["x-sidekick-problems"]] == sorted(
        entry["status"] for entry in contract["x-sidekick-problems"]
    )
    for operation in _operations(contract).values():
        assert "422" not in operation["responses"]
        ref = operation["responses"]["default"]["content"]["application/problem+json"]["schema"]
        assert ref == {"$ref": "#/components/schemas/Problem"}
    assert "HTTPValidationError" not in contract["components"]["schemas"]


def _raised_problems() -> set[tuple[int, str, str | None]]:
    """The (status, code, reason) of every `CompanionProblem(...)` written with literals."""

    raised: set[tuple[int, str, str | None]] = set()
    for source in API_SOURCES:
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "CompanionProblem"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[1], ast.Constant)
            ):
                continue
            reason = next(
                (
                    keyword.value.value
                    for keyword in node.keywords
                    if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant)
                ),
                None,
            )
            raised.add((node.args[0].value, node.args[1].value, reason))
    return raised


def test_every_refusal_a_route_raises_is_in_the_published_vocabulary() -> None:
    declared = {(kind.status, kind.code): kind for kind in PROBLEMS}
    raised = _raised_problems()
    assert raised, "the scan found no CompanionProblem; the pattern no longer matches the code"
    for status, code, reason in raised:
        kind = declared.get((status, code))
        assert kind is not None, f"{status} {code} is raised but not listed in PROBLEMS"
        if reason is not None:
            assert reason in kind.reasons, f"{code} reason {reason} is not listed in PROBLEMS"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


BODY = RequestBody(_Body, 64)


@pytest.fixture
def body_client() -> TestClient:
    """An app with one route that reads `BODY`, refusals rendered as (status, code)."""

    app = FastAPI()

    @app.exception_handler(CompanionProblem)
    async def refuse(_request: Request, problem: CompanionProblem) -> JSONResponse:
        return JSONResponse({"code": problem.code}, status_code=problem.status)

    @app.post("/body")
    async def read(request: Request) -> dict[str, str]:
        return {"name": (await BODY.read(request)).name}

    return TestClient(app)


def test_a_body_is_read_as_its_declared_model(body_client: TestClient) -> None:
    response = body_client.post("/body", json={"name": "milk"})
    assert response.status_code == 200
    assert response.json() == {"name": "milk"}


def test_a_body_that_is_not_json_is_refused_before_it_is_read(body_client: TestClient) -> None:
    response = body_client.post(
        "/body", content=b'{"name": "milk"}', headers={"content-type": "text/plain"}
    )
    assert (response.status_code, response.json()) == (415, {"code": "unsupported_media_type"})


def test_a_body_over_its_cap_is_refused(body_client: TestClient) -> None:
    response = body_client.post("/body", json={"name": "x" * 100})
    assert (response.status_code, response.json()) == (413, {"code": "payload_too_large"})


@pytest.mark.parametrize("payload", [{}, {"name": "milk", "extra": 1}, {"name": 3}])
def test_a_body_the_model_refuses_is_a_validation_error(
    body_client: TestClient, payload: dict[str, Any]
) -> None:
    response = body_client.post("/body", json=payload)
    assert (response.status_code, response.json()) == (422, {"code": "validation_error"})

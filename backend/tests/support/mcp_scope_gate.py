"""Shared test helpers moved out of `tests/contract/test_mcp_tool_scope_gate.py`."""

from typing import Any
from uuid import uuid4

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor

# Tools whose input must carry a change before the use case runs; the generic sample is minimal and
# would be refused as an empty update. These add the one field that makes the call well formed.
EXTRA_ARGUMENTS: dict[str, dict[str, Any]] = {
    "update_saved_work_view": {"name": "Renamed view"},
    "update_shopping_item": {"item": {"name": "Milk"}},
}


def _sample(schema: dict[str, Any], root: dict[str, Any], *, top: bool = False) -> Any:
    """A minimal value that satisfies a JSON schema, enough to get past input validation."""

    if "$ref" in schema:
        return _sample(root["$defs"][schema["$ref"].rsplit("/", 1)[-1]], root)
    if "anyOf" in schema:
        options = [option for option in schema["anyOf"] if option.get("type") != "null"]
        return _sample(options[0], root)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        properties = schema.get("properties", {})
        names = schema.get("required") or ([] if top else list(properties)[:1])
        return {name: _sample(properties[name], root) for name in names}
    if kind == "array":
        return [_sample(schema["items"], root)] if schema.get("minItems", 0) else []
    if kind == "integer":
        return max(1, schema.get("minimum", 1))
    if kind == "boolean":
        return True
    formats = {"uuid": str(uuid4()), "date": "2026-01-01", "date-time": "2026-01-01T00:00:00Z"}
    if schema.get("format") in formats:
        return formats[schema["format"]]
    if schema.get("pattern") == "^[0-9a-f]{64}$":
        return "a" * 64
    return "x" * max(8, schema.get("minLength", 1))


async def _call_every_tool(container: Container, actor: Actor) -> dict[str, CallToolResult]:
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    results: dict[str, CallToolResult] = {}
    async with Client(server) as client:
        for tool in await client.list_tools():
            arguments = _sample(tool.inputSchema, tool.inputSchema, top=True)
            arguments |= EXTRA_ARGUMENTS.get(tool.name, {})
            results[tool.name] = await client.call_tool(tool.name, arguments, raise_on_error=False)
    return results


def _code(result: CallToolResult) -> str | None:
    return (result.structured_content or {}).get("code") if result.is_error else None


ALL_SCOPES = frozenset(MCP_SCOPES)


def _digests(factory: sessionmaker[Session]) -> dict[str, str]:
    """A digest of every row of every table, so any committed change shows as a difference."""

    digests: dict[str, str] = {}
    with factory() as session:
        names = session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'sidekick' ORDER BY 1")
        ).scalars()
        for name in list(names):
            digests[name] = session.execute(
                text(
                    "SELECT coalesce(md5(string_agg(t::text, '' ORDER BY t::text)), '') "
                    f'FROM sidekick."{name}" t'
                )
            ).scalar_one()
    return digests


async def _seed(container: Container, owner: Any) -> dict[str, Any]:
    """One Domain, Process, Project and Task made through the tools with every scope."""

    server = create_mcp_server(
        container, actor_provider=lambda: Actor(owner, ALL_SCOPES), enable_auth=False
    )
    async with Client(server) as client:

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            result = await client.call_tool(name, arguments)
            return result.structured_content or {}

        domain = (await call("create_domain", {"name": "Home", "idempotency_key": "seed-domain"}))[
            "domain"
        ]
        process = (
            await call(
                "create_process",
                {"domain_id": domain["id"], "name": "Weekly", "idempotency_key": "seed-process"},
            )
        )["process"]
        project = (
            await call(
                "create_project",
                {"domain_id": domain["id"], "title": "Garden", "idempotency_key": "seed-project"},
            )
        )["project"]
        task = (await call("create_task", {"title": "Rake", "idempotency_key": "seed-task"}))[
            "task"
        ]
    return {"domain": domain, "process": process, "project": project, "task": task}

"""Answer the SDK's per-call input-schema lookup from a cache instead of running `tools/list`.

mcp 2.3.0 checks the `Mcp-Param-*` headers of every 2026-07-28 `tools/call` that carries arguments
against the called tool's input schema. Unless the low-level server has `get_tool_input_schema`,
the SDK gets that schema by running the server's whole `tools/list` handler first. FastMCP 4.1.6
does not set it, so every call paid for a full listing: about 70 ms of CPU on the event loop with
Sidekick's ~94 tools, which also queued concurrent calls behind each other.

This module installs the lookup on a server, backed by `{tool name: inputSchema}` built from the
same listing `tools/list` returns (`FastMCP.list_tools()` through the whole middleware chain and
the same wire conversion), so the schemas are byte-identical to what a client is shown.

The cache is built lazily. The SDK reads `get_tool_input_schema` on each call, so it stays `None`
(the SDK's own path, exact but slow) until the first `tools/call` has built the cache; from then on
the lookup answers from memory. Building on first use, not at construction, means transforms and
middleware added after `create_mcp_server` are in the listing.

The SDK calls the lookup before middleware and without the caller in view, so a cache is only
sound when the listing is a static catalog that does not depend on the caller. It is built only
when (a) no provider tool carries a component `auth` check (Sidekick sets none; scopes are enforced
inside the tools) and (b) every middleware that can touch a listing (`on_list_tools`, `on_request`
or `on_message`) is one known to be caller-blind. Anything else, such as tool injection or a
caller-dependent listing middleware, keeps the SDK's path. FastMCP's per-session visibility
(`ctx.enable_components` and friends) would also make the listing caller-dependent; Sidekick never
uses it, and a test keeps it that way.

The wiring uses two internal interfaces (`FastMCP._mcp_server` and the SDK's
`Server.get_tool_input_schema`) and a few fastmcp/mcp helpers the lazy build calls. It is installed
only for the exact reviewed versions of fastmcp and mcp (pinned in `pyproject.toml` and
`uv.lock`), and only when the hook is a constructor parameter of the low-level server, is still
unset on this server, and every helper the build needs imports. On any deviation nothing is
installed and one warning is logged. `tests/mcp/test_input_schemas.py` fails when the installed
libraries or the lock drift from the reviewed versions.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping
from contextvars import ContextVar
from importlib import metadata
from typing import Any, Final

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams

LOGGER = logging.getLogger("sidekick.mcp.input_schemas")

REVIEWED_FASTMCP_VERSION: Final = "4.1.6"
REVIEWED_MCP_VERSION: Final = "2.3.0"
#: The only protocol era that reaches the lookup: the `Mcp-Param` check is on the 2026-07-28 path.
MODERN_PROTOCOL_VERSION: Final = "2026-07-28"

#: True while this module runs its own listing, so request logging does not report it as a client's.
INTERNAL_LISTING: Final[ContextVar[bool]] = ContextVar("sidekick_internal_listing", default=False)

#: Middleware whose listing hooks are known not to depend on the caller (by qualified class name,
#: so this module need not import them).
CALLER_BLIND_LISTING_MIDDLEWARE: Final = frozenset(
    {
        "fastmcp.server.middleware.dereference.DereferenceRefsMiddleware",
        "sidekick.mcp.request_log.McpRequestLogging",
    }
)
_LISTING_HOOKS: Final = ("on_list_tools", "on_request", "on_message")

_warned = False


def _unreviewed_reason() -> str | None:
    """Return why the installed libraries are not the reviewed ones, or None when they are."""

    for package, reviewed in (("fastmcp", REVIEWED_FASTMCP_VERSION), ("mcp", REVIEWED_MCP_VERSION)):
        installed = metadata.version(package)
        if installed != reviewed:
            return f"{package} {installed} is not the reviewed {reviewed}"
    return None


def _internals_reason(server: FastMCP) -> str | None:
    """Return why the internals this module relies on are not as reviewed, or None when they are.

    The lazy build imports its helpers on the first call. Checking them here makes a changed
    library visible at startup, not on the first tool call.
    """

    low_level = getattr(server, "_mcp_server", None)
    if low_level is None or not hasattr(low_level, "get_tool_input_schema"):
        return "the low-level server has no get_tool_input_schema"
    if low_level.get_tool_input_schema is not None:
        return "the low-level server already has a get_tool_input_schema"
    constructors = (
        vars(cls)["__init__"] for cls in type(low_level).__mro__ if "__init__" in vars(cls)
    )
    if not any(
        "get_tool_input_schema" in inspect.signature(init).parameters for init in constructors
    ):
        return "the SDK server no longer takes get_tool_input_schema"
    try:
        _import_build_helpers()
    except (ImportError, AttributeError, AssertionError) as error:
        return f"a helper the lookup needs is missing ({type(error).__name__})"
    return None


def _import_build_helpers() -> None:
    """Import every version-sensitive helper the lazy build uses; raises when one is gone."""

    from fastmcp.server.middleware.tool_injection import ToolInjectionMiddleware
    from fastmcp.server.providers.aggregate import AggregateProvider
    from fastmcp.utilities.versions import dedupe_with_versions
    from mcp_types.methods import serialize_server_result

    for helper in (
        ToolInjectionMiddleware,
        AggregateProvider.list_tools,
        dedupe_with_versions,
        serialize_server_result,
    ):
        assert callable(helper)


def _warn_once(reason: str) -> None:
    global _warned
    if not _warned:
        _warned = True
        # The reason names only packages and versions, never request data.
        LOGGER.warning("mcp_input_schema_lookup_not_installed: %s", reason)


class _InputSchemaLookup(Middleware):
    """Build the schema cache on the first `tools/call`, then hand it to the SDK."""

    def __init__(self, server: FastMCP) -> None:
        self._server = server
        self._building = False
        self._done = False

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if not self._done and not self._building:
            self._building = True
            try:
                await self._build()
            except Exception as error:
                # Never fail a working call. The SDK's own path stays in use.
                LOGGER.warning("mcp_input_schema_lookup_build_failed: %s", type(error).__name__)
            finally:
                self._building = False
            # Reached on success or a handled failure. A cancelled build skips it, so a later call
            # retries.
            self._done = True
        return await call_next(context)

    async def _build(self) -> None:
        # `_import_build_helpers` checked these at install; a failure here still keeps the SDK's
        # path in use instead of failing the call.
        from fastmcp.utilities.versions import dedupe_with_versions
        from mcp_types.methods import serialize_server_result

        server = self._server
        reason = _caller_dependent_middleware(server)
        if reason is not None:
            _warn_once(reason)
            return
        # Component auth is the one per-caller filter in the listing. A tool that has it makes the
        # listing depend on the caller, which a caller-blind lookup cannot honour.
        for tool in await _provider_tools(server):
            if tool.auth is not None:
                _warn_once(
                    "a tool has a component auth check, so the listing depends on the caller"
                )
                return
        token = INTERNAL_LISTING.set(True)
        try:
            listed = dedupe_with_versions(list(await server.list_tools()), lambda t: t.name)
        finally:
            INTERNAL_LISTING.reset(token)
        # The handler's result then passes the SDK's per-version sieve, which fixes key order and
        # drops fields the version does not define. The cache holds the schemas as sieved.
        # That version requires `resultType`, `ttlMs` and `cacheScope`; they play no part here.
        dumped = {
            "resultType": "complete",
            "ttlMs": 0,
            "cacheScope": "private",
            "tools": [
                tool.to_mcp_tool(name=tool.name).model_dump(
                    by_alias=True, mode="json", exclude_none=True
                )
                for tool in listed
            ],
        }
        wire = serialize_server_result("tools/list", MODERN_PROTOCOL_VERSION, dumped)
        schemas: dict[str, Mapping[str, Any]] = {t["name"]: t["inputSchema"] for t in wire["tools"]}
        server._mcp_server.get_tool_input_schema = schemas.get  # pyright: ignore[reportPrivateUsage]


def _caller_dependent_middleware(server: FastMCP) -> str | None:
    """Name a middleware that may make the listing depend on the caller, or None."""

    from fastmcp.server.middleware.tool_injection import ToolInjectionMiddleware

    for middleware in server.middleware:
        cls = type(middleware)
        if isinstance(middleware, ToolInjectionMiddleware):
            # FastMCP lists injected tools outside the providers, so their auth is never checked.
            return "a ToolInjectionMiddleware adds tools outside the providers"
        if not any(getattr(cls, hook) is not getattr(Middleware, hook) for hook in _LISTING_HOOKS):
            continue
        name = f"{cls.__module__}.{cls.__qualname__}"
        if name not in CALLER_BLIND_LISTING_MIDDLEWARE:
            return f"middleware {name} may change the listing per caller"
    return None


async def _provider_tools(server: FastMCP) -> list[Any]:
    """Every tool the providers and transforms yield, before enabled and auth filtering."""

    from fastmcp.server.providers.aggregate import AggregateProvider

    return list(await AggregateProvider.list_tools(server))


def install_input_schema_lookup(server: FastMCP) -> bool:
    """Install the cached lookup on one server; return whether it is armed.

    Safe on any `FastMCP` built by Sidekick. Does nothing, with one warning, if the installed
    fastmcp or mcp is not the reviewed version or the expected internals are missing or changed.
    """

    reason = _unreviewed_reason() or _internals_reason(server)
    if reason is not None:
        _warn_once(reason)
        return False
    server.add_middleware(_InputSchemaLookup(server))
    return True

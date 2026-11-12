"""The public MCP server: the FastMCP instance, its middleware and the tool modules it composes."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.prompts import Prompt
from fastmcp.resources import Resource, ResourceTemplate
from fastmcp.server.auth import AuthProvider
from fastmcp.tools import Tool

from sidekick import __version__
from sidekick.mcp.auth import PersonalTokenVerifier, current_actor
from sidekick.mcp.batch_tasks import register_batch_task_tools
from sidekick.mcp.board import register_board_tools
from sidekick.mcp.brief import register_brief_tools
from sidekick.mcp.change_source import ToolChangeSource
from sidekick.mcp.changes import register_change_tools
from sidekick.mcp.contacts import register_contacts_tools
from sidekick.mcp.control import register_control_tools
from sidekick.mcp.input_schemas import install_input_schema_lookup
from sidekick.mcp.instructions import server_instructions
from sidekick.mcp.instrument import instrument_mcp
from sidekick.mcp.journal import register_journal_tools
from sidekick.mcp.license import register_license_tools
from sidekick.mcp.lifecycle import register_lifecycle_tools
from sidekick.mcp.memory import register_memory_tools
from sidekick.mcp.references import register_reference_tools
from sidekick.mcp.reply_scopes import WriteReplyScopes
from sidekick.mcp.request_log import McpRequestLogging
from sidekick.mcp.reschedule import register_reschedule_tools
from sidekick.mcp.rooms import remove_disabled_room_tools, room_actor_provider
from sidekick.mcp.search import register_search_tools
from sidekick.mcp.shopping import register_shopping_tools
from sidekick.mcp.sidekick_app import register_sidekick_app_resource
from sidekick.mcp.titles import LocalizeToolTitles, MirrorToolTitles
from sidekick.mcp.tool_context import ToolContext
from sidekick.mcp.validation_errors import install_validation_error_redaction
from sidekick.mcp.work_cards import register_work_card_tools
from sidekick.mcp.work_tools import register_work_tools
from sidekick.shared.compat import local_provider_components
from sidekick.shared.observability import register_trusted_mcp_names
from sidekick.shared.observability.library_logs import withhold_record_content
from sidekick.shared.types import Actor

if TYPE_CHECKING:
    from collections.abc import Collection

    from sidekick.composition import Container


def _select_auth(container: Container) -> AuthProvider:
    """The bearer scheme for the public MCP surface, chosen by `SIDEKICK_MCP_AUTH_MODE`."""

    if container.settings.mcp_auth_mode == "github_oauth":
        from sidekick.mcp.oauth import build_github_oauth_provider

        return build_github_oauth_provider(container.settings, container.auth, container.telemetry)
    return PersonalTokenVerifier(container.auth)


# FastMCP and the MCP SDK write tool arguments, validation inputs and serializer errors into these
# loggers. Their records are reduced to constant templates for both auth modes, so no argument
# value reaches a log sink even before Sidekick's own sanitised error handling runs.
TOOL_ARGUMENT_LOGGERS = (
    "fastmcp.server.server",
    "fastmcp.server.mixins.mcp_operations",
    "fastmcp.server.low_level",
    "fastmcp.server.http",
    "fastmcp.server.dependencies",
    "fastmcp.tools.base",
    "fastmcp.tools.function_tool",
    "fastmcp.tools.function_parsing",
    "mcp.server.lowlevel.server",
    "mcp.server.streamable_http",
    "mcp.server.streamable_http_manager",
    "mcp.server._streamable_http_modern",
    "mcp.server.session",
    "mcp.server.context",
    "mcp.server.connection",
    "mcp.server.runner",
    "mcp.shared.jsonrpc_dispatcher",
    "mcp.shared.dispatcher",
    "mcp.shared.direct_dispatcher",
    # The SSE response stream logs each chunk (the whole tool result) at DEBUG.
    "sse_starlette.sse",
)


def _register_tools(
    mcp: FastMCP, container: Container, actor_provider: Callable[[], Actor]
) -> None:
    """Register every tool module, in the order the tool list shows them."""

    ctx = ToolContext(
        container,
        actor_provider,
        lambda tool_name: instrument_mcp(container, tool_name),
    )
    register_contacts_tools(mcp, ctx)
    register_journal_tools(mcp, ctx)
    register_control_tools(mcp, ctx)
    register_shopping_tools(mcp, ctx)
    register_lifecycle_tools(mcp, ctx)
    register_reference_tools(mcp, ctx)
    register_search_tools(mcp, ctx)
    register_memory_tools(mcp, ctx)
    register_license_tools(mcp, ctx)
    register_work_card_tools(mcp, ctx)
    register_brief_tools(mcp, ctx)
    register_change_tools(mcp, ctx)
    register_reschedule_tools(mcp, ctx)
    register_batch_task_tools(mcp, ctx)
    register_board_tools(mcp, ctx)
    register_work_tools(mcp, ctx)


def _register_app_resources(
    mcp: FastMCP,
    container: Container,
    actor_provider: Callable[[], Actor],
    enabled: Collection[str],
) -> None:
    locale = container.settings.mcp_app_locale
    update = container.settings.update_reminder
    license_view = container.license.display
    register_sidekick_app_resource(
        mcp,
        actor_provider,
        locale,
        enabled,
        update,
        license_view,
        owner_timezone=container.settings.owner_timezone,
    )


def _local_components(mcp: FastMCP) -> list[object]:
    """The components registered on the server's local provider.

    FastMCP's public listings (`local_provider.list_tools()` and friends) are coroutines, and the
    span allowlist must be filled while the server is built, so this reads the provider's component
    store (`_components`, a dict) directly. That store is internal to fastmcp (pinned to 4.1.6 in
    `pyproject.toml`). When its shape is not the reviewed one this raises, so a library change stops
    startup instead of silently leaving the allowlist empty.
    """

    store = local_provider_components(mcp)
    if store is None:
        raise RuntimeError("fastmcp no longer exposes the local provider's component store")
    return list(store.values())


def _register_trusted_span_names(mcp: FastMCP) -> None:
    """Tell the span allowlist which tool names, resource URIs and prompt names are the server's.

    A span named after anything else (an unknown tool a client called) is exported as `unknown`.
    """

    components = _local_components(mcp)
    register_trusted_mcp_names(
        tools=[item.name for item in components if isinstance(item, Tool)],
        resources=[
            *(str(item.uri) for item in components if isinstance(item, Resource)),
            *(item.uri_template for item in components if isinstance(item, ResourceTemplate)),
        ],
        prompts=[item.name for item in components if isinstance(item, Prompt)],
    )


def create_mcp_server(
    container: Container,
    *,
    actor_provider: Callable[[], Actor] = current_actor,
    enable_auth: bool = True,
) -> FastMCP:
    withhold_record_content(TOOL_ARGUMENT_LOGGERS, label="fastmcp tool")
    enabled = container.settings.enabled_room_set
    # A room that is switched off also loses its scopes, so tools that look across rooms skip it.
    actor_provider = room_actor_provider(actor_provider, enabled)
    mcp = FastMCP(
        container.settings.mcp_server_name,
        instructions=server_instructions(enabled),
        version=__version__,
        auth=_select_auth(container) if enable_auth else None,
        mask_error_details=True,
        # Arguments are checked against the listed JSON Schema by
        # `install_validation_error_redaction`, then validated by pydantic in its usual mode.
        strict_input_validation=False,
    )
    mcp.add_middleware(McpRequestLogging())
    mcp.add_middleware(ToolChangeSource(mcp))
    install_validation_error_redaction(mcp)
    # After the NUL and schema checks, so malformed input is still answered as such.
    mcp.add_middleware(WriteReplyScopes(mcp, actor_provider))
    install_input_schema_lookup(mcp)
    _register_tools(mcp, container, actor_provider)
    _register_app_resources(mcp, container, actor_provider, enabled)
    # After every tool is registered: leave out the rooms that are switched off, give each tool its
    # title in the app language, then mirror that title into annotations.title.
    remove_disabled_room_tools(mcp, enabled)
    mcp.add_transform(LocalizeToolTitles(container.settings.mcp_app_locale))
    mcp.add_transform(MirrorToolTitles())
    _register_trusted_span_names(mcp)
    return mcp

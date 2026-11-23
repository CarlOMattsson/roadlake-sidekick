"""Tell the audit trail whether an MCP tool call is the model's or the owner's app.

A tool hidden from the model (`visibility=["app"]`) is only called by the Sidekick app on the
owner's behalf, so its changes are the owner's. The app also calls the tools Claude uses; those
calls carry `APP_ORIGIN_META` in the request's `_meta`, which the app's bridge adds to every
`tools/call` and which the model cannot set (it only sends arguments). Any other call is a model
call, so its changes are Claude's. The mark is a label for the history, not a permission: every
call is authorized by its scopes as before. The middleware sets the source for the duration of the
call; the audit writer reads it (`sidekick.shared.change_source`). It reads the tool's listed
visibility and the request's origin mark, never its arguments.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Final, cast
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams

from sidekick.mcp.correlation import UNKNOWN_CORRELATION
from sidekick.mcp.decision_ticket import (
    TICKET_ARGUMENT,
    DecisionTickets,
    SpentTicket,
    TicketEntry,
    TicketRefusal,
    binding_of,
    request_client_id,
)
from sidekick.mcp.results import error_result
from sidekick.shared.change_source import ChangeSource, change_source
from sidekick.shared.errors import AuthenticationRequiredError, PermissionDeniedError
from sidekick.shared.observability import safe_log_fields
from sidekick.shared.types import Actor

LOGGER = logging.getLogger("sidekick.mcp.tool")

APP_ORIGIN_META = "com.roadlake.sidekick/origin"
"""The `_meta` key the Sidekick app puts on its `tools/call`; its value is `"app"`."""


OWNER_DECISION_META: Final = "com.roadlake.sidekick/ownerDecision"
"""The tool meta that marks a decision only the owner makes, by a click in the app (approve, run).

It is not `anthropic/requiresUserInteraction`. That key makes Claude Code ask a person before each
call that Claude makes, and a host may apply it to a call the app makes as well, so the owner's own
click in the open app could be refused by the host. The gates here are the app-only visibility (the
model never lists the tool), the server refusal of a call without the app's origin mark, and the
click itself.
"""


REQUIRES_APP_META: Final = "com.roadlake.sidekick/requiresApp"
"""The tool meta that marks a tool only the app may call, without a person confirming each call.

A tool that takes or returns the bytes of a photo carries it: it is hidden from the model, and the
server refuses a call that does not come from the app, so a model that names the tool is refused.
"""


def called_by_app(call_meta: Mapping[str, object] | None) -> bool:
    """Whether the request carries the app's origin mark, which the model cannot add."""

    return (call_meta or {}).get(APP_ORIGIN_META) == "app"


def source_of_tool(meta: Mapping[str, object] | None) -> ChangeSource:
    """`you` for a tool whose `_meta.ui.visibility` is exactly `["app"]`, else `claude`."""

    ui: object = (meta or {}).get("ui")
    visibility = cast("dict[str, object]", ui).get("visibility") if isinstance(ui, dict) else None
    return "you" if visibility == ["app"] else "claude"


def source_of_call(
    tool_meta: Mapping[str, object] | None, call_meta: Mapping[str, object] | None
) -> ChangeSource:
    """`you` for an app-only tool or a call the app marked as its own, else `claude`."""

    if called_by_app(call_meta):
        return "you"
    return source_of_tool(tool_meta)


class ToolChangeSource(Middleware):
    """Run each `tools/call` with the change source of the tool that was called."""

    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool = await self._mcp.get_tool(context.message.name)
        request = context.fastmcp_context.request_context if context.fastmcp_context else None
        source = source_of_call(
            tool.meta if tool is not None else None, request.meta if request else None
        )
        with change_source(source):
            return await call_next(context)


def is_owner_decision(tool_meta: Mapping[str, object] | None) -> bool:
    """Whether the tool is hidden from the model and is the owner's decision (approve or run)."""

    return source_of_tool(tool_meta) == "you" and (tool_meta or {}).get(OWNER_DECISION_META) is True


def requires_app(tool_meta: Mapping[str, object] | None) -> bool:
    """Whether the server refuses the tool unless the request comes from the app.

    That holds for an owner's decision and for every tool that carries `REQUIRES_APP_META`; each is
    hidden from the model as well.
    """

    return source_of_tool(tool_meta) == "you" and (
        (tool_meta or {}).get(OWNER_DECISION_META) is True
        or (tool_meta or {}).get(REQUIRES_APP_META) is True
    )


UI_EXTENSION: Final = "io.modelcontextprotocol/ui"
"""The client capability extension a host declares when it renders MCP Apps."""


def client_ui_signal(context: MiddlewareContext[CallToolRequestParams]) -> str:
    """Whether the client declared the MCP Apps extension: `declared`, `absent` or `unknown`.

    Only a diagnostic for the owner's real-host tests; nothing is decided by it yet.
    """

    try:
        capabilities = (
            context.fastmcp_context.session.client_capabilities if context.fastmcp_context else None
        )
    except (AttributeError, RuntimeError):
        return "unknown"
    if capabilities is None:
        return "unknown"
    return "declared" if UI_EXTENSION in (capabilities.extensions or {}) else "absent"


class OwnerDecisionsFromTheApp(Middleware):
    """Refuse a call by name to an app-only tool unless the app made it.

    An approval, a spending decision or a photo is hidden from the model, but hiding is only a
    listing. The server also refuses the call unless it proves the app made it, so a model naming
    the tool is refused before anything is read or written, and the audit trail never labels such a
    call as the owner's. The tools are those that `requires_app` names, by their metadata and never
    by a list of names. The refusal is the ordinary `forbidden` result with the reason `app_only`.

    The proof is a decision ticket, a signed single-use token the app got with the data it renders
    the decision from and sends back as `decision_ticket` (see `decision_ticket`). For one release
    the request's origin mark, which a host may drop on its way (Claude Desktop over stdio does),
    is still accepted in its place, so nothing that works today stops working. A tool that takes no
    ticket (a photo tool, which no app card calls) needs the origin mark as before.
    """

    def __init__(
        self, mcp: FastMCP, tickets: DecisionTickets, actor_provider: Callable[[], Actor]
    ) -> None:
        self._mcp = mcp
        self._tickets = tickets
        self._actor_provider = actor_provider

    def _check_ticket(
        self, tool_meta: Mapping[str, object] | None, name: str, arguments: Mapping[str, object]
    ) -> SpentTicket | str:
        """The spent ticket, or the closed code that says why the call has none that holds."""

        binding = binding_of(tool_meta)
        if binding is None:
            return "app_only"
        ticket = arguments.get(TICKET_ARGUMENT)
        if not isinstance(ticket, str) or not ticket:
            return "decision_ticket_missing"
        object_arg, digest_arg = binding
        object_id, digest = arguments.get(object_arg), arguments.get(digest_arg)
        if not isinstance(object_id, str | UUID) or not isinstance(digest, str):
            return f"decision_ticket_{TicketRefusal.MISMATCH}"
        try:
            owner = str(self._actor_provider().user_id)
        except AuthenticationRequiredError:
            return "app_only"
        entry = TicketEntry(name, str(object_id), digest)
        verdict = self._tickets.verify(ticket, entry, owner=owner, client=request_client_id())
        return verdict if isinstance(verdict, SpentTicket) else f"decision_ticket_{verdict}"

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        tool = await self._mcp.get_tool(name)
        if tool is None or not requires_app(tool.meta):
            return await call_next(context)
        request = context.fastmcp_context.request_context if context.fastmcp_context else None
        marked = called_by_app(request.meta if request else None)
        proof = self._check_ticket(tool.meta, name, context.message.arguments or {})
        ui = client_ui_signal(context)
        if isinstance(proof, SpentTicket):
            return await self._decide(context, call_next, proof, marked=marked, ui=ui)
        if marked:
            # The host kept the origin mark but no ticket holds: allowed for this release, logged.
            LOGGER.info(
                "mcp_owner_decision",
                extra=safe_log_fields(
                    {
                        "mcp_tool_name": name,
                        "mcp_decision_via": "origin_mark",
                        "mcp_error_code": proof,
                        "mcp_client_ui": ui,
                    }
                ),
            )
            return await call_next(context)
        return self._refuse(name, proof, ui)

    async def _decide(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
        spent: SpentTicket,
        *,
        marked: bool,
        ui: str,
    ) -> ToolResult:
        """Run the decision on a valid ticket; a failed call gives the ticket back for a retry."""

        LOGGER.info(
            "mcp_owner_decision",
            extra=safe_log_fields(
                {
                    "mcp_tool_name": context.message.name,
                    "mcp_decision_via": "ticket",
                    "mcp_origin_mark": "present" if marked else "absent",
                    "mcp_client_ui": ui,
                }
            ),
        )
        try:
            outcome = await call_next(context)
        except BaseException:
            self._tickets.release(spent)
            raise
        if outcome.is_error:
            self._tickets.release(spent)
        return outcome

    @staticmethod
    def _refuse(name: str, code: str, ui: str) -> ToolResult:
        error = PermissionDeniedError("this is done in the app", reason="app_only")
        refusal = error_result(error)
        LOGGER.info(
            "mcp_tool_failed",
            extra=safe_log_fields(
                {
                    "correlation_id": (refusal.structured_content or {}).get(
                        "correlation_id", UNKNOWN_CORRELATION
                    ),
                    "mcp_tool_name": name,
                    "mcp_error_class": type(error).__name__,
                    # Tells this refusal from a scope refusal, and says what the app did not
                    # send: `decision_ticket_missing` is a host that dropped the result `_meta`
                    # the ticket travels in, `app_only` a call with neither ticket nor mark.
                    "mcp_error_code": code,
                    "mcp_client_ui": ui,
                }
            ),
        )
        return refusal

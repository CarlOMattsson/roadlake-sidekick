"""The MCP tool that sets the instance's license key (D-081: offline signed license keys):
`set_license_key`.

It calls the same use case as the companion route and the command line
(`sidekick.license.service`). Only the installation's only active user may set the key; the tool
also needs its own scope, `license:write`, so a token that only changes tasks (or is read-only)
cannot. The key is an argument and is never echoed, logged or put in an error: the answer carries
the display state alone. A key that does not verify changes nothing and is reported as not
accepted.

The tool is app-only (`visibility=["app"]`, as the other owner-UI writes): the license field of
the app calls it and the model's tool list does not show it. That is a visibility marker, not a
confidential channel: the call still passes through the MCP host, which can see its argument. The
key is a signed license string, not an account credential, and Sidekick never logs or echoes it.
"""

from __future__ import annotations

from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.apps import AppConfig

from sidekick.license.key import LicenseView
from sidekick.mcp.annotations import WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.tool_context import ToolContext
from sidekick.structured.base import Output

WRITE_SCOPE = "license:write"

SET_LICENSE_DESCRIPTION = (
    "App-only. Enters the instance's license key (ROADLAKE-1.…), checked offline against the "
    "owner's public key. Only the installation's only owner may. Returns whether the key was "
    "accepted and the license state; a key that is not accepted changes nothing."
)


class SetLicenseKeyResult(Output):
    """The display state (`state`, and `licensee`, `kind`, `expires` when it carries them) plus
    whether the key was accepted. The same shape the app document and the companion routes use."""

    state: Literal["unlicensed", "licensed", "expired", "invalid"]
    licensee: str | None = None
    kind: Literal["personal", "org"] | None = None
    expires: str | None = None
    accepted: bool


def _summary(accepted: bool, view: LicenseView) -> str:
    if not accepted:
        return "That license key was not accepted. Nothing changed."
    if view.state == "expired":
        return f"License key saved, but it expired {view.expires}."
    return f"License key saved. Licensed to {view.licensee} until {view.expires}."


def register_license_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register `set_license_key` over the license use case."""

    @mcp.tool(
        name="set_license_key",
        description=SET_LICENSE_DESCRIPTION,
        output_schema=output_schema(SetLicenseKeyResult),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("set_license_key")
    def set_license_key(key: str) -> Any:
        actor = ctx.actor_provider()
        actor.require(WRITE_SCOPE)
        outcome = ctx.container.license.set_by_owner(
            actor.user_id, key, correlation_id=request_correlation_id_or_new()
        )
        output = SetLicenseKeyResult.model_validate(
            {**outcome.view.as_json(), "accepted": outcome.accepted}
        )
        return result(
            output.model_dump(mode="json", exclude_none=True),
            _summary(outcome.accepted, outcome.view),
        )

"""Mark every HTTP request as the owner's own app, as far as the audit trail is concerned.

The REST and companion routes are called by the Sidekick app and the companion app, which act for
the owner. The mounted MCP server overrides this for each tool call (`sidekick.mcp.change_source`),
because a model tool there is Claude's change.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

from sidekick.shared.change_source import change_source


class OwnerAppChangeSource:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with change_source("you"):
            await self.app(scope, receive, send)

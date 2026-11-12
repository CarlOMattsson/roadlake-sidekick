"""The Sidekick MCP App resource: the one URI every app tool names in `_meta.ui.resourceUri`.

Every app tool points at `SIDEKICK_APP_URI`, so the host fetches and caches the app HTML (450 kB)
once for the whole server. The app reads its data only through `tools/call`, on the tools that
open it, and each of those tools checks its own scope. The resource therefore needs only that the
caller can read at least one kind of record, the same floor as the Control card.

There is no per-app resource: the former work, journal, shopping and control URIs are gone.
"""

from collections.abc import Callable, Collection

from fastmcp import FastMCP

from sidekick.license.key import LicenseView
from sidekick.mcp.app_meta import (
    APP_RESOURCE,
    app_html_path,
    with_app_context,
)
from sidekick.shared.build_info import UpdateReminder
from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE
from sidekick.shared.locale import AppLocale
from sidekick.shared.types import Actor

SIDEKICK_APP_URI = "ui://sidekick/app-v1.html"
# Any one of these opens the app. Each tool still checks its own scope when it returns data.
APP_READ_SCOPES = (
    "tasks:read",
    "projects:read",
    "contacts:read",
    "journal:read",
    "shopping:read",
)
# Served until `npm --prefix frontend run build:mcp-app` has written the built view.
_NOT_BUILT = (
    '<!doctype html><html><head><meta charset="utf-8"><title>Sidekick</title></head>'
    "<body><p>Sidekick is not available.</p></body></html>\n"
)


def require_any_app_read_scope(actor: Actor) -> None:
    """Passes when the actor reads at least one kind of record, else raises like a missing scope."""
    if not any(scope in actor.scopes for scope in APP_READ_SCOPES):
        actor.require(APP_READ_SCOPES[0])


def register_sidekick_app_resource(
    mcp: FastMCP,
    actor_provider: Callable[[], Actor],
    locale: AppLocale,
    rooms: Collection[str],
    update: UpdateReminder | None,
    license_view: Callable[[], LicenseView],
    owner_timezone: str = DEFAULT_OWNER_TIMEZONE,
) -> None:
    @mcp.resource(SIDEKICK_APP_URI, name="Sidekick", app=APP_RESOURCE)
    def sidekick_app() -> str:
        require_any_app_read_scope(actor_provider())
        built = app_html_path()
        if not built.exists():
            return with_app_context(
                _NOT_BUILT, locale, rooms, update, license_view(), owner_timezone
            )
        return with_app_context(
            built.read_text(encoding="utf-8"), locale, rooms, update, license_view(), owner_timezone
        )

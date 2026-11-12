"""Shared MCP App resource metadata. Every Sidekick app resource declares the same host contract.

The app HTML makes no network calls and loads nothing from outside its own bundle, so the CSP
lists no domains (`connect-src 'none'` in the host). The app draws its own frame, so the host
should not add a border.
"""

import json
from collections.abc import Collection
from html import escape
from pathlib import Path

from fastmcp.apps import AppConfig, ResourceCSP

from sidekick.license.key import LicenseView
from sidekick.shared.build_info import UpdateReminder
from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE
from sidekick.shared.locale import AppLocale
from sidekick.shared.rooms import ordered

APP_RESOURCE = AppConfig(prefers_border=False, csp=ResourceCSP())
APPS_DIR = Path(__file__).parent / "apps"
UNIFIED_APP_FILE = "sidekick.html"


def app_html_path() -> Path:
    """The app HTML every Sidekick app resource serves: the one unified app.

    Looked up on every call, so a build that lands while the server runs is picked up without a
    restart, and tests can point APPS_DIR at a temporary directory.
    """
    return APPS_DIR / UNIFIED_APP_FILE


def with_app_locale(html: str, locale: AppLocale) -> str:
    """Declares the Sidekick app locale in the document head, where the view reads it on start.

    The host's locale is never used for the apps; this value comes only from
    SIDEKICK_MCP_APP_LOCALE.
    """
    return html.replace("<head>", f'<head><meta name="sidekick-app-locale" content="{locale}">', 1)


def with_owner_timezone(html: str, timezone: str) -> str:
    """Expose SIDEKICK_OWNER_TIMEZONE to every room through the app bootstrap."""
    return html.replace(
        "<head>",
        f'<head><meta name="sidekick-owner-timezone" content="{escape(timezone)}">',
        1,
    )


def with_enabled_rooms(html: str, rooms: Collection[str]) -> str:
    """Declares the rooms this instance shows (SIDEKICK_ENABLED_ROOMS), comma-separated.

    The view reads it on start and leaves every other room out of its navigation and its links.
    Without the meta the view shows every room.
    """
    content = ",".join(ordered(rooms))
    return html.replace("<head>", f'<head><meta name="sidekick-rooms" content="{content}">', 1)


def with_update_reminder(html: str, reminder: UpdateReminder | None) -> str:
    """Declares the running code and when to remind (SIDEKICK_UPDATE_REMINDER_DAYS), for the app.

    The app counts the age itself, from the commit date and its own clock, so it needs no network.
    Without the metas (reminder off, or the age unknown) the app never reminds.
    """
    if reminder is None:
        return html
    build = reminder.build
    return html.replace(
        "<head>",
        f'<head><meta name="sidekick-build-commit" content="{build.commit}">'
        f'<meta name="sidekick-build-date" content="{build.committed_at.isoformat()}">'
        f'<meta name="sidekick-update-days" content="{reminder.after_days}">',
        1,
    )


def with_license(html: str, view: LicenseView | None) -> str:
    """Declares the instance's license state (D-081) as compact JSON: `state`, `licensee`, `kind`
    and `expires`, with `null` for what the state does not carry. Never the key itself.

    The licensee is a free-text name, so the JSON is escaped for an HTML attribute. Without the
    meta the app treats the instance as unlicensed.
    """
    if view is None:
        return html
    content = escape(json.dumps(view.as_json(), separators=(",", ":"), ensure_ascii=False))
    return html.replace("<head>", f'<head><meta name="sidekick-license" content="{content}">', 1)


def with_app_context(
    html: str,
    locale: AppLocale,
    rooms: Collection[str],
    update: UpdateReminder | None,
    license_view: LicenseView | None = None,
    owner_timezone: str = DEFAULT_OWNER_TIMEZONE,
) -> str:
    """The app document with all the instance declares: language, time zone, rooms, update reminder
    and license state. `license_view` `None` declares no license."""
    declared = with_update_reminder(
        with_enabled_rooms(with_app_locale(html, locale), rooms), update
    )
    return with_owner_timezone(with_license(declared, license_view), owner_timezone)

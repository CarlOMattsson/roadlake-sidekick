"""Operator commands for companion devices (ADR-005: bounded operator bootstrap).

    python -m sidekick.companion.cli pair --label "Samsung" [--user-id UUID]
        (--scope companion:tasks:read [--scope ...] | --preset app) [--device-days 30]
        [--server-url https://sidekick.example]
    python -m sidekick.companion.cli grant --device-id UUID [--user-id UUID]
        (--scope companion:shopping:read [--scope ...] | --preset app)
    python -m sidekick.companion.cli list [--user-id UUID]
    python -m sidekick.companion.cli revoke --device-id UUID [--user-id UUID]

`pair` requires an explicit choice of rights: `--scope` (repeatable, companion scopes only) or
`--preset app` (tasks, Shopping, Journal, notifications and the license key). It shows the rights
and lifetimes in the app language (on stderr) before it prints the pairing secret once, with its
expiry: paste it into the app within 10 minutes (there is no QR code). With `--server-url` the JSON
also carries `pairing_link`, `sidekick://pair?server=<url>&code=<code>`, which opens the phone's app
with both fields filled in (the app still asks before it pairs). It is single-use; the device
exchanges it at `POST /companion/v1/pair` for its own credential, which the operator never sees.
Without `--user-id` the command uses the installation's only active owner and refuses when there is
not exactly one.

`grant` adds capabilities to a device that is already paired (for example Shopping and Journal to a
phone paired before those rooms existed). It never removes one; the device keeps its credential.
Like `pair` it shows the device's resulting rights in the app language on stderr.

These commands read the database settings from the environment like `sidekick-admin`. They never
print a device credential, and `list` never prints a secret.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from sidekick.companion.persistence import CompanionDeviceStore
from sidekick.companion.service import (
    DEFAULT_DEVICE_LIFETIME_DAYS,
    MAX_DEVICE_LIFETIME_DAYS,
    CompanionDeviceService,
    CompanionDeviceView,
    PairingTicket,
)
from sidekick.shared.auth import COMPANION_SCOPES, AuthService
from sidekick.shared.cli_errors import run_guarded
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale, LocalizedText, localized

PRESETS: dict[str, frozenset[str]] = {
    "app": frozenset(
        {
            "companion:tasks:read",
            "companion:tasks:complete",
            "companion:push",
            "companion:shopping:read",
            "companion:shopping:write",
            "companion:journal:read",
            "companion:journal:write",
            "companion:license",
        }
    ),
}
SCOPE_DESCRIPTIONS: dict[str, LocalizedText] = {
    "companion:tasks:read": {
        "sv": "läsa uppgifter, steg, projekt och dagens agenda",
        "en": "read tasks, steps, projects, and today\u2019s agenda",
    },
    "companion:tasks:complete": {
        "sv": "bocka av och öppna uppgifter och steg igen",
        "en": "check off and reopen tasks and steps",
    },
    "companion:push": {
        "sv": "ta emot aviseringar (registrera telefonens pushadress)",
        "en": "receive notifications (register the phone\u2019s push address)",
    },
    "companion:shopping:read": {
        "sv": "läsa inköpslistor och varor",
        "en": "read shopping lists and items",
    },
    "companion:shopping:write": {
        "sv": "lägga till, ändra och bocka av varor och listor",
        "en": "add, edit, and check off items and lists",
    },
    "companion:journal:read": {
        "sv": "läsa dagbokens dagar och inlägg",
        "en": "read journal days and entries",
    },
    "companion:journal:write": {
        "sv": "skriva och ändra dagboksinlägg för hand (ingen AI)",
        "en": "write and edit journal entries by hand (no AI)",
    },
    "companion:license": {
        "sv": "se licensstatus och ange instansens licensnyckel (bara instansens ägare)",
        "en": "see the license status and enter the instance\u2019s license key (owner only)",
    },
}
UNKNOWN_SCOPE: LocalizedText = {"sv": "okänd rättighet", "en": "unknown permission"}
# Operator-facing notices (stderr). `{label}`, `{expires}` and `{days}` are filled in when printed.
NOTICES: dict[str, LocalizedText] = {
    "granted": {
        "sv": 'Enheten "{label}" har nu följande rättigheter (inga har tagits bort):',
        "en": 'Device "{label}" now has the following permissions (none were removed):',
    },
    "pairing": {
        "sv": 'Enheten "{label}" får följande rättigheter:',
        "en": 'Device "{label}" gets the following permissions:',
    },
    "secret_valid": {
        "sv": "Parningshemligheten gäller till {expires} (10 minuter) och kan användas en gång.",
        "en": "The pairing secret is valid until {expires} (10 minutes) and can be used once.",
    },
    "device_valid": {
        "sv": "Enhetens inloggning gäller i {days} dagar.",
        "en": "The device\u2019s sign-in is valid for {days} days.",
    },
    "shown_once": {
        "sv": "Hemligheten visas bara nu:",
        "en": "The secret is shown only now:",
    },
}


PAIRING_LINK_SCHEME = "sidekick://pair"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "10.0.2.2"})


def _server_origin(text: str) -> str:
    """An https origin (http only for this machine, in development), nothing after the host."""
    parts = urlsplit(text.strip())
    allowed = parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS)
    if (
        not allowed
        or not parts.hostname
        or parts.username is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise argparse.ArgumentTypeError("must be an https origin such as https://sidekick.example")
    return f"{parts.scheme}://{parts.netloc}"


def pairing_link(server_url: str, secret: str) -> str:
    """The deep link that fills in the app's pairing screen (the app asks before it pairs)."""
    return f"{PAIRING_LINK_SCHEME}?{urlencode({'server': server_url, 'code': secret})}"


USER_ID_HELP = "the owner; default is the only active owner"


def build_parser() -> argparse.ArgumentParser:
    """The parser of `sidekick-companion`; building it reads no settings or database."""

    parser = argparse.ArgumentParser(prog="sidekick-companion")
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair", help="issue a 10-minute, single-use pairing secret")
    pair.add_argument("--label", required=True, help="the device's name, e.g. Samsung")
    pair.add_argument("--user-id", type=UUID, help=USER_ID_HELP)
    pair.add_argument(
        "--scope",
        action="append",
        choices=sorted(COMPANION_SCOPES),
        help="grant this device capability; repeatable, companion scopes only "
        "(required unless --preset is given)",
    )
    pair.add_argument(
        "--preset",
        action="append",
        choices=sorted(PRESETS),
        help="named set of capabilities, only when written explicitly: "
        "app = tasks, Inköp and Dagbok, notifications, license key (companion:tasks:read + "
        "companion:tasks:complete + companion:push + companion:shopping:read/write + "
        "companion:journal:read/write + companion:license)",
    )
    pair.add_argument(
        "--server-url",
        type=_server_origin,
        help="the https address the phone reaches this server on (scheme and host, nothing after); "
        "adds a sidekick://pair link that fills in the app's pairing screen",
    )
    pair.add_argument(
        "--device-days",
        type=int,
        default=DEFAULT_DEVICE_LIFETIME_DAYS,
        help=f"device credential lifetime in days, 1 to {MAX_DEVICE_LIFETIME_DAYS}",
    )
    grant = commands.add_parser("grant", help="add capabilities to a paired device (never removes)")
    grant.add_argument("--device-id", type=UUID, required=True, help="the device to add to")
    grant.add_argument("--user-id", type=UUID, help=USER_ID_HELP)
    grant.add_argument(
        "--scope",
        action="append",
        choices=sorted(COMPANION_SCOPES),
        help="add this device capability; repeatable (required unless --preset is given)",
    )
    grant.add_argument(
        "--preset",
        action="append",
        choices=sorted(PRESETS),
        help="add a named set of capabilities, only when written explicitly (see pair)",
    )
    listing = commands.add_parser("list", help="list the owner's companion devices")
    listing.add_argument("--user-id", type=UUID, help=USER_ID_HELP)
    revoke = commands.add_parser("revoke", help="revoke one companion device")
    revoke.add_argument("--device-id", type=UUID, required=True, help="the device to revoke")
    revoke.add_argument("--user-id", type=UUID, help=USER_ID_HELP)
    return parser


def run(
    argv: Sequence[str] | None,
    store: CompanionDeviceStore,
    auth: AuthService,
    out: TextIO = sys.stdout,
    notice: TextIO | None = None,
    locale: AppLocale = DEFAULT_LOCALE,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    scopes: frozenset[str] = frozenset()
    if args.command in ("pair", "grant"):
        scopes = frozenset(args.scope or ()).union(*(PRESETS[name] for name in args.preset or ()))
        if not scopes:
            parser.error(
                f"{args.command} requires an explicit --scope (repeatable) or --preset app"
            )
    service = CompanionDeviceService(store, auth)
    try:
        user_id = args.user_id or _only_active_owner(store)
    except ValueError as error:
        parser.error(str(error))
    if args.command == "pair":
        try:
            ticket = service.create_pairing(
                user_id, args.label, scopes=scopes, device_lifetime_days=args.device_days
            )
        except ValueError as error:
            parser.error(str(error))
        # The rights go to stderr so stdout stays one JSON document; they come first.
        print(_rights_notice(ticket, locale), file=notice or sys.stderr, flush=True)
        link = pairing_link(args.server_url, ticket.secret) if args.server_url else None
        print(json.dumps(_ticket_json(ticket, link), indent=2), file=out)
        return 0
    if args.command == "grant":
        try:
            granted = service.grant_scopes(user_id, args.device_id, scopes)
        except ValueError as error:
            parser.error(str(error))
        if granted is None:
            parser.error("device not found or revoked")
        print(_granted_notice(granted, locale), file=notice or sys.stderr, flush=True)
        print(json.dumps(_device_json(granted), indent=2), file=out)
        return 0
    if args.command == "list":
        print(
            json.dumps([_device_json(item) for item in service.list_devices(user_id)], indent=2),
            file=out,
        )
        return 0
    if not service.revoke_device(user_id, args.device_id):
        parser.error("device not found")
    print(json.dumps({"revoked": str(args.device_id)}), file=out)
    return 0


def _only_active_owner(store: CompanionDeviceStore) -> UUID:
    owners = store.read(lambda session: store.active_owner_ids(session, 2))
    if len(owners) != 1:
        raise ValueError("pass --user-id: there is not exactly one active owner")
    return owners[0]


def _scope_lines(scopes: Sequence[str], locale: AppLocale) -> list[str]:
    return [
        f"  - {scope}: {localized(SCOPE_DESCRIPTIONS.get(scope, UNKNOWN_SCOPE), locale)}"
        for scope in sorted(scopes)
    ]


def _granted_notice(device: CompanionDeviceView, locale: AppLocale) -> str:
    lines = [localized(NOTICES["granted"], locale).format(label=device.label)]
    lines += _scope_lines(device.scopes, locale)
    return "\n".join(lines)


def _rights_notice(ticket: PairingTicket, locale: AppLocale) -> str:
    lines = [localized(NOTICES["pairing"], locale).format(label=ticket.label)]
    lines += _scope_lines(ticket.scopes, locale)
    lines.append(
        localized(NOTICES["secret_valid"], locale).format(expires=ticket.expires_at.isoformat())
    )
    lines.append(
        localized(NOTICES["device_valid"], locale).format(days=ticket.device_lifetime_days)
    )
    lines.append(localized(NOTICES["shown_once"], locale))
    return "\n".join(lines)


def _ticket_json(ticket: PairingTicket, link: str | None = None) -> dict[str, object]:
    document: dict[str, object] = {
        "pairing_secret": ticket.secret,
        "expires_at": ticket.expires_at.isoformat(),
        "label": ticket.label,
        "scopes": list(ticket.scopes),
        "device_lifetime_days": ticket.device_lifetime_days,
        "exchange": 'POST /companion/v1/pair {"pairing_secret": ...}',
    }
    if link is not None:
        document["pairing_link"] = link
    return document


def _device_json(device: CompanionDeviceView) -> dict[str, object]:
    return {
        "id": str(device.id),
        "label": device.label,
        "scopes": list(device.scopes),
        "expires_at": device.expires_at.isoformat(),
        "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
        "last_used_at": device.last_used_at.isoformat() if device.last_used_at else None,
        "created_at": device.created_at.isoformat(),
    }


def _run_from_settings() -> int:
    from sidekick.composition import create_auth_service
    from sidekick.shared.config import get_settings
    from sidekick.shared.persistence import create_session_factory

    settings = get_settings()
    factory = create_session_factory(settings.database_url, timeouts=settings.database_timeouts)
    return run(
        None,
        CompanionDeviceStore(factory),
        create_auth_service(factory, settings),
        locale=settings.mcp_app_locale,
    )


def main() -> None:
    raise SystemExit(run_guarded("sidekick-companion", _run_from_settings))


if __name__ == "__main__":
    main()

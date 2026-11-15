"""Operator commands for webhook tokens (home and phone automation, `/webhooks/v1/`).

    python -m sidekick.webhooks.cli create --label "Home Assistant"
        --scope webhook:shopping:add [--scope webhook:tasks:create] [--user-id UUID]
        [--expires-in-days 365] [--rate-limit 30]
    python -m sidekick.webhooks.cli list [--user-id UUID]
    python -m sidekick.webhooks.cli revoke --token-id UUID [--user-id UUID]

`create` requires an explicit choice of scopes (no scope is implied), prints the token once as JSON
and never again: only its keyed digest and its first characters are stored. A token lasts a year
unless `--expires-in-days` says otherwise (at most two years, never forever) and may make 30 calls
a minute unless `--rate-limit` says otherwise (at most 600). `list` shows each token's record id,
label, prefix, scopes, limits and times, never a token. `revoke` stops a token at once; it is
idempotent. Without `--user-id` the commands use the installation's only active owner and refuse
when there is not exactly one.

These commands read the database settings from the environment like `sidekick-admin`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO
from uuid import UUID

from sidekick.shared.cli_errors import run_guarded
from sidekick.webhooks.store import WebhookTokenRecord, WebhookTokenStore
from sidekick.webhooks.tokens import (
    DEFAULT_LIFETIME_DAYS,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    MAX_LIFETIME_DAYS,
    MAX_RATE_LIMIT_PER_MINUTE,
    WEBHOOK_SCOPES,
    IssuedWebhookToken,
    WebhookTokenService,
)

USER_ID_HELP = "the owner; default is the only active owner"


def build_parser() -> argparse.ArgumentParser:
    """The parser of the webhook commands; building it reads no settings or database."""

    parser = argparse.ArgumentParser(prog="sidekick-webhooks")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="issue a webhook token and print it once")
    create.add_argument(
        "--label", required=True, help="the integration's name, e.g. Home Assistant"
    )
    create.add_argument("--user-id", type=UUID, help=USER_ID_HELP)
    create.add_argument(
        "--scope",
        action="append",
        choices=sorted(WEBHOOK_SCOPES),
        required=True,
        help="an action the token may call; repeatable. No scope is implied",
    )
    create.add_argument(
        "--expires-in-days",
        type=int,
        default=DEFAULT_LIFETIME_DAYS,
        help=f"token lifetime in days, 1 to {MAX_LIFETIME_DAYS} (default {DEFAULT_LIFETIME_DAYS})",
    )
    create.add_argument(
        "--rate-limit",
        type=int,
        default=DEFAULT_RATE_LIMIT_PER_MINUTE,
        help=f"calls per minute, 1 to {MAX_RATE_LIMIT_PER_MINUTE} "
        f"(default {DEFAULT_RATE_LIMIT_PER_MINUTE})",
    )
    listing = commands.add_parser("list", help="list the owner's webhook tokens (never a token)")
    listing.add_argument("--user-id", type=UUID, help=USER_ID_HELP)
    revoke = commands.add_parser("revoke", help="revoke one webhook token")
    revoke.add_argument("--token-id", type=UUID, required=True, help="the token to revoke")
    revoke.add_argument("--user-id", type=UUID, help=USER_ID_HELP)
    return parser


def run(argv: Sequence[str] | None, service: WebhookTokenService, out: TextIO = sys.stdout) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    user_id = args.user_id or _only_active_owner(parser, service)
    if args.command == "create":
        try:
            issued = service.create(
                user_id,
                args.label,
                args.scope,
                lifetime_days=args.expires_in_days,
                rate_limit_per_minute=args.rate_limit,
            )
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps(_issued_json(issued), indent=2), file=out)
        return 0
    if args.command == "list":
        print(
            json.dumps([_token_json(item) for item in service.list_tokens(user_id)], indent=2),
            file=out,
        )
        return 0
    if not service.revoke(user_id, args.token_id):
        parser.error("token not found")
    print(json.dumps({"revoked": str(args.token_id)}), file=out)
    return 0


def _only_active_owner(parser: argparse.ArgumentParser, service: WebhookTokenService) -> UUID:
    owners = service.active_owner_ids(2)
    if len(owners) != 1:
        parser.error("pass --user-id: there is not exactly one active owner")
    return owners[0]


def _token_json(view: WebhookTokenRecord) -> dict[str, object]:
    return {
        "id": str(view.id),
        "label": view.label,
        "token_prefix": view.token_prefix,
        "scopes": list(view.scopes),
        "rate_limit_per_minute": view.rate_limit_per_minute,
        "expires_at": view.expires_at.isoformat(),
        "revoked_at": view.revoked_at.isoformat() if view.revoked_at else None,
        "last_used_at": view.last_used_at.isoformat() if view.last_used_at else None,
        "created_at": view.created_at.isoformat(),
    }


def _issued_json(issued: IssuedWebhookToken) -> dict[str, object]:
    return {"token": issued.token, "shown_once": True, **_token_json(issued.record)}


def _run_from_settings() -> int:
    from sidekick.composition import create_auth_service
    from sidekick.shared.config import get_settings
    from sidekick.shared.persistence import create_session_factory

    settings = get_settings()
    factory = create_session_factory(settings.database_url, timeouts=settings.database_timeouts)
    return run(
        None,
        WebhookTokenService(WebhookTokenStore(factory), create_auth_service(factory, settings)),
    )


def main() -> None:
    raise SystemExit(run_guarded("sidekick-webhooks", _run_from_settings))


if __name__ == "__main__":
    main()

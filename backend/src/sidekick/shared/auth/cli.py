"""Finite operator commands for provisioning users and MCP credentials.

`create-user` needs no terminal: it prints the new user's UUID, which is what
`SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES` maps a GitHub identity to. The commands read the same
settings as the API except that the MCP OAuth policy is not validated (see `get_admin_settings`),
so the first user can be created before that policy names them.

`empty-trash` is the operator's way to empty the trash (D-031): it only counts unless `--yes` is
given, and every removal goes through the lifecycle use case that accepts only trashed records.
"""

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sidekick.shared.auth import OPT_IN_SCOPES, TOKEN_SCOPES
from sidekick.shared.cli_errors import run_guarded
from sidekick.shared.config import Settings, get_admin_settings
from sidekick.shared.persistence import create_session_factory

TOKEN_SCOPE_CHOICES = tuple(sorted(TOKEN_SCOPES | OPT_IN_SCOPES))
# A token with no explicit lifetime lasts this long; `--expires-in-days` may ask for up to the
# maximum, and only `--never-expires` (a deliberate, separate flag) issues a token that never ends.
DEFAULT_TOKEN_LIFETIME_DAYS = 90
MAX_TOKEN_LIFETIME_DAYS = 365
MAX_TRASH_AGE_DAYS = 36500
# The unique constraint of `users.username` (baseline migration): only it means a login clash.
USERNAME_CONSTRAINT = "users_username_key"


def build_parser() -> argparse.ArgumentParser:
    """The parser of `sidekick-admin`; building it reads no settings and touches no database."""

    parser = argparse.ArgumentParser(prog="sidekick-admin")
    subparsers = parser.add_subparsers(dest="command", required=True)
    user = subparsers.add_parser("create-user", help="create a user and print its UUID")
    user.add_argument("--login", required=True, help="the user's login name")
    user.add_argument("--display-name", required=True, help="the name shown for the user")
    token = subparsers.add_parser(
        "create-token", help="issue a personal access token for MCP clients and print it once"
    )
    token.add_argument("--user-id", type=UUID, required=True, help="the user the token belongs to")
    token.add_argument("--label", required=True, help="a name that tells the token apart in lists")
    token.add_argument(
        "--scope",
        action="append",
        choices=TOKEN_SCOPE_CHOICES,
        help="a scope the client needs; repeat once per scope. Required: no scope is implied",
    )
    lifetime = token.add_mutually_exclusive_group()
    lifetime.add_argument(
        "--expires-in-days",
        type=int,
        choices=range(1, MAX_TOKEN_LIFETIME_DAYS + 1),
        metavar=f"1..{MAX_TOKEN_LIFETIME_DAYS}",
        default=DEFAULT_TOKEN_LIFETIME_DAYS,
        help=f"token lifetime in days (default {DEFAULT_TOKEN_LIFETIME_DAYS})",
    )
    lifetime.add_argument(
        "--never-expires",
        action="store_true",
        help="issue a token without an end date; revoke it with revoke-token when done",
    )
    token_list = subparsers.add_parser(
        "list-tokens", help="list a user's personal tokens as JSON (never the token itself)"
    )
    token_list.add_argument("--user-id", type=UUID, required=True, help="the user to list for")
    token_revoke = subparsers.add_parser("revoke-token", help="revoke one personal token")
    token_revoke.add_argument("--token-id", type=UUID, required=True, help="the token to revoke")
    disable = subparsers.add_parser(
        "disable-user", help="disable a user so none of their credentials work"
    )
    disable.add_argument("--user-id", type=UUID, required=True, help="the user to disable")
    trash = subparsers.add_parser(
        "empty-trash",
        help="permanently remove everything in the trash (counts only unless --yes is given)",
    )
    trash.add_argument(
        "--yes",
        action="store_true",
        help="really delete; without it the command only prints how many records it would delete",
    )
    trash.add_argument(
        "--older-than",
        type=int,
        metavar="DAYS",
        choices=range(0, MAX_TRASH_AGE_DAYS + 1),
        help="only records that have been in the trash for at least this many days",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    code = run_guarded(
        "sidekick-admin",
        lambda: _run_command(parser, args),
        conflict_message="user already exists" if args.command == "create-user" else None,
        conflict_constraint=USERNAME_CONSTRAINT,
    )
    if code:
        sys.exit(code)


def _run_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    settings = get_admin_settings()
    if args.command == "empty-trash":
        run_empty_trash(settings, remove=args.yes, older_than_days=args.older_than)
        return
    # Imported late: this entrance provisions owners, which needs the other contexts' hooks that
    # only the composition root wires, and composition itself imports `sidekick.shared.auth`.
    from sidekick.composition import create_auth_service

    service = create_auth_service(
        create_session_factory(settings.database_url, timeouts=settings.database_timeouts),
        settings,
    )
    if args.command == "create-user":
        print(service.provision_user(args.login, args.display_name))
    elif args.command == "create-token":
        if not args.scope:
            parser.error(missing_scope_message())
        expires_at = (
            None if args.never_expires else service_now() + timedelta(days=args.expires_in_days)
        )
        token = service.create_personal_token(
            args.user_id, args.label, scopes=frozenset(args.scope), expires_at=expires_at
        )
        if expires_at is None:
            print(
                "warning: this token never expires; revoke it with revoke-token.", file=sys.stderr
            )
        print(token)
    elif args.command == "list-tokens":
        print(
            json.dumps(
                [
                    {
                        "id": str(item.id),
                        "label": item.label,
                        "scopes": item.scopes,
                        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                        "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
                        "last_used_at": item.last_used_at.isoformat()
                        if item.last_used_at
                        else None,
                        "created_at": item.created_at.isoformat(),
                        "purpose": item.purpose,
                    }
                    for item in service.list_personal_tokens(args.user_id)
                ],
                indent=2,
            )
        )
    elif args.command == "revoke-token":
        if not service.revoke_personal_token(args.token_id):
            parser.error("token not found")
    elif args.command == "disable-user" and not service.disable_user(args.user_id):
        parser.error("user not found")


def run_empty_trash(settings: Settings, *, remove: bool, older_than_days: int | None) -> None:
    """Print counts per record kind, and delete only with `remove`; never a title or any text."""

    # Imported late for the same reason as in `main`: composition imports `sidekick.shared.auth`.
    from sidekick.composition import create_admin_lifecycle_service, sweep_trash_for_admin

    lifecycle = create_admin_lifecycle_service(
        create_session_factory(settings.database_url, timeouts=settings.database_timeouts),
        settings,
    )
    result = sweep_trash_for_admin(
        lifecycle,
        remove=remove,
        older_than=None if older_than_days is None else timedelta(days=older_than_days),
        correlation_id=uuid4().hex,
    )
    if not result.matched:
        print("The trash is empty.")
    elif not remove:
        print(f"Dry run: nothing was deleted. {sum(result.matched.values())} in the trash:")
        print_counts(result.matched)
        print("Run again with --yes to delete them permanently.")
    else:
        print(f"Permanently removed {sum(result.removed.values())} record(s):")
        print_counts(result.removed)
        if result.kept:
            print(
                f"Kept {sum(result.kept.values())} that cannot be removed yet "
                "(still has descendants or links, or is a shopping item):"
            )
            print_counts(result.kept)


def print_counts(counts: Mapping[Any, int]) -> None:
    """One line per record kind (a string enum), so no title or text can reach the output."""

    for kind, count in sorted(counts.items(), key=lambda entry: str(entry[0])):
        print(f"  {kind}: {count}")


def missing_scope_message() -> str:
    """Refuse a token with no scope choice, and show how to name the scopes it needs."""

    return (
        "create-token needs at least one --scope; no scope is granted by default. Write "
        "scopes such as tasks:write and journal:write let a client change the owner's data. "
        "Pass --scope once per capability the client needs, for example "
        "--scope projects:read --scope tasks:read. Available: " + ", ".join(TOKEN_SCOPE_CHOICES)
    )


def service_now() -> datetime:
    """Late import keeps CLI time handling explicit and UTC-aware."""

    from sidekick.shared.types import utc_now

    return utc_now()


if __name__ == "__main__":
    main()

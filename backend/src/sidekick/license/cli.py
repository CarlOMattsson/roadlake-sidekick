"""Operator commands for the instance's license key (D-081).

    python -m sidekick.license.cli set [KEY]     store a key (read from stdin when KEY is left out)
    python -m sidekick.license.cli show          print the license state
    python -m sidekick.license.cli clear         remove the stored key
    python -m sidekick.license.cli reset-clock   set the highest date seen to today

`set` checks the key offline against the instance's public key (`SIDEKICK_LICENSE_PUBLIC_KEY`)
and stores it only if it verifies. Every command prints the display state as one JSON document on
stdout (`state`, `licensee`, `kind`, `expires`) and never the key; `set` exits 1 for a key that is
not accepted, and says so on stderr in the app language. Passing the key on stdin keeps it out of
the shell history and the process list.

Like the other operator commands these read the database settings from the environment. The
operator's access to the host is the authorization; the user channels (MCP, the companion app) are
limited to the instance's only owner instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO

from sqlalchemy.orm import Session, sessionmaker

from sidekick.license.key import MAX_PASTED_LENGTH, LicenseView
from sidekick.license.persistence import LicenseStore
from sidekick.license.service import LicenseService
from sidekick.shared.cli_errors import run_guarded
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale, LocalizedText, localized

NOT_ACCEPTED: LocalizedText = {
    "sv": "Licensnyckeln godtogs inte och ingenting ändrades.",
    "en": "The license key wasn\u2019t accepted and nothing was changed.",
}


def build_parser() -> argparse.ArgumentParser:
    """The parser of `sidekick-license`; building it reads no settings and touches no database."""

    parser = argparse.ArgumentParser(prog="sidekick-license")
    commands = parser.add_subparsers(dest="command", required=True)
    store = commands.add_parser("set", help="store a license key, checked offline")
    store.add_argument("key", nargs="?", help="the key; read from stdin when left out")
    commands.add_parser("show", help="print the license state")
    commands.add_parser("clear", help="remove the stored license key")
    commands.add_parser(
        "reset-clock",
        help="set the highest date seen to today (after the clock ran far ahead by mistake)",
    )
    return parser


def run(
    argv: Sequence[str] | None,
    session_factory: sessionmaker[Session],
    public_key: str | None,
    out: TextIO = sys.stdout,
    notice: TextIO | None = None,
    stdin: TextIO | None = None,
    locale: AppLocale = DEFAULT_LOCALE,
) -> int:
    args = build_parser().parse_args(argv)
    service = LicenseService(LicenseStore(session_factory), public_key)
    if args.command == "set":
        raw = args.key if args.key is not None else (stdin or sys.stdin).read(MAX_PASTED_LENGTH + 1)
        outcome = service.set_key(raw)
        _print(out, outcome.view)
        if not outcome.accepted:
            print(localized(NOT_ACCEPTED, locale), file=notice or sys.stderr, flush=True)
            return 1
        return 0
    if args.command == "clear":
        service.clear()
    elif args.command == "reset-clock":
        service.reset_clock()
    _print(out, service.view())
    return 0


def _print(out: TextIO, view: LicenseView) -> None:
    print(json.dumps(view.as_json(), indent=2), file=out)


def _run_from_settings() -> int:
    from sidekick.shared.config import get_settings
    from sidekick.shared.persistence import create_session_factory

    settings = get_settings()
    factory = create_session_factory(settings.database_url, timeouts=settings.database_timeouts)
    return run(None, factory, settings.license_public_key, locale=settings.mcp_app_locale)


def main() -> None:
    raise SystemExit(run_guarded("sidekick-license", _run_from_settings))


if __name__ == "__main__":
    main()

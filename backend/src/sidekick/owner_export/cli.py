"""Command-line verification for an owner export file."""

import argparse
import errno
import json
import os
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from sidekick.owner_export.catalogue import ExportRefused
from sidekick.owner_export.document import verify_export
from sidekick.owner_export.formats import (
    ExportFormatError,
    contacts_to_vcard,
    journal_to_markdown,
)
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.shared.cli_errors import run_guarded
from sidekick.shared.config import get_settings
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale
from sidekick.shared.persistence import create_session_factory
from sidekick.store import SqlAlchemyStore

_EXPECTED_ERRORS = (
    OSError,
    json.JSONDecodeError,
    TypeError,
    ValueError,
    ExportRefused,
    ExportFormatError,
)


def _app_locale() -> AppLocale:
    """The language `SIDEKICK_MCP_APP_LOCALE` names in the environment; Swedish otherwise.

    The file commands read no settings and open no database, so this looks at the one variable
    instead of loading `Settings`.
    """

    value = os.environ.get("SIDEKICK_MCP_APP_LOCALE", DEFAULT_LOCALE).strip().lower()
    return "en" if value == "en" else DEFAULT_LOCALE


def _safe_reason(error: Exception) -> str:
    """A reason that is safe to print: curated refusals pass through, anything else is generic.

    `ExportRefused` and `ExportFormatError` carry fixed messages that name collections, row
    positions and fields only. Other parser, conversion and file errors can quote the offending
    value or path, so they map to fixed text and never echo their own message.
    """

    if isinstance(error, (ExportRefused, ExportFormatError)):
        return str(error)
    if isinstance(error, json.JSONDecodeError):
        return "file is not valid JSON"
    if isinstance(error, OSError):
        return "file could not be read or written"
    return "export content could not be read"


def _create_missing_directories(path: Path) -> None:
    """Create `path` and any missing ancestors, each with mode 0700 (the umask only narrows it)."""

    missing: list[Path] = []
    current = path
    while not os.path.lexists(current):
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        os.mkdir(directory, 0o700)


@contextmanager
def _private_directory(path: Path, *, create: bool, require_private: bool = True) -> Iterator[int]:
    """Yield a descriptor for an owner-only output directory, refusing anything else.

    The directory is opened without following a symbolic link, must belong to the current user,
    and must be closed to group and others, checked on the opened descriptor. Nothing is ever
    chmod-ed: `mkdir` with 0700 cannot grant more bits, so a directory open to others is not
    one we made (it may have replaced ours) and is refused. With
    `require_private=False` only the symbolic-link refusal applies (file names that reveal
    nothing, as for the vCard file).
    """

    absolute = Path(os.path.abspath(path))
    if create:
        _create_missing_directories(absolute)
    try:
        descriptor = os.open(absolute, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ExportFormatError("output directory must be a real directory") from None
        raise
    try:
        info = os.fstat(descriptor)
        if not require_private:
            yield descriptor
            return
        if info.st_uid != os.getuid():
            raise ExportFormatError("output directory must belong to the current user")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise ExportFormatError("output directory must not be accessible to others")
        yield descriptor
    finally:
        os.close(descriptor)


def _write_private_file(directory_fd: int, name: str, content: bytes) -> None:
    """Create `name` in the directory exclusively, never through a link, with mode 0600."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    except FileExistsError:
        raise ExportFormatError("output file already exists") from None
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sidekick-owner-export")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="verify an owner export manifest")
    verify.add_argument("path", type=Path, help="the owner export JSON file")
    plan = commands.add_parser("plan-restore", help="prepare a write-free restore plan")
    plan.add_argument("path", type=Path, help="the owner export JSON file")
    plan.add_argument(
        "--target-owner-id",
        type=str,
        help="target owner UUID; defaults to the source owner in the export",
    )
    restore = commands.add_parser(
        "restore", help="apply a previously reviewed restore plan atomically"
    )
    restore.add_argument("path", type=Path, help="the owner export JSON file")
    restore.add_argument(
        "--apply", action="store_true", required=True, help="really write the reviewed plan"
    )
    restore.add_argument(
        "--target-owner-id", type=UUID, required=True, help="the owner to restore into"
    )
    restore.add_argument("--plan-checksum", required=True, help="checksum printed by plan-restore")
    vcard = commands.add_parser(
        "vcard", help="write the contacts of a verified export as one vCard 4.0 file"
    )
    vcard.add_argument("path", type=Path, help="the owner export JSON file")
    vcard.add_argument("output", type=Path, help="the vCard file to write")
    markdown = commands.add_parser(
        "markdown", help="write the journal entries of a verified export as Markdown files"
    )
    markdown.add_argument("path", type=Path, help="the owner export JSON file")
    markdown.add_argument("output_dir", type=Path, help="the directory the Markdown files go to")
    markdown.add_argument(
        "--locale",
        choices=("sv", "en"),
        help="language of the words the files write themselves (default: SIDEKICK_MCP_APP_LOCALE)",
    )
    return parser


def _read_document(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _refuse(message: str, error: Exception) -> int:
    print(f"{message}: {_safe_reason(error)}", file=sys.stderr)
    return 1


def _command_verify(args: argparse.Namespace) -> int:
    try:
        result = verify_export(_read_document(args.path))
    except _EXPECTED_ERRORS as error:
        return _refuse("invalid owner export", error)
    _print_json(
        {
            "owner_id": str(result.owner_id),
            "sha256": result.checksum,
            "collection_counts": result.collection_counts,
        }
    )
    return 0


def _command_plan_restore(args: argparse.Namespace) -> int:
    try:
        document = _read_document(args.path)
        source_owner_id = verify_export(document).owner_id
        target_owner_id = (
            source_owner_id if args.target_owner_id is None else UUID(args.target_owner_id)
        )
        result = build_restore_plan(document, target_owner_id)
    except _EXPECTED_ERRORS as error:
        return _refuse("invalid restore plan input", error)
    _print_json(result.as_dict())
    return 0


def _command_vcard(args: argparse.Namespace) -> int:
    # Reads an existing export file only; no database or settings are touched.
    try:
        document = _read_document(args.path)
        verification = verify_export(document)
        if args.output.exists():
            raise ExportFormatError("output file already exists")
        data = contacts_to_vcard(document).encode("utf-8")
        with _private_directory(
            args.output.parent, create=False, require_private=False
        ) as directory_fd:
            _write_private_file(directory_fd, args.output.name, data)
    except _EXPECTED_ERRORS as error:
        return _refuse("vcard export refused", error)
    _print_json({"contact_count": verification.collection_counts["contacts"]})
    return 0


def _command_markdown(args: argparse.Namespace) -> int:
    # Reads an existing export file only; no database or settings are touched.
    try:
        document = _read_document(args.path)
        verify_export(document)
        files = journal_to_markdown(document, args.locale or _app_locale())
        targets = {args.output_dir / name: content for name, content in files.items()}
        if any(target.exists() for target in targets):
            raise ExportFormatError("output directory already contains a journal file")
        with _private_directory(args.output_dir, create=True) as directory_fd:
            for target, content in targets.items():
                _write_private_file(directory_fd, target.name, content.encode("utf-8"))
    except _EXPECTED_ERRORS as error:
        return _refuse("markdown export refused", error)
    _print_json({"entry_count": len(targets)})
    return 0


def _command_restore(args: argparse.Namespace) -> int:
    try:
        document = _read_document(args.path)
        settings = get_settings()
        store = SqlAlchemyStore(
            create_session_factory(
                settings.database_url,
                timeouts=settings.database_timeouts.unbounded_statements(),
            )
        )
        result = OwnerRestoreService(store).restore(
            document,
            target_owner_id=args.target_owner_id,
            expected_plan_checksum=args.plan_checksum,
        )
    except _EXPECTED_ERRORS as error:
        return _refuse("restore refused", error)
    _print_json(
        {
            "source_checksum": result.source_checksum,
            "plan_checksum": result.plan_checksum,
            "target_owner_id": str(result.target_owner_id),
            "imported_rows": result.imported_rows,
        }
    )
    return 0


_COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "verify": _command_verify,
    "plan-restore": _command_plan_restore,
    "vcard": _command_vcard,
    "markdown": _command_markdown,
    "restore": _command_restore,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = _COMMANDS.get(args.command)
    if command is None:
        return 2
    return run_guarded("sidekick-owner-export", lambda: command(args))


if __name__ == "__main__":
    raise SystemExit(main())

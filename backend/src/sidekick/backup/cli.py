"""CLI for creating, verifying, extracting, importing, and pruning local encrypted backups."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import ValidationError

from sidekick import composition
from sidekick.backup.bundle import (
    MAX_BACKUP_FILE_BYTES,
    OwnerBackupService,
    decrypt_backup_envelope,
    open_media_store,
    prune_backup_files,
    read_backup_file_bytes,
    recorded_missing_files,
)
from sidekick.backup.export_folder import write_export_folder
from sidekick.backup.importer import LoadedExport, apply_import, load_export, plan_import
from sidekick.backup.media import MediaReference, check_media
from sidekick.owner_export.catalogue import ExportRefused
from sidekick.owner_export.document import canonical_json, verify_export
from sidekick.owner_export.media import (
    EXPORT_DOCUMENT_NAME,
    EXPORT_MEDIA_FOLDER,
    ExportMediaFolder,
    MediaSource,
    media_files,
)
from sidekick.shared.cli_errors import (
    EXIT_FAILED,
    EXIT_UNEXPECTED,
    describe_failure,
    report_failure,
)
from sidekick.shared.config import get_settings
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import SystemClock


def _settings_key(settings: Any) -> str:
    key = settings.backup_encryption_key
    if key is None or not key.get_secret_value().strip():
        raise ExportRefused("SIDEKICK_BACKUP_ENCRYPTION_KEY is required")
    return key.get_secret_value()


def _verify(path: Path, media_directory: Path | None = None) -> dict[str, Any]:
    """Counts of a backup; with `media_directory`, also whether every photo file it lists is there
    and readable (each is decrypted and hashed once)."""

    settings = get_settings()
    envelope = json.loads(read_backup_file_bytes(path).decode("utf-8"))
    bundle = decrypt_backup_envelope(envelope, _settings_key(settings))
    exports = bundle["exports"]
    result: dict[str, Any] = {
        "format": envelope["format"],
        "created_at": envelope["created_at"],
        "ciphertext_sha256": envelope["sha256"],
        "owner_count": len(exports),
        "collection_counts": [
            {
                "collection_count": len(export["collections"]),
                "row_count": sum(len(rows) for rows in export["collections"].values()),
            }
            for export in exports
        ],
    }
    if media_directory is not None:
        check = check_media(
            open_media_store(media_directory, _settings_key(settings)),
            [
                MediaReference(UUID(str(export["owner_id"])), file)
                for export in exports
                for file in media_files(export)
            ],
            recorded_missing_files(bundle),
        )
        result["media"] = {
            "files": check.listed,
            "readable": check.readable,
            "recorded_missing": check.recorded_missing,
            "unreadable": check.unreadable,
        }
    return result


def _extract_export(path: Path, output: Path) -> dict[str, Any]:
    """Write the single owner export of an encrypted backup to a new JSON file.

    Reads the backup file and the configured key only; no database is touched. The output is
    created exclusively with private permissions, so an existing file is never overwritten.
    """

    settings = get_settings()
    loaded: Any = json.loads(read_backup_file_bytes(path).decode("utf-8"))
    if not isinstance(loaded, dict):
        raise ExportRefused("backup envelope must be an object")
    envelope = cast("dict[str, Any]", loaded)
    bundle = decrypt_backup_envelope(envelope, _settings_key(settings))
    exports = bundle["exports"]
    if len(exports) != 1:
        raise ExportRefused("backup must contain exactly one owner export")
    export = exports[0]
    verification = verify_export(export)
    payload = canonical_json(export) + b"\n"
    # Opened outside the try block: a FileExistsError must never remove the existing file.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {
        "owner_id": str(verification.owner_id),
        "sha256": verification.checksum,
        "collection_counts": verification.collection_counts,
    }


def _extract_export_folder(
    path: Path, output: Path, media_directory: Path | None
) -> dict[str, Any]:
    """Write the single owner export of an encrypted backup, and its photo files, to a new folder.

    The folder holds `export.json` and `media/<digest>.<type>`; the encrypted files are read from
    `media_directory` (default: the `media` folder beside the backup file).
    """

    settings = get_settings()
    loaded: Any = json.loads(read_backup_file_bytes(path).decode("utf-8"))
    if not isinstance(loaded, dict):
        raise ExportRefused("backup envelope must be an object")
    bundle = decrypt_backup_envelope(cast("dict[str, Any]", loaded), _settings_key(settings))
    exports = bundle["exports"]
    if len(exports) != 1:
        raise ExportRefused("backup must contain exactly one owner export")
    folder = media_directory or path.parent / EXPORT_MEDIA_FOLDER
    written = write_export_folder(
        output,
        exports[0],
        open_media_store(folder, _settings_key(settings)),
        recorded_missing_files(bundle),
    )
    return {"owner_id": str(verify_export(exports[0]).owner_id), **written}


def _import_key(key_file: Path | None) -> str | None:
    """The key from a private key file, else from the environment; None when neither is set."""

    if key_file is not None:
        if key_file.stat().st_mode & 0o077:
            raise ExportRefused("key file must not be readable by group or others (use mode 600)")
        key = key_file.read_text(encoding="ascii").strip()
        if not key:
            raise ExportRefused("key file is empty")
        return key
    key = get_settings().backup_encryption_key
    if key is None or not key.get_secret_value().strip():
        return None
    return key.get_secret_value()


def _import_store() -> StoreBase:
    """A store for backup and import, which may run statements longer than the app's budget."""

    settings = get_settings()
    return StoreBase(
        create_session_factory(
            settings.database_url, timeouts=settings.database_timeouts.unbounded_statements()
        )
    )


def _read_capped(path: Path) -> bytes:
    """A file read with the input ceiling, so oversize input never fills memory before the check."""

    with path.open("rb") as handle:
        return handle.read(MAX_BACKUP_FILE_BYTES + 1)


def _media_source(loaded: LoadedExport, folder: Path | None, key: str | None) -> MediaSource | None:
    """The photo files of the input: encrypted next to a backup, plain beside an export."""

    if folder is None:
        return None
    if not loaded.encrypted:
        return ExportMediaFolder(folder)
    if key is None:
        raise ExportRefused("an encryption key is required to read the photo files of a backup")
    return open_media_store(folder, key)


def _import(args: argparse.Namespace) -> dict[str, Any]:
    """Plan (default) or apply the import of one owner. FILE `-` reads standard input.

    FILE may also be an export folder (`export.json` and `media/`), which then supplies its photo
    files unless `--media-directory` names others.
    """

    media_folder: Path | None = args.media_directory
    if str(args.file) == "-":
        raw = sys.stdin.buffer.read(MAX_BACKUP_FILE_BYTES + 1)
    elif args.file.is_dir():
        raw = _read_capped(args.file / EXPORT_DOCUMENT_NAME)
        media_folder = media_folder or args.file / EXPORT_MEDIA_FOLDER
    else:
        raw = _read_capped(args.file)
    key = _import_key(args.key_file)
    loaded = load_export(raw, key=key, source_owner=args.source_owner)
    media = _media_source(loaded, media_folder, key)
    store = _import_store()
    if not args.apply:
        return plan_import(
            store,
            loaded.document,
            args.target_owner,
            media=media,
            recorded_missing=loaded.media_missing,
        )
    return apply_import(
        store,
        loaded.document,
        args.target_owner,
        plan_checksum=args.plan_checksum,
        media=media,
        photo_files=(
            composition.create_photo_files(get_settings()) if media_files(loaded.document) else None
        ),
        recorded_missing=loaded.media_missing,
    )


# The path arguments of the commands: the attribute, how the message names it, and whether the
# file name may be shown. A key file's name is withheld: it points at where the secret lives.
_PATH_ARGUMENTS = (
    ("path", "backup file", True),
    ("output", "output file or folder", True),
    ("file", "import file", True),
    ("directory", "backup directory", True),
    ("media_directory", "--media-directory", False),
    ("key_file", "--key-file", False),
)


def _describe_os_error(error: OSError, args: argparse.Namespace) -> str:
    """The operating system's reason and which argument it concerns, never a directory path.

    The file name of an argument the operator typed (not the key file) may be shown, without its
    directories. A path that came from the settings, or an error without a path, is not named.
    """

    reason = error.strerror or type(error).__name__
    failed = error.filename
    if isinstance(failed, (str, bytes, Path)):
        for name, label, show_name in _PATH_ARGUMENTS:
            value = getattr(args, name, None)
            if value is None or os.fsdecode(failed) != os.fsdecode(value):
                continue
            return f"{reason} ({label}: {Path(value).name})" if show_name else f"{reason} ({label})"
    return reason


def build_parser() -> argparse.ArgumentParser:
    """The parser of `sidekick-backup`; building it reads no settings and touches no database."""

    parser = argparse.ArgumentParser(prog="sidekick-backup")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("keygen", help="generate a Fernet key for a secret store")
    create = commands.add_parser("create", help="create an encrypted local owner backup")
    create.add_argument("--directory", type=Path, help="override configured backup directory")
    verify = commands.add_parser("verify", help="verify and inspect an encrypted backup")
    verify.add_argument("path", type=Path, help="the encrypted backup file")
    verify.add_argument(
        "--media-directory",
        type=Path,
        help="also read every photo file the backup lists from this folder (its media/ folder)",
    )
    extract = commands.add_parser(
        "extract-export",
        help="write the verified owner export of an encrypted backup to a new JSON file",
    )
    extract.add_argument("path", type=Path, help="the encrypted backup file")
    extract.add_argument("output", type=Path, help="the new JSON file to write; never overwritten")
    folder = commands.add_parser(
        "extract-export-folder",
        help="write the verified owner export of an encrypted backup, with its photo files, "
        "to a new folder (export.json and media/)",
    )
    folder.add_argument("path", type=Path, help="the encrypted backup file")
    folder.add_argument("output", type=Path, help="the new folder to write; never overwritten")
    folder.add_argument(
        "--media-directory",
        type=Path,
        help="the backup's photo files (default: the media/ folder next to the backup file)",
    )
    import_ = commands.add_parser(
        "import",
        help="plan, or with --apply write, the import of one owner into an existing empty owner",
    )
    import_.add_argument(
        "file",
        type=Path,
        help="an encrypted backup (.skbackup), a plain owner export .json, an export folder, "
        "or - for stdin",
    )
    import_.add_argument(
        "--target-owner", type=UUID, required=True, help="the existing empty owner to import into"
    )
    import_.add_argument(
        "--source-owner", type=UUID, help="required if the file holds several owners"
    )
    import_.add_argument(
        "--key-file",
        type=Path,
        help="Fernet key file (mode 600); default is SIDEKICK_BACKUP_ENCRYPTION_KEY",
    )
    import_.add_argument(
        "--media-directory",
        type=Path,
        help="the photo files of the input: the backup's media/ folder, or an export's media/ "
        "folder (an export folder supplies its own)",
    )
    import_.add_argument(
        "--apply", action="store_true", help="write the plan given by --plan-checksum"
    )
    import_.add_argument(
        "--plan-checksum", help="checksum printed by the plan; required with --apply"
    )
    commands.add_parser("prune", help="apply configured backup retention")
    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "keygen":
        print(Fernet.generate_key().decode("ascii"))
        return 0
    if args.command == "create":
        settings = get_settings()
        service = OwnerBackupService(
            _import_store(), photo_files=composition.create_photo_files(settings)
        )
        result = service.create(
            directory=args.directory or settings.backup_directory,
            key=_settings_key(settings),
            retention_count=settings.backup_retention_count,
            retention_days=settings.backup_retention_days,
            min_keep=settings.backup_min_keep,
            space_margin_percent=settings.backup_space_margin_pct,
        )
        print(
            json.dumps(
                {
                    "path": str(result.path),
                    "owner_count": result.owner_count,
                    "ciphertext_sha256": result.ciphertext_sha256,
                    "pruned_count": result.pruned_count,
                    "media_stored": result.media_stored,
                    "media_missing": result.media_missing,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "verify":
        verified = _verify(args.path, args.media_directory)
        print(json.dumps(verified, sort_keys=True))
        if verified.get("media", {}).get("unreadable"):
            print("backup verification failed: photo files are missing or damaged", file=sys.stderr)
            return 1
        return 0
    if args.command == "extract-export-folder":
        print(
            json.dumps(
                _extract_export_folder(args.path, args.output, args.media_directory),
                sort_keys=True,
            )
        )
        return 0
    if args.command == "extract-export":
        print(json.dumps(_extract_export(args.path, args.output), sort_keys=True))
        return 0
    if args.command == "import":
        result = _import(args)
        print(json.dumps(result, sort_keys=True))
        if args.apply and not result["verified"]:
            print("import verification failed: row counts differ", file=sys.stderr)
            return 1
        return 0
    if args.command == "prune":
        settings = get_settings()
        deleted = prune_backup_files(
            settings.backup_directory,
            retention_count=settings.backup_retention_count,
            retention_days=settings.backup_retention_days,
            now=SystemClock().now(),
            min_keep=settings.backup_min_keep,
        )
        print(json.dumps({"pruned_count": len(deleted)}, sort_keys=True))
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "import" and args.apply != (args.plan_checksum is not None):
        parser.error("--apply and --plan-checksum must be given together")

    try:
        return _dispatch(args)
    except ValidationError as error:
        # pydantic's ValidationError is a ValueError and can echo rejected input values.
        print(f"backup operation refused: {describe_failure(error).message}", file=sys.stderr)
        return EXIT_FAILED
    except ExportRefused as error:  # a fixed reason or a field name, never a row value
        print(f"backup operation refused: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"backup operation refused: {_describe_os_error(error, args)}", file=sys.stderr)
        return EXIT_FAILED
    except json.JSONDecodeError as error:
        # The parser's message holds a fixed phrase and a position, never the document.
        if args.command != "import":
            print(f"backup operation refused: {error}", file=sys.stderr)
            return EXIT_FAILED
        print(f"import failed: {type(error).__name__}", file=sys.stderr)
        return EXIT_FAILED
    except (TypeError, ValueError) as error:
        # A parser or driver error can quote the value it choked on: type only.
        prefix = "import failed" if args.command == "import" else "backup operation refused"
        print(f"{prefix}: {type(error).__name__}", file=sys.stderr)
        return EXIT_FAILED
    except Exception as error:  # a driver or settings message is never echoed
        if args.command == "import" and describe_failure(error).exit_code == EXIT_UNEXPECTED:
            # An unclassified failure of the import is a refusal, as before.
            print(f"import failed: {type(error).__name__}", file=sys.stderr)
            return EXIT_FAILED
        # A conflict (3) or a database failure (4) keeps its code from the shared table.
        return report_failure("sidekick-backup", error)


if __name__ == "__main__":
    raise SystemExit(main())

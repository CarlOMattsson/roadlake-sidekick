"""Local encrypted owner-backup bundles and bounded retention.

Backups are application exports wrapped in authenticated Fernet encryption.  The
outer envelope contains no owner data; the encryption key is supplied by the
process environment or another secret store and is never persisted by Sidekick.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from sidekick.owner_export.catalogue import EXPORT_FORMAT_VERSION, ExportRefused
from sidekick.owner_export.document import ExportBudget, canonical_json, verify_export
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore_plan import verify_restorable
from sidekick.shared.backup_files import (
    BACKUP_FILE_PREFIX,
    BACKUP_FILE_SUFFIX,
    finished_backup_time,
)
from sidekick.shared.observability import NoopTelemetryAdapter, TelemetryPort
from sidekick.shared.types import Clock, SystemClock

BACKUP_FORMAT = "sidekick.encrypted-owner-backup"
BACKUP_FORMAT_VERSION = 1
BUNDLE_FORMAT = "sidekick.owner-backup-bundle"
# Free space needed for the next backup: the newest finished backup times this margin, but
# never less than the floor (the first backup has nothing to compare with).
DEFAULT_SPACE_MARGIN_PERCENT = 150
SPACE_FLOOR_BYTES = 64 * 1024 * 1024
# Fernet is not a streaming format (the bundle is one token), so a bundle is held in memory while
# it is encrypted or decrypted.  This ceiling on the plaintext keeps that bounded and mirrors
# deploy/selfhost/snapshot_crypto.py.  A larger bundle is refused with `BackupTooLarge` before it is
# encrypted, and a larger backup file or token is refused before it is parsed or decrypted.
MAX_BUNDLE_PLAINTEXT_BYTES = 512 * 1024 * 1024
_FERNET_OVERHEAD_BYTES = 16 + 73  # padding plus header and MAC
# base64 grows the token by 4/3.
MAX_BACKUP_TOKEN_BYTES = (MAX_BUNDLE_PLAINTEXT_BYTES + _FERNET_OVERHEAD_BYTES) * 4 // 3 + 4
# The envelope JSON adds a fixed few hundred bytes around the token; leave generous room.
MAX_BACKUP_FILE_BYTES = MAX_BACKUP_TOKEN_BYTES + 4096


class BackupTooLarge(ExportRefused):
    """A bundle, backup file or token is over the in-memory ceiling.

    The message carries sizes in MiB only: never a key, an identifier or any owner content.
    """


def _mib(size: int) -> int:
    return size // (1024 * 1024)


def _too_large(what: str, limit: int) -> BackupTooLarge:
    return BackupTooLarge(f"backup {what} is over the {_mib(limit)} MiB ceiling")


def bounded_canonical_json(value: Mapping[str, Any], limit: int) -> bytes:
    """`canonical_json(value)`, byte for byte, but abandoned as soon as it grows past `limit`.

    The document is encoded piece by piece, so an oversize bundle is refused after about `limit`
    bytes instead of after a full second copy has been built.
    """

    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # One growing buffer instead of a list of tiny bytes objects (each with its own overhead)
    # that would then be joined into a second full copy.
    buffer = bytearray()
    for chunk in encoder.iterencode(value):
        buffer += chunk.encode("utf-8")
        if len(buffer) > limit:
            raise _too_large("bundle", limit)
    return bytes(buffer)


def read_backup_file_bytes(path: Path) -> bytes:
    """Read a backup file, refusing one over `MAX_BACKUP_FILE_BYTES` without reading it all."""

    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_BACKUP_FILE_BYTES + 1)
    except OSError as error:
        raise ExportRefused("written backup cannot be read back") from error
    if len(data) > MAX_BACKUP_FILE_BYTES:
        raise _too_large("file", MAX_BACKUP_FILE_BYTES)
    return data


def _raw_secret_value(key: str | bytes | SecretStr) -> object:
    return key.get_secret_value() if isinstance(key, SecretStr) else key


def _secret_value(key: str | bytes | SecretStr) -> str | bytes:
    raw_value = _raw_secret_value(key)
    value = raw_value.strip() if isinstance(raw_value, (bytes, str)) else ""
    if not value:
        raise ExportRefused("backup encryption key is required")
    return value


def _fernet(key: str | bytes | SecretStr) -> Fernet:
    try:
        value = _secret_value(key)
        encoded = value if isinstance(value, bytes) else value.encode("ascii")
        return Fernet(encoded)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ExportRefused("backup encryption key must be a valid Fernet key") from error


def verify_backup_file(path: Path, key: str | bytes | SecretStr) -> int:
    """Re-open a written backup and prove every owner export in it can be restored.

    Decryption and the envelope checks run on the bytes that were written, and each export's
    references are resolved against the export itself.  Returns the owner count.
    """

    raw = read_backup_file_bytes(path)
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExportRefused("written backup cannot be read back") from error
    if not isinstance(envelope, Mapping):
        raise ExportRefused("written backup cannot be read back")
    bundle = decrypt_backup_envelope(cast(Mapping[str, Any], envelope), key)
    exports = cast(list[Mapping[str, Any]], bundle["exports"])
    for export in exports:
        verify_restorable(export)
    return len(exports)


def build_backup_bundle(exports: Sequence[Any]) -> dict[str, Any]:
    """Validate and package owner exports without exposing their contents in metadata."""

    normalized: list[dict[str, Any]] = []
    owners: set[str] = set()
    for export in exports:
        if not isinstance(export, Mapping):
            raise ExportRefused("backup exports must contain objects")
        verification = verify_export(cast(Mapping[str, Any], export))
        if str(verification.owner_id) in owners:
            raise ExportRefused("backup contains the same owner more than once")
        owners.add(str(verification.owner_id))
        normalized.append(dict(cast(Mapping[str, Any], export)))
    return {
        "format": BUNDLE_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "export_format_version": EXPORT_FORMAT_VERSION,
        "exports": normalized,
    }


def build_backup_envelope(
    bundle: Mapping[str, Any],
    key: str | bytes | SecretStr,
    *,
    created_at: datetime,
) -> dict[str, Any]:
    """Encrypt a validated bundle with authenticated Fernet encryption."""

    if bundle.get("format") != BUNDLE_FORMAT:
        raise ExportRefused("unsupported backup bundle format")
    if bundle.get("format_version") != BACKUP_FORMAT_VERSION:
        raise ExportRefused("unsupported backup bundle version")
    if bundle.get("export_format_version") != EXPORT_FORMAT_VERSION:
        raise ExportRefused("unsupported export bundle version")
    exports = bundle.get("exports")
    if not isinstance(exports, list):
        raise ExportRefused("backup exports must be an array")
    validated_bundle = build_backup_bundle(cast(list[Any], exports))
    plaintext = bounded_canonical_json(validated_bundle, MAX_BUNDLE_PLAINTEXT_BYTES)
    ciphertext = _fernet(key).encrypt(plaintext).decode("ascii")
    return {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": created_at.isoformat(),
        "ciphertext": ciphertext,
        "sha256": hashlib.sha256(ciphertext.encode("ascii")).hexdigest(),
    }


def decrypt_backup_envelope(
    envelope: Mapping[str, Any], key: str | bytes | SecretStr
) -> dict[str, Any]:
    """Authenticate, decrypt, and verify every owner export in a backup."""

    if envelope.get("format") != BACKUP_FORMAT:
        raise ExportRefused("unsupported backup format")
    if envelope.get("format_version") != BACKUP_FORMAT_VERSION:
        raise ExportRefused("unsupported backup version")
    if not isinstance(envelope.get("created_at"), str):
        raise ExportRefused("invalid backup timestamp")
    ciphertext = envelope.get("ciphertext")
    checksum = envelope.get("sha256")
    if not isinstance(ciphertext, str) or not isinstance(checksum, str):
        raise ExportRefused("invalid backup envelope")
    if len(ciphertext) > MAX_BACKUP_TOKEN_BYTES:
        raise _too_large("ciphertext", MAX_BACKUP_TOKEN_BYTES)
    if hashlib.sha256(ciphertext.encode("ascii")).hexdigest() != checksum:
        raise ExportRefused("backup checksum mismatch")
    try:
        plaintext = _fernet(key).decrypt(ciphertext.encode("ascii"))
    except InvalidToken as error:
        raise ExportRefused("backup authentication failed") from error
    if len(plaintext) > MAX_BUNDLE_PLAINTEXT_BYTES:
        raise _too_large("bundle", MAX_BUNDLE_PLAINTEXT_BYTES)
    try:
        bundle_value = json.loads(plaintext)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExportRefused("backup payload is not valid JSON") from error
    if not isinstance(bundle_value, Mapping):
        raise ExportRefused("backup payload must be an object")
    bundle = cast(Mapping[str, Any], bundle_value)
    if bundle.get("format") != BUNDLE_FORMAT:
        raise ExportRefused("unsupported backup bundle format")
    if bundle.get("format_version") != BACKUP_FORMAT_VERSION:
        raise ExportRefused("unsupported backup bundle version")
    if not isinstance(bundle.get("exports"), list):
        raise ExportRefused("backup exports must be an array")
    build_backup_bundle(cast(list[Mapping[str, Any]], bundle["exports"]))
    return dict(bundle)


def backup_file_path(directory: Path, created_at: datetime) -> Path:
    stamp = created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return directory / f"{BACKUP_FILE_PREFIX}{stamp}-{uuid4().hex[:12]}{BACKUP_FILE_SUFFIX}"


def _fsync_directory(directory: Path) -> None:
    """Flush a directory entry (a rename or an unlink) to disk; an `OSError` propagates."""

    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def newest_backup_size(directory: Path) -> int:
    """Size in bytes of the newest finished backup file in `directory`, 0 if there is none."""

    newest: tuple[datetime, int] | None = None
    try:
        files = [path for path in directory.iterdir() if path.is_file() and not path.is_symlink()]
    except OSError:
        return 0
    for path in files:
        created = finished_backup_time(path.name)
        if created is None:
            continue
        with suppress(OSError):
            size = path.stat().st_size
            if newest is None or created > newest[0]:
                newest = (created, size)
    return newest[1] if newest is not None else 0


def ensure_free_space(
    directory: Path,
    *,
    margin_percent: int = DEFAULT_SPACE_MARGIN_PERCENT,
    floor_bytes: int = SPACE_FLOOR_BYTES,
) -> None:
    """Refuse to start a backup when `directory` cannot take another one.

    Needed room is the newest finished backup times the margin, at least `floor_bytes`. The check
    runs before the export is read, so a full disk is found before any work is done. A free size
    that cannot be read counts as a refusal.
    """

    if margin_percent < 100:
        raise ExportRefused("backup space margin must be at least 100 percent")
    needed = max(newest_backup_size(directory) * margin_percent // 100, floor_bytes)
    probe = directory
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as error:
        raise ExportRefused("cannot determine free disk space for the backup") from error
    if free < needed:
        raise ExportRefused(
            f"not enough free disk space for a backup: {free} bytes free, {needed} needed"
        )


def write_backup_file(envelope: Mapping[str, Any], path: Path) -> None:
    """Write one backup with private permissions, an fsynced file and an atomic, fsynced rename.

    Any failure, including a failed directory fsync after the rename, propagates and leaves no file
    under the final name: a backup whose durability is unproven never counts as a finished one, so
    it cannot become "the newest good backup" that retention protects the older ones behind.
    """

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with suppress(OSError):
        path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    renamed = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb", buffering=0) as handle:
            handle.write(canonical_json(dict(envelope)) + b"\n")
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        renamed = True
        path.chmod(0o600)
        _fsync_directory(path.parent)
    except BaseException:
        if renamed:
            path.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def prune_backup_files(
    directory: Path,
    *,
    retention_count: int,
    retention_days: int,
    now: datetime,
    keep: Path | None = None,
    min_keep: int = 1,
) -> tuple[Path, ...]:
    """Delete only Sidekick-generated backup names beyond count or age limits.

    `keep` is the newest backup that was written and read back successfully; it is never deleted,
    whatever the limits or the file times say. The newest `min_keep` finished backups (by the time
    in their name) are also kept, however old; they are all files that were read back before they
    were renamed into place.
    """

    if retention_count < 1 or retention_days < 1 or min_keep < 1:
        raise ExportRefused("backup retention must be positive")
    files = sorted(
        (
            path
            for path in directory.iterdir()
            if finished_backup_time(path.name) is not None and path.is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    cutoff = now.timestamp() - timedelta(days=retention_days).total_seconds()
    deleted: list[Path] = []
    for index, path in enumerate(files):
        if (keep is not None and path == keep) or index < min_keep:
            continue
        if index >= retention_count or path.stat().st_mtime < cutoff:
            path.unlink()
            deleted.append(path)
    if deleted:
        # The files are already gone; failing to flush that must not fail a good backup.
        with suppress(OSError):
            _fsync_directory(directory)
    return tuple(deleted)


@dataclass(frozen=True, slots=True)
class BackupResult:
    path: Path
    owner_count: int
    ciphertext_sha256: str
    pruned_count: int


class OwnerBackupService:
    """Create one encrypted, local backup bundle and apply retention."""

    def __init__(
        self,
        store: Any,
        clock: Clock | None = None,
        telemetry: TelemetryPort | None = None,
    ) -> None:
        self._export = OwnerExportService(store, clock, telemetry)
        self._clock = clock or SystemClock()
        self._telemetry = telemetry or NoopTelemetryAdapter()

    def create(
        self,
        *,
        directory: Path,
        key: str | bytes | SecretStr,
        retention_count: int,
        retention_days: int,
        min_keep: int = 1,
        space_margin_percent: int = DEFAULT_SPACE_MARGIN_PERCENT,
    ) -> BackupResult:
        created_at = self._clock.now()
        try:
            ensure_free_space(directory, margin_percent=space_margin_percent)
        except ExportRefused:
            self._telemetry.count(
                "sidekick.owner_backup",
                {"owner_backup.operation": "create", "outcome": "refused"},
            )
            raise
        try:
            # The export is held to the bundle ceiling while it is read: it stops at the first row
            # that takes the rows over it, instead of building the whole snapshot first.
            exports = self._export.export_all(
                ExportBudget(
                    MAX_BUNDLE_PLAINTEXT_BYTES,
                    lambda: _too_large("bundle", MAX_BUNDLE_PLAINTEXT_BYTES),
                )
            )
            # A backup that could not be restored must never be reported as good.  The exports
            # are checked before anything is written, and the file is read back once written.
            for export in exports:
                verify_restorable(export)
            bundle = build_backup_bundle(exports)
            envelope = build_backup_envelope(bundle, key, created_at=created_at)
            path = backup_file_path(directory, created_at)
            try:
                write_backup_file(envelope, path)
            except OSError as error:
                # Nothing under the final name survives; retention below is never reached.
                raise ExportRefused("backup could not be written durably") from error
            try:
                verify_backup_file(path, key)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        except BackupTooLarge:
            self._telemetry.count(
                "sidekick.owner_backup",
                {
                    "owner_backup.operation": "create",
                    "outcome": "refused",
                    "owner_backup.reason": "too_large",
                },
            )
            raise
        except ExportRefused:
            self._telemetry.count(
                "sidekick.owner_backup",
                {"owner_backup.operation": "create", "outcome": "refused"},
            )
            raise
        deleted = prune_backup_files(
            directory,
            retention_count=retention_count,
            retention_days=retention_days,
            now=created_at,
            keep=path,
            min_keep=min_keep,
        )
        self._telemetry.count(
            "sidekick.owner_backup",
            {
                "owner_backup.operation": "create",
                "outcome": "success",
                "owner_backup.owner_count": str(len(exports)),
                "owner_backup.pruned_count": str(len(deleted)),
            },
        )
        return BackupResult(
            path=path,
            owner_count=len(exports),
            ciphertext_sha256=envelope["sha256"],
            pruned_count=len(deleted),
        )

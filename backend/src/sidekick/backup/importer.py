"""Import one owner from an encrypted backup or a plain owner export, plan first.

This is the operator-facing wrapper around the existing building blocks:
`decrypt_backup_envelope`, `verify_export`, `build_restore_plan` and `OwnerRestoreService`.
It adds only input detection, owner selection and the count check after a write. The decrypted
export stays in this process's memory; results hold identifiers, checksums and row counts, never
owner content.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import SecretStr

from sidekick.backup.bundle import (
    BACKUP_FORMAT,
    MAX_BACKUP_FILE_BYTES,
    MAX_BUNDLE_PLAINTEXT_BYTES,
    BackupTooLarge,
    decrypt_backup_envelope,
    recorded_missing_files,
)
from sidekick.owner_export.catalogue import EXPORT_FORMAT, ExportRefused
from sidekick.owner_export.document import verify_export
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.media import MediaSource, can_read, media_files
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor

_ENVELOPE_START = re.compile(rb'\s*\{\s*"ciphertext"\s*:')


def _looks_like_envelope(raw: bytes) -> bool:
    """Whether `raw` starts like an encrypted backup as written (`ciphertext` sorts first)."""

    return _ENVELOPE_START.match(raw[:64]) is not None


@dataclass(frozen=True, slots=True)
class LoadedExport:
    """The one owner export an input holds, and what is known about its photo files."""

    document: dict[str, Any]
    encrypted: bool
    # Photo files the backup recorded as already gone when it was made (a plain export has none).
    media_missing: frozenset[tuple[UUID, str]]


def load_export(
    raw: bytes,
    *,
    key: str | bytes | SecretStr | None,
    source_owner: UUID | None,
) -> LoadedExport:
    """Return the one verified owner export held by `raw`.

    `raw` is either an encrypted backup envelope (the key is required) or a plain owner export.
    A backup may hold several owners, then `source_owner` selects one. Input over the in-memory
    ceiling is refused with `BackupTooLarge` before it is parsed or decrypted.
    """

    # An envelope may be as large as the file ceiling; anything else (a plain export, or any input
    # when there is no key to open an envelope with) is held to the smaller plaintext ceiling, and
    # that is checked before the bytes are parsed.
    is_envelope = key is not None and _looks_like_envelope(raw)
    limit = MAX_BACKUP_FILE_BYTES if is_envelope else MAX_BUNDLE_PLAINTEXT_BYTES
    if len(raw) > limit:
        raise BackupTooLarge(f"input is over the {limit // (1024 * 1024)} MiB ceiling")
    try:
        loaded: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExportRefused("input is not a backup or an owner export") from error
    if not isinstance(loaded, dict):
        raise ExportRefused("input is not a backup or an owner export")
    document = cast("dict[str, Any]", loaded)
    kind = document.get("format")
    missing: frozenset[tuple[UUID, str]] = frozenset()
    if kind == EXPORT_FORMAT:
        exports = [document]
    elif kind == BACKUP_FORMAT:
        if key is None:
            raise ExportRefused("an encryption key is required to read an encrypted backup")
        bundle = decrypt_backup_envelope(document, key)
        exports = bundle["exports"]
        missing = recorded_missing_files(bundle)
    else:
        raise ExportRefused("input is not a backup or an owner export")
    if source_owner is None:
        if len(exports) != 1:
            raise ExportRefused(
                f"input contains {len(exports)} owners; pass --source-owner to choose one"
            )
        selected = exports[0]
    else:
        matches = [e for e in exports if verify_export(e).owner_id == source_owner]
        if len(matches) != 1:
            raise ExportRefused("source owner is not present in the input")
        selected = matches[0]
    owner = verify_export(selected).owner_id
    return LoadedExport(
        cast("dict[str, Any]", selected),
        kind == BACKUP_FORMAT,
        frozenset(pair for pair in missing if pair[0] == owner),
    )


def load_export_document(
    raw: bytes,
    *,
    key: str | bytes | SecretStr | None,
    source_owner: UUID | None,
) -> dict[str, Any]:
    """The one verified owner export held by `raw` (see `load_export`)."""

    return load_export(raw, key=key, source_owner=source_owner).document


def _owner_exists(store: StoreBase, owner_id: UUID) -> bool:
    return store.transaction(lambda session: store.owner_exists(session, owner_id))


class PhotoFileWriter(Protocol):
    """The live photo files of the instance a restore writes into (`OwnerPhotoFiles`)."""

    def put(self, owner_id: UUID, data: bytes) -> str:
        """Store the bytes under the owner and return their SHA-256 digest."""
        ...


def _media_summary(
    document: Mapping[str, Any],
    media: MediaSource | None,
    recorded_missing: frozenset[tuple[UUID, str]],
) -> dict[str, int]:
    """How many photo files the export lists and how many of them can be read now; counts only."""

    owner = verify_export(document).owner_id
    files = media_files(document)
    readable = recorded = 0
    for file in files:
        if (owner, file.digest) in recorded_missing:
            recorded += 1
        elif media is not None and can_read(media, owner, file):
            readable += 1
    return {
        "files": len(files),
        "readable": readable,
        "recorded_missing": recorded,
        "unreadable": len(files) - readable - recorded,
    }


def plan_import(
    store: StoreBase,
    document: Mapping[str, Any],
    target_owner: UUID,
    *,
    media: MediaSource | None = None,
    recorded_missing: frozenset[tuple[UUID, str]] = frozenset(),
) -> dict[str, Any]:
    """The reviewable plan as a dict. Reads whether the target exists; writes nothing.

    The `media` entry says how many photo files the export lists and how many can be read from
    `media` now. It is not part of the plan checksum: the plan covers the rows.
    """

    if not _owner_exists(store, target_owner):
        raise ExportRefused("target owner does not exist")
    plan = build_restore_plan(document, target_owner).as_dict()
    plan["media"] = _media_summary(document, media, recorded_missing)
    return plan


def _restore_media(
    document: Mapping[str, Any],
    target_owner: UUID,
    *,
    media: MediaSource | None,
    photo_files: PhotoFileWriter | None,
    recorded_missing: frozenset[tuple[UUID, str]],
) -> dict[str, int]:
    """Write the photo files of the export under the target owner, one file at a time.

    Every file the export lists must be readable, unless the backup recorded it as gone; the first
    that is not stops the restore before a row is written. A file already written stays: it is
    named by its content and harmless without a row.
    """

    files = media_files(document)
    if not files:
        return {"restored": 0, "missing": 0}
    if media is None or photo_files is None:
        raise ExportRefused("the export lists photo files: pass --media-directory to restore them")
    source_owner = verify_export(document).owner_id
    restored = absent = 0
    for file in files:
        if (source_owner, file.digest) in recorded_missing:
            absent += 1
            continue
        data = media.read(source_owner, file)
        if photo_files.put(target_owner, data) != file.digest:
            raise ExportRefused("a photo file was not stored under its name")
        restored += 1
    return {"restored": restored, "missing": absent}


def apply_import(
    store: StoreBase,
    document: Mapping[str, Any],
    target_owner: UUID,
    *,
    plan_checksum: str,
    media: MediaSource | None = None,
    photo_files: PhotoFileWriter | None = None,
    recorded_missing: frozenset[tuple[UUID, str]] = frozenset(),
) -> dict[str, Any]:
    """Apply the reviewed plan atomically, then compare row counts with a fresh export.

    The service refuses a blocked plan, a checksum mismatch and a non-empty target owner. A count
    mismatch after the write cannot be rolled back here, so it is reported as `verified: false`.
    The photo files are written first, once the plan is known to be the reviewed one.
    """

    reviewed = build_restore_plan(document, target_owner)
    if reviewed.status != "ready":
        raise ExportRefused("restore plan is blocked")
    if reviewed.plan_checksum != plan_checksum:
        raise ExportRefused("restore plan checksum mismatch")
    files = _restore_media(
        document,
        target_owner,
        media=media,
        photo_files=photo_files,
        recorded_missing=recorded_missing,
    )
    result = OwnerRestoreService(store).restore(
        document, target_owner_id=target_owner, expected_plan_checksum=plan_checksum
    )
    source_counts = verify_export(document).collection_counts
    restored = OwnerExportService(store).export(Actor(user_id=target_owner, scopes=frozenset()))
    restored_counts = verify_export(restored).collection_counts
    return {
        "target_owner_id": str(result.target_owner_id),
        "plan_checksum": result.plan_checksum,
        "imported_rows": result.imported_rows,
        "verified": source_counts == restored_counts,
        "collection_counts": restored_counts,
        "media_restored": files["restored"],
        "media_missing": files["missing"],
    }

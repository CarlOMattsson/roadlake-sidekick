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
from typing import Any, cast
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select

from sidekick.backup.bundle import (
    BACKUP_FORMAT,
    MAX_BACKUP_FILE_BYTES,
    MAX_BUNDLE_PLAINTEXT_BYTES,
    BackupTooLarge,
    decrypt_backup_envelope,
)
from sidekick.owner_export.core import (
    EXPORT_FORMAT,
    ExportRefused,
    OwnerExportService,
    OwnerRestoreService,
    build_restore_plan,
    verify_export,
)
from sidekick.shared.persistence.models import UserRow
from sidekick.shared.types import Actor
from sidekick.store import SqlAlchemyStore

_ENVELOPE_START = re.compile(rb'\s*\{\s*"ciphertext"\s*:')


def _looks_like_envelope(raw: bytes) -> bool:
    """Whether `raw` starts like an encrypted backup as written (`ciphertext` sorts first)."""

    return _ENVELOPE_START.match(raw[:64]) is not None


def load_export_document(
    raw: bytes,
    *,
    key: str | bytes | SecretStr | None,
    source_owner: UUID | None,
) -> dict[str, Any]:
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
    if kind == EXPORT_FORMAT:
        exports = [document]
    elif kind == BACKUP_FORMAT:
        if key is None:
            raise ExportRefused("an encryption key is required to read an encrypted backup")
        exports = decrypt_backup_envelope(document, key)["exports"]
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
    verify_export(selected)
    return cast("dict[str, Any]", selected)


def _owner_exists(store: SqlAlchemyStore, owner_id: UUID) -> bool:
    return store.transaction(
        lambda session: (
            session.scalar(select(UserRow.id).where(UserRow.id == owner_id)) is not None
        ),
    )


def plan_import(
    store: SqlAlchemyStore, document: Mapping[str, Any], target_owner: UUID
) -> dict[str, Any]:
    """The reviewable plan as a dict. Reads whether the target exists; writes nothing."""

    if not _owner_exists(store, target_owner):
        raise ExportRefused("target owner does not exist")
    return build_restore_plan(document, target_owner).as_dict()


def apply_import(
    store: SqlAlchemyStore,
    document: Mapping[str, Any],
    target_owner: UUID,
    *,
    plan_checksum: str,
) -> dict[str, Any]:
    """Apply the reviewed plan atomically, then compare row counts with a fresh export.

    The service refuses a blocked plan, a checksum mismatch and a non-empty target owner. A count
    mismatch after the write cannot be rolled back here, so it is reported as `verified: false`.
    """

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
    }

"""Applying a reviewed restore into an empty owner scope, atomically."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sidekick.owner_export.catalogue import EXPORT_SOURCES, ExportRefused
from sidekick.owner_export.persistence import (
    lock_memory_settings,
    lock_restore_scope,
    owner_has_rows,
)
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.owner_export.restore_remap import (
    document_collections,
    remapped_restore_rows,
    restore_lock_id,
    restore_source_order,
)
from sidekick.shared.observability import NoopTelemetryAdapter, TelemetryPort
from sidekick.shared.persistence.models import MemorySettingsRow
from sidekick.shared.types import TxSession


def _is_untouched_memory_default(row: MemorySettingsRow) -> bool:
    """True for the row AuthService writes at provisioning, when the owner has not changed it.

    Four domains on, not paused, version 1. Any other values or a later version is the owner's
    own choice, and restore refuses to overwrite it.
    """

    return (row.journal, row.contacts, row.projects, row.tasks, row.paused, row.version) == (
        True,
        True,
        True,
        True,
        False,
        1,
    )


@dataclass(frozen=True, slots=True)
class RestoreResult:
    source_checksum: str
    plan_checksum: str
    target_owner_id: UUID
    imported_rows: int


class OwnerRestoreService:
    """Apply one reviewed restore into an empty owner scope atomically."""

    def __init__(self, store: Any, telemetry: TelemetryPort | None = None) -> None:
        self._store = store
        self._telemetry = telemetry or NoopTelemetryAdapter()

    def restore(
        self,
        document: Mapping[str, Any],
        *,
        target_owner_id: UUID,
        expected_plan_checksum: str,
    ) -> RestoreResult:
        plan = build_restore_plan(document, target_owner_id)
        if plan.status != "ready":
            raise ExportRefused("restore plan is blocked")
        if plan.conflict_policy != "new_ids_only":
            raise ExportRefused("unsupported restore conflict policy")
        if plan.plan_checksum != expected_plan_checksum:
            raise ExportRefused("restore plan checksum mismatch")
        remapped = remapped_restore_rows(document, target_owner_id)

        def write(session: TxSession) -> RestoreResult:
            lock_restore_scope(session, restore_lock_id(target_owner_id))
            if not self._store.owner_exists(session, target_owner_id):
                raise ExportRefused("target owner does not exist")
            # The settings row AuthService writes at provisioning is not content. An untouched
            # default row is overwritten by the document's row; any other settings row refuses.
            settings_row = lock_memory_settings(session, target_owner_id)
            if settings_row is not None and not _is_untouched_memory_default(settings_row):
                raise ExportRefused("target owner must be empty before restore")
            for source in EXPORT_SOURCES:
                if source.row_type is MemorySettingsRow:
                    continue
                if owner_has_rows(session, source.row_type, target_owner_id):
                    raise ExportRefused("target owner must be empty before restore")
            imported_rows = 0
            for source in restore_source_order(document_collections(document)):
                for row in remapped[source.name]:
                    if source.row_type is MemorySettingsRow and settings_row is not None:
                        # The app role may not delete the default row, so it is overwritten.
                        for field, value in row.items():
                            setattr(settings_row, field, value)
                    else:
                        session.add(source.row_type(**row))
                    imported_rows += 1
                session.flush()
            self._store.append_audit(
                session,
                actor_id=target_owner_id,
                event="owner.restore",
                outcome="success",
                target_type="owner",
                target_id=target_owner_id,
                correlation_id=plan.plan_checksum,
            )
            return RestoreResult(
                source_checksum=plan.source_checksum,
                plan_checksum=plan.plan_checksum,
                target_owner_id=target_owner_id,
                imported_rows=imported_rows,
            )

        try:
            result = self._store.transaction(write)
        except Exception:
            self._telemetry.count(
                "sidekick.owner_export",
                {"owner_export.operation": "restore", "outcome": "failure"},
            )
            raise
        self._telemetry.count(
            "sidekick.owner_export",
            {
                "owner_export.operation": "restore",
                "outcome": "success",
                "owner_export.row_count": str(result.imported_rows),
            },
        )
        return result

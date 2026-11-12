"""The restore dry-run: a pure, reviewable plan that proves an export's references resolve."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sidekick.owner_export.catalogue import EXPORT_SOURCES, ExportRefused, ExportSource
from sidekick.owner_export.document import ExportVerification, canonical_json, verify_export
from sidekick.owner_export.restore_remap import (
    document_collections,
    foreign_key_targets,
    historical_reference_source,
    remap_user_reference,
    remapped_restore_rows,
    restore_identity_map,
    restore_source_order,
    user_reference_fields,
    uuid_or_none,
)


@dataclass(frozen=True, slots=True)
class RestoreCollectionPlan:
    """Safe, non-mutating restore preparation for one export collection."""

    name: str
    row_count: int
    remapped_id_count: int
    unresolved_reference_count: int


@dataclass(frozen=True, slots=True)
class RestorePlan:
    """A reviewable restore plan; it contains no write capability."""

    source_owner_id: UUID
    target_owner_id: UUID
    source_checksum: str
    status: str
    conflict_policy: str
    collections: tuple[RestoreCollectionPlan, ...]
    total_rows: int
    remapped_id_count: int
    unresolved_references: tuple[str, ...]
    warnings: tuple[str, ...]

    def _payload(self) -> dict[str, Any]:
        return {
            "source_owner_id": str(self.source_owner_id),
            "target_owner_id": str(self.target_owner_id),
            "source_checksum": self.source_checksum,
            "status": self.status,
            "conflict_policy": self.conflict_policy,
            "collections": [
                {
                    "name": collection.name,
                    "row_count": collection.row_count,
                    "remapped_id_count": collection.remapped_id_count,
                    "unresolved_reference_count": collection.unresolved_reference_count,
                }
                for collection in self.collections
            ],
            "total_rows": self.total_rows,
            "remapped_id_count": self.remapped_id_count,
            "unresolved_references": list(self.unresolved_references),
            "warnings": list(self.warnings),
        }

    @property
    def plan_checksum(self) -> str:
        """Fingerprint the exact review result a future writer must require."""

        return hashlib.sha256(canonical_json(self._payload())).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload(), "plan_checksum": self.plan_checksum}


_UNRESOLVED_REPORT_LIMIT = 20
# Without a foreign key these cannot be rewritten by the dry-run, so a value in them is a blocker.
_UNRESOLVABLE_REFERENCE_FIELDS = frozenset(
    {"aggregate_id", "entity_id", "target_entity_id", "applied_entity_id", "confirmed_task_id"}
)


@dataclass(frozen=True, slots=True)
class _ReferenceResolver:
    """Decides, for one collection, whether a UUID-valued field is remapped or unresolved."""

    source: ExportSource
    identity_map: Mapping[tuple[str, UUID], UUID]
    source_owner_id: UUID
    target_owner_id: UUID

    def is_resolved(self, row: Mapping[str, Any], field: str, old_value: UUID) -> bool | None:
        """True when the value is remapped, False when it blocks the plan, None when ignored."""

        if field == "owner_id":
            return True
        if field in user_reference_fields(self.source):
            return self._user_reference_resolves(field, old_value)
        targets = foreign_key_targets(self.source).get(field)
        if field == "id":
            targets = frozenset({self.source.name})
        elif not targets and historical_reference_source(row, field) is not None:
            return True  # a stable id, never a blocker
        if not targets:
            # Metadata/correlation IDs or a future polymorphic relation: not safely rewritable.
            return False if field in _UNRESOLVABLE_REFERENCE_FIELDS else None
        mapped = [self.identity_map.get((target, old_value)) for target in targets]
        return any(item is not None for item in mapped) or "users" in targets

    def _user_reference_resolves(self, field: str, old_value: UUID) -> bool:
        try:
            remap_user_reference(
                self.source, field, old_value, self.source_owner_id, self.target_owner_id
            )
        except ExportRefused:
            return False
        return True


def _excluded_required_fields(source: ExportSource) -> list[str]:
    """Redacted fields the database requires without a default, so a restore cannot fill them."""

    return [
        field
        for field in source.redacted_fields
        if not (column := source.row_type.__table__.columns[field]).nullable
        and column.default is None
        and column.server_default is None
    ]


def _plan_collection(
    source: ExportSource,
    rows: list[Mapping[str, Any]],
    resolver: _ReferenceResolver,
    unresolved: list[str],
) -> RestoreCollectionPlan:
    """Count a collection's remapped and unresolved references; descriptions go to `unresolved`."""

    remapped = 0
    blocked = 0

    def note(description: str) -> None:
        if len(unresolved) < _UNRESOLVED_REPORT_LIMIT:
            unresolved.append(description)

    if rows:
        for field in _excluded_required_fields(source):
            blocked += len(rows)
            note(f"{source.name}.*.{field} (excluded required field)")
    for row_index, row in enumerate(rows):
        for field, value in row.items():
            old_value = uuid_or_none(value)
            if old_value is None:
                continue
            resolved = resolver.is_resolved(row, field, old_value)
            if resolved is None:
                continue
            if resolved:
                remapped += 1
            else:
                blocked += 1
                note(f"{source.name}[{row_index}].{field}")
    return RestoreCollectionPlan(
        name=source.name,
        row_count=len(rows),
        remapped_id_count=remapped,
        unresolved_reference_count=blocked,
    )


def build_restore_plan(
    document: Mapping[str, Any],
    target_owner_id: UUID,
) -> RestorePlan:
    """Validate an export and prepare an ID-remapping dry-run.

    This function is intentionally pure.  It reads the supplied JSON-shaped
    document only; no store, session, transaction, or write handler is
    reachable from it.  A plan is blocked when a UUID relation cannot be
    resolved from the closed export catalogue.
    """

    verification = verify_export(document)
    collections = document_collections(document)
    identity_map = restore_identity_map(document, target_owner_id)
    unresolved: list[str] = []
    collection_plans = tuple(
        _plan_collection(
            source,
            cast(list[Mapping[str, Any]], collections[source.name]),
            _ReferenceResolver(source, identity_map, verification.owner_id, target_owner_id),
            unresolved,
        )
        for source in EXPORT_SOURCES
    )
    unresolved_total = sum(item.unresolved_reference_count for item in collection_plans)
    try:
        restore_source_order(collections)
    except ExportRefused as error:
        unresolved_total += 1
        if len(unresolved) < _UNRESOLVED_REPORT_LIMIT:
            unresolved.append(str(error))
    return RestorePlan(
        source_owner_id=verification.owner_id,
        target_owner_id=target_owner_id,
        source_checksum=verification.checksum,
        status="blocked" if unresolved_total else "ready",
        conflict_policy="new_ids_only",
        collections=collection_plans,
        total_rows=sum(item.row_count for item in collection_plans),
        remapped_id_count=sum(item.remapped_id_count for item in collection_plans),
        unresolved_references=tuple(unresolved),
        warnings=(
            "Dry-run only: no database records were created, changed, or deleted.",
            "Authentication material, sessions, derived memory metadata, and operational "
            "worker state are not restorable from this export.",
        ),
    )


def verify_restorable(document: Mapping[str, Any]) -> ExportVerification:
    """Verify an export and prove its references resolve, so a restore of it cannot be blocked.

    The restore plan is the existing dry-run: it is pure and checks that every foreign key and
    polymorphic reference points at a row inside the export.  The remap that a restore performs
    is run too, so a reference the plan accepts but the writer would refuse is also caught.
    The refusal names collections, row positions and fields only, never row content.
    """

    verification = verify_export(document)
    plan = build_restore_plan(document, verification.owner_id)
    if plan.status != "ready":
        detail = ", ".join(plan.unresolved_references)
        raise ExportRefused(f"export has unresolved references: {detail}")
    remapped_restore_rows(document, verification.owner_id)
    return verification

"""Identity remapping for a restore: the stable ids a restored record gets and the write order."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID, uuid5

from sidekick.owner_export.catalogue import (
    EXPORT_SOURCES,
    SOURCES_BY_NAME,
    TABLE_TO_SOURCE,
    ExportRefused,
    ExportSource,
)
from sidekick.owner_export.persistence import coerce_restore_value, is_derived_column

_RESTORE_NAMESPACE = UUID("8db7a0e3-4f84-5c6a-9f7d-3e40ab69d4b8")
POLYMORPHIC_SOURCE_NAMES = {
    "domain": "domains",
    "process": "processes",
    "project": "projects",
    "task": "tasks",
    "step": "steps",
    "action": "actions",
    "work_tag": "work_tags",
    "contact": "contacts",
    "journal_source": "journal_sources",
    "journal_entry": "journal_entries",
    # Every aggregate type the ledger writes today (ActivityLedger.append callers) is named here.
    "process_run": "process_runs",
    "shopping_list": "shopping_lists",
    "shopping_item": "shopping_items",
}
# Polymorphic references (``domain_events`` and ``activity_entries`` ``aggregate_id``) are
# append-only history, not foreign keys. The record they name may legitimately be gone: a Task,
# contact or step removed permanently from the trash keeps its events. Such a reference cannot
# resolve, so it is rewritten to the stable restore id the record would have had (the same id a
# live record of that kind gets), which keeps every reference to it equal and never carries a
# source id into the target owner. It must not block a restore, or a long-lived instance could
# never be backed up.
# Real foreign keys stay strict: they are resolved only through the catalogue.


def foreign_key_targets(source: ExportSource) -> dict[str, frozenset[str]]:
    targets: dict[str, set[str]] = {}
    for foreign_key in source.row_type.__table__.foreign_keys:
        target = TABLE_TO_SOURCE.get(foreign_key.column.table.name)
        if target is not None:
            targets.setdefault(foreign_key.parent.name, set()).add(target)
    return {field: frozenset(values) for field, values in targets.items()}


def user_reference_fields(source: ExportSource) -> frozenset[str]:
    """Columns other than ``owner_id`` that point at a user (for example ``actor_id``)."""

    return frozenset(
        foreign_key.parent.name
        for foreign_key in source.row_type.__table__.foreign_keys
        if foreign_key.column.table.name == "users" and foreign_key.parent.name != "owner_id"
    )


def remap_user_reference(
    source: ExportSource,
    field: str,
    old_value: UUID,
    source_owner_id: UUID,
    target_owner_id: UUID,
) -> UUID | None:
    """Move the exporting owner to the target owner; any other user cannot exist in the target.

    A nullable reference to an unknown user becomes NULL (the same effect as deleting that user);
    a required one is reported as unresolved by the plan.
    """

    if old_value in {source_owner_id, target_owner_id}:
        return target_owner_id
    if source.row_type.__table__.columns[field].nullable:
        return None
    raise ExportRefused(f"unresolved restore reference {source.name}.{field}")


def restore_id(old_id: UUID, target_owner_id: UUID, source_name: str) -> UUID:
    """Create a stable target identity without reusing source primary keys."""

    return uuid5(
        _RESTORE_NAMESPACE,
        f"{target_owner_id}:{source_name}:{old_id}",
    )


def restore_lock_id(target_owner_id: UUID) -> int:
    return int.from_bytes(
        hashlib.sha256(b"sidekick:owner-restore:" + target_owner_id.bytes).digest()[:8],
        signed=True,
    )


def _polymorphic_type(row: Mapping[str, Any], field: str) -> str | None:
    type_value = row.get("entity_type") or row.get("target_entity_type")
    if field == "aggregate_id":
        type_value = row.get("aggregate_type")
    return type_value if isinstance(type_value, str) else None


def historical_reference_source(row: Mapping[str, Any], field: str) -> str | None:
    """The source name a polymorphic history reference is restored under, if it is one.

    A mapped type uses its source name; an unknown type uses its own label, so the id
    is still rewritten deterministically and per type. None when the row carries no type.
    """

    type_value = _polymorphic_type(row, field)
    if type_value is None:
        return None
    return POLYMORPHIC_SOURCE_NAMES.get(type_value) or type_value


def document_collections(document: Mapping[str, Any]) -> dict[str, Any]:
    collections = cast(Mapping[str, Any], document["collections"])
    return {name: collections[name] for name in SOURCES_BY_NAME}


def uuid_or_none(value: Any) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def restore_source_order(
    collections: Mapping[str, Any] | None = None,
) -> tuple[ExportSource, ...]:
    """Order populated collections after their exported FK dependencies."""

    dependencies = {
        source.name: {
            target
            for targets in foreign_key_targets(source).values()
            for target in targets
            if target != source.name
        }
        for source in EXPORT_SOURCES
    }
    if collections is not None:
        active = {
            source.name for source in EXPORT_SOURCES if cast(list[Any], collections[source.name])
        }
        dependencies = {
            name: targets & active for name, targets in dependencies.items() if name in active
        }
    ordered: list[ExportSource] = []
    remaining = set(dependencies)
    while remaining:
        ready = sorted(name for name in remaining if not (dependencies[name] & remaining))
        if not ready:
            raise ExportRefused("restore collection dependencies contain a cycle")
        ordered.extend(SOURCES_BY_NAME[name] for name in ready)
        remaining.difference_update(ready)
    return tuple(ordered)


def restore_identity_map(
    document: Mapping[str, Any], target_owner_id: UUID
) -> dict[tuple[str, UUID], UUID]:
    collections = document_collections(document)
    identity_map: dict[tuple[str, UUID], UUID] = {}
    for source in EXPORT_SOURCES:
        for row in cast(list[Mapping[str, Any]], collections[source.name]):
            old_id = uuid_or_none(row.get("id"))
            if old_id is not None:
                identity_map[(source.name, old_id)] = restore_id(
                    old_id, target_owner_id, source.name
                )
    return identity_map


def _remap_restore_value(
    source: ExportSource,
    row: Mapping[str, Any],
    field: str,
    value: Any,
    identity_map: Mapping[tuple[str, UUID], UUID],
    source_owner_id: UUID,
    target_owner_id: UUID,
) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        old_value = UUID(value)
    except ValueError:
        return value
    if field == "owner_id":
        return target_owner_id
    if field in user_reference_fields(source):
        return remap_user_reference(source, field, old_value, source_owner_id, target_owner_id)
    targets = foreign_key_targets(source).get(field)
    if field == "id":
        targets = frozenset({source.name})
    elif not targets:
        historical_source = historical_reference_source(row, field)
        if historical_source is not None:
            # The same id a live record of that kind gets, so references stay consistent.
            return restore_id(old_value, target_owner_id, historical_source)
    if not targets:
        return old_value
    for target in targets:
        mapped = identity_map.get((target, old_value))
        if mapped is not None:
            return mapped
    raise ExportRefused(f"unresolved restore reference {source.name}.{field}")


def remapped_restore_rows(
    document: Mapping[str, Any], target_owner_id: UUID
) -> dict[str, list[dict[str, Any]]]:
    collections = document_collections(document)
    identity_map = restore_identity_map(document, target_owner_id)
    source_owner_id = UUID(str(document["owner_id"]))
    remapped: dict[str, list[dict[str, Any]]] = {}
    for source in EXPORT_SOURCES:
        rows = cast(list[Mapping[str, Any]], collections[source.name])
        remapped[source.name] = [
            {
                field: coerce_restore_value(
                    source.row_type.__table__.columns[field],
                    _remap_restore_value(
                        source,
                        row,
                        field,
                        value,
                        identity_map,
                        source_owner_id,
                        target_owner_id,
                    ),
                )
                for field, value in row.items()
                if not is_derived_column(source.row_type.__table__.columns[field])
            }
            for row in rows
        ]
    return remapped

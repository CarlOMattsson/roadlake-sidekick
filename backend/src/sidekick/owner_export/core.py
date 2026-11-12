"""Owner-controlled data export with a deterministic integrity manifest.

The export catalogue is deliberately closed.  It is not a database dump: each
owner-scoped product relation is named here, while authentication material,
operational leases, derived Hindsight metadata, and non-owner-scoped audit data
are explicitly excluded.  A future restore path can therefore evolve against a
stable, reviewable format instead of accepting arbitrary table input.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid5

from sqlalchemy import Column, Date, DateTime, Numeric, func, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session

from sidekick.references.persistence import ExternalReferenceRow, TaskExternalReferenceRow
from sidekick.shared.errors.core import ValidationError
from sidekick.shared.observability import NoopTelemetryAdapter, TelemetryPort
from sidekick.shared.persistence.models import (
    ActionRow,
    ActivityEntryRow,
    AssistantAutomationControlRow,
    AssistantAutomationPolicyRow,
    AssistantAutomationRunRow,
    AssistantTaskReviewFindingRow,
    ContactAliasRow,
    ContactRow,
    DailyJournalSummaryEntryRow,
    DailyJournalSummaryRow,
    DomainEventRow,
    DomainRow,
    DomainTagRow,
    JournalDraftRow,
    JournalEntryContactRow,
    JournalEntryProjectRow,
    JournalEntryRow,
    JournalEntryTaskRow,
    JournalProcessingRunRow,
    JournalSourceRow,
    JournalSummaryProposalRow,
    MemorySettingsRow,
    ProcessRow,
    ProcessRunRow,
    ProcessRunTemplateRow,
    ProcessTagRow,
    ProjectContactRow,
    ProjectRow,
    ProjectTagRow,
    SavedViewRow,
    StepRow,
    TaskContactRow,
    TaskRow,
    TaskStatusHistoryRow,
    TaskTagRow,
    UserRow,
    WorkTagRow,
)
from sidekick.shared.types import Actor, Clock, SystemClock
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow, ShoppingStatusRow
from sidekick.work.domain.context import DOMAIN_ACCENTS

EXPORT_FORMAT = "sidekick.owner-export"
EXPORT_FORMAT_VERSION = 4
# Every migration of the chain, in order, with whether it leaves the exported tables and columns
# alone (an index, say). An export stamped at any head from the last format-changing migration
# onward is readable by this version; an export from before it is refused. A test pins this list to
# the files in `migrations/`, so a new migration forces a decision here.
SCHEMA_CHAIN: tuple[tuple[str, bool], ...] = (
    ("100_baseline_0_1_0", False),
    ("101_tasks_project_and_due_indexes", True),
    ("102_event_ledger_append_only", True),
    ("103_trash_sweep_delete_grants", True),
    ("104_audit_event_source", True),
    ("105_drop_sessions_and_password_hash", True),
)
SCHEMA_HEAD = SCHEMA_CHAIN[-1][0]


def accepted_schema_heads(chain: tuple[tuple[str, bool], ...]) -> frozenset[str]:
    """The heads an export may carry: from the last format-changing migration to the newest."""

    last_format_change = max(
        index for index, (_, format_neutral) in enumerate(chain) if not format_neutral
    )
    return frozenset(migration for migration, _ in chain[last_format_change:])


ACCEPTED_SCHEMA_HEADS = accepted_schema_heads(SCHEMA_CHAIN)


class ExportRefused(ValidationError):
    """An export, backup or restore was refused for a reason that names no owner data.

    The message holds a fixed reason or a collection/field name, never a row value, so the
    command line may print it. Any other error from a restore is reported by its type only.
    """


@dataclass(frozen=True, slots=True)
class ExportSource:
    """One explicitly approved owner-scoped relation in the export contract."""

    name: str
    row_type: type[Any]
    redacted_fields: frozenset[str] = frozenset()


EXPORT_SOURCES: tuple[ExportSource, ...] = (
    ExportSource("domains", DomainRow),
    ExportSource("processes", ProcessRow),
    ExportSource("process_run_templates", ProcessRunTemplateRow),
    ExportSource("process_runs", ProcessRunRow),
    ExportSource("projects", ProjectRow),
    ExportSource("tasks", TaskRow),
    ExportSource("task_status_history", TaskStatusHistoryRow),
    ExportSource("steps", StepRow),
    ExportSource("actions", ActionRow),
    ExportSource("work_tags", WorkTagRow),
    ExportSource("domain_tags", DomainTagRow),
    ExportSource("process_tags", ProcessTagRow),
    ExportSource("project_tags", ProjectTagRow),
    ExportSource("task_tags", TaskTagRow),
    ExportSource("saved_work_views", SavedViewRow),
    ExportSource("domain_events", DomainEventRow),
    ExportSource("activity_entries", ActivityEntryRow),
    ExportSource("assistant_automation_policies", AssistantAutomationPolicyRow),
    ExportSource("assistant_automation_control", AssistantAutomationControlRow),
    ExportSource("assistant_automation_runs", AssistantAutomationRunRow),
    ExportSource("assistant_task_review_findings", AssistantTaskReviewFindingRow),
    ExportSource("contacts", ContactRow),
    ExportSource("shopping_lists", ShoppingListRow),
    ExportSource("shopping_items", ShoppingItemRow),
    ExportSource("shopping_item_status_history", ShoppingStatusRow),
    ExportSource("contact_aliases", ContactAliasRow),
    ExportSource("project_contacts", ProjectContactRow),
    ExportSource("task_contacts", TaskContactRow),
    ExportSource("external_references", ExternalReferenceRow),
    ExportSource("task_external_references", TaskExternalReferenceRow),
    ExportSource("journal_sources", JournalSourceRow),
    ExportSource("journal_processing_runs", JournalProcessingRunRow),
    ExportSource("journal_drafts", JournalDraftRow),
    ExportSource("journal_summary_proposals", JournalSummaryProposalRow),
    ExportSource("journal_entries", JournalEntryRow),
    ExportSource("journal_entry_projects", JournalEntryProjectRow),
    ExportSource("journal_entry_tasks", JournalEntryTaskRow),
    ExportSource("journal_entry_contacts", JournalEntryContactRow),
    ExportSource("daily_journal_summaries", DailyJournalSummaryRow),
    ExportSource("daily_journal_summary_entries", DailyJournalSummaryEntryRow),
    ExportSource("memory_settings", MemorySettingsRow),
)

# Authentication, instance configuration, operational state and derived memory stay local.
EXCLUDED_COLLECTIONS: tuple[str, ...] = (
    "users_and_password_hashes",
    "sessions_and_csrf_digests",
    "personal_access_tokens",
    "idempotency_operations",
    "audit_events_without_owner_scope",
    "process_run_outbox_worker_state",
    "memory_sources_derived_metadata",
    "memory_usage_daily_derived_counters",
    "hindsight_memory_bank_content",
)

_SOURCES_BY_NAME = {source.name: source for source in EXPORT_SOURCES}
_TABLE_TO_SOURCE = {source.row_type.__table__.name: source.name for source in EXPORT_SOURCES}
_RESTORE_NAMESPACE = UUID("8db7a0e3-4f84-5c6a-9f7d-3e40ab69d4b8")
_POLYMORPHIC_SOURCE_NAMES = {
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
    "automation_run": "assistant_automation_runs",
    "shopping_list": "shopping_lists",
    "shopping_item": "shopping_items",
}
# Polymorphic references (``domain_events`` and ``activity_entries`` ``aggregate_id``) are
# append-only history, not foreign keys. The record they name may legitimately be gone: a Task,
# contact or step removed permanently from the trash keeps its events, and a chat or proposal
# record of an older version lives in a table the 0.1.0 baseline dropped. Such a reference cannot
# resolve, so it is rewritten to the stable restore id the record would have had (the same id a
# live record of that kind gets), which keeps every reference to it equal and never carries a
# source id into the target owner. It must not block a restore, or a long-lived instance could
# never be backed up.
# Real foreign keys stay strict: they are resolved only through the catalogue.
_RETIRED_POLYMORPHIC_SOURCE_NAMES = {
    "chat_conversation": "chat_conversations",
    "conversation": "chat_conversations",
    "chat_message": "chat_messages",
    "message": "chat_messages",
    "chat_action_proposal": "chat_action_proposals",
    "conversation_proposal": "conversation_proposals",
    "agent_proposal": "agent_proposals",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, (UUID, datetime, date)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, Any], value)
        return {str(key): _json_safe(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(list[Any] | tuple[Any, ...], value)
        return [_json_safe(item) for item in sequence]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported export value: {type(value).__name__}")


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _is_derived_column(column: Column[Any]) -> bool:
    """Generated columns (for example search vectors) are derived from other columns.

    They are neither exported nor restored: the database recomputes them, and a restore
    must not try to write them.
    """

    return column.computed is not None


def _source_fields(source: ExportSource) -> tuple[str, ...]:
    return tuple(
        column.name
        for column in source.row_type.__table__.columns
        if column.name not in source.redacted_fields and not _is_derived_column(column)
    )


def _without_checksum(document: Mapping[str, Any]) -> dict[str, Any]:
    manifest_value = document.get("manifest")
    if not isinstance(manifest_value, Mapping):
        raise ExportRefused("manifest must be an object")
    manifest = cast(Mapping[str, Any], manifest_value)
    return {
        **document,
        "manifest": {
            "collection_counts": manifest.get("collection_counts"),
        },
    }


def export_checksum(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_without_checksum(document))).hexdigest()


class ExportBudget:
    """A byte budget charged row by row while an export is serialised.

    Each row is charged its canonical-JSON size, which is a lower bound of the final document, so
    the first row that takes the total over `limit` ends the export with the error `exceeded`
    builds, before the rest of the data has been read or copied.  The caller picks the error, so
    the export stays free of the backup module's classes.
    """

    def __init__(self, limit: int, exceeded: Callable[[], Exception]) -> None:
        self._limit = limit
        self._exceeded = exceeded
        self._spent = 0

    def charge(self, row: Mapping[str, Any]) -> None:
        self._spent += len(canonical_json(row))
        if self._spent > self._limit:
            raise self._exceeded()


def _assemble_export_document(
    owner_id: UUID,
    normalized_collections: dict[str, list[Any]],
    *,
    exported_at: datetime,
) -> dict[str, Any]:
    """Wrap collections whose rows are already JSON-safe in the checksummed export document."""

    counts = {name: len(normalized_collections[name]) for name in normalized_collections}
    document: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "schema_head": SCHEMA_HEAD,
        "owner_id": str(owner_id),
        "exported_at": exported_at.isoformat(),
        "collections": normalized_collections,
        "excluded": list(EXCLUDED_COLLECTIONS),
        "manifest": {"collection_counts": counts},
    }
    document["manifest"] = {"collection_counts": counts, "sha256": export_checksum(document)}
    return document


def build_export_document(
    owner_id: UUID,
    collections: Mapping[str, list[Mapping[str, Any]]],
    *,
    exported_at: datetime,
) -> dict[str, Any]:
    normalized_collections = {
        name: [_json_safe(dict(row)) for row in rows] for name, rows in collections.items()
    }
    return _assemble_export_document(owner_id, normalized_collections, exported_at=exported_at)


@dataclass(frozen=True, slots=True)
class ExportVerification:
    owner_id: UUID
    checksum: str
    collection_counts: dict[str, int]


def verify_export(document: Mapping[str, Any]) -> ExportVerification:
    if document.get("format") != EXPORT_FORMAT:
        raise ExportRefused("unsupported export format")
    if document.get("schema_head") not in ACCEPTED_SCHEMA_HEADS:
        raise ExportRefused("unsupported schema head")
    format_version = document.get("format_version")
    if (
        not isinstance(format_version, int)
        or isinstance(format_version, bool)
        or format_version != EXPORT_FORMAT_VERSION
    ):
        raise ExportRefused("unsupported export version")
    if not isinstance(document.get("exported_at"), str):
        raise ExportRefused("invalid export timestamp")
    try:
        owner_id = UUID(str(document["owner_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ExportRefused("invalid owner id") from error

    collections_value = document.get("collections")
    if not isinstance(collections_value, Mapping):
        raise ExportRefused("collections must be an object")
    collections = cast(Mapping[str, Any], collections_value)
    if set(collections) != set(_SOURCES_BY_NAME):
        raise ExportRefused("export collection catalogue does not match format")

    for name, source in _SOURCES_BY_NAME.items():
        rows_value = collections[name]
        if not isinstance(rows_value, list):
            raise ExportRefused(f"collection {name} must be an array")
        rows = cast(list[Any], rows_value)
        fields = set(_source_fields(source))
        for row_value in rows:
            if not isinstance(row_value, Mapping):
                raise ExportRefused(f"collection {name} contains a non-object row")
            row = cast(Mapping[str, Any], row_value)
            if set(row) != fields:
                raise ExportRefused(f"collection {name} has an unexpected row shape")
            if row.get("owner_id") != str(owner_id):
                raise ExportRefused(f"collection {name} crosses the owner boundary")
            # The accent is a closed palette, mirroring the domain entity and the DB CHECK.
            if name == "domains" and row.get("accent") not in (None, *DOMAIN_ACCENTS):
                raise ExportRefused(f"collection {name} has an invalid domain accent")

    excluded = document.get("excluded")
    if excluded != list(EXCLUDED_COLLECTIONS):
        raise ExportRefused("export exclusion catalogue does not match format")
    manifest_value = document.get("manifest")
    if not isinstance(manifest_value, Mapping):
        raise ExportRefused("manifest must be an object")
    manifest = cast(Mapping[str, Any], manifest_value)
    counts = manifest.get("collection_counts")
    document_counts = {name: len(collections[name]) for name in _SOURCES_BY_NAME}
    if counts != document_counts:
        raise ExportRefused("manifest counts do not match collections")
    checksum = manifest.get("sha256")
    if not isinstance(checksum, str) or checksum != export_checksum(document):
        raise ExportRefused("export checksum mismatch")
    return ExportVerification(owner_id, checksum, document_counts)


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


def _foreign_key_targets(source: ExportSource) -> dict[str, frozenset[str]]:
    targets: dict[str, set[str]] = {}
    for foreign_key in source.row_type.__table__.foreign_keys:
        target = _TABLE_TO_SOURCE.get(foreign_key.column.table.name)
        if target is not None:
            targets.setdefault(foreign_key.parent.name, set()).add(target)
    return {field: frozenset(values) for field, values in targets.items()}


def _user_reference_fields(source: ExportSource) -> frozenset[str]:
    """Columns other than ``owner_id`` that point at a user (for example ``actor_id``)."""

    return frozenset(
        foreign_key.parent.name
        for foreign_key in source.row_type.__table__.foreign_keys
        if foreign_key.column.table.name == "users" and foreign_key.parent.name != "owner_id"
    )


def _remap_user_reference(
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


def _restore_id(old_id: UUID, target_owner_id: UUID, source_name: str) -> UUID:
    """Create a stable target identity without reusing source primary keys."""

    return uuid5(
        _RESTORE_NAMESPACE,
        f"{target_owner_id}:{source_name}:{old_id}",
    )


def _restore_lock_id(target_owner_id: UUID) -> int:
    return int.from_bytes(
        hashlib.sha256(b"sidekick:owner-restore:" + target_owner_id.bytes).digest()[:8],
        signed=True,
    )


def _polymorphic_type(row: Mapping[str, Any], field: str) -> str | None:
    type_value = row.get("entity_type") or row.get("target_entity_type")
    if field == "aggregate_id":
        type_value = row.get("aggregate_type")
    return type_value if isinstance(type_value, str) else None


def _historical_reference_source(row: Mapping[str, Any], field: str) -> str | None:
    """The source name a polymorphic history reference is restored under, if it is one.

    A mapped or retired type uses its source name; an unknown type uses its own label, so the id
    is still rewritten deterministically and per type. None when the row carries no type.
    """

    type_value = _polymorphic_type(row, field)
    if type_value is None:
        return None
    return (
        _POLYMORPHIC_SOURCE_NAMES.get(type_value)
        or _RETIRED_POLYMORPHIC_SOURCE_NAMES.get(type_value)
        or type_value
    )


def _document_collections(document: Mapping[str, Any]) -> dict[str, Any]:
    collections = cast(Mapping[str, Any], document["collections"])
    return {name: collections[name] for name in _SOURCES_BY_NAME}


_UNRESOLVED_REPORT_LIMIT = 20
# Without a foreign key these cannot be rewritten by the dry-run, so a value in them is a blocker.
_UNRESOLVABLE_REFERENCE_FIELDS = frozenset(
    {"aggregate_id", "entity_id", "target_entity_id", "applied_entity_id", "confirmed_task_id"}
)


def _uuid_or_none(value: Any) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


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
        if field in _user_reference_fields(self.source):
            return self._user_reference_resolves(field, old_value)
        targets = _foreign_key_targets(self.source).get(field)
        if field == "id":
            targets = frozenset({self.source.name})
        elif not targets and _historical_reference_source(row, field) is not None:
            return True  # a stable id, never a blocker
        if not targets:
            # Metadata/correlation IDs or a future polymorphic relation: not safely rewritable.
            return False if field in _UNRESOLVABLE_REFERENCE_FIELDS else None
        mapped = [self.identity_map.get((target, old_value)) for target in targets]
        return any(item is not None for item in mapped) or "users" in targets

    def _user_reference_resolves(self, field: str, old_value: UUID) -> bool:
        try:
            _remap_user_reference(
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
            old_value = _uuid_or_none(value)
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
    collections = _document_collections(document)
    identity_map = _restore_identity_map(document, target_owner_id)
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
        _restore_source_order(collections)
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
    _remapped_restore_rows(document, verification.owner_id)
    return verification


def _restore_source_order(
    collections: Mapping[str, Any] | None = None,
) -> tuple[ExportSource, ...]:
    """Order populated collections after their exported FK dependencies."""

    dependencies = {
        source.name: {
            target
            for targets in _foreign_key_targets(source).values()
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
        ordered.extend(_SOURCES_BY_NAME[name] for name in ready)
        remaining.difference_update(ready)
    return tuple(ordered)


def _restore_identity_map(
    document: Mapping[str, Any], target_owner_id: UUID
) -> dict[tuple[str, UUID], UUID]:
    collections = _document_collections(document)
    identity_map: dict[tuple[str, UUID], UUID] = {}
    for source in EXPORT_SOURCES:
        for row in cast(list[Mapping[str, Any]], collections[source.name]):
            old_id = _uuid_or_none(row.get("id"))
            if old_id is not None:
                identity_map[(source.name, old_id)] = _restore_id(
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
    if field in _user_reference_fields(source):
        return _remap_user_reference(source, field, old_value, source_owner_id, target_owner_id)
    targets = _foreign_key_targets(source).get(field)
    if field == "id":
        targets = frozenset({source.name})
    elif not targets:
        historical_source = _historical_reference_source(row, field)
        if historical_source is not None:
            # The same id a live record of that kind gets, so references stay consistent.
            return _restore_id(old_value, target_owner_id, historical_source)
    if not targets:
        return old_value
    for target in targets:
        mapped = identity_map.get((target, old_value))
        if mapped is not None:
            return mapped
    raise ExportRefused(f"unresolved restore reference {source.name}.{field}")


def _coerce_restore_value(column: Any, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, PGUUID):
        return value if isinstance(value, UUID) else UUID(str(value))
    if isinstance(column.type, DateTime):
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if isinstance(column.type, Date):
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    if isinstance(column.type, Numeric):
        return value if isinstance(value, Decimal) else Decimal(str(value))
    return value


def _remapped_restore_rows(
    document: Mapping[str, Any], target_owner_id: UUID
) -> dict[str, list[dict[str, Any]]]:
    collections = _document_collections(document)
    identity_map = _restore_identity_map(document, target_owner_id)
    source_owner_id = UUID(str(document["owner_id"]))
    remapped: dict[str, list[dict[str, Any]]] = {}
    for source in EXPORT_SOURCES:
        rows = cast(list[Mapping[str, Any]], collections[source.name])
        remapped[source.name] = [
            {
                field: _coerce_restore_value(
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
                if not _is_derived_column(source.row_type.__table__.columns[field])
            }
            for row in rows
        ]
    return remapped


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
        remapped = _remapped_restore_rows(document, target_owner_id)

        def write(session: Session) -> RestoreResult:
            session.execute(select(func.pg_advisory_xact_lock(_restore_lock_id(target_owner_id))))
            if session.scalar(select(UserRow.id).where(UserRow.id == target_owner_id)) is None:
                raise ExportRefused("target owner does not exist")
            # The settings row AuthService writes at provisioning is not content. An untouched
            # default row is overwritten by the document's row; any other settings row refuses.
            settings_row = session.scalar(
                select(MemorySettingsRow)
                .where(MemorySettingsRow.owner_id == target_owner_id)
                .with_for_update()
            )
            if settings_row is not None and not _is_untouched_memory_default(settings_row):
                raise ExportRefused("target owner must be empty before restore")
            for source in EXPORT_SOURCES:
                if source.row_type is MemorySettingsRow:
                    continue
                owner_column = source.row_type.owner_id
                if (
                    session.scalar(
                        select(source.row_type).where(owner_column == target_owner_id).limit(1)
                    )
                    is not None
                ):
                    raise ExportRefused("target owner must be empty before restore")
            imported_rows = 0
            for source in _restore_source_order(_document_collections(document)):
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


class OwnerExportService:
    """Application service for an authenticated owner's complete export."""

    def __init__(
        self,
        store: Any,
        clock: Clock | None = None,
        telemetry: TelemetryPort | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or SystemClock()
        self._telemetry = telemetry or NoopTelemetryAdapter()

    def _export_owner_in_session(
        self,
        session: Session,
        owner_id: UUID,
        *,
        exported_at: datetime,
        budget: ExportBudget | None = None,
    ) -> dict[str, Any]:
        collections: dict[str, list[Any]] = {}
        for source in EXPORT_SOURCES:
            fields = _source_fields(source)
            exported: list[Any] = []
            # The rows are read as a stream and each one is turned into its JSON-safe form once,
            # so no second copy of the data is built and an over-budget export stops here.
            for row in self._store.export_owner_rows(
                session,
                owner_id=owner_id,
                row_type=source.row_type,
            ):
                document_row = {field: _json_safe(getattr(row, field)) for field in fields}
                if budget is not None:
                    budget.charge(document_row)
                exported.append(document_row)
            collections[source.name] = exported
        return _assemble_export_document(owner_id, collections, exported_at=exported_at)

    def export(self, actor: Actor) -> dict[str, Any]:
        def read(session: Session) -> dict[str, Any]:
            return self._export_owner_in_session(
                session, actor.user_id, exported_at=self._clock.now()
            )

        document = self._store.snapshot_transaction(read)

        verification = verify_export(document)
        self._telemetry.count(
            "sidekick.owner_export",
            {
                "owner_export.operation": "export",
                "outcome": "success",
                "owner_export.collection_count": str(len(verification.collection_counts)),
            },
        )
        return document

    def export_all(self, budget: ExportBudget | None = None) -> list[dict[str, Any]]:
        """Export every owner from one repeatable-read snapshot of the database.

        With a `budget`, the export is abandoned with the budget's error as soon as the rows read
        so far are over it.
        """

        def read(session: Session) -> list[dict[str, Any]]:
            exported_at = self._clock.now()
            owner_ids = session.scalars(select(UserRow.id).order_by(UserRow.id)).all()
            return [
                self._export_owner_in_session(
                    session, owner_id, exported_at=exported_at, budget=budget
                )
                for owner_id in owner_ids
            ]

        documents = self._store.snapshot_transaction(read)
        for document in documents:
            verify_export(document)
        return documents

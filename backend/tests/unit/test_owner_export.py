from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from sidekick.owner_export.catalogue import (
    ACCEPTED_SCHEMA_HEADS_BY_FORMAT,
    EXCLUDED_COLLECTIONS,
    EXPORT_FORMAT_VERSION,
    EXPORT_SOURCES,
    FOLDED_CHAIN_HEADS,
    PREVIOUS_EXPORT_FORMAT_VERSION,
    RETIRED_COLLECTIONS,
    SCHEMA_CHAIN,
    SCHEMA_HEAD,
    ExportRefused,
    accepted_schema_heads,
)
from sidekick.owner_export.document import build_export_document, export_checksum, verify_export
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan, verify_restorable
from sidekick.owner_export.restore_remap import (
    POLYMORPHIC_SOURCE_NAMES,
    restore_id,
)
from sidekick.shared.persistence.models import (
    ActivityEntryRow,
    ContactRow,
    DomainRow,
    TaskStatusHistoryRow,
)
from sidekick.shared.types import Actor
from tests.support.export_format4 import BASELINE_HEAD, as_format_4

OWNER_ID = UUID("00000000-0000-7000-8000-000000000001")
# Tables with a generated `search_vector` (0.1.0 baseline); it is derived, never exported.
SEARCH_VECTOR_COLLECTIONS = (
    "journal_sources",
    "journal_entries",
    "tasks",
    "projects",
    "contacts",
    "contact_aliases",
)


def empty_collections() -> dict[str, list[dict[str, object]]]:
    return {source.name: [] for source in EXPORT_SOURCES}


def test_empty_export_has_a_stable_manifest_and_verifies() -> None:
    document = build_export_document(
        OWNER_ID,
        empty_collections(),
        exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )

    result = verify_export(document)

    assert result.owner_id == OWNER_ID
    assert len(result.checksum) == 64
    assert result.collection_counts == {source.name: 0 for source in EXPORT_SOURCES}
    assert document["excluded"] == list(EXCLUDED_COLLECTIONS)


def test_verification_rejects_cross_owner_rows() -> None:
    collections = empty_collections()
    collections["domains"] = [
        {
            "id": str(OWNER_ID),
            "owner_id": str(UUID("00000000-0000-7000-8000-000000000002")),
            "name": "wrong owner",
            "description": None,
            "status": "active",
            "created_at": "2026-08-29T12:00:00+00:00",
            "updated_at": "2026-08-29T12:00:00+00:00",
            "version": 1,
            "review_cadence": None,
            "last_reviewed_at": None,
            "trashed_at": None,
            "accent": None,
        }
    ]
    document = build_export_document(
        OWNER_ID,
        collections,
        exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )

    with pytest.raises(ExportRefused, match="crosses the owner boundary"):
        verify_export(document)


def test_verification_rejects_tampered_manifest() -> None:
    document = build_export_document(
        OWNER_ID,
        empty_collections(),
        exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )
    document["manifest"]["sha256"] = "0" * 64  # type: ignore[index]

    with pytest.raises(ExportRefused, match="checksum mismatch"):
        verify_export(document)


def test_restore_plan_is_deterministic_and_does_not_mutate_export() -> None:
    domain_id = UUID("00000000-0000-7000-8000-000000000010")
    collections = empty_collections()
    collections["domains"] = [
        {
            "id": str(domain_id),
            "owner_id": str(OWNER_ID),
            "name": "Restore candidate",
            "description": None,
            "status": "active",
            "created_at": "2026-08-29T12:00:00+00:00",
            "updated_at": "2026-08-29T12:00:00+00:00",
            "version": 1,
            "review_cadence": None,
            "last_reviewed_at": None,
            "trashed_at": None,
            "accent": None,
        }
    ]
    document = build_export_document(
        OWNER_ID,
        collections,
        exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )
    before = repr(document)
    target_owner = UUID("00000000-0000-7000-8000-000000000002")

    first = build_restore_plan(document, target_owner)
    second = build_restore_plan(document, target_owner)

    assert first.status == "ready"
    assert first.as_dict() == second.as_dict()
    assert first.total_rows == 1
    assert first.remapped_id_count == 2
    assert first.unresolved_references == ()
    assert len(first.plan_checksum) == 64
    assert first.as_dict()["conflict_policy"] == "new_ids_only"
    assert repr(document) == before


def test_restore_plan_rejects_invalid_export_before_any_preparation() -> None:
    with pytest.raises(ExportRefused, match="unsupported export format"):
        build_restore_plan({"format": "not-sidekick"}, OWNER_ID)


def domain_event_export(aggregate_type: str) -> dict[str, Any]:
    source = next(source for source in EXPORT_SOURCES if source.name == "domain_events")
    row: dict[str, Any] = {column.name: None for column in source.row_type.__table__.columns}
    row.update(
        {
            "id": "00000000-0000-7000-8000-000000000010",
            "owner_id": str(OWNER_ID),
            "aggregate_id": "00000000-0000-7000-8000-000000000011",
            "aggregate_type": aggregate_type,
        }
    )
    collections = empty_collections()
    collections[source.name] = [row]
    return build_export_document(
        OWNER_ID,
        collections,
        exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )


def test_a_real_foreign_key_that_does_not_resolve_still_blocks() -> None:
    """Only polymorphic history is tolerant; a foreign key into the export must resolve."""

    document = domain_event_export("task")
    document["collections"]["activity_entries"] = [
        {
            **{column.name: None for column in ActivityEntryRow.__table__.columns},
            "id": "00000000-0000-7000-8000-000000000020",
            "owner_id": str(OWNER_ID),
            "domain_event_id": "00000000-0000-7000-8000-0000000000ff",
            "aggregate_type": "task",
            "aggregate_id": "00000000-0000-7000-8000-000000000011",
        }
    ]
    document["manifest"]["collection_counts"]["activity_entries"] = 1
    document["manifest"]["sha256"] = export_checksum(document)

    plan = build_restore_plan(document, OWNER_ID)

    assert plan.status == "blocked"
    assert plan.unresolved_references == ("activity_entries[0].domain_event_id",)


def test_a_required_user_reference_that_cannot_resolve_blocks_the_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal is counted as unresolved; it does not abort the plan."""

    document = domain_event_export("task")
    row = document["collections"]["domain_events"][0]
    row["actor_id"] = "00000000-0000-7000-8000-0000000000aa"
    document["manifest"]["sha256"] = export_checksum(document)

    def refuse(*_args: object) -> None:
        raise ExportRefused("unresolved restore reference domain_events.actor_id")

    monkeypatch.setattr("sidekick.owner_export.restore_plan.remap_user_reference", refuse)

    plan = build_restore_plan(document, OWNER_ID)

    assert plan.status == "blocked"
    assert plan.unresolved_references == ("domain_events[0].actor_id",)


def test_a_restore_order_cycle_blocks_the_plan_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(_collections: object) -> None:
        raise ExportRefused("restore order has a cycle")

    monkeypatch.setattr("sidekick.owner_export.restore_plan.restore_source_order", refuse)

    plan = build_restore_plan(domain_event_export("task"), OWNER_ID)

    assert plan.status == "blocked"
    assert "restore order has a cycle" in plan.unresolved_references


def _restored_aggregate_id(aggregate_type: str, target_owner: UUID) -> UUID:
    document = domain_event_export(aggregate_type)
    plan = build_restore_plan(document, target_owner)
    assert plan.status == "ready"
    store = FakeRestoreStore()
    OwnerRestoreService(store).restore(
        document, target_owner_id=target_owner, expected_plan_checksum=plan.plan_checksum
    )
    return store.session.added[0].aggregate_id  # type: ignore[attr-defined,no-any-return]


# Every aggregate type with a mapping, and one nothing knows: the record is gone in each case
# (the export has no row of it), and none may stop a backup or a restore.
HISTORY_AGGREGATE_TYPES = (
    *sorted(POLYMORPHIC_SOURCE_NAMES),
    "unknown_future_kind",
)


@pytest.mark.parametrize("aggregate_type", HISTORY_AGGREGATE_TYPES)
def test_a_history_reference_to_a_removed_record_is_stable_and_never_blocks(
    aggregate_type: str,
) -> None:
    target_owner = UUID("00000000-0000-7000-8000-000000000002")
    old_id = UUID("00000000-0000-7000-8000-000000000011")

    document = domain_event_export(aggregate_type)
    assert build_restore_plan(document, target_owner).status == "ready"
    assert verify_restorable(document).owner_id == OWNER_ID
    restored = _restored_aggregate_id(aggregate_type, target_owner)

    assert restored != old_id
    assert restored == _restored_aggregate_id(aggregate_type, target_owner)
    source = POLYMORPHIC_SOURCE_NAMES.get(aggregate_type) or aggregate_type
    # The id a live record of that kind would have got, so references stay consistent.
    assert restored == restore_id(old_id, target_owner, source)


def test_every_aggregate_type_the_ledger_writes_has_a_mapping() -> None:
    from sidekick.automation.application.service import ACTIVITY_AGGREGATE_SCOPES

    # The run records of the retired automation engine have no export source any more; their ledger
    # type stays readable and is restored under its own label like any unmapped type.
    written = {"task", "process_run", *ACTIVITY_AGGREGATE_SCOPES} - {"automation_run"}
    assert written <= set(POLYMORPHIC_SOURCE_NAMES)
    assert set(POLYMORPHIC_SOURCE_NAMES.values()) <= {source.name for source in EXPORT_SOURCES}


class FakeRestoreSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.scalar_calls = 0

    def scalar(self, _query: object) -> object | None:
        self.scalar_calls += 1
        return None

    def execute(self, _query: object) -> None:
        return None

    def add(self, row: object) -> None:
        self.added.append(row)

    def flush(self) -> None:
        return None


class FakeRestoreStore:
    def __init__(self) -> None:
        self.session = FakeRestoreSession()
        self.audit: list[dict[str, object]] = []

    def transaction(self, operation: object) -> object:
        return operation(self.session)  # type: ignore[operator]

    def owner_exists(self, session: object, owner_id: UUID) -> bool:
        return True

    def append_audit(self, session: object, **fields: object) -> None:
        self.audit.append(fields)


def test_restore_service_writes_only_after_the_reviewed_plan_matches() -> None:
    domain_id = UUID("00000000-0000-7000-8000-000000000010")
    collections = empty_collections()
    collections["domains"] = [
        {
            "id": str(domain_id),
            "owner_id": str(OWNER_ID),
            "name": "Restore candidate",
            "description": None,
            "status": "active",
            "created_at": "2026-08-29T12:00:00+00:00",
            "updated_at": "2026-08-29T12:00:00+00:00",
            "version": 1,
            "review_cadence": None,
            "last_reviewed_at": None,
            "trashed_at": None,
            "accent": None,
        }
    ]
    document = build_export_document(
        OWNER_ID,
        collections,
        exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )
    target_owner = UUID("00000000-0000-7000-8000-000000000002")
    plan = build_restore_plan(document, target_owner)
    store = FakeRestoreStore()

    result = OwnerRestoreService(store).restore(
        document,
        target_owner_id=target_owner,
        expected_plan_checksum=plan.plan_checksum,
    )

    assert result.imported_rows == 1
    assert len(store.session.added) == 1
    restored = store.session.added[0]
    assert restored.owner_id == target_owner  # type: ignore[attr-defined]
    assert restored.id != domain_id  # type: ignore[attr-defined]
    assert store.audit[0]["event"] == "owner.restore"


def test_restore_service_refuses_a_changed_plan_before_opening_transaction() -> None:
    document = build_export_document(
        OWNER_ID,
        empty_collections(),
        exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )
    store = FakeRestoreStore()

    with pytest.raises(ExportRefused, match="plan checksum mismatch"):
        OwnerRestoreService(store).restore(
            document,
            target_owner_id=OWNER_ID,
            expected_plan_checksum="0" * 64,
        )

    assert store.session.scalar_calls == 0


DOMAIN_ROW = {
    "id": "00000000-0000-7000-8000-000000000010",
    "owner_id": str(OWNER_ID),
    "name": "Legacy domain",
    "description": None,
    "status": "active",
    "created_at": "2026-08-29T12:00:00+00:00",
    "updated_at": "2026-08-29T12:00:00+00:00",
    "version": 1,
    "review_cadence": None,
    "last_reviewed_at": None,
    "trashed_at": None,
}


def reseal(document: dict[str, Any]) -> dict[str, Any]:
    document["manifest"] = {"collection_counts": document["manifest"]["collection_counts"]}
    document["manifest"]["sha256"] = export_checksum(document)
    return document


def test_current_export_is_format_five_at_the_chain_head() -> None:
    document = build_export_document(
        OWNER_ID, empty_collections(), exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )
    assert document["format_version"] == EXPORT_FORMAT_VERSION == 5
    assert document["schema_head"] == SCHEMA_HEAD
    assert "external_references" in document["collections"]
    assert "task_external_references" in document["collections"]
    assert "memory_settings" in document["collections"]
    assert "chat_conversations" not in document["collections"]
    assert not RETIRED_COLLECTIONS & set(document["collections"])
    assert "chat_memory_documents_derived_metadata" not in document["excluded"]


def test_schema_head_is_the_last_migration() -> None:
    migrations = sorted(
        path.stem
        for path in (Path(__file__).resolve().parents[3] / "migrations").glob(
            "[0-9][0-9][0-9]_*.py"
        )
    )
    assert migrations[-1] == SCHEMA_HEAD


def test_the_schema_chain_lists_every_migration_file() -> None:
    files = sorted(
        path.stem
        for path in (Path(__file__).resolve().parents[3] / "migrations").glob(
            "[0-9][0-9][0-9]_*.py"
        )
    )
    assert [migration for migration, _ in SCHEMA_CHAIN] == files


def _current_document() -> dict[str, Any]:
    return build_export_document(
        OWNER_ID, empty_collections(), exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )


@pytest.mark.parametrize("head", sorted(FOLDED_CHAIN_HEADS | {BASELINE_HEAD}))
def test_a_format_4_export_from_the_baseline_or_the_folded_chain_is_still_accepted(
    head: str,
) -> None:
    """Format 4 was written at the baseline or at a head of the chain the baseline folded in
    (the owner's installation carries 105). It differs from the current format only by four empty
    collections of the retired automation engine, which are ignored."""

    assert head in ACCEPTED_SCHEMA_HEADS_BY_FORMAT[PREVIOUS_EXPORT_FORMAT_VERSION]
    assert head not in ACCEPTED_SCHEMA_HEADS_BY_FORMAT[EXPORT_FORMAT_VERSION]

    verification = verify_export(as_format_4(_current_document(), head))

    assert verification.owner_id == OWNER_ID
    # The ignored collections are not part of what a reader sees.
    assert verification.collection_counts == {source.name: 0 for source in EXPORT_SOURCES}


def test_the_current_head_is_the_drop_of_the_retired_automation_tables() -> None:
    assert SCHEMA_HEAD == "106_drop_retired_automation_tables"
    assert ACCEPTED_SCHEMA_HEADS_BY_FORMAT[EXPORT_FORMAT_VERSION] == {SCHEMA_HEAD}


@pytest.mark.parametrize("name", sorted(RETIRED_COLLECTIONS))
def test_a_format_4_export_with_a_row_in_a_retired_collection_is_refused(name: str) -> None:
    document = as_format_4(_current_document(), retired_rows={name: [{"owner_id": str(OWNER_ID)}]})

    with pytest.raises(ExportRefused, match=f"collection {name} of a retired feature"):
        verify_export(document)


def test_a_format_4_export_must_carry_every_retired_collection() -> None:
    document = as_format_4(_current_document())
    del document["collections"]["assistant_automation_runs"]
    del document["manifest"]["collection_counts"]["assistant_automation_runs"]

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(reseal(document))


def test_a_format_5_export_cannot_carry_a_retired_collection() -> None:
    document = _current_document()
    document["collections"]["assistant_automation_runs"] = []
    document["manifest"]["collection_counts"]["assistant_automation_runs"] = 0

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(reseal(document))


def test_the_head_of_one_format_is_not_accepted_for_the_other() -> None:
    new_with_old_head = {**_current_document(), "schema_head": BASELINE_HEAD}
    old_with_new_head = as_format_4(_current_document(), SCHEMA_HEAD)

    for document in (new_with_old_head, old_with_new_head):
        with pytest.raises(ExportRefused, match="unsupported schema head"):
            verify_export(reseal(document))


def test_a_real_format_change_ends_compatibility_with_older_heads() -> None:
    chain = (("100_a", False), ("101_index", True), ("102_new_column", False), ("103_index", True))

    assert accepted_schema_heads(chain) == {"102_new_column", "103_index"}
    assert accepted_schema_heads(chain[:2]) == {"100_a", "101_index"}


@pytest.mark.parametrize(
    "head", ["055_app_reads_migration_head", "101_future", "100_schema_baseline", "", None, 7]
)
def test_any_other_schema_head_is_refused(head: object) -> None:
    document = build_export_document(
        OWNER_ID, empty_collections(), exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )
    document["schema_head"] = head

    with pytest.raises(ExportRefused, match="unsupported schema head"):
        verify_export(reseal(document))


def test_an_export_written_before_the_baseline_is_refused() -> None:
    """Formats 1 to 3 (the retired chain) are no longer readable; only formats 4 and 5 are."""

    document = build_export_document(
        OWNER_ID, empty_collections(), exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )
    document["format_version"] = 3
    document["schema_head"] = "055_app_reads_migration_head"
    document["collections"]["chat_conversations"] = []
    document["manifest"]["collection_counts"]["chat_conversations"] = 0

    with pytest.raises(ExportRefused, match="unsupported export version"):
        verify_export(reseal(document))


def test_a_current_export_cannot_carry_a_collection_the_catalogue_lacks() -> None:
    document = build_export_document(
        OWNER_ID, empty_collections(), exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )
    document["collections"]["chat_conversations"] = []
    document["manifest"]["collection_counts"]["chat_conversations"] = 0

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(reseal(document))


CONTACT_ROW_040 = {
    "id": "00000000-0000-7000-8000-00000000c001",
    "owner_id": str(OWNER_ID),
    "display_name": "Anna",
    "display_name_key": "anna",
    "context_note": None,
    "email": None,
    "email_key": None,
    "phone": None,
    "phone_key": None,
    "created_at": "2026-08-29T12:00:00+00:00",
    "updated_at": "2026-08-29T12:00:00+00:00",
    "archived_at": None,
    "archived": False,
    "version": 1,
    "trashed_at": None,
}


def test_a_current_export_carries_the_profile_columns() -> None:
    collections = empty_collections()
    collections["contacts"] = [
        {
            **CONTACT_ROW_040,
            "relationship": "syster",
            "organization": None,
            "role": None,
            "address": None,
        }
    ]
    document = build_export_document(
        OWNER_ID, collections, exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )

    assert verify_export(document).collection_counts["contacts"] == 1
    assert document["collections"]["contacts"][0]["relationship"] == "syster"


@pytest.mark.parametrize("version", [0, 1, 3, 6, "5", True, None, [5]])
def test_a_format_version_that_the_head_never_wrote_is_refused(version: object) -> None:
    current = build_export_document(
        OWNER_ID, empty_collections(), exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )
    current["format_version"] = version

    with pytest.raises(ExportRefused, match="unsupported export version"):
        verify_export(reseal(current))


def test_a_current_export_missing_a_current_collection_is_refused() -> None:
    document = build_export_document(
        OWNER_ID, empty_collections(), exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )
    del document["collections"]["external_references"]
    del document["manifest"]["collection_counts"]["external_references"]

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(reseal(document))


MEMORY_SETTINGS_ROW = {
    "owner_id": str(OWNER_ID),
    "journal": True,
    "contacts": False,
    "projects": False,
    "tasks": True,
    "paused": False,
    "version": 2,
    "created_at": "2026-08-29T12:00:00+00:00",
    "updated_at": "2026-08-29T12:00:00+00:00",
}


def test_a_current_export_carries_memory_settings_and_excludes_the_memory_tables() -> None:
    collections = empty_collections()
    collections["memory_settings"] = [dict(MEMORY_SETTINGS_ROW)]
    document = build_export_document(
        OWNER_ID, collections, exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )

    assert verify_export(document).collection_counts["memory_settings"] == 1
    assert document["collections"]["memory_settings"] == [MEMORY_SETTINGS_ROW]
    assert {"memory_sources", "memory_usage_daily"}.isdisjoint(document["collections"])
    assert {
        "memory_sources_derived_metadata",
        "memory_usage_daily_derived_counters",
        "hindsight_memory_bank_content",
    } <= set(document["excluded"])


def test_pairings_and_token_purpose_never_travel_with_an_export() -> None:
    from sidekick.shared.persistence.models import PersonalAccessTokenRow

    exported_tables = {source.row_type.__table__.name for source in EXPORT_SOURCES}
    assert "companion_pairings" not in exported_tables
    assert "instance_license" not in exported_tables
    assert PersonalAccessTokenRow.__table__.name not in exported_tables
    assert "personal_access_tokens" in EXCLUDED_COLLECTIONS
    document = build_export_document(
        OWNER_ID, empty_collections(), exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )
    assert "companion_pairings" not in document["collections"]
    assert "instance_license" not in document["collections"]


def test_a_current_export_without_memory_settings_is_refused() -> None:
    document = build_export_document(
        OWNER_ID, empty_collections(), exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )
    del document["collections"]["memory_settings"]
    del document["manifest"]["collection_counts"]["memory_settings"]

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(reseal(document))


class FakeExportStore:
    """Returns ORM instances per row type, like the owner-scoped export query would."""

    def __init__(self, rows: dict[type[Any], list[Any]]) -> None:
        self._rows = rows

    def snapshot_transaction(self, operation: object) -> object:
        return operation(object())  # type: ignore[operator]

    def export_owner_rows(self, _session: object, *, owner_id: UUID, row_type: type[Any]) -> list:
        return self._rows.get(row_type, [])


def test_export_omits_generated_search_vectors_and_verifies() -> None:
    rows: dict[type[Any], list[Any]] = {}
    for source in EXPORT_SOURCES:
        if source.name in SEARCH_VECTOR_COLLECTIONS:
            rows[source.row_type] = [
                source.row_type(id=UUID("00000000-0000-7000-8000-0000000000a1"), owner_id=OWNER_ID)
            ]

    document = OwnerExportService(FakeExportStore(rows)).export(
        Actor(user_id=OWNER_ID, scopes=frozenset())
    )

    for name in SEARCH_VECTOR_COLLECTIONS:
        (row,) = document["collections"][name]
        assert "search_vector" not in row
    assert verify_export(document).collection_counts["contacts"] == 1


def test_restore_of_an_export_without_search_vectors_writes_plain_columns_only() -> None:
    contact_id = UUID("00000000-0000-7000-8000-0000000000c1")
    rows: dict[type[Any], list[Any]] = {
        ContactRow: [
            ContactRow(
                id=contact_id,
                owner_id=OWNER_ID,
                display_name="Klas Ekdahl",
                display_name_key="klas ekdahl",
                archived=False,
                version=1,
            )
        ]
    }
    document = OwnerExportService(FakeExportStore(rows)).export(
        Actor(user_id=OWNER_ID, scopes=frozenset())
    )
    target_owner = UUID("00000000-0000-7000-8000-000000000002")
    plan = build_restore_plan(document, target_owner)
    store = FakeRestoreStore()

    result = OwnerRestoreService(store).restore(
        document, target_owner_id=target_owner, expected_plan_checksum=plan.plan_checksum
    )

    assert result.imported_rows == 1
    restored = store.session.added[0]
    assert isinstance(restored, ContactRow)
    assert restored.display_name == "Klas Ekdahl"
    assert restored.owner_id == target_owner
    assert restored.search_vector is None


def domain_export_with_accent(accent: object) -> dict[str, Any]:
    """A current-head export whose single domain row carries the given accent value."""

    collections = empty_collections()
    collections["domains"] = [{**DOMAIN_ROW, "accent": accent}]
    document = build_export_document(
        OWNER_ID, collections, exported_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    )
    return reseal(document)


def test_a_current_export_with_a_forged_domain_accent_is_refused() -> None:
    document = domain_export_with_accent("neon")

    with pytest.raises(ExportRefused, match="invalid domain accent") as error:
        verify_export(document)

    # The error must not echo the rejected value back.
    assert "neon" not in str(error.value)


def test_a_domain_accent_from_the_current_head_verifies_plans_and_restores() -> None:
    document = domain_export_with_accent("green")
    target_owner = UUID("00000000-0000-7000-8000-000000000002")

    assert verify_export(document).collection_counts["domains"] == 1
    plan = build_restore_plan(document, target_owner)
    assert plan.status == "ready"
    store = FakeRestoreStore()

    result = OwnerRestoreService(store).restore(
        document, target_owner_id=target_owner, expected_plan_checksum=plan.plan_checksum
    )

    assert result.imported_rows == 1
    restored = store.session.added[0]
    assert isinstance(restored, DomainRow)
    assert restored.accent == "green"
    assert restored.owner_id == target_owner


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


def test_snapshot_transaction_sets_repeatable_read_before_anything_else() -> None:
    from sidekick.store import SqlAlchemyStore

    session = RecordingSession()

    class Factory:
        def begin(self) -> "Factory":
            return self

        def __enter__(self) -> RecordingSession:
            return session

        def __exit__(self, *_exc: object) -> None:
            return None

    store = SqlAlchemyStore(Factory())  # type: ignore[arg-type]

    assert store.snapshot_transaction(lambda s: s.statements.copy()) == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY DEFERRABLE"
    ]


def test_verify_restorable_accepts_a_closed_export_and_names_only_positions_when_it_refuses() -> (
    None
):
    assert verify_restorable(domain_event_export("unknown_future_kind")).owner_id == OWNER_ID

    document = domain_event_export("task")
    document["collections"]["task_status_history"] = [
        {
            **{column.name: None for column in TaskStatusHistoryRow.__table__.columns},
            "id": "00000000-0000-7000-8000-000000000030",
            "owner_id": str(OWNER_ID),
            "task_id": "00000000-0000-7000-8000-0000000000fe",
        }
    ]
    document["manifest"]["collection_counts"]["task_status_history"] = 1
    document["manifest"]["sha256"] = export_checksum(document)
    with pytest.raises(ExportRefused) as refused:
        verify_restorable(document)
    assert str(refused.value) == "export has unresolved references: task_status_history[0].task_id"

"""Automations in the owner export (format 9): the six collections, the ids a restore rewrites,
and what it leaves behind from the instance the export came from."""

import copy
import json
import types
import typing
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from sidekick.automations.domain.effects import CATALOGUE
from sidekick.owner_export.catalogue import (
    COLLECTIONS_ADDED_IN_FORMAT_9,
    EXPORT_SOURCES,
    SCHEMA_HEAD,
    SOURCES_BY_NAME,
    ExportRefused,
    source_fields,
)
from sidekick.owner_export.document import build_export_document, export_checksum, verify_export
from sidekick.owner_export.restore_automations import PAYLOAD_REFERENCES
from sidekick.owner_export.restore_plan import build_restore_plan, verify_restorable
from sidekick.owner_export.restore_remap import (
    foreign_key_targets,
    remapped_restore_rows,
    restore_id,
    restore_source_order,
)
from tests.support.older_export_formats import HEAD_115, as_format_8

OWNER_ID = UUID("00000000-0000-7000-8000-000000000001")
TARGET_ID = UUID("00000000-0000-7000-8000-0000000000aa")
AUTOMATION_ID = UUID("00000000-0000-7000-8000-000000000011")
RUN_ID = UUID("00000000-0000-7000-8000-000000000012")
OPEN_RUN_ID = UUID("00000000-0000-7000-8000-000000000013")
DATAPOINT_ID = UUID("00000000-0000-7000-8000-000000000014")
SUGGESTION_ID = UUID("00000000-0000-7000-8000-000000000015")
CHECK_ID = UUID("00000000-0000-7000-8000-000000000016")
PROJECT_ID = UUID("00000000-0000-7000-8000-000000000017")
APPLIED_TASK_ID = UUID("00000000-0000-7000-8000-000000000018")
GONE_DATAPOINT_ID = UUID("00000000-0000-7000-8000-000000000019")
STAMP = "2026-11-22T12:00:00+00:00"
CANARY = "canary-instruction-never-in-a-plan"


def _empty() -> dict[str, list[dict[str, object]]]:
    return {source.name: [] for source in EXPORT_SOURCES}


def _automation() -> dict[str, object]:
    return {
        "id": str(AUTOMATION_ID),
        "owner_id": str(OWNER_ID),
        "title": "Morning mail",
        "purpose": "Collect what the mail asks of me",
        "instruction": CANARY,
        "sources": ["mail"],
        "runner": "claude",
        "cadence": {},
        "allowed_effects": ["create_task"],
        "apply_mode": "suggest",
        "auto_effects": [],
        "bulk_threshold": 90,
        "auto_threshold": 95,
        "max_suggestions_per_run": 15,
        "run_budget_microusd": 1_000_000,
        "model_tier": "standard",
        "state": "active",
        "spec_digest": "a" * 64,
        "approved_digest": "a" * 64,
        "approved_at": STAMP,
        "last_run_at": STAMP,
        "version": 3,
        "created_at": STAMP,
        "updated_at": STAMP,
    }


def _run(run_id: UUID, state: str, **overrides: object) -> dict[str, object]:
    return {
        "id": str(run_id),
        "owner_id": str(OWNER_ID),
        "automation_id": str(AUTOMATION_ID),
        "occurrence_key": f"d:{run_id.hex[-4:]}",
        "attempt": 1,
        "runner": "server",
        "state": state,
        "stage": None,
        "spec_digest": "a" * 64,
        "session_digest": None,
        "credential_kind": "worker",
        "worker_id": "worker-1" if state in {"queued", "running", "checking"} else None,
        "lease_until": STAMP if state in {"queued", "running", "checking"} else None,
        "queued_at": STAMP,
        "started_at": STAMP,
        "finished_at": None if state in {"queued", "running", "checking"} else STAMP,
        "datapoint_count": 1,
        "suggestion_count": 1,
        "rejected_count": 0,
        "flagged_count": 0,
        "auto_applied_count": 0,
        "summary": None,
        "outcome": None,
        "model": None,
        "checker_model": None,
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reserved_microusd": 400_000 if state in {"queued", "running", "checking"} else 0,
        "cost_microusd": 1_200,
        "cost_source": "provider",
        "version": 2,
        "created_at": STAMP,
        "updated_at": STAMP,
        **overrides,
    }


def _datapoint() -> dict[str, object]:
    return {
        "id": str(DATAPOINT_ID),
        "owner_id": str(OWNER_ID),
        "run_id": str(RUN_ID),
        "automation_id": str(AUTOMATION_ID),
        "kind": "person",
        "fields": {"name": "Anna"},
        "source_kind": "mail",
        "source_fingerprint": "f" * 64,
        "source_label": None,
        "source_received_at": None,
        "created_at": STAMP,
        "purge_after": STAMP,
        "purged_at": None,
    }


def _suggestion(**overrides: object) -> dict[str, object]:
    return {
        "id": str(SUGGESTION_ID),
        "owner_id": str(OWNER_ID),
        "automation_id": str(AUTOMATION_ID),
        "run_id": str(RUN_ID),
        "effect": "create_task",
        "effect_version": 1,
        "payload": {"title": "Call Anna", "project_id": str(PROJECT_ID)},
        "proposed_payload": {"title": "Call Anna", "project_id": str(PROJECT_ID)},
        "rationale": None,
        "datapoint_ids": [str(DATAPOINT_ID), str(GONE_DATAPOINT_ID)],
        "dedupe_fingerprint": "e" * 64,
        "state": "applied",
        "screening_flags": [],
        "check_state": "checked",
        "verdict": "ok",
        "confidence": 97,
        "bulk_eligible": False,
        "decided_at": STAMP,
        "decided_by": "you",
        "decision_channel": "app",
        "applied_kind": "task",
        "applied_id": str(APPLIED_TASK_ID),
        "applied_version": 1,
        "undone_at": None,
        "apply_error": None,
        "expires_at": STAMP,
        "payload_purged_at": None,
        "version": 4,
        "created_at": STAMP,
        "updated_at": STAMP,
        **overrides,
    }


def _check() -> dict[str, object]:
    return {
        "id": str(CHECK_ID),
        "owner_id": str(OWNER_ID),
        "suggestion_id": str(SUGGESTION_ID),
        "run_id": str(RUN_ID),
        "attempt": 1,
        "checker": "openai_compat",
        "model": "checker",
        "verdict": "ok",
        "confidence": 97,
        "reason_codes": [],
        "checked_at": STAMP,
    }


def _cursor() -> dict[str, object]:
    return {"owner_id": str(OWNER_ID), "seen_until": STAMP, "version": 1, "updated_at": STAMP}


def _document(**collections: list[dict[str, object]]) -> dict[str, Any]:
    rows = _empty()
    rows.update(
        {
            "automations": [_automation()],
            "automation_runs": [_run(RUN_ID, "done"), _run(OPEN_RUN_ID, "running")],
            "automation_datapoints": [_datapoint()],
            "automation_suggestions": [_suggestion()],
            "automation_checks": [_check()],
            "automation_report_cursors": [_cursor()],
        }
    )
    rows.update(collections)
    return build_export_document(
        OWNER_ID, rows, exported_at=datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    )


def _reseal(document: dict[str, Any]) -> dict[str, Any]:
    document["manifest"] = {"collection_counts": document["manifest"]["collection_counts"]}
    document["manifest"]["sha256"] = export_checksum(document)
    return document


def test_the_export_catalogue_names_the_six_automation_collections() -> None:
    assert {
        "automations",
        "automation_runs",
        "automation_datapoints",
        "automation_suggestions",
        "automation_checks",
        "automation_report_cursors",
    } == COLLECTIONS_ADDED_IN_FORMAT_9
    assert set(SOURCES_BY_NAME) >= COLLECTIONS_ADDED_IN_FORMAT_9
    assert SCHEMA_HEAD >= "116_automations"


def test_every_automation_row_of_the_tests_has_exactly_the_exported_fields() -> None:
    document = _document()

    for name in COLLECTIONS_ADDED_IN_FORMAT_9:
        for row in document["collections"][name]:
            assert set(row) == set(source_fields(SOURCES_BY_NAME[name])), name
    assert verify_export(document).collection_counts["automation_runs"] == 2


def test_a_reference_to_the_automation_through_a_run_resolves_to_the_automation() -> None:
    """A datapoint and a suggestion name their automation through their run's composite key; the
    column is an automation id, not a run id."""

    assert foreign_key_targets(SOURCES_BY_NAME["automation_datapoints"])["automation_id"] == {
        "automations"
    }
    assert foreign_key_targets(SOURCES_BY_NAME["automation_suggestions"])["automation_id"] == {
        "automations"
    }
    assert foreign_key_targets(SOURCES_BY_NAME["automation_suggestions"])["run_id"] == {
        "automation_runs"
    }
    assert foreign_key_targets(SOURCES_BY_NAME["automation_checks"])["suggestion_id"] == {
        "automation_suggestions"
    }


def test_the_restore_order_puts_every_automation_collection_after_what_it_names() -> None:
    document = _document()
    order = [source.name for source in restore_source_order(document["collections"])]

    assert order.index("automations") < order.index("automation_runs")
    assert order.index("automation_runs") < order.index("automation_datapoints")
    assert order.index("automation_runs") < order.index("automation_suggestions")
    assert order.index("automation_suggestions") < order.index("automation_checks")


def test_the_plan_of_an_automation_export_is_ready_and_resolves_every_reference() -> None:
    plan = build_restore_plan(_document(), TARGET_ID)

    assert plan.status == "ready", plan.unresolved_references
    by_name = {collection.name: collection for collection in plan.collections}
    assert by_name["automation_suggestions"].row_count == 1
    assert by_name["automation_suggestions"].unresolved_reference_count == 0
    assert by_name["automation_datapoints"].unresolved_reference_count == 0


def test_a_restore_leaves_no_id_of_the_source_instance_in_any_automation_row() -> None:
    document = _document()
    rows = remapped_restore_rows(document, TARGET_ID)
    source_ids = {
        AUTOMATION_ID,
        RUN_ID,
        OPEN_RUN_ID,
        DATAPOINT_ID,
        SUGGESTION_ID,
        CHECK_ID,
        PROJECT_ID,
        APPLIED_TASK_ID,
        GONE_DATAPOINT_ID,
        OWNER_ID,
    }

    text = json.dumps({name: rows[name] for name in COLLECTIONS_ADDED_IN_FORMAT_9}, default=str)

    for old in source_ids:
        assert str(old) not in text, old
    suggestion = rows["automation_suggestions"][0]
    assert suggestion["owner_id"] == TARGET_ID
    assert suggestion["automation_id"] == restore_id(AUTOMATION_ID, TARGET_ID, "automations")
    assert suggestion["run_id"] == restore_id(RUN_ID, TARGET_ID, "automation_runs")
    assert rows["automation_checks"][0]["suggestion_id"] == suggestion["id"]
    assert rows["automation_report_cursors"][0]["owner_id"] == TARGET_ID


def test_the_ids_a_suggestion_holds_follow_the_records_they_name() -> None:
    suggestion = remapped_restore_rows(_document(), TARGET_ID)["automation_suggestions"][0]

    assert suggestion["datapoint_ids"] == [
        restore_id(DATAPOINT_ID, TARGET_ID, "automation_datapoints"),
        restore_id(GONE_DATAPOINT_ID, TARGET_ID, "automation_datapoints"),
    ]
    project = str(restore_id(PROJECT_ID, TARGET_ID, "projects"))
    assert suggestion["payload"] == {"title": "Call Anna", "project_id": project}
    assert suggestion["proposed_payload"] == {"title": "Call Anna", "project_id": project}
    assert suggestion["applied_id"] == restore_id(APPLIED_TASK_ID, TARGET_ID, "tasks")


def test_an_applied_contact_follows_its_kind() -> None:
    document = _document(
        automation_suggestions=[
            _suggestion(
                effect="create_contact", payload={"display_name": "Anna"}, applied_kind="contact"
            )
        ]
    )

    suggestion = remapped_restore_rows(document, TARGET_ID)["automation_suggestions"][0]

    assert suggestion["applied_id"] == restore_id(APPLIED_TASK_ID, TARGET_ID, "contacts")


def test_restoring_does_not_change_the_export_it_reads() -> None:
    document = _document()
    before = copy.deepcopy(document)

    remapped_restore_rows(document, TARGET_ID)
    build_restore_plan(document, TARGET_ID)

    assert document == before


def test_an_automation_is_restored_without_its_approval() -> None:
    automation = remapped_restore_rows(_document(), TARGET_ID)["automations"][0]

    assert automation["approved_digest"] is None
    assert automation["approved_at"] is None
    assert automation["spec_digest"] == "a" * 64
    assert automation["state"] == "active"
    assert automation["version"] == 3


@pytest.mark.parametrize("state", ["queued", "running", "checking"])
def test_a_run_in_progress_is_restored_as_cancelled_without_a_lease_or_reservation(
    state: str,
) -> None:
    document = _document(automation_runs=[_run(RUN_ID, "done"), _run(OPEN_RUN_ID, state)])

    run = remapped_restore_rows(document, TARGET_ID)["automation_runs"][1]

    assert run["state"] == "cancelled"
    assert run["lease_until"] is None
    assert run["worker_id"] is None
    assert run["reserved_microusd"] == 0
    assert run["finished_at"] == run["updated_at"]
    assert run["cost_microusd"] == 1_200


@pytest.mark.parametrize("state", ["done", "failed", "cancelled", "lapsed"])
def test_a_run_that_is_not_in_progress_keeps_its_state(state: str) -> None:
    document = _document(automation_runs=[_run(RUN_ID, state), _run(OPEN_RUN_ID, "done")])

    run = remapped_restore_rows(document, TARGET_ID)["automation_runs"][0]

    assert run["state"] == state
    assert run["finished_at"] == datetime.fromisoformat(STAMP)


def test_the_plan_warns_in_counts_about_what_it_does_not_carry_over() -> None:
    plan = build_restore_plan(_document(), TARGET_ID)

    assert "1 approved automation(s) are not restored as approved" in " ".join(plan.warnings)
    assert "1 queued or running automation run(s) are restored as cancelled" in " ".join(
        plan.warnings
    )


def test_an_export_without_automations_has_no_automation_warning() -> None:
    document = build_export_document(
        OWNER_ID, _empty(), exported_at=datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    )

    assert not any(
        "automation" in warning for warning in build_restore_plan(document, TARGET_ID).warnings
    )


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"datapoint_ids": ["not-an-id"]}, "datapoint_ids"),
        ({"datapoint_ids": None}, "datapoint_ids"),
        ({"payload": {"title": "x", "project_id": "nope"}}, "payload.project_id"),
        ({"proposed_payload": {"title": "x", "project_id": 7}}, "proposed_payload.project_id"),
    ],
)
def test_a_suggestion_with_an_id_that_is_not_an_id_is_refused_by_position_and_field(
    override: dict[str, object], field: str
) -> None:
    document = _document(automation_suggestions=[_suggestion(**override)])

    with pytest.raises(ExportRefused) as refused:
        build_restore_plan(document, TARGET_ID)
    with pytest.raises(ExportRefused):
        verify_restorable(document)

    assert str(refused.value) == (
        f"export has an invalid reference: automation_suggestions[0]: {field}"
    )


def test_the_text_of_an_automation_never_reaches_a_plan_or_a_refusal() -> None:
    document = _document(
        automation_suggestions=[_suggestion(payload={"title": CANARY, "project_id": "nope"})]
    )

    with pytest.raises(ExportRefused) as refused:
        build_restore_plan(document, TARGET_ID)

    assert CANARY not in str(refused.value)
    assert CANARY not in json.dumps(build_restore_plan(_document(), TARGET_ID).as_dict())


def test_an_automation_row_of_another_owner_is_refused() -> None:
    other = _automation() | {"owner_id": str(TARGET_ID)}
    document = _document(automations=[other])

    with pytest.raises(ExportRefused, match="crosses the owner boundary"):
        verify_export(document)


@pytest.mark.parametrize(
    "head",
    [HEAD_115, "116_automations", "117_journal_attachments", "124_journal_attachment_details"],
)
def test_a_format_8_export_is_read_and_restores_without_automations(head: str) -> None:
    older = as_format_8(_document(), head)

    assert older["format_version"] == 8
    assert not COLLECTIONS_ADDED_IN_FORMAT_9 & set(older["collections"])
    verify_export(older)
    plan = build_restore_plan(older, TARGET_ID)
    assert plan.status == "ready"
    rows = remapped_restore_rows(older, TARGET_ID)
    assert all(rows[name] == [] for name in COLLECTIONS_ADDED_IN_FORMAT_9)


@pytest.mark.parametrize("name", sorted(COLLECTIONS_ADDED_IN_FORMAT_9))
def test_a_format_8_export_cannot_carry_an_automation_collection(name: str) -> None:
    older = as_format_8(_document(), "116_automations")
    older["collections"][name] = []
    older["manifest"]["collection_counts"][name] = 0

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(_reseal(older))


@pytest.mark.parametrize("name", sorted(COLLECTIONS_ADDED_IN_FORMAT_9))
def test_a_current_export_must_carry_every_automation_collection(name: str) -> None:
    document = _document()
    del document["collections"][name]
    del document["manifest"]["collection_counts"][name]

    with pytest.raises(ExportRefused, match="collection catalogue does not match"):
        verify_export(_reseal(document))


def _uuid_field_names(model: Any) -> set[str]:
    names: set[str] = set()
    for name, field in model.model_fields.items():
        annotation = field.annotation
        arguments = (
            typing.get_args(annotation)
            if isinstance(annotation, types.UnionType)
            else (annotation,)
        )
        if UUID in arguments:
            names.add(name)
    return names


def test_every_id_field_of_an_effect_payload_is_one_a_restore_rewrites() -> None:
    """A new effect that names another record must say which collection it points at, or a restore
    would carry the id of the source instance into the target."""

    assert set(PAYLOAD_REFERENCES) == {kind.value for kind in CATALOGUE}
    for kind, entry in CATALOGUE.items():
        assert _uuid_field_names(entry.model) == set(PAYLOAD_REFERENCES[kind.value]), kind
        for collection in PAYLOAD_REFERENCES[kind.value].values():
            assert collection in SOURCES_BY_NAME


@pytest.mark.parametrize(("state", "check_state"), [("received", "off"), ("checking", "queued")])
def test_a_suggestion_still_being_checked_is_restored_as_pending_with_a_failed_check(
    state: str, check_state: str
) -> None:
    """Nothing on the new instance would finish the check; a suggestion left in `received` or
    `checking` would never be shown and its fingerprint would block the same proposal."""

    unfinished = _suggestion(
        state=state,
        check_state=check_state,
        verdict=None,
        confidence=None,
        decided_at=None,
        decided_by=None,
        decision_channel=None,
        applied_kind=None,
        applied_id=None,
        applied_version=None,
    )
    document = _document(automation_suggestions=[unfinished])

    suggestion = remapped_restore_rows(document, TARGET_ID)["automation_suggestions"][0]

    assert (suggestion["state"], suggestion["check_state"]) == ("pending", "failed")
    assert (suggestion["verdict"], suggestion["confidence"]) == (None, None)


@pytest.mark.parametrize("state", ["pending", "applied", "dismissed", "expired", "undone"])
def test_a_decided_or_pending_suggestion_keeps_its_state(state: str) -> None:
    document = _document(automation_suggestions=[_suggestion(state=state)])

    suggestion = remapped_restore_rows(document, TARGET_ID)["automation_suggestions"][0]

    assert (suggestion["state"], suggestion["check_state"]) == (state, "checked")

"""The replay record an idempotent operation may store: identifiers only, never free text."""

import pytest

from sidekick.shared.persistence.stores.base import (
    IDEMPOTENCY_RETENTION,
    MAX_REPLAY_RECORD_BYTES,
    ReplayRecordError,
    StoreBase,
)
from sidekick.shared.replay import id_replay_record, items_replay_record

ID = "0192f1a0-0000-7000-8000-000000000001"
SECRET = "Hemlig titel Zxqv"


def test_retention_is_thirty_days() -> None:
    assert IDEMPOTENCY_RETENTION.days == 30


def test_the_cap_holds_the_largest_batch_a_write_records() -> None:
    # A board-column reorder of 100 Tasks keeps an id, a rank and a version each.
    placements = [{"task_id": ID, "board_rank": 100, "version": 1000}] * 100

    record = StoreBase.replay_record("reorder_board_column", {"items": placements}, None)

    assert record == {"items": placements}
    assert MAX_REPLAY_RECORD_BYTES == 16 * 1024


def test_a_projection_reduces_the_result_to_identifiers() -> None:
    result = {"id": ID, "display_name": SECRET, "version": 3, "archived": False}

    record = StoreBase.replay_record(
        "create_contact", result, lambda full: {"id": full["id"], "version": full["version"]}
    )

    assert record == {"id": ID, "version": 3}
    assert SECRET not in str(record)


def test_the_shared_projections_keep_only_ids() -> None:
    task = {"id": ID, "title": SECRET, "status": "todo"}

    assert id_replay_record(task) == {"id": ID}
    assert items_replay_record({"items": [task, task]}) == {"items": [{"id": ID}, {"id": ID}]}
    assert items_replay_record({"runs": [task]}, "runs") == {"runs": [{"id": ID}]}
    assert SECRET not in str(StoreBase.replay_record("create_task", task, id_replay_record))


def test_an_allow_listed_identity_operation_stores_its_identifier_result() -> None:
    result = {"entry_id": ID}

    assert StoreBase.replay_record("create_manual_journal_entry", result, None) == result


@pytest.mark.parametrize(
    "operation", ["brand_new_operation", "create_task", "update_project", "shopping.add_items"]
)
def test_an_operation_without_a_projection_or_allow_list_entry_is_refused(
    operation: str,
) -> None:
    with pytest.raises(ReplayRecordError):
        StoreBase.replay_record(operation, {"id": ID}, None)


def test_the_full_result_of_a_former_legacy_operation_is_not_stored() -> None:
    """Every task, project, shopping and trash result used to be kept whole; it no longer can be."""

    with pytest.raises(ReplayRecordError):
        StoreBase.replay_record("create_task", {"id": ID, "title": SECRET}, None)
    with pytest.raises(ReplayRecordError):
        StoreBase.replay_record(
            "shopping.add_items", {"id": ID}, lambda full: {**full, "name": SECRET}
        )


def test_free_text_in_a_projection_or_identity_result_is_refused() -> None:
    with pytest.raises(ReplayRecordError):
        StoreBase.replay_record("create_contact", {"id": ID, "name": SECRET}, lambda full: full)
    with pytest.raises(ReplayRecordError):
        StoreBase.replay_record("create_manual_journal_entry", {"entry_id": SECRET}, None)


def test_an_oversized_record_is_refused() -> None:
    ids = [ID] * (MAX_REPLAY_RECORD_BYTES // len(ID) + 10)

    with pytest.raises(ReplayRecordError):
        StoreBase.replay_record("create_contact", {"ids": ids}, lambda full: full)

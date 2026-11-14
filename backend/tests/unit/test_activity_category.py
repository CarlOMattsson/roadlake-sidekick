"""The category a recorded Task operation is filed under; a pure mapping, no framework."""

import pytest

from sidekick.activity.domain import ActivityCategory, category_for_operation


@pytest.mark.parametrize(
    ("operation", "changed_fields", "expected"),
    [
        ("create_task", None, ActivityCategory.TASK_CREATE),
        ("update_task", None, ActivityCategory.TASK_UPDATE),
        ("update_task", frozenset({"title"}), ActivityCategory.TASK_UPDATE),
        ("update_task", frozenset({"status", "title"}), ActivityCategory.TASK_STATUS_CHANGE),
        ("update_task", frozenset({"project_id"}), ActivityCategory.PROJECT_CHANGES),
        ("complete_task", frozenset({"status"}), ActivityCategory.TASK_MAINTENANCE),
        ("run_process", None, ActivityCategory.TASK_MAINTENANCE),
    ],
)
def test_an_operation_is_filed_under_its_category(
    operation: str, changed_fields: frozenset[str] | None, expected: ActivityCategory
) -> None:
    assert category_for_operation(operation, changed_fields) is expected

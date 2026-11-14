"""Activity vocabulary: the categories an activity entry is filed under.

Pure values, so any context's application layer can label the activity it records without
importing the activity application layer.
"""

from enum import StrEnum


class ActivityCategory(StrEnum):
    TASK_MAINTENANCE = "task_maintenance"
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    TASK_STATUS_CHANGE = "task_status_change"
    PROJECT_CHANGES = "project_changes"


def category_for_operation(
    operation: str, changed_fields: frozenset[str] | None = None
) -> ActivityCategory:
    """The category a recorded Task operation is filed under."""

    if operation == "create_task":
        return ActivityCategory.TASK_CREATE
    if operation == "update_task":
        fields = changed_fields or frozenset()
        if "status" in fields:
            return ActivityCategory.TASK_STATUS_CHANGE
        if "project_id" in fields:
            return ActivityCategory.PROJECT_CHANGES
        return ActivityCategory.TASK_UPDATE
    return ActivityCategory.TASK_MAINTENANCE

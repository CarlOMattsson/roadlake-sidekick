"""Automation policy vocabulary: the policy modes and the categories activity is filed under.

Pure values, so any context's application layer can label the activity it records without
importing the automation application layer.
"""

from enum import StrEnum


class AutomationPolicyMode(StrEnum):
    REVIEW = "review"
    AUTO_REVERSIBLE = "auto_reversible"
    DISABLED = "disabled"


class AutomationCategory(StrEnum):
    TASK_MAINTENANCE = "task_maintenance"
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    TASK_STATUS_CHANGE = "task_status_change"
    RELATIONS = "relations"
    PROJECT_CHANGES = "project_changes"
    CONTACT_CHANGES = "contact_changes"
    JOURNAL_CHANGES = "journal_changes"
    ARCHIVE_OR_DELETE = "archive_or_delete"
    EXTERNAL_EFFECTS = "external_effects"


def category_for_operation(
    operation: str, changed_fields: frozenset[str] | None = None
) -> AutomationCategory:
    """Map a typed proposal operation to the smallest policy bucket."""

    if operation == "create_task":
        return AutomationCategory.TASK_CREATE
    if operation == "update_task":
        fields = changed_fields or frozenset()
        if "status" in fields:
            return AutomationCategory.TASK_STATUS_CHANGE
        if "project_id" in fields:
            return AutomationCategory.PROJECT_CHANGES
        return AutomationCategory.TASK_UPDATE
    if operation.startswith("link_"):
        return AutomationCategory.RELATIONS
    if operation.startswith("create_project"):
        return AutomationCategory.PROJECT_CHANGES
    if operation.startswith("create_contact"):
        return AutomationCategory.CONTACT_CHANGES
    if operation.startswith("create_journal"):
        return AutomationCategory.JOURNAL_CHANGES
    if operation.startswith("archive") or operation.startswith("delete"):
        return AutomationCategory.ARCHIVE_OR_DELETE
    return AutomationCategory.TASK_MAINTENANCE

"""`PartialChanges`: null is "not sent", `clear` empties, and the two never overlap."""

import pytest

from sidekick.shared.errors import FieldValidationError
from sidekick.structured.shopping import ItemPatchInput
from sidekick.structured.work_records import ProjectChanges, TaskChanges


def test_nulls_are_not_sent_and_are_reported_in_declaration_order() -> None:
    changes = TaskChanges.model_validate({"tags": [], "due_at": None, "title": None})

    assert changes.model_fields_set == {"tags"}
    assert changes.ignored_nulls == ["title", "due_at"]


def test_clear_makes_a_field_sent_with_no_value_and_drops_it_from_the_ignored_nulls() -> None:
    changes = TaskChanges.model_validate({"title": "Paint", "project_id": None, "due_at": None})

    changes.resolve(["project_id"])

    assert changes.model_dump(exclude_unset=True) == {"title": "Paint", "project_id": None}
    assert changes.ignored_nulls == ["due_at"]


def test_a_field_given_a_value_and_cleared_is_refused_by_name() -> None:
    changes = TaskChanges(title="Paint", description="Two coats")

    with pytest.raises(FieldValidationError) as refused:
        changes.resolve(["description"])

    assert refused.value.rows == ("changes.description: also named in clear",)


def test_nothing_sent_is_refused_unless_the_update_allows_it() -> None:
    with pytest.raises(FieldValidationError):
        TaskChanges.model_validate({"due_at": None}).resolve()

    ItemPatchInput.model_validate({"note": None}).resolve()


def test_the_companion_reading_clears_a_clearable_field_and_ignores_the_rest() -> None:
    changes = ProjectChanges.from_sent({"description": None, "title": None, "status": "active"})

    assert changes.model_dump(exclude_unset=True) == {"description": None, "status": "active"}


def test_tags_and_fixed_fields_cannot_be_cleared() -> None:
    clearable = TaskChanges.clearable_fields()

    assert "tags" not in clearable
    assert not set(TaskChanges.fixed_fields) & set(clearable)

"""The Journal analysis models reuse the owning contexts' enums instead of copying them."""

from sidekick.journal.domain import analysis, entry
from sidekick.tasks.domain import Priority, TaskStatus


def test_analysis_models_use_the_entry_and_task_enums() -> None:
    assert analysis.KeyPointKind is entry.KeyPointKind
    assert analysis.TaskStatus is TaskStatus


def test_task_priority_values_match_the_task_context() -> None:
    # `TaskPriority` stays a separate class so the published schema title does not change.
    assert [member.value for member in analysis.TaskPriority] == [
        member.value for member in Priority
    ]
    assert [member.name for member in analysis.TaskPriority] == [member.name for member in Priority]

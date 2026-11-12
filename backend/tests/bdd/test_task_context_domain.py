from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sidekick.shared.errors import ValidationError
from sidekick.tasks.domain import Priority, Task, TaskStatus


def _task(**overrides: object) -> Task:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "id": uuid4(),
        "owner_id": uuid4(),
        "project_id": None,
        "title": "Capture",
        "description": None,
        "status": TaskStatus.TODO,
        "priority": Priority.NORMAL,
        "due_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Task(**values)  # type: ignore[arg-type]


def test_task_can_select_one_context_or_stay_standalone() -> None:
    assert _task().domain_id is None
    assert _task(domain_id=uuid4()).domain_id
    assert _task(process_id=uuid4()).process_id
    assert _task(project_id=uuid4()).project_id


def test_task_rejects_competing_contexts() -> None:
    with pytest.raises(ValidationError, match="at most one"):
        _task(domain_id=uuid4(), project_id=uuid4())


def test_task_update_rejects_context_collision() -> None:
    task = _task(domain_id=uuid4())
    with pytest.raises(ValidationError, match="at most one"):
        task.update(now=datetime.now(UTC), process_id=uuid4())

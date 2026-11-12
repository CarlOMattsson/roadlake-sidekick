from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sidekick.shared.errors import ValidationError
from sidekick.tasks.domain import TaskStatus
from sidekick.work.domain import Action, ActionStatus, Step


def test_step_keeps_semantic_position_and_version() -> None:
    now = datetime.now(UTC)
    step = Step(uuid4(), uuid4(), uuid4(), "Plan", TaskStatus.TODO, 0, None, False, now, now)
    updated = step.update(now=now, status=TaskStatus.IN_PROGRESS)
    assert updated.position == 0
    assert updated.version == 2


def test_action_requires_step_and_has_display_order_only() -> None:
    now = datetime.now(UTC)
    action = Action(uuid4(), uuid4(), uuid4(), "Call", ActionStatus.OPEN, 2, None, False, now, now)
    assert action.complete(now=now).status is ActionStatus.COMPLETED


@pytest.mark.parametrize("position", [-1])
def test_negative_positions_are_rejected(position: int) -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        Step(uuid4(), uuid4(), uuid4(), "Plan", TaskStatus.TODO, position, None, False, now, now)

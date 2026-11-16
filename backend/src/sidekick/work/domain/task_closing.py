"""What completing a Task does to its Steps and Actions, and what reopening it undoes.

Completing a Task completes its open Steps and their open Actions at the same instant. A Step or
Action that was already done keeps its own time, so a reopening can tell what the completion
closed (done at the Task's completion time) from what was done before it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sidekick.shared.types import UNSET
from sidekick.tasks.domain import TaskStatus
from sidekick.work.domain.ai_spec import Performer
from sidekick.work.domain.steps import Action, ActionStatus, Step


@dataclass(frozen=True, slots=True)
class StepsChanged:
    """The new versions of the Steps and Actions a completion or reopening changed."""

    steps: tuple[Step, ...] = ()
    actions: tuple[Action, ...] = ()


def close_with_task(
    steps: Sequence[Step], actions_by_step: Mapping[UUID, Sequence[Action]], *, now: datetime
) -> StepsChanged:
    """The open Steps completed, and the open Actions of those Steps.

    A Step that is already done is left as it is, with its Actions. An AI Step no longer waits
    for the owner's attention, since the Task it belongs to is done.
    """

    closed_steps: list[Step] = []
    closed_actions: list[Action] = []
    for step in steps:
        if step.status is TaskStatus.COMPLETED:
            continue
        closed_steps.append(
            step.update(
                now=now,
                status=TaskStatus.COMPLETED,
                attention_requested=False if step.performer is Performer.AI else UNSET,
            )
        )
        closed_actions.extend(
            action.complete(now=now)
            for action in actions_by_step.get(step.id, ())
            if action.status is ActionStatus.OPEN
        )
    return StepsChanged(tuple(closed_steps), tuple(closed_actions))


def reopen_with_task(
    steps: Sequence[Step],
    actions_by_step: Mapping[UUID, Sequence[Action]],
    *,
    completed_at: datetime,
    now: datetime,
) -> StepsChanged:
    """The Steps and Actions that were done at `completed_at` opened again.

    What was done earlier, or later by hand, stays done. Without a record of their earlier
    status the Steps come back as to do.
    """

    reopened_steps: list[Step] = []
    reopened_actions: list[Action] = []
    for step in steps:
        if step.status is not TaskStatus.COMPLETED or step.completed_at != completed_at:
            continue
        reopened_steps.append(step.update(now=now, status=TaskStatus.TODO))
        reopened_actions.extend(
            action.update(now=now, status=ActionStatus.OPEN)
            for action in actions_by_step.get(step.id, ())
            if action.status is ActionStatus.COMPLETED and action.updated_at == completed_at
        )
    return StepsChanged(tuple(reopened_steps), tuple(reopened_actions))


def reset_for_next_run(
    steps: Sequence[Step], actions_by_step: Mapping[UUID, Sequence[Action]], *, now: datetime
) -> StepsChanged:
    """Every Step to do again and every Action open again, for a repeating Task's next run.

    An AI Step no longer waits for the owner's attention: the run it was waiting on belongs
    to the run of the Task that just ended.
    """

    reset_steps: list[Step] = []
    reset_actions: list[Action] = []
    for step in steps:
        fresh = step.update(
            now=now,
            status=TaskStatus.TODO,
            attention_requested=False if step.performer is Performer.AI else UNSET,
        )
        if fresh is not step:
            reset_steps.append(fresh)
        reset_actions.extend(
            action.update(now=now, status=ActionStatus.OPEN)
            for action in actions_by_step.get(step.id, ())
            if action.status is ActionStatus.COMPLETED
        )
    return StepsChanged(tuple(reset_steps), tuple(reset_actions))

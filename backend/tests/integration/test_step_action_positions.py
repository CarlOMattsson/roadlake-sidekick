"""Step and Action positions: allocated atomically per parent, unique among live siblings."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

from sidekick.api.app import Container, create_container
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.types import Actor
from sidekick.work.application import steps_service
from sidekick.work.domain import Action, Step
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"tasks:read", "tasks:write"})
WORKERS = 8


def _harness(username: str) -> tuple[Container, Actor, UUID]:
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user(username, "Position Owner")
    actor = Actor(user_id, SCOPES)
    task = container.tasks.create(actor, title="Ordered task", idempotency_key=f"{username}-task")
    return container, actor, task.id


def _step_positions(container: Container, actor: Actor, task_id: UUID) -> list[int]:
    return [step.position for step in container.steps.list_steps(actor, task_id).items]


def _action_positions(container: Container, actor: Actor, step_id: UUID) -> list[int]:
    return [action.position for action in container.steps.list_actions(actor, step_id).items]


def _new_step(container: Container, actor: Actor, task_id: UUID, name: str) -> Step:
    return container.steps.create_step(
        actor, task_id, title=name, idempotency_key=f"create-step-{name}"
    )


def _new_action(container: Container, actor: Actor, step_id: UUID, name: str) -> Action:
    return container.steps.create_action(
        actor, step_id, title=name, idempotency_key=f"create-action-{name}"
    )


@pytest.mark.integration
def test_new_step_never_reuses_a_position_after_an_earlier_step_is_archived() -> None:
    container, actor, task_id = _harness("pos-steps-archive")
    first, second, third = (_new_step(container, actor, task_id, n) for n in "abc")
    container.steps.archive_step(
        actor, second.id, version=second.version, idempotency_key="archive-step-b"
    )

    fourth = _new_step(container, actor, task_id, "d")

    live = _step_positions(container, actor, task_id)
    assert len(set(live)) == len(live) == 3
    assert fourth.position > max(first.position, third.position)


@pytest.mark.integration
def test_restored_step_does_not_share_a_position_with_a_live_sibling() -> None:
    container, actor, task_id = _harness("pos-steps-restore")
    steps = [_new_step(container, actor, task_id, n) for n in "abc"]
    archived = container.steps.archive_step(
        actor, steps[1].id, version=steps[1].version, idempotency_key="archive-step-b"
    )
    # Renumbering the live steps makes room for position 1 to be taken by another step.
    live = container.steps.list_steps(actor, task_id).items
    container.steps.reorder_steps(
        actor,
        task_id,
        items=[(step.id, step.version) for step in reversed(live)],
        idempotency_key="reorder-steps-1",
    )
    container.steps.restore_step(
        actor, archived.id, version=archived.version, idempotency_key="restore-step-b"
    )

    positions = _step_positions(container, actor, task_id)

    assert len(positions) == 3
    assert len(set(positions)) == 3


@pytest.mark.integration
def test_reorder_steps_persists_the_new_order() -> None:
    container, actor, task_id = _harness("pos-steps-reorder")
    steps = [_new_step(container, actor, task_id, n) for n in "abc"]

    container.steps.reorder_steps(
        actor,
        task_id,
        items=[(step.id, step.version) for step in reversed(steps)],
        idempotency_key="reorder-steps-2",
    )

    listed = container.steps.list_steps(actor, task_id).items
    assert [step.id for step in listed] == [step.id for step in reversed(steps)]
    assert [step.position for step in listed] == [0, 1, 2]


@pytest.mark.integration
def test_reorder_actions_persists_the_new_order() -> None:
    container, actor, task_id = _harness("pos-actions-reorder")
    step = _new_step(container, actor, task_id, "parent")
    actions = [_new_action(container, actor, step.id, n) for n in "abc"]

    container.steps.reorder_actions(
        actor,
        step.id,
        items=[(action.id, action.version) for action in reversed(actions)],
        idempotency_key="reorder-actions-1",
    )

    listed = container.steps.list_actions(actor, step.id).items
    assert [action.id for action in listed] == [action.id for action in reversed(actions)]
    assert [action.position for action in listed] == [0, 1, 2]


@pytest.mark.integration
def test_new_action_never_reuses_a_position_and_restore_stays_unique() -> None:
    container, actor, task_id = _harness("pos-actions-archive")
    step = _new_step(container, actor, task_id, "parent")
    actions = [_new_action(container, actor, step.id, n) for n in "abc"]
    archived = container.steps.archive_action(
        actor, actions[1].id, version=actions[1].version, idempotency_key="archive-action-b"
    )
    fourth = _new_action(container, actor, step.id, "d")
    assert fourth.position > max(actions[0].position, actions[2].position)

    live = container.steps.list_actions(actor, step.id).items
    container.steps.reorder_actions(
        actor,
        step.id,
        items=[(action.id, action.version) for action in reversed(live)],
        idempotency_key="reorder-actions-2",
    )
    container.steps.restore_action(
        actor, archived.id, version=archived.version, idempotency_key="restore-action-b"
    )

    positions = _action_positions(container, actor, step.id)
    assert len(positions) == 4
    assert len(set(positions)) == 4


def _concurrently(count: int, create: Callable[[int], object]) -> None:
    with ThreadPoolExecutor(max_workers=count) as pool:
        for future in [pool.submit(create, index) for index in range(count)]:
            future.result()


@pytest.mark.integration
def test_concurrent_step_creates_get_distinct_positions() -> None:
    container, actor, task_id = _harness("pos-steps-race")

    _concurrently(WORKERS, lambda i: _new_step(container, actor, task_id, f"s{i}"))

    assert sorted(_step_positions(container, actor, task_id)) == list(range(WORKERS))


@pytest.mark.integration
def test_concurrent_action_creates_get_distinct_positions() -> None:
    container, actor, task_id = _harness("pos-actions-race")
    step = _new_step(container, actor, task_id, "parent")

    _concurrently(WORKERS, lambda i: _new_action(container, actor, step.id, f"a{i}"))

    assert sorted(_action_positions(container, actor, step.id)) == list(range(WORKERS))


@pytest.mark.integration
def test_steps_and_actions_are_paged_by_cursor_in_display_order() -> None:
    container, actor, task_id = _harness("pos-paging")
    steps = [_new_step(container, actor, task_id, n) for n in "abcde"]
    actions = [_new_action(container, actor, steps[0].id, n) for n in "abcde"]

    step_pages = [container.steps.list_steps(actor, task_id, limit=2)]
    while step_pages[-1].next_cursor:
        step_pages.append(
            container.steps.list_steps(actor, task_id, limit=2, cursor=step_pages[-1].next_cursor)
        )
    action_pages = [container.steps.list_actions(actor, steps[0].id, limit=2)]
    while action_pages[-1].next_cursor:
        action_pages.append(
            container.steps.list_actions(
                actor, steps[0].id, limit=2, cursor=action_pages[-1].next_cursor
            )
        )

    assert [len(page.items) for page in step_pages] == [2, 2, 1]
    assert [step.id for page in step_pages for step in page.items] == [s.id for s in steps]
    assert [len(page.items) for page in action_pages] == [2, 2, 1]
    assert [a.id for page in action_pages for a in page.items] == [a.id for a in actions]


@pytest.mark.integration
def test_reorder_steps_covers_a_task_with_more_than_one_page_of_steps() -> None:
    container, actor, task_id = _harness("pos-steps-reorder-many")
    steps = [_new_step(container, actor, task_id, f"{n:03d}") for n in range(120)]

    reordered = container.steps.reorder_steps(
        actor,
        task_id,
        items=[(step.id, step.version) for step in reversed(steps)],
        idempotency_key="reorder-steps-many",
    )

    expected = [step.id for step in reversed(steps)]
    assert [step.id for step in reordered.items] == expected
    listed: list[Step] = []
    cursor: str | None = None
    while True:
        page = container.steps.list_steps(actor, task_id, cursor=cursor)
        listed.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert [step.id for step in listed] == expected
    positions = [step.position for step in listed]
    assert positions == sorted(set(positions))


@pytest.mark.integration
def test_reorder_steps_refuses_a_task_with_more_steps_than_one_call_can_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(steps_service, "MAX_REORDER_STEPS", 4)
    container, actor, task_id = _harness("pos-steps-reorder-cap")
    steps = [_new_step(container, actor, task_id, f"{n}") for n in range(5)]

    with pytest.raises(InvalidInputError):
        container.steps.reorder_steps(
            actor,
            task_id,
            items=[(step.id, step.version) for step in steps],
            idempotency_key="reorder-steps-cap",
        )

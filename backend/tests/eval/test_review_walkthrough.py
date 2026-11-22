"""Going through 120 open Tasks by voice stays cheap, resumable and safe against concurrent edits.

The scripted owner of `walker.py` runs the real MCP server in process, with the in-process memory
provider. What is measured: tool calls, characters per read, a walk that stops and resumes, a stale
version in the middle, and a Project with more Tasks than one save takes.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from sidekick.tasks.application.models import MAX_REVIEW_DECISIONS, UpdateTaskCommand
from sidekick.tasks.application.review import MAX_REVIEW_PAGE
from sidekick.tasks.domain import TaskStatus
from tests.eval.scenario import PER_BUCKET, Scenario, seed_main, seed_project
from tests.eval.walker import Walker, connect

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# The whole walk, counting reads and saves: one save per five decisions is the guide's own pace.
MAX_CALLS = 30
MAX_READ_CHARACTERS = 4_000
INTERRUPTED_AT = 47


def _versions(rows: list[dict[str, object]]) -> dict[str, int]:
    return {str(row["id"]): int(str(row["version"])) for row in rows}


def _assert_each_decided_once(scenario: Scenario, before: dict[str, int]) -> None:
    """Every Task has been through exactly one write: one more version, none twice."""

    for task_id, version in before.items():
        task = scenario.container.tasks.get(scenario.actor, UUID(task_id))
        assert task.version == version + 1, task.title
        assert task.last_reviewed_at is not None


async def test_the_whole_list_is_gone_through_in_at_most_30_calls() -> None:
    scenario = seed_main("eval-whole")
    async with connect(scenario) as client:
        walker = Walker(client)
        queue = await walker.order()
        assert len(queue) == sum(PER_BUCKET.values())
        for bucket, count in PER_BUCKET.items():
            assert sum(row["bucket"] == bucket for row in queue) == count
        before = _versions(queue)

        decided = await walker.walk()

        remaining = await walker.order()
    assert decided == len(queue)
    assert remaining == []
    assert walker.calls <= MAX_CALLS, (walker.calls, walker.reads, walker.saves)
    assert max(walker.reads) <= MAX_READ_CHARACTERS, walker.reads
    assert sorted(walker.saved_ids) == sorted(before)
    _assert_each_decided_once(scenario, before)
    likely_done = [row for row in queue if row["bucket"] == "likely_done"]
    for row in likely_done:
        assert (
            scenario.container.tasks.get(scenario.actor, UUID(row["id"])).status
            is TaskStatus.COMPLETED
        )


async def test_a_walk_stopped_at_47_resumes_at_48_without_a_repeat() -> None:
    scenario = seed_main("eval-resume")
    async with connect(scenario) as first:
        queue = await Walker(first).order()
    before = _versions(queue)
    async with connect(scenario) as client:
        interrupted = Walker(client)
        assert await interrupted.walk(stop_after=INTERRUPTED_AT) == INTERRUPTED_AT
    assert interrupted.saved_ids == [row["id"] for row in queue[:INTERRUPTED_AT]]

    async with connect(scenario) as client:
        resumed = Walker(client)
        head = await resumed.read(scope="all", limit=MAX_REVIEW_PAGE)
        assert head["tasks"][0]["id"] == queue[INTERRUPTED_AT]["id"]
        assert head["remaining_total"] == len(queue) - INTERRUPTED_AT
        await resumed.walk()

    assert [*interrupted.saved_ids, *resumed.saved_ids] == [row["id"] for row in queue]
    _assert_each_decided_once(scenario, before)


async def test_a_stale_version_in_the_middle_is_refused_and_read_again() -> None:
    scenario = seed_main("eval-stale")
    async with connect(scenario) as client:
        walker = Walker(client)
        page = await walker.read(scope="all", limit=MAX_REVIEW_PAGE)
        rows = page["tasks"][:10]
        edited = rows[7]
        scenario.container.tasks.update(
            scenario.actor,
            UUID(edited["id"]),
            version=edited["version"],
            idempotency_key=f"eval-{uuid4().hex}",
            command=UpdateTaskCommand(title="Ändrad på telefonen"),
        )

        refused = await walker.save(rows)

        assert refused.is_error
        assert refused.structured_content is not None
        assert refused.structured_content["reason"] == "stale_version"
        assert walker.saved_ids == []
        again = await walker.read(scope="all", limit=MAX_REVIEW_PAGE)
        assert again["remaining_total"] == page["remaining_total"]
        assert [row["id"] for row in again["tasks"]] == [row["id"] for row in page["tasks"]]
        fresh = again["tasks"][:10]
        assert fresh[7]["version"] == edited["version"] + 1
        assert fresh[7]["title"] == "Ändrad på telefonen"

        saved = await walker.save(fresh)

    assert not saved.is_error, saved.structured_content
    assert walker.saved_ids == [row["id"] for row in fresh]
    assert walker.calls == 4


async def test_23_tasks_of_one_project_take_one_read_and_two_saves() -> None:
    in_project, loose = 23, 7
    scenario = seed_project("eval-project", in_project=in_project, loose=loose)
    async with connect(scenario) as client:
        walker = Walker(client)
        page = await walker.read(scope="all", limit=MAX_REVIEW_PAGE)
        project_rows = [row for row in page["tasks"] if row["project_title"] == "Altanen"]
        assert len(project_rows) == in_project, "the Project's Tasks come together on one page"
        assert [row["project_title"] for row in page["tasks"][:in_project]] == [
            "Altanen"
        ] * in_project

        first = await walker.save(project_rows[:MAX_REVIEW_DECISIONS])
        second = await walker.save(project_rows[MAX_REVIEW_DECISIONS:])

    assert not first.is_error and not second.is_error
    assert walker.saves == [MAX_REVIEW_DECISIONS, in_project - MAX_REVIEW_DECISIONS]
    assert walker.calls == 3

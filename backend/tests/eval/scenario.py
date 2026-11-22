"""A long, untended list of open Tasks, seeded the way a review of many Tasks meets it.

The clock of the Task service is movable: Tasks are created "long ago" and the review then runs at
`NOW`, so an overdue Task is overdue by the right number of days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sidekick.api.app import Container, create_container
from sidekick.shared.types import Actor
from sidekick.tasks.application.models import NewTaskItem, UpdateTaskCommand
from sidekick.tasks.domain import Priority
from tests.db import database_factory
from tests.support.settings import make_settings

ZONE = ZoneInfo("Europe/Stockholm")
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=ZONE)
LONG_AGO = NOW - timedelta(days=90)
SCOPES = frozenset({"tasks:read", "tasks:write", "projects:read", "projects:write"})

# The 120 Tasks of the main scenario, per bucket of the review queue.
PER_BUCKET = {
    "likely_done": 10,
    "long_overdue": 25,
    "follow_up_due": 15,
    "overdue": 30,
    "other": 40,
}
BATCH = 20
PROJECT_TITLE = "Altanen"


class MovableClock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


@dataclass(frozen=True, slots=True)
class Scenario:
    container: Container
    actor: Actor
    project_id: UUID


def _key() -> str:
    return f"eval-{uuid4().hex}"


def _items(
    prefix: str,
    count: int,
    *,
    due_at: datetime | None = None,
    steps: tuple[str, ...] = (),
    project_id: UUID | None = None,
) -> list[NewTaskItem]:
    return [
        NewTaskItem(f"{prefix} {number}", due_at, Priority.NORMAL, (), steps, project_id=project_id)
        for number in range(1, count + 1)
    ]


def _create(scenario: Scenario, items: list[NewTaskItem]) -> list[UUID]:
    """Create the Tasks in batches of at most 20; their ids, in order."""

    ids: list[UUID] = []
    for start in range(0, len(items), BATCH):
        batch = scenario.container.task_bulk.create_batch(
            scenario.actor, items[start : start + BATCH], idempotency_key=_key()
        )
        for created in batch.tasks:
            for step in created.steps:
                scenario.container.steps.complete_step(
                    scenario.actor,
                    UUID(step["id"]),
                    version=step["version"],
                    idempotency_key=_key(),
                )
            ids.append(created.task.id)
    return ids


def _wait_for_an_answer(scenario: Scenario, prefix: str, count: int, follow_up: datetime) -> None:
    for task_id in _create(scenario, _items(prefix, count)):
        task = scenario.container.tasks.get(scenario.actor, task_id)
        scenario.container.tasks.update(
            scenario.actor,
            task_id,
            version=task.version,
            idempotency_key=_key(),
            command=UpdateTaskCommand(waiting_since=LONG_AGO, follow_up_at=follow_up),
        )


def start(username: str) -> tuple[Scenario, MovableClock]:
    """An owner with an empty list and a Project, the clock at `LONG_AGO`."""

    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(username, "Eval Owner")
    clock = MovableClock(LONG_AGO)
    container.tasks.clock = clock
    actor = Actor(owner, SCOPES)
    domain = container.contexts.create_domain(
        actor, name="Huset", description=None, idempotency_key=_key()
    )
    project = container.projects.create(
        actor, title=PROJECT_TITLE, domain_id=domain.id, idempotency_key=_key()
    )
    return Scenario(container, actor, project.id), clock


def seed_main(username: str) -> Scenario:
    """120 open Tasks: 10 with every Step done, 25 long overdue, 15 whose follow-up has passed,
    30 overdue, and 40 in no bucket (they come with `scope=all`)."""

    scenario, clock = start(username)
    _create(scenario, _items("Klar", PER_BUCKET["likely_done"], steps=("Första", "Andra")))
    _create(
        scenario,
        _items(
            "Länge försenad", 12, due_at=NOW - timedelta(days=35), project_id=scenario.project_id
        ),
    )
    _create(scenario, _items("Länge försenad utan projekt", 13, due_at=NOW - timedelta(days=35)))
    _wait_for_an_answer(scenario, "Väntar", PER_BUCKET["follow_up_due"], NOW - timedelta(days=2))
    _create(scenario, _items("Försenad", PER_BUCKET["overdue"], due_at=NOW - timedelta(days=3)))
    clock.at = NOW
    _create(scenario, _items("Kommande", 20, due_at=NOW + timedelta(days=5)))
    _create(scenario, _items("Odaterad", 20))
    return scenario


def seed_project(username: str, *, in_project: int, loose: int) -> Scenario:
    """`in_project` overdue Tasks in one Project and `loose` overdue Tasks outside any."""

    scenario, clock = start(username)
    due = NOW - timedelta(days=3)
    _create(scenario, _items("Altan", in_project, due_at=due, project_id=scenario.project_id))
    _create(scenario, _items("Lös", loose, due_at=due))
    clock.at = NOW
    return scenario

"""A Task whose parent (Project, Process or Domain) is in the trash is hidden, then returns.

The rule: the Task is not trashed itself, so the trash view shows the parent; every normal read
(Task list, board, agenda, Work list, search, counts) leaves the Task out until the parent is
restored. Also pins that reading a list of Tasks does not query per Task.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

from sidekick.lifecycle import RecordKind, RecordLifecycleService
from sidekick.projects.application import ProjectService
from sidekick.search.persistence import SearchStore
from sidekick.shared.auth import ALL_SCOPES, AuthService
from sidekick.shared.errors import NotFoundError
from sidekick.shared.types import Actor, SystemClock
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.application import TaskService
from sidekick.work.application.models import WorkQuery
from sidekick.work.application.service import ContextService
from sidekick.work.application.work_lists import WorkListService
from tests.db import database_factory
from tests.support.fakes import make_cursor_codec

PARENT_KINDS = ("project", "process", "domain")


@dataclass
class _World:
    actor: Actor
    factory: sessionmaker[Session]
    store: SqlAlchemyStore
    tasks: TaskService
    projects: ProjectService
    contexts: ContextService
    work_lists: WorkListService
    lifecycle: RecordLifecycleService
    domain_id: UUID

    @classmethod
    def build(cls) -> "_World":
        factory = database_factory()
        owner_id = AuthService(factory, "pepper" * 8).provision_user("owner", "Owner")
        store = SqlAlchemyStore(factory)
        codec = make_cursor_codec()
        contexts = ContextService(store, SystemClock(), codec, owner_timezone=UTC)
        work_lists = WorkListService(store, SystemClock(), codec, owner_timezone=UTC)
        actor = Actor(owner_id, ALL_SCOPES)
        domain = contexts.create_domain(
            actor, name="Hem", description=None, idempotency_key="domain-home"
        )
        return cls(
            actor=actor,
            factory=factory,
            store=store,
            tasks=TaskService(store, SystemClock(), codec),
            projects=ProjectService(store, SystemClock(), codec),
            contexts=contexts,
            work_lists=work_lists,
            lifecycle=RecordLifecycleService(store, SystemClock(), codec),
            domain_id=domain.id,
        )

    def trash(self, kind: RecordKind, record_id: UUID, version: int, key: str) -> None:
        self.lifecycle.trash(self.actor, kind, record_id, version=version, idempotency_key=key)

    def restore(self, kind: RecordKind, record_id: UUID, version: int, key: str) -> None:
        self.lifecycle.restore(self.actor, kind, record_id, version=version, idempotency_key=key)

    def listed_titles(self) -> set[str]:
        return {task.title for task in self.tasks.list(self.actor, limit=100).items}

    def work_titles(self, *, agenda: bool = False) -> set[str]:
        query = WorkQuery(kind="task", limit=100)
        page = (
            self.work_lists.work_agenda_page(self.actor, query)
            if agenda
            else self.work_lists.work_list_page(self.actor, query)
        )
        return {item.title for item in page.items}

    def board_titles(self) -> set[str]:
        columns, _ = self.work_lists.work_board_page(self.actor, WorkQuery(kind="task", limit=100))
        return {item.title for items in columns.values() for item in items}

    def search_titles(self, term: str) -> set[str]:
        hits = self.store.transaction(
            lambda session: SearchStore.search_tasks(session, self.actor.user_id, [term], limit=25)
        )
        return {hit.title for hit in hits}


def _seed(world: _World) -> dict[str, tuple[RecordKind, UUID, int]]:
    """One Task under each kind of parent, plus a loose Task; returns the parents by kind."""

    due = SystemClock().now() - timedelta(days=1)
    project = world.projects.create(
        world.actor, title="Renovering", domain_id=world.domain_id, idempotency_key="project"
    )
    process = world.contexts.create_process(
        world.actor,
        domain_id=world.domain_id,
        name="Månadsavslut",
        description=None,
        idempotency_key="process",
    )
    other_domain = world.contexts.create_domain(
        world.actor, name="Arbete", description=None, idempotency_key="domain-work"
    )
    contexts: dict[str, dict[str, Any]] = {
        "project": {"project_id": project.id},
        "process": {"process_id": process.id},
        "domain": {"domain_id": other_domain.id},
    }
    for kind, parent in contexts.items():
        world.tasks.create(
            world.actor,
            title=f"Plock {kind}",
            idempotency_key=f"task-{kind}",
            due_at=due,
            **parent,
        )
    world.tasks.create(world.actor, title="Plock lös", idempotency_key="task-loose", due_at=due)
    return {
        "project": (RecordKind.PROJECT, project.id, project.version),
        "process": (RecordKind.PROCESS, process.id, process.version),
        "domain": (RecordKind.DOMAIN, other_domain.id, other_domain.version),
    }


@pytest.mark.integration
@pytest.mark.parametrize("kind", PARENT_KINDS)
def test_task_of_a_trashed_parent_is_hidden_everywhere_until_the_parent_is_restored(
    kind: str,
) -> None:
    world = _World.build()
    parents = _seed(world)
    record_kind, record_id, version = parents[kind]
    visible = {"Plock project", "Plock process", "Plock domain", "Plock lös"}

    assert world.listed_titles() == visible
    world.trash(record_kind, record_id, version, f"trash-{kind}")

    expected = visible - {f"Plock {kind}"}
    assert world.listed_titles() == expected
    assert world.work_titles() == expected
    assert world.work_titles(agenda=True) == expected
    assert world.board_titles() == expected
    assert world.search_titles("plock") == expected

    world.restore(record_kind, record_id, version + 1, f"restore-{kind}")

    assert world.listed_titles() == visible
    assert world.work_titles() == visible
    assert world.work_titles(agenda=True) == visible
    assert world.board_titles() == visible
    assert world.search_titles("plock") == visible


@pytest.mark.integration
def test_task_of_a_trashed_project_cannot_be_read_by_id() -> None:
    world = _World.build()
    project = world.projects.create(
        world.actor, title="Renovering", domain_id=world.domain_id, idempotency_key="project"
    )
    task = world.tasks.create(
        world.actor, title="Måla", project_id=project.id, idempotency_key="task"
    )
    world.trash(RecordKind.PROJECT, project.id, project.version, "trash-project")

    with pytest.raises(NotFoundError):
        world.tasks.get(world.actor, task.id)

    world.restore(RecordKind.PROJECT, project.id, project.version + 1, "restore-project")
    assert world.tasks.get(world.actor, task.id).derived_domain_id == world.domain_id


@contextmanager
def _count_statements(world: _World) -> Iterator[list[str]]:
    engine: Engine = world.factory.kw["bind"]
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


@pytest.mark.integration
def test_listing_tasks_loads_parent_context_in_a_constant_number_of_queries() -> None:
    world = _World.build()
    counts: list[int] = []
    created = 0
    for size in (2, 12):
        while created < size:
            project = world.projects.create(
                world.actor,
                title=f"Projekt {created}",
                domain_id=world.domain_id,
                idempotency_key=f"project-{created}",
            )
            process = world.contexts.create_process(
                world.actor,
                domain_id=world.domain_id,
                name=f"Process {created}",
                description=None,
                idempotency_key=f"process-{created}",
            )
            world.tasks.create(
                world.actor,
                title=f"Uppgift p{created}",
                project_id=project.id,
                idempotency_key=f"task-p-{created}",
            )
            world.tasks.create(
                world.actor,
                title=f"Uppgift r{created}",
                process_id=process.id,
                idempotency_key=f"task-r-{created}",
            )
            created += 1
        with _count_statements(world) as statements:
            page = world.tasks.list(world.actor, limit=100)
        assert len(page.items) == 2 * size
        assert all(task.derived_domain_id == world.domain_id for task in page.items)
        counts.append(len(statements))

    assert counts[0] == counts[1]
    assert counts[0] <= 4  # the list query and one lookup each for Process and Project Domains


@pytest.mark.integration
def test_trashed_parents_leave_the_derived_domain_of_a_replayed_create_unset() -> None:
    world = _World.build()
    project = world.projects.create(
        world.actor, title="Renovering", domain_id=world.domain_id, idempotency_key="project"
    )
    first = world.tasks.create(
        world.actor, title="Måla", project_id=project.id, idempotency_key="task"
    )
    world.trash(RecordKind.PROJECT, project.id, project.version, "trash-project")

    replay = world.tasks.create(
        world.actor, title="Måla", project_id=project.id, idempotency_key="task"
    )

    assert replay.id == first.id
    assert replay.derived_domain_id is None

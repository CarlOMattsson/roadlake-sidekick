"""Shared test helpers moved out of `tests/integration/test_work_list_database_paging.py`."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, event, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.auth import AuthService
from sidekick.shared.persistence.models import (
    DomainRow,
    ProjectRow,
    TaskRow,
)
from sidekick.shared.types import Actor, new_uuid7
from sidekick.store import SqlAlchemyStore
from sidekick.work.application.service import ContextService, WorkQuery
from tests.db import database_factory
from tests.support.fakes import make_cursor_codec

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


BASE = NOW - timedelta(days=400)


SCOPES = frozenset({"projects:read", "tasks:read"})


class _FixedClock:
    def now(self) -> datetime:
        return NOW


class WorkFixture:
    def __init__(self) -> None:
        self.factory: sessionmaker[Session] = database_factory()
        auth = AuthService(self.factory, "pepper" * 8)
        self.owner_id = auth.provision_user("owner", "Owner")
        self.other_id = auth.provision_user("other", "Other")
        self.codec = make_cursor_codec()
        self.contexts = ContextService(
            SqlAlchemyStore(self.factory), _FixedClock(), self.codec, owner_timezone=UTC
        )
        self.actor = Actor(self.owner_id, SCOPES)
        self.domains: dict[UUID, UUID] = {}
        self.domain_id = self.domain_for(self.owner_id)

    def domain_for(self, owner_id: UUID) -> UUID:
        domain_id = self.domains.setdefault(owner_id, new_uuid7())
        with self.factory.begin() as session:
            session.execute(
                insert(DomainRow).on_conflict_do_nothing(),
                [
                    {
                        "id": domain_id,
                        "owner_id": owner_id,
                        "name": "Hem",
                        "status": "active",
                        "created_at": BASE,
                        "updated_at": BASE,
                        "version": 1,
                    }
                ],
            )
        return domain_id

    def seed(self, projects: int, tasks: int, *, owner_id: UUID | None = None) -> None:
        """Bulk insert; index 0 is the oldest. Tasks cycle: overdue, due today, undated, done."""

        owner = owner_id or self.owner_id
        domain_id = self.domain_for(owner)
        # UUIDv7 bits below the millisecond are random, so ids made in one burst sort in random
        # order. Lists tie-break on id; sorting the ids by index keeps every page's contents (and
        # so the lookups a page needs) the same on every run, however fast or loaded the machine.
        project_ids = sorted(new_uuid7() for _ in range(projects))
        task_ids = sorted(new_uuid7() for _ in range(tasks))
        project_rows: list[dict[str, Any]] = []
        for index in range(projects):
            project_rows.append(
                {
                    "id": project_ids[index],
                    "owner_id": owner,
                    "domain_id": domain_id,
                    "title": "Gammal nål" if index == 0 else f"Projekt {index}",
                    "status": "active",
                    "created_at": BASE + timedelta(minutes=index),
                    "updated_at": BASE + timedelta(minutes=index),
                    "version": 1 + index % 5,
                }
            )
        task_rows: list[dict[str, Any]] = []
        for index in range(tasks):
            due = None
            if index % 10 == 0:
                due = NOW - timedelta(days=1, minutes=index)
            elif index % 10 == 1:
                due = NOW + timedelta(minutes=1 + index % 600)
            task_rows.append(
                {
                    "id": task_ids[index],
                    "owner_id": owner,
                    "title": "Gammal uppgift" if index == 0 else f"Uppgift {index}",
                    "status": "completed" if index % 10 == 5 else "todo",
                    "completed_at": BASE if index % 10 == 5 else None,
                    "priority": "normal",
                    "due_at": due,
                    "created_at": BASE + timedelta(minutes=index),
                    "updated_at": BASE + timedelta(minutes=index),
                    "version": 1 + index % 7,
                    "project_id": project_rows[index % len(project_rows)]["id"]
                    if project_rows and index % 3 == 0
                    else None,
                    "domain_id": domain_id if not (project_rows and index % 3 == 0) else None,
                }
            )
        with self.factory.begin() as session:
            if project_rows:
                session.execute(insert(ProjectRow), project_rows)
            if task_rows:
                session.execute(insert(TaskRow), task_rows)

    def ids(self, model: Any) -> list[UUID]:
        with self.factory() as session:
            return list(session.scalars(model.__table__.select().with_only_columns(model.id)))

    def updated_at_by_id(self) -> dict[UUID, datetime]:
        """The last-change time of every Domain, Project and Task, by id."""

        with self.factory() as session:
            return {
                row_id: moment
                for model in (DomainRow, ProjectRow, TaskRow)
                for row_id, moment in session.execute(select(model.id, model.updated_at))
            }

    def walk(self, query: WorkQuery) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(100):
            page = self.contexts.work_list_page(self.actor, replace(query, cursor=cursor))
            items.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return items
        raise AssertionError("pagination did not end")

    @contextmanager
    def count_statements(self) -> Iterator[list[str]]:
        engine: Engine = self.factory.kw["bind"]
        statements: list[str] = []

        def record(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            yield statements
        finally:
            event.remove(engine, "before_cursor_execute", record)

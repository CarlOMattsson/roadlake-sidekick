"""One flush writes referenced rows before the rows that reference them.

The mappers have no `relationship()` between them, so the unit of work falls back to a sort key.
`order_flushes_by_foreign_keys` (models/base.py) makes that key follow the foreign keys; this file
fails if it stops doing so, for mappings in the core package and in later-imported modules.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Mapper, Session, configure_mappers, sessionmaker

from sidekick.shared.auth import AuthService
from sidekick.shared.persistence.models import Base, DomainRow, ProjectRow, StepRow, TaskRow
from sidekick.shared.types import new_uuid7
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow
from tests.db import database_factory

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _world() -> tuple[sessionmaker[Session], UUID]:
    factory = database_factory()
    return factory, AuthService(factory, "pepper" * 8).provision_user("flush-owner", "Owner")


@pytest.mark.integration
@pytest.mark.parametrize("children_first", [False, True])
def test_a_domain_project_task_and_step_added_together_are_written_in_foreign_key_order(
    children_first: bool,
) -> None:
    factory, owner = _world()
    domain = DomainRow(
        id=new_uuid7(), owner_id=owner, name="Hemmet", status="active",
        created_at=NOW, updated_at=NOW, version=1,
    )  # fmt: skip
    project = ProjectRow(
        id=new_uuid7(), owner_id=owner, domain_id=domain.id, title="Stugan", status="active",
        created_at=NOW, updated_at=NOW, version=1,
    )  # fmt: skip
    task = TaskRow(
        id=new_uuid7(), owner_id=owner, project_id=project.id, title="Måla", status="todo",
        priority="normal", created_at=NOW, updated_at=NOW, version=1,
    )  # fmt: skip
    step = StepRow(
        id=new_uuid7(), owner_id=owner, task_id=task.id, title="Köp färg", status="todo",
        position=0, created_at=NOW, updated_at=NOW, version=1,
    )  # fmt: skip
    rows = [domain, project, task, step]

    with factory.begin() as session:
        session.add_all(reversed(rows) if children_first else rows)


@pytest.mark.integration
def test_a_shopping_list_and_its_item_added_together_are_written_in_foreign_key_order() -> None:
    factory, owner = _world()
    shopping_list = ShoppingListRow(
        id=new_uuid7(), owner_id=owner, name="Vecka", archived=False, version=1,
        created_at=NOW, updated_at=NOW,
    )  # fmt: skip
    item = ShoppingItemRow(
        id=new_uuid7(), owner_id=owner, list_id=shopping_list.id, name="Kaffe",
        quantity=Decimal(1), purchased=False, version=1, created_at=NOW, updated_at=NOW,
    )  # fmt: skip

    with factory.begin() as session:
        session.add_all([item, shopping_list])


def test_every_mapper_sorts_after_the_mappers_it_references() -> None:
    configure_mappers()
    by_table = {mapper.local_table: mapper for mapper in Base.registry.mappers}
    unordered = [
        f"{table.name} -> {key.column.table.name}"
        for table in by_table
        for key in table.foreign_keys
        if key.column.table is not table
        and by_table[key.column.table]._sort_key >= by_table[table]._sort_key
    ]

    assert unordered == []
    assert all(isinstance(mapper, Mapper) for mapper in by_table.values())

"""Restore into a new owner: the untouched memory default row is overwritten, anything else refuses.

AuthService writes a memory settings row when it provisions an owner (all four domains on, not
paused, version 1). That row is not content, so a restore may overwrite it. A row the owner has
changed, or any other owner data, keeps the rule that the target must be empty.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container, create_container
from sidekick.owner_export.catalogue import ExportRefused
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.shared.persistence.models import MemorySettingsRow
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

REFUSAL = "target owner must be empty before restore"


def _setup() -> tuple[sessionmaker[Session], Container, UUID, UUID]:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    source = container.auth.provision_user("restore-source", "Source")
    target = container.auth.provision_user("restore-target", "Target")
    return factory, container, source, target


def _change_settings(factory: sessionmaker[Session], owner: UUID, **values: Any) -> None:
    with factory.begin() as session:
        row = session.get(MemorySettingsRow, owner)
        assert row is not None
        for name, value in values.items():
            setattr(row, name, value)


def _settings_values(factory: sessionmaker[Session], owner: UUID) -> tuple[Any, ...]:
    with factory() as session:
        row = session.get(MemorySettingsRow, owner)
        assert row is not None
        return (row.journal, row.contacts, row.projects, row.tasks, row.paused, row.version)


def _restore(
    container: Container, factory: sessionmaker[Session], source: UUID, target: UUID
) -> None:
    exported = OwnerExportService(StoreBase(factory)).export(Actor(source, frozenset()))
    plan = build_restore_plan(exported, target)
    assert plan.status == "ready"
    OwnerRestoreService(StoreBase(factory)).restore(
        exported, target_owner_id=target, expected_plan_checksum=plan.plan_checksum
    )


@pytest.mark.integration
def test_an_untouched_default_settings_row_is_overwritten_by_the_document() -> None:
    factory, container, source, target = _setup()
    _change_settings(factory, source, journal=False, paused=True, version=2)
    assert _settings_values(factory, target) == (True, True, True, True, False, 1)

    _restore(container, factory, source, target)

    assert _settings_values(factory, target) == (False, True, True, True, True, 2)


@pytest.mark.integration
@pytest.mark.parametrize(
    "change",
    [{"version": 2}, {"journal": False, "version": 2}, {"paused": True}],
)
def test_a_settings_row_the_owner_changed_refuses_the_restore(change: dict[str, Any]) -> None:
    factory, container, source, target = _setup()
    _change_settings(factory, target, **change)
    before = _settings_values(factory, target)

    with pytest.raises(ExportRefused, match=REFUSAL):
        _restore(container, factory, source, target)

    assert _settings_values(factory, target) == before


@pytest.mark.integration
def test_an_untouched_default_row_beside_other_owner_data_still_refuses() -> None:
    factory, container, source, target = _setup()
    container.tasks.create(
        Actor(target, frozenset({"tasks:read", "tasks:write"})),
        title="Plan",
        idempotency_key="restore-target-task",
    )
    assert _settings_values(factory, target) == (True, True, True, True, False, 1)

    with pytest.raises(ExportRefused, match=REFUSAL):
        _restore(container, factory, source, target)

    assert _settings_values(factory, target) == (True, True, True, True, False, 1)

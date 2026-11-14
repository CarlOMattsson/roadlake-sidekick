"""The owner export is one consistent snapshot, and a backup is only good when it can be restored.

A write that commits between two collection reads must not tear related rows apart: a task that
a later `domain_events` read could see but the earlier `tasks` read could not would be a dangling
reference in the export.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from sidekick.api.app import create_container
from sidekick.backup.bundle import OwnerBackupService, verify_backup_file
from sidekick.owner_export.document import verify_export
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore_plan import build_restore_plan, verify_restorable
from sidekick.shared.persistence.models import TaskRow
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"tasks:read", "tasks:write"})


class ConcurrentWriteStore(StoreBase):
    """Commits one related write from another session right after the tasks have been read."""

    def __init__(self, factory: Any, write: Any) -> None:
        super().__init__(factory)
        self._write = write
        self._fired = False

    def export_owner_rows(  # type: ignore[override]
        self, session: Session, *, owner_id: UUID, row_type: type[Any]
    ) -> list[Any]:
        rows = super().export_owner_rows(session, owner_id=owner_id, row_type=row_type)
        if row_type is TaskRow and not self._fired:
            self._fired = True
            self._write()
        return rows


class ReadCommittedStore(ConcurrentWriteStore):
    """The behaviour before the snapshot, kept only to prove the test would notice it."""

    def snapshot_transaction(self, operation: Any) -> Any:
        return self.transaction(operation)


class Env:
    def __init__(self) -> None:
        self.factory = database_factory()
        self.container = create_container(make_settings(), self.factory)
        self.owner = self.container.auth.provision_user("snapshot-owner", "Owner")
        self.actor = Actor(self.owner, SCOPES)
        self.container.tasks.create(self.actor, title="Before", idempotency_key="before")

    def write_related_rows(self) -> None:
        self.container.tasks.create(self.actor, title="During", idempotency_key="during")

    def task_count(self) -> int:
        with self.factory() as session:
            return (
                session.scalar(
                    select(func.count()).select_from(TaskRow).where(TaskRow.owner_id == self.owner)
                )
                or 0
            )


def event_aggregates(document: dict[str, Any]) -> set[str]:
    return {row["aggregate_id"] for row in document["collections"]["domain_events"]}


@pytest.mark.integration
def test_a_write_during_the_export_is_not_half_visible() -> None:
    env = Env()
    store = ConcurrentWriteStore(env.factory, env.write_related_rows)

    document = OwnerExportService(store).export(Actor(env.owner, frozenset()))

    task_ids = {row["id"] for row in document["collections"]["tasks"]}
    assert env.task_count() == 2  # the concurrent write did commit
    assert len(task_ids) == 1  # the snapshot predates it...
    assert event_aggregates(document) <= task_ids  # ...in every collection
    verify_restorable(document)


@pytest.mark.integration
def test_read_committed_would_tear_the_export_which_the_snapshot_prevents() -> None:
    env = Env()
    store = ReadCommittedStore(env.factory, env.write_related_rows)

    document = OwnerExportService(store).export(Actor(env.owner, frozenset()))

    # Without the snapshot the later read sees the new task's event but the earlier read did not.
    assert verify_export(document).owner_id == env.owner  # still a well-formed document
    assert build_restore_plan(document, env.owner).status == "blocked"


@pytest.mark.integration
def test_export_all_is_one_snapshot_too() -> None:
    env = Env()
    store = ConcurrentWriteStore(env.factory, env.write_related_rows)

    documents = OwnerExportService(store).export_all()

    (document,) = [d for d in documents if d["owner_id"] == str(env.owner)]
    assert len(document["collections"]["tasks"]) == 1
    for each in documents:
        verify_restorable(each)


@pytest.mark.integration
def test_history_of_a_task_removed_directly_does_not_block_a_backup(
    tmp_path: Path,
) -> None:
    env = Env()
    key = Fernet.generate_key()
    result = OwnerBackupService(StoreBase(env.factory)).create(
        directory=tmp_path, key=key, retention_count=5, retention_days=5
    )
    assert verify_backup_file(result.path, key) == result.owner_count

    # A task removed without the application leaves its domain events naming nothing. That is
    # allowed history (the same state a permanent removal leaves), not a dangling reference.
    with env.factory.begin() as session:
        session.execute(delete(TaskRow).where(TaskRow.owner_id == env.owner))
    again = OwnerBackupService(StoreBase(env.factory)).create(
        directory=tmp_path, key=key, retention_count=5, retention_days=5
    )
    assert verify_backup_file(again.path, key) == again.owner_count

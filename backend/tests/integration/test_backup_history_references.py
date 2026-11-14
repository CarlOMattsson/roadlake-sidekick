"""A backup of a long-lived instance stays restorable after records were removed.

Domain events and activity entries are append-only history that name a record by a polymorphic
``aggregate_id``. A process run writes such an event, and a Task removed permanently from the
trash leaves its events behind. Neither is an unresolved reference: the backup must be written,
read back, and restored, with the history ids rewritten consistently.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.activity.application.service import ActivityLedger
from sidekick.activity.domain import ActivityCategory
from sidekick.api.app import Container, create_container
from sidekick.backup.bundle import OwnerBackupService, decrypt_backup_envelope, verify_backup_file
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.lifecycle.domain import RecordKind
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.owner_export.restore_remap import (
    POLYMORPHIC_SOURCE_NAMES,
    restore_id,
)
from sidekick.shared.cadence import Cadence
from sidekick.shared.persistence.models import ActivityEntryRow, DomainEventRow, TaskRow
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor
from sidekick.work.application.models import UpdateContextCommand
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset(
    {
        "tasks:read",
        "tasks:write",
        "projects:read",
        "projects:write",
        "contacts:read",
        "contacts:write",
    }
)


class Env:
    def __init__(self) -> None:
        self.factory: sessionmaker[Session] = database_factory()
        self.container: Container = create_container(make_settings(), self.factory)
        self.owner = self.container.auth.provision_user("history-owner", "Owner")
        self.target = self.container.auth.provision_user("history-target", "Target")
        self.actor = Actor(self.owner, SCOPES)
        self.key = Fernet.generate_key()

    def backup(self, directory: Path) -> Path:
        result = OwnerBackupService(StoreBase(self.factory)).create(
            directory=directory, key=self.key, retention_count=5, retention_days=5
        )
        assert verify_backup_file(result.path, self.key) == result.owner_count
        return result.path

    def restore(self, path: Path) -> None:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        bundle = decrypt_backup_envelope(envelope, self.key)
        (export,) = [item for item in bundle["exports"] if item["owner_id"] == str(self.owner)]
        plan = build_restore_plan(export, self.target)
        assert plan.status == "ready"
        OwnerRestoreService(StoreBase(self.factory)).restore(
            export, target_owner_id=self.target, expected_plan_checksum=plan.plan_checksum
        )

    def events(self, owner: UUID) -> list[tuple[str, UUID]]:
        with self.factory() as session:
            rows = session.execute(
                select(DomainEventRow.aggregate_type, DomainEventRow.aggregate_id).where(
                    DomainEventRow.owner_id == owner
                )
            ).all()
        return [(kind, identifier) for kind, identifier in rows]

    def activity(self, owner: UUID) -> list[tuple[str, UUID]]:
        with self.factory() as session:
            rows = session.execute(
                select(ActivityEntryRow.aggregate_type, ActivityEntryRow.aggregate_id).where(
                    ActivityEntryRow.owner_id == owner
                )
            ).all()
        return [(kind, identifier) for kind, identifier in rows]

    def record_history(self, aggregate_type: str, aggregate_id: UUID) -> None:
        def write(session: Any) -> None:
            ActivityLedger(self.container.activity.store).append(
                session,
                owner_id=self.owner,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_version=1,
                event_type=f"{aggregate_type}.recorded",
                actor_type="user",
                actor_id=self.owner,
                operation="record",
                category=ActivityCategory.TASK_MAINTENANCE,
                summary="history",
                occurred_at=datetime.now(UTC),
            )

        self.container.activity.store.transaction(write)

    def remove_permanently(self, kind: RecordKind, record_id: UUID, version: int) -> None:
        lifecycle = self.container.lifecycle
        trashed = lifecycle.trash(
            self.actor, kind, record_id, version=version, idempotency_key=f"trash-{record_id}"
        )
        lifecycle.permanently_remove(
            self.actor,
            kind,
            record_id,
            version=trashed.version,
            idempotency_key=f"remove-{record_id}",
        )


@pytest.mark.integration
def test_a_backup_after_a_process_run_is_written_and_restores(tmp_path: Path) -> None:
    env = Env()
    contexts = env.container.contexts
    domain = contexts.create_domain(
        env.actor, name="Home", description=None, idempotency_key="history-domain"
    )
    process = contexts.create_process(
        env.actor,
        domain_id=domain.id,
        name="Weekly review",
        description=None,
        idempotency_key="history-process",
    )
    contexts.update_process(
        env.actor,
        process.id,
        version=process.version,
        idempotency_key="history-cadence",
        command=UpdateContextCommand(cadence=Cadence.WEEKLY),
    )
    due = datetime.now(UTC) - timedelta(days=1)
    with env.factory.begin() as session:
        session.execute(
            text("UPDATE sidekick.processes SET next_expected_run_at = :due WHERE id = :id"),
            {"due": due, "id": process.id},
        )
        session.execute(
            text(
                "UPDATE sidekick.process_run_outbox SET scheduled_for = :due WHERE process_id = :id"
            ),
            {"due": due, "id": process.id},
        )
    runs = env.container.process_runs.run_due("history-worker", max_runs=1)
    assert len(runs) == 1
    assert ("process_run", runs[0].id) in env.events(env.owner)

    env.restore(env.backup(tmp_path))

    restored = dict(env.events(env.target))
    assert restored["process_run"] == restore_id(runs[0].id, env.target, "process_runs")
    assert ("process_run", restored["process_run"]) in env.activity(env.target)


@pytest.mark.integration
def test_a_backup_after_a_task_was_removed_permanently_is_written_and_restores(
    tmp_path: Path,
) -> None:
    env = Env()
    task = env.container.tasks.create(env.actor, title="Doomed", idempotency_key="doomed-task")
    kept = env.container.tasks.create(env.actor, title="Kept", idempotency_key="kept-task")
    env.remove_permanently(RecordKind.TASK, task.id, task.version)
    with env.factory() as session:
        remaining = set(session.scalars(select(TaskRow.id).where(TaskRow.owner_id == env.owner)))
    assert remaining == {kept.id}
    assert ("task", task.id) in env.events(env.owner)  # the history outlives the Task

    env.restore(env.backup(tmp_path))

    restored_ids = {identifier for _, identifier in env.events(env.target)}
    assert restore_id(task.id, env.target, "tasks") in restored_ids  # same id a live Task gets
    assert restore_id(kept.id, env.target, "tasks") in restored_ids
    with env.factory() as session:
        restored_tasks = set(
            session.scalars(select(TaskRow.id).where(TaskRow.owner_id == env.target))
        )
    assert restored_tasks == {restore_id(kept.id, env.target, "tasks")}


def _removable_contact(env: Env) -> tuple[RecordKind, UUID, int]:
    contact = env.container.contacts.create(
        env.actor, CreateContactCommand(display_name="Gone"), "history-contact"
    )
    return RecordKind.CONTACT, contact.id, contact.version


def _removable_step(env: Env) -> tuple[RecordKind, UUID, int]:
    task = env.container.tasks.create(env.actor, title="Holder", idempotency_key="step-holder")
    step = env.container.steps.create_step(
        env.actor, task.id, title="Gone", idempotency_key="history-step"
    )
    return RecordKind.STEP, step.id, step.version


def _removable_project(env: Env) -> tuple[RecordKind, UUID, int]:
    domain = env.container.contexts.create_domain(
        env.actor, name="Holder", description=None, idempotency_key="history-project-domain"
    )
    project = env.container.projects.create(
        env.actor, title="Gone", domain_id=domain.id, idempotency_key="history-gone-project"
    )
    return RecordKind.PROJECT, project.id, project.version


@pytest.mark.integration
@pytest.mark.parametrize(
    "make", [_removable_contact, _removable_step, _removable_project], ids=lambda f: f.__name__
)
def test_removed_records_of_other_kinds_never_make_a_backup_unrestorable(
    tmp_path: Path, make: Callable[[Env], tuple[RecordKind, UUID, int]]
) -> None:
    env = Env()
    kind, record_id, version = make(env)
    # The ledger does not write these kinds today; the history row is what a future writer or an
    # older release would have left behind for the record.
    env.record_history(kind.value, record_id)
    env.remove_permanently(kind, record_id, version)

    env.restore(env.backup(tmp_path))

    source = POLYMORPHIC_SOURCE_NAMES[kind.value]
    assert (kind.value, restore_id(record_id, env.target, source)) in env.events(env.target)


@pytest.mark.integration
@pytest.mark.parametrize(
    "aggregate_type",
    [*sorted(POLYMORPHIC_SOURCE_NAMES), "legacy_kind"],
)
def test_history_that_names_no_record_at_all_is_restored_with_a_stable_id(
    tmp_path: Path, aggregate_type: str
) -> None:
    env = Env()
    unknown = uuid4()
    env.record_history(aggregate_type, unknown)

    env.restore(env.backup(tmp_path))

    source = POLYMORPHIC_SOURCE_NAMES.get(aggregate_type) or aggregate_type
    expected = (aggregate_type, restore_id(unknown, env.target, source))
    assert expected in env.events(env.target)
    assert expected in env.activity(env.target)

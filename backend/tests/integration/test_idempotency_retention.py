"""Idempotency replay records: replay within retention, key reuse, pruning, and no stored text."""

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_app
from sidekick.automation.worker import prune_idempotency_records
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.lifecycle import RecordKind
from sidekick.shared.errors import IdempotencyKeyReusedError, NotFoundError
from sidekick.shared.persistence.models import IdempotencyRow
from sidekick.shared.persistence.stores.base import IDEMPOTENCY_RETENTION, ReplayRecordError
from sidekick.shared.types import Actor, new_uuid7, utc_now
from sidekick.shopping.application.schemas import BatchItem
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.application.models import NewTaskItem
from sidekick.tasks.domain import Priority
from tests.db import database_factory
from tests.support.settings import make_settings

SECRET_NAME = "Hemlig Kontakt Zxqv"
SECRET_NOTE = "Hemlig anteckning Qwzx"


def _owner(factory: sessionmaker[Session]) -> UUID:
    app = create_app(make_settings(), factory)
    return app.state.container.auth.provision_user("idem-owner", "Owner")


def _run(
    store: SqlAlchemyStore,
    owner: UUID,
    *,
    key: str,
    payload: dict[str, Any],
    calls: list[int],
    operation: str = "create_journal_source",
) -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        calls.append(1)
        return {"source_id": str(new_uuid7())}

    return store.transaction(
        lambda session: store.idempotent(
            session, actor_id=owner, operation=operation, key=key, payload=payload, execute=execute
        )
    )


@pytest.mark.integration
def test_replay_within_retention_returns_the_stored_result_and_executes_once() -> None:
    factory = database_factory()
    store = SqlAlchemyStore(factory)
    owner = _owner(factory)
    calls: list[int] = []

    first = _run(store, owner, key="k1", payload={"a": 1}, calls=calls)
    again = _run(store, owner, key="k1", payload={"a": 1}, calls=calls)

    assert again == first
    assert len(calls) == 1


@pytest.mark.integration
def test_a_reused_key_with_another_payload_is_refused() -> None:
    factory = database_factory()
    store = SqlAlchemyStore(factory)
    owner = _owner(factory)
    calls: list[int] = []
    _run(store, owner, key="k1", payload={"a": 1}, calls=calls)

    with pytest.raises(IdempotencyKeyReusedError):
        _run(store, owner, key="k1", payload={"a": 2}, calls=calls)

    assert len(calls) == 1


@pytest.mark.integration
def test_pruning_removes_expired_records_and_keeps_fresh_ones() -> None:
    factory = database_factory()
    store = SqlAlchemyStore(factory)
    owner = _owner(factory)
    calls: list[int] = []
    for key in ("old", "fresh"):
        _run(store, owner, key=key, payload={"k": key}, calls=calls)
    with factory.begin() as session:
        old = session.scalars(select(IdempotencyRow).where(IdempotencyRow.idempotency_key == "old"))
        for row in old:
            row.created_at = utc_now() - IDEMPOTENCY_RETENTION - timedelta(days=1)

    removed = prune_idempotency_records(store)

    assert removed == 1
    with factory() as session:
        left = set(session.scalars(select(IdempotencyRow.idempotency_key)))
    assert left == {"fresh"}
    # A retry after expiry is a new request; within retention it is still a replay.
    _run(store, owner, key="old", payload={"k": "old"}, calls=calls)
    _run(store, owner, key="fresh", payload={"k": "fresh"}, calls=calls)
    assert len(calls) == 3


@pytest.mark.integration
def test_an_operation_without_a_projection_or_allow_list_entry_writes_nothing() -> None:
    factory = database_factory()
    store = SqlAlchemyStore(factory)
    owner = _owner(factory)

    with pytest.raises(ReplayRecordError):
        _run(store, owner, key="k1", payload={}, calls=[], operation="brand_new_operation")

    with factory() as session:
        assert session.scalars(select(IdempotencyRow)).all() == []


@pytest.mark.integration
def test_contact_writes_store_only_the_contact_id_and_replay_rereads_it() -> None:
    factory = database_factory()
    app = create_app(make_settings(), factory)
    owner_id = app.state.container.auth.provision_user("idem-contact", "Owner")
    actor = Actor(owner_id, frozenset({"contacts:read", "contacts:write"}))
    contacts = app.state.container.contacts
    command = CreateContactCommand(SECRET_NAME, context_note=SECRET_NOTE, aliases=["Smeknamn Zxqv"])

    created = contacts.create(actor, command, "idem-contact-create")
    replayed = contacts.create(actor, command, "idem-contact-create")

    assert replayed.id == created.id
    assert replayed.display_name == SECRET_NAME
    with factory() as session:
        records = list(session.scalars(select(IdempotencyRow.result)))
    assert records == [{"id": str(created.id)}]
    stored = str(records)
    assert SECRET_NAME not in stored and SECRET_NOTE not in stored


WORK_SCOPES = frozenset(
    {
        "projects:read",
        "projects:write",
        "tasks:read",
        "tasks:write",
        "shopping:read",
        "shopping:write",
    }
)


@pytest.mark.integration
def test_work_and_shopping_writes_keep_only_ids_and_a_retry_reads_the_record_again() -> None:
    """Domains, Projects, Tasks, Steps, tags and shopping used to keep their full result."""

    factory = database_factory()
    app = create_app(make_settings(), factory)
    container = app.state.container
    owner_id = container.auth.provision_user("idem-work", "Owner")
    actor = Actor(owner_id, WORK_SCOPES)
    secret = "Hemlig rubrik Zxqv"

    domain = container.contexts.create_domain(
        actor, name=secret + " domän", description=secret, idempotency_key="idem-domain-1"
    )
    project = container.projects.create(
        actor, title=secret + " projekt", domain_id=domain.id, idempotency_key="idem-project-1"
    )
    task = container.tasks.create(
        actor, title=secret + " uppgift", project_id=project.id, idempotency_key="idem-task-1"
    )
    step = container.steps.create_step(
        actor, task.id, title=secret + " steg", idempotency_key="idem-step-1"
    )
    action = container.steps.create_action(
        actor, step.id, title=secret + " handling", idempotency_key="idem-action-1"
    )
    tag = container.work_tags.create(actor, label=secret + " etikett", idempotency_key="idem-tag-1")
    created_list = container.shopping.create_list(
        actor, secret + " lista", idempotency_key="idem-list-001"
    )
    list_id = created_list.shopping_list.id
    items = [BatchItem(name=secret + " vara", client_ref="ref-1")]
    added = container.shopping.add_items(actor, list_id, items, idempotency_key="idem-items-001")
    completed = container.tasks.complete(
        actor, task.id, version=task.version, idempotency_key="idem-complete-1"
    )

    with factory() as session:
        stored = str(list(session.scalars(select(IdempotencyRow.result))))
    assert secret not in stored

    # A retry returns the records as they are now, built from ids alone.
    assert (
        container.contexts.create_domain(
            actor, name=secret + " domän", description=secret, idempotency_key="idem-domain-1"
        )
        == domain
    )
    assert (
        container.projects.create(
            actor, title=secret + " projekt", domain_id=domain.id, idempotency_key="idem-project-1"
        )
        == project
    )
    assert (
        container.steps.create_action(
            actor, step.id, title=secret + " handling", idempotency_key="idem-action-1"
        )
        == action
    )
    assert (
        container.work_tags.create(actor, label=secret + " etikett", idempotency_key="idem-tag-1")
        == tag
    )
    replayed_task = container.tasks.complete(
        actor, task.id, version=task.version, idempotency_key="idem-complete-1"
    )
    assert replayed_task == completed
    assert replayed_task.title == secret + " uppgift"
    replayed = container.shopping.add_items(actor, list_id, items, idempotency_key="idem-items-001")
    assert replayed.items[0].client_ref == "ref-1"
    assert replayed.items[0].item == added.items[0].item
    assert replayed.list_name == secret + " lista"


@pytest.mark.integration
def test_a_batch_a_step_reorder_and_a_trash_replay_from_ids() -> None:
    factory = database_factory()
    app = create_app(make_settings(), factory)
    container = app.state.container
    owner_id = container.auth.provision_user("idem-batch", "Owner")
    actor = Actor(owner_id, WORK_SCOPES)
    secret = "Hemlig uppgift Zxqv"
    item = NewTaskItem(secret, None, Priority.NORMAL, (), (secret + " ett", secret + " två"))

    batch = container.task_bulk.create_batch(actor, [item], idempotency_key="idem-batch-001")
    task = batch.tasks[0].task
    assert [step["title"] for step in batch.tasks[0].steps] == [secret + " ett", secret + " två"]
    steps = container.steps.list_steps(actor, task.id).items
    order = [(steps[1].id, steps[1].version), (steps[0].id, steps[0].version)]
    reordered = container.steps.reorder_steps(
        actor, task.id, items=order, idempotency_key="idem-reorder-1"
    )
    trashed = container.lifecycle.trash(
        actor, RecordKind.TASK, task.id, version=task.version, idempotency_key="idem-trash-001"
    )

    with factory() as session:
        stored = str(list(session.scalars(select(IdempotencyRow.result))))
    assert secret not in stored
    assert (
        container.steps.reorder_steps(actor, task.id, items=order, idempotency_key="idem-reorder-1")
        == reordered
    )
    assert trashed.label == secret
    assert (
        container.lifecycle.trash(
            actor, RecordKind.TASK, task.id, version=task.version, idempotency_key="idem-trash-001"
        )
        == trashed
    )
    # The Task is in the trash now: a batch retry reads it again and no longer finds it, rather
    # than answering from a stored copy of its title.
    with pytest.raises(NotFoundError):
        container.task_bulk.create_batch(actor, [item], idempotency_key="idem-batch-001")

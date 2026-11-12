"""The operator trash sweep against PostgreSQL: only trashed records go, for every owner."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text

from sidekick.api.app import create_container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.lifecycle.application.empty_trash import empty_trash
from sidekick.lifecycle.domain import RecordKind
from sidekick.shared.auth import ALL_SCOPES
from sidekick.shared.persistence.models import (
    AuditEventRow,
    ContactRow,
    DomainRow,
    JournalEntryRow,
    JournalSourceRow,
    ProcessRow,
    StepRow,
    TaskRow,
)
from sidekick.shared.types import Actor
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


@pytest.mark.integration
def test_empty_trash_removes_only_trashed_records_of_every_owner_and_audits_each() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner = container.auth.provision_user("trash-owner", "Owner")
    other = container.auth.provision_user("trash-other", "Other")
    actor, other_actor = Actor(owner, SCOPES), Actor(other, SCOPES)
    lifecycle = container.lifecycle

    active = container.tasks.create(actor, title="Active", idempotency_key="active-task")
    holder = container.tasks.create(actor, title="Holder", idempotency_key="holder-task")
    step = container.steps.create_step(
        actor, holder.id, title="Child", idempotency_key="child-step"
    )
    archived = container.contacts.create(
        actor, CreateContactCommand(display_name="Archived"), "archived-contact"
    )
    container.contacts.archive(actor, archived.id, archived.version, "archive-contact")
    contact = container.contacts.create(
        other_actor, CreateContactCommand(display_name="Other trashed"), "other-contact"
    )
    # A parent and its child are both trashed: the sweep removes the child first.
    trashed_step = lifecycle.trash(
        actor, RecordKind.STEP, step.id, version=step.version, idempotency_key="trash-step-1"
    )
    holder_now = container.tasks.get(actor, holder.id)
    lifecycle.trash(
        actor,
        RecordKind.TASK,
        holder.id,
        version=holder_now.version,
        idempotency_key="trash-holder",
    )
    lifecycle.trash(
        other_actor,
        RecordKind.CONTACT,
        contact.id,
        version=contact.version,
        idempotency_key="trash-other",
    )
    assert trashed_step.trashed_at is not None

    dry = empty_trash(lifecycle, remove=False)

    assert dict(dry.matched) == {RecordKind.TASK: 1, RecordKind.STEP: 1, RecordKind.CONTACT: 1}
    with factory() as session:
        assert session.scalar(select(StepRow.id).where(StepRow.id == step.id)) == step.id

    # Nothing is old enough yet.
    assert not empty_trash(lifecycle, remove=True, older_than=timedelta(days=1)).removed

    result = empty_trash(lifecycle, remove=True, correlation_id="empty-trash-test")

    assert dict(result.removed) == {RecordKind.TASK: 1, RecordKind.STEP: 1, RecordKind.CONTACT: 1}
    assert not result.kept
    with factory() as session:
        assert set(session.scalars(select(TaskRow.id).where(TaskRow.owner_id == owner))) == {
            active.id
        }
        assert set(session.scalars(select(StepRow.id))) == set()
        # The archived contact stays; the other owner's trashed contact is gone.
        assert set(session.scalars(select(ContactRow.id))) == {archived.id}
        events = set(
            session.scalars(
                select(AuditEventRow.event).where(AuditEventRow.event.like("%permanently_removed"))
            )
        )
    assert events == {
        "task.permanently_removed",
        "step.permanently_removed",
        "contact.permanently_removed",
    }
    assert empty_trash(lifecycle, remove=True).matched == {}


@pytest.mark.integration
def test_older_than_only_removes_records_trashed_long_enough_ago() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner = container.auth.provision_user("trash-age", "Owner")
    actor = Actor(owner, SCOPES)
    old = container.tasks.create(actor, title="Old", idempotency_key="old-task")
    recent = container.tasks.create(actor, title="Recent", idempotency_key="recent-task")
    for task, key in ((old, "trash-old"), (recent, "trash-recent")):
        container.lifecycle.trash(
            actor, RecordKind.TASK, task.id, version=task.version, idempotency_key=key
        )
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE sidekick.tasks SET trashed_at = now() - interval '40 days' WHERE id = :id"
            ),
            {"id": old.id},
        )

    result = empty_trash(container.lifecycle, remove=True, older_than=timedelta(days=30))

    assert dict(result.removed) == {RecordKind.TASK: 1}
    with factory() as session:
        remaining: set[UUID] = set(session.scalars(select(TaskRow.id)))
    assert remaining == {recent.id}


@pytest.mark.integration
def test_a_record_a_foreign_key_still_protects_is_kept_and_the_sweep_goes_on() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner = container.auth.provision_user("trash-linked", "Owner")
    actor = Actor(owner, SCOPES | {"journal:read", "journal:write"})
    lifecycle = container.lifecycle
    linked = container.tasks.create(actor, title="Linked", idempotency_key="linked-task")
    others = [
        container.tasks.create(actor, title=f"Loose {number}", idempotency_key=f"loose-{number}")
        for number in range(2)
    ]
    container.journal_capture.write_entry(
        actor,
        source_type=SourceType.TRANSCRIPT_TEXT,
        journal_date=date(2026, 7, 21),
        occurred_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
        raw_text="Synthetic source text",
        language="sv",
        title="Synthetic entry",
        summary=None,
        key_points=(KeyPoint(KeyPointKind.FACT, "A synthetic fact."),),
        task_ids=(linked.id,),
        idempotency_key="linked-entry",
    )
    for task in (linked, *others):
        current = container.tasks.get(actor, task.id)
        lifecycle.trash(
            actor,
            RecordKind.TASK,
            task.id,
            version=current.version,
            idempotency_key=f"trash-{task.id}",
        )

    result = empty_trash(lifecycle, remove=True, correlation_id="empty-trash-linked")

    assert dict(result.matched) == {RecordKind.TASK: 3}
    assert dict(result.removed) == {RecordKind.TASK: 2}
    assert dict(result.kept) == {RecordKind.TASK: 1}
    with factory() as session:
        assert set(session.scalars(select(TaskRow.id).where(TaskRow.owner_id == owner))) == {
            linked.id
        }
        audited = session.scalars(
            select(AuditEventRow.target_id).where(AuditEventRow.event == "task.permanently_removed")
        ).all()
    assert linked.id not in audited
    assert len(audited) == 2


@pytest.mark.integration
def test_the_sweep_as_the_application_role_removes_domains_and_processes_keeps_journal() -> None:
    """The sweep uses the ordinary application connection, so that role must hold DELETE on every
    table it removes from (the 0.1.0 baseline left it out for domains and processes; migration 103
    grants it). Journal entries and sources are never erased by the runtime: the sweep counts a
    trashed entry as kept and leaves it and its source."""

    factory = database_factory()
    with factory() as session:
        assert session.scalar(text("SELECT current_user")) == "sidekick_app"
    container = create_container(make_settings(), factory)
    owner = container.auth.provision_user("trash-grant", "Owner")
    actor = Actor(owner, ALL_SCOPES)
    lifecycle = container.lifecycle
    domain = container.contexts.create_domain(
        actor, name="Home", description=None, idempotency_key="grant-domain"
    )
    process = container.contexts.create_process(
        actor, domain_id=domain.id, name="Monthly", description=None, idempotency_key="grant-proc"
    )
    source, entry = container.journal_capture.write_entry(
        actor,
        source_type=SourceType.TRANSCRIPT_TEXT,
        journal_date=date(2026, 7, 22),
        occurred_at=datetime(2026, 7, 22, 9, tzinfo=UTC),
        raw_text="Synthetic source text",
        language="sv",
        title="Synthetic entry",
        summary=None,
        key_points=(KeyPoint(KeyPointKind.FACT, "A synthetic fact."),),
        idempotency_key="grant-entry",
    )
    trashed = {
        RecordKind.PROCESS: (process.id, process.version),
        RecordKind.DOMAIN: (domain.id, domain.version),
    }
    lifecycle.trash(
        actor,
        RecordKind.JOURNAL_ENTRY,
        entry.id,
        version=entry.version,
        idempotency_key="grant-trash-journal-entry",
    )
    for kind, (record_id, version) in trashed.items():
        lifecycle.trash(
            actor, kind, record_id, version=version, idempotency_key=f"grant-trash-{kind.value}"
        )

    result = empty_trash(lifecycle, remove=True, correlation_id="empty-trash-grant")

    assert dict(result.removed) == dict.fromkeys(trashed, 1)
    assert dict(result.kept) == {RecordKind.JOURNAL_ENTRY: 1}
    with factory() as session:
        for row_type, record_id in (
            (DomainRow, domain.id),
            (ProcessRow, process.id),
        ):
            assert session.scalar(select(row_type.id).where(row_type.id == record_id)) is None
        # The Journal entry and its immutable source stay.
        assert session.scalar(select(JournalEntryRow.id)) == entry.id
        assert session.scalar(select(JournalSourceRow.id)) == source.id

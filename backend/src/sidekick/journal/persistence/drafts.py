"""Journal draft review, finalization and rejection."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from sidekick.contacts.persistence import ContactStore
from sidekick.journal.domain.analysis import (
    CreateTaskProposal,
    UpdateTaskProposal,
)
from sidekick.journal.domain.analysis import (
    KeyPoint as AnalysisKeyPoint,
)
from sidekick.journal.domain.entry import JournalEntry, KeyPoint
from sidekick.journal.domain.finalize import (
    FinalizeCommand,
    FinalizeProposalConflict,
    FinalizeResult,
)
from sidekick.journal.domain.review import CandidateCatalog, DraftReview
from sidekick.journal.persistence.entries import JournalEntryStore
from sidekick.journal.persistence.mappers import draft_review_from_row
from sidekick.journal.persistence.summaries import JournalSummaryStore
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sidekick.shared.persistence.models import (
    ContactRow,
    JournalDraftRow,
    JournalEntryRow,
    JournalProcessingRunRow,
    JournalSourceRow,
    ProjectRow,
    TaskRow,
)
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import new_uuid7
from sidekick.tasks.domain import Priority, Task, TaskStatus
from sidekick.tasks.persistence import ProjectTaskStore, task_from_row
from sidekick.work.domain.tag_assignment import apply_record_tags
from sidekick.work.persistence.tags import WorkTagStore


class JournalDraftStore:
    """Journal draft review, finalization and rejection.

    Mixin composed into ``SqlAlchemyStore``; methods are static and owner-filtered.
    """

    @staticmethod
    def get_journal_draft(session: Session, owner_id: UUID, draft_id: UUID) -> DraftReview:
        row = session.scalar(
            select(JournalDraftRow)
            .options(joinedload(JournalDraftRow.source))
            .where(
                JournalDraftRow.id == draft_id,
                JournalDraftRow.owner_id == owner_id,
            )
        )
        if row is None:
            raise NotFoundError("journal draft not found")
        return draft_review_from_row(session, row)

    @staticmethod
    def update_journal_draft(
        session: Session,
        *,
        owner_id: UUID,
        draft_id: UUID,
        expected_version: int,
        title: str,
        summary: str | None,
        key_points: tuple[AnalysisKeyPoint, ...],
        task_proposals: tuple[CreateTaskProposal | UpdateTaskProposal, ...],
        now: datetime,
        correlation_id: str | None = None,
    ) -> DraftReview:
        row = session.scalar(
            select(JournalDraftRow)
            .where(
                JournalDraftRow.id == draft_id,
                JournalDraftRow.owner_id == owner_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("journal draft not found")
        if row.state != "pending_review" or row.version != expected_version:
            raise ConflictError("journal draft is no longer current")
        row.title = title.strip()
        row.summary = summary
        row.key_points = [point.model_dump(mode="json") for point in key_points]
        row.task_proposals = [
            proposal.model_dump(mode="json", exclude_unset=True) for proposal in task_proposals
        ]
        row.version += 1
        row.updated_at = now
        session.flush()
        StoreBase.append_audit(
            session,
            actor_id=owner_id,
            event="journal.draft_updated",
            outcome="success",
            target_type="journal_draft",
            target_id=row.id,
            correlation_id=correlation_id,
        )
        return draft_review_from_row(session, row)

    @staticmethod
    def journal_source_has_live_replacement(
        session: Session, owner_id: UUID, source_id: UUID
    ) -> bool:
        """True when a live (untrashed) source replaces this one."""

        return (
            session.scalar(
                select(JournalSourceRow.id)
                .where(
                    JournalSourceRow.owner_id == owner_id,
                    JournalSourceRow.replaces_source_id == source_id,
                    JournalSourceRow.trashed_at.is_(None),
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def supersede_pending_journal_drafts(
        session: Session,
        *,
        owner_id: UUID,
        source_id: UUID,
        now: datetime,
        correlation_id: str | None,
    ) -> int:
        """Close every pending AI draft on a source that has just been replaced.

        The draft was derived from text that is no longer the entry's source, so it must not be
        finalized into a second entry. Audit carries ids only, never draft text.
        """

        rows = session.scalars(
            select(JournalDraftRow)
            .where(
                JournalDraftRow.owner_id == owner_id,
                JournalDraftRow.source_id == source_id,
                JournalDraftRow.state == "pending_review",
            )
            .order_by(JournalDraftRow.id)
            .with_for_update()
        ).all()
        for row in rows:
            row.state = "superseded"
            row.version += 1
            row.updated_at = now
            row.lifecycle_at = now
            session.flush()
            StoreBase.append_audit(
                session,
                actor_id=owner_id,
                event="journal.draft_superseded",
                outcome="success",
                target_type="journal_draft",
                target_id=row.id,
                correlation_id=correlation_id,
            )
        return len(rows)

    @staticmethod
    def finalize_journal_draft(
        session: Session,
        *,
        owner_id: UUID,
        command: FinalizeCommand,
        now: datetime,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        """Apply one reviewed package while holding all mutable target locks."""
        draft, source, catalog = _load_finalize_inputs(session, owner_id, command)
        tasks = _lock_finalize_targets(session, owner_id, command, catalog)
        _assert_source_not_consumed(session, owner_id, source.id)

        created_task_ids, updated_task_ids = _apply_task_proposals(
            session, owner_id=owner_id, proposals=command.task_proposals, tasks=tasks, now=now
        )

        entry = _build_journal_entry(owner_id, source, command, now)
        JournalEntryStore.save_journal_entry(session, entry)
        selection = command.relation_selection
        JournalEntryStore.add_journal_entry_relations(
            session,
            owner_id=owner_id,
            entry_id=entry.id,
            project_ids=tuple(identifier for identifier, _origin in selection["projects"]),
            task_ids=tuple(identifier for identifier, _origin in selection["tasks"]),
            contact_ids=tuple(identifier for identifier, _origin in selection["contacts"]),
        )
        if command.tags:
            apply_record_tags(
                WorkTagStore,
                session,
                owner_id=owner_id,
                kind="journal_entry",
                record_id=entry.id,
                values=command.tags,
                now=now,
            )
        draft.state = "finalized"
        draft.version += 1
        draft.updated_at = now
        draft.lifecycle_at = now
        JournalSummaryStore.mark_daily_journal_summary_stale(session, owner_id, source.journal_date)
        StoreBase.append_audit(
            session,
            actor_id=owner_id,
            event="journal.draft_finalized",
            outcome="success",
            target_type="journal_draft",
            target_id=draft.id,
            correlation_id=correlation_id,
        )
        session.flush()
        return {
            "entry_id": str(entry.id),
            "created_task_ids": [str(identifier) for identifier in created_task_ids],
            "updated_task_ids": [str(identifier) for identifier in updated_task_ids],
        }

    @staticmethod
    def get_finalize_result(
        session: Session, owner_id: UUID, result: dict[str, Any]
    ) -> FinalizeResult:
        entry = JournalEntryStore.get_journal_entry(session, owner_id, UUID(result["entry_id"]))
        relations = JournalEntryStore.get_journal_entry_relations(session, owner_id, entry.id)
        return FinalizeResult(
            entry=entry,
            project_ids=relations.project_ids,
            task_ids=relations.task_ids,
            contact_ids=relations.contact_ids,
            created_task_ids=tuple(UUID(identifier) for identifier in result["created_task_ids"]),
            updated_task_ids=tuple(UUID(identifier) for identifier in result["updated_task_ids"]),
        )

    @staticmethod
    def reject_journal_draft(
        session: Session,
        *,
        owner_id: UUID,
        draft_id: UUID,
        expected_version: int,
        now: datetime,
        correlation_id: str | None = None,
    ) -> DraftReview:
        row = session.scalar(
            select(JournalDraftRow)
            .where(
                JournalDraftRow.id == draft_id,
                JournalDraftRow.owner_id == owner_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("journal draft not found")
        if row.state != "pending_review" or row.version != expected_version:
            raise ConflictError("journal draft is no longer current")
        row.state = "rejected"
        row.version += 1
        row.updated_at = now
        row.lifecycle_at = now
        session.flush()
        StoreBase.append_audit(
            session,
            actor_id=owner_id,
            event="journal.draft_rejected",
            outcome="success",
            target_type="journal_draft",
            target_id=row.id,
            correlation_id=correlation_id,
        )
        return draft_review_from_row(session, row)


def _load_finalize_inputs(
    session: Session, owner_id: UUID, command: FinalizeCommand
) -> tuple[JournalDraftRow, JournalSourceRow, CandidateCatalog]:
    """Lock the pending draft and load its source and candidate catalog."""
    draft = session.scalar(
        select(JournalDraftRow)
        .where(JournalDraftRow.id == command.draft_id, JournalDraftRow.owner_id == owner_id)
        .with_for_update()
    )
    if draft is None:
        raise NotFoundError("journal draft not found")
    if draft.state != "pending_review" or draft.version != command.expected_version:
        raise ConflictError("journal draft is no longer current")
    # No lock: a Journal source is immutable after creation and `sidekick_app` is denied
    # UPDATE on `journal_sources` by design (baseline grants), so `FOR UPDATE` here would
    # only fail with a permission error, never protect against a concurrent write.
    source = session.scalar(
        select(JournalSourceRow).where(
            JournalSourceRow.id == draft.source_id, JournalSourceRow.owner_id == owner_id
        )
    )
    if source is None:
        raise NotFoundError("journal source not found")

    catalog_run = session.scalar(
        select(JournalProcessingRunRow).where(
            JournalProcessingRunRow.id == draft.catalog_run_id,
            JournalProcessingRunRow.owner_id == owner_id,
        )
    )
    if catalog_run is None:
        raise NotFoundError("journal processing run not found")
    # `candidate_catalog` is a JSONB column, so SQLAlchemy hands back a plain dict with
    # string UUIDs. `CandidateCatalog` is `strict=True` on purpose, and strict mode
    # refuses to coerce a plain Python string into `UUID`; only its JSON parsing path
    # does that coercion. `model_validate_json` round-trips through JSON text, exactly
    # like the other two call sites already do.
    catalog = CandidateCatalog.model_validate_json(json.dumps(catalog_run.candidate_catalog))
    return draft, source, catalog


def _lock_finalize_targets(
    session: Session, owner_id: UUID, command: FinalizeCommand, catalog: CandidateCatalog
) -> dict[UUID, TaskRow]:
    """Lock every project, task and contact the package touches, then validate them.

    Returns the locked task rows by id; the update proposals need them.
    """
    selection = command.relation_selection
    update_proposals = [p for p in command.task_proposals if isinstance(p, UpdateTaskProposal)]
    create_proposals = [p for p in command.task_proposals if isinstance(p, CreateTaskProposal)]
    selected_projects = {identifier for identifier, _origin in selection["projects"]}
    selected_tasks = {identifier for identifier, _origin in selection["tasks"]}
    selected_contacts = {identifier for identifier, _origin in selection["contacts"]}
    update_ids = {proposal.task_id for proposal in update_proposals}
    update_projects = {
        proposal.project_id
        for proposal in update_proposals
        if "project_id" in proposal.model_fields_set and proposal.project_id is not None
    }
    create_projects = {
        proposal.project_id for proposal in create_proposals if proposal.project_id is not None
    }
    create_contacts = {
        contact_id for proposal in create_proposals for contact_id in proposal.contact_ids
    }
    locked_projects = _lock_rows(
        session, ProjectRow, owner_id, selected_projects | create_projects | update_projects
    )
    locked_tasks = _lock_rows(session, TaskRow, owner_id, selected_tasks | update_ids)
    locked_contacts = _lock_rows(session, ContactRow, owner_id, selected_contacts | create_contacts)
    projects = {row.id: row for row in locked_projects}
    tasks = {row.id: row for row in locked_tasks}
    contacts = {row.id: row for row in locked_contacts}

    _validate_locked_relations(
        command, catalog=catalog, projects=projects, tasks=tasks, contacts=contacts
    )
    return tasks


def _assert_source_not_consumed(session: Session, owner_id: UUID, source_id: UUID) -> None:
    existing_entry = session.scalar(
        select(JournalEntryRow)
        .where(JournalEntryRow.owner_id == owner_id, JournalEntryRow.source_id == source_id)
        .with_for_update()
    )
    if existing_entry is not None:
        raise ConflictError("journal source already has an entry")
    if JournalDraftStore.journal_source_has_live_replacement(session, owner_id, source_id):
        raise ConflictError("journal source was replaced")


_UPDATE_PROPOSAL_FIELDS = (
    "project_id",
    "title",
    "description",
    "status",
    "priority",
    "due_at",
)


def _apply_task_proposals(
    session: Session,
    *,
    owner_id: UUID,
    proposals: tuple[CreateTaskProposal | UpdateTaskProposal, ...],
    tasks: dict[UUID, TaskRow],
    now: datetime,
) -> tuple[list[UUID], list[UUID]]:
    """Create or update the proposed tasks; returns (created ids, updated ids)."""
    created_task_ids: list[UUID] = []
    updated_task_ids: list[UUID] = []
    for proposal in proposals:
        if isinstance(proposal, CreateTaskProposal):
            task = Task(
                id=new_uuid7(),
                owner_id=owner_id,
                project_id=proposal.project_id,
                title=proposal.title,
                description=proposal.description,
                status=TaskStatus.TODO,
                priority=Priority(proposal.priority.value),
                due_at=proposal.due_at,
                completed_at=None,
                created_at=now,
                updated_at=now,
            )
            ProjectTaskStore.save_task(session, task)
            for contact_id in proposal.contact_ids:
                ContactStore.link_task_contact(session, owner_id, task.id, contact_id)
            created_task_ids.append(task.id)
        else:
            current = task_from_row(tasks[proposal.task_id])
            updated = current.update(now=now, **_update_proposal_changes(proposal))
            ProjectTaskStore.save_task(
                session, updated, expected_version=proposal.expected_task_version
            )
            updated_task_ids.append(updated.id)
    return created_task_ids, updated_task_ids


def _update_proposal_changes(proposal: UpdateTaskProposal) -> dict[str, Any]:
    """Only the fields the proposal explicitly set, mapped to Task domain values."""
    changes: dict[str, Any] = {}
    for field_name in _UPDATE_PROPOSAL_FIELDS:
        if field_name in proposal.model_fields_set:
            value = getattr(proposal, field_name)
            if field_name == "priority" and value is not None:
                value = Priority(value.value)
            changes[field_name] = value
    return changes


def _build_journal_entry(
    owner_id: UUID, source: JournalSourceRow, command: FinalizeCommand, now: datetime
) -> JournalEntry:
    return JournalEntry(
        id=new_uuid7(),
        owner_id=owner_id,
        source_id=source.id,
        journal_date=source.journal_date,
        occurred_at=source.occurred_at,
        source_recorded_at=source.source_recorded_at,
        title=command.title,
        summary=command.summary,
        key_points=tuple(
            KeyPoint(kind=point.kind, text=point.text) for point in command.key_points
        ),
        version=1,
        created_at=now,
        updated_at=now,
        archived_at=None,
    )


def _lock_rows(
    session: Session, row_type: Any, owner_id: UUID, identifiers: set[UUID]
) -> list[Any]:
    if not identifiers:
        return []
    return list(
        session.scalars(
            select(row_type)
            .where(row_type.owner_id == owner_id, row_type.id.in_(identifiers))
            .order_by(row_type.id.asc())
            .with_for_update()
        )
    )


def _validate_locked_relations(
    command: FinalizeCommand,
    *,
    catalog: CandidateCatalog,
    projects: dict[UUID, ProjectRow],
    tasks: dict[UUID, TaskRow],
    contacts: dict[UUID, ContactRow],
) -> None:
    catalog_ids = {
        "projects": {candidate.id for candidate in catalog.projects},
        "tasks": {candidate.id for candidate in catalog.tasks},
        "contacts": {candidate.id for candidate in catalog.contacts},
    }
    catalog_task_versions = {candidate.id: candidate.version for candidate in catalog.tasks}
    for kind, values in command.relation_selection.items():
        for identifier, origin in values:
            if origin == "model_suggested" and identifier not in catalog_ids[kind]:
                raise ValidationError("model suggestion is outside the immutable snapshot")
            if origin not in {"model_suggested", "user_selected"}:
                raise ValidationError("unknown relation origin")
            if kind == "projects":
                row = projects.get(identifier)
                if row is None or row.archived_at is not None or row.status == "completed":
                    raise NotFoundError("relation target not found")
            elif kind == "tasks":
                row = tasks.get(identifier)
                if row is None or row.archived_at is not None or row.status == "completed":
                    raise NotFoundError("relation target not found")
            else:
                row = contacts.get(identifier)
                if row is None or row.archived:
                    raise NotFoundError("relation target not found")

    for proposal in command.task_proposals:
        if isinstance(proposal, CreateTaskProposal):
            if proposal.project_id is not None:
                if proposal.project_id not in catalog_ids["projects"]:
                    raise ValidationError("proposal references an unknown project")
                project = projects.get(proposal.project_id)
                if (
                    project is None
                    or project.archived_at is not None
                    or project.status == "completed"
                ):
                    raise NotFoundError("project not found")
            for contact_id in proposal.contact_ids:
                contact = contacts.get(contact_id)
                if contact is None or contact.archived:
                    raise NotFoundError("contact not found")
        else:
            candidate_version = catalog_task_versions.get(proposal.task_id)
            row = tasks.get(proposal.task_id)
            if candidate_version is None or candidate_version != proposal.expected_task_version:
                raise ValidationError("proposal references an unknown Task version")
            if row is None or row.archived_at is not None:
                raise NotFoundError("task not found")
            if row.version != proposal.expected_task_version:
                raise FinalizeProposalConflict(proposal.proposal_id)
            if "project_id" in proposal.model_fields_set and proposal.project_id is not None:
                project = projects.get(proposal.project_id)
                if (
                    project is None
                    or project.archived_at is not None
                    or project.status == "completed"
                ):
                    raise NotFoundError("project not found")

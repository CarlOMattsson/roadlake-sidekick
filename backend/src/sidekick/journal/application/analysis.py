"""Review-only Journal draft orchestration.

Drafts are produced by the connected assistant through MCP and persisted as pending
proposals. This service reads, edits and rejects them; a draft has no durable Journal,
relation, Task, or summary effect until it is finalized by the owner.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sidekick.contacts.domain.contact import Contact
from sidekick.journal.domain.analysis import (
    CreateTaskProposal,
    KeyPoint,
    UpdateTaskProposal,
)
from sidekick.journal.domain.review import CandidateCatalog, DraftReview, ScopedDraft, scope_draft
from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.errors import NotFoundError, ValidationError
from sidekick.shared.types import Actor, Clock, IdempotentStore, TransactionalStore, TxSession
from sidekick.tasks.domain import Task, TaskStatus

T = TypeVar("T")


class AnalysisStore(TransactionalStore, IdempotentStore, Protocol):
    def get_journal_draft(
        self, session: TxSession, owner_id: UUID, draft_id: UUID
    ) -> DraftReview: ...

    def update_journal_draft(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        draft_id: UUID,
        expected_version: int,
        title: str,
        summary: str | None,
        key_points: tuple[KeyPoint, ...],
        task_proposals: tuple[CreateTaskProposal | UpdateTaskProposal, ...],
        now: datetime,
        correlation_id: str | None = None,
    ) -> DraftReview: ...

    def reject_journal_draft(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        draft_id: UUID,
        expected_version: int,
        now: datetime,
        correlation_id: str | None = None,
    ) -> DraftReview: ...

    def get_project(self, session: TxSession, owner_id: UUID, project_id: UUID) -> Project: ...
    def get_task(self, session: TxSession, owner_id: UUID, task_id: UUID) -> Task: ...
    def get_contact(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        include_archived: bool = False,
    ) -> Contact: ...


class JournalAnalysisService:
    """Owner-scoped orchestration for strict, review-only Journal proposals."""

    def __init__(self, store: AnalysisStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    def get_draft(self, actor: Actor, draft_id: UUID) -> DraftReview:
        actor.require("journal:read")
        return self.store.transaction(
            lambda session: self.store.get_journal_draft(session, actor.user_id, draft_id)
        )

    def read_draft(
        self, actor: Actor, draft_id: UUID, *, include_content: bool = True
    ) -> ScopedDraft:
        """The draft as the caller's scopes allow it; no `include_content` leaves owner text out."""

        draft = self.get_draft(actor, draft_id)
        return scope_draft(draft, actor.scopes, include_content=include_content)

    def update_draft(
        self,
        actor: Actor,
        *,
        draft_id: UUID,
        expected_version: int,
        title: str,
        summary: str | None,
        key_points: tuple[KeyPoint, ...],
        relation_selection: dict[str, tuple[tuple[UUID, str], ...]],
        task_proposals: tuple[CreateTaskProposal | UpdateTaskProposal, ...],
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> DraftReview:
        actor.require("journal:write")
        title = title.strip()
        if not title:
            raise ValidationError("journal draft title is required")
        payload = {
            "draft_id": str(draft_id),
            "expected_version": expected_version,
            "title": title,
            "summary": summary,
            "key_points": [point.model_dump(mode="json") for point in key_points],
            "relation_selection": {
                kind: [[str(identifier), origin] for identifier, origin in values]
                for kind, values in relation_selection.items()
            },
            "task_proposals": [
                proposal.model_dump(mode="json", exclude_unset=True) for proposal in task_proposals
            ],
        }

        def operation(session: TxSession) -> DraftReview:
            def execute() -> dict[str, Any]:
                draft = self.store.get_journal_draft(session, actor.user_id, draft_id)
                validate_task_proposals(task_proposals, draft.catalog)
                validate_relation_selection(
                    self.store, session, actor.user_id, relation_selection, draft.catalog
                )
                updated = self.store.update_journal_draft(
                    session,
                    owner_id=actor.user_id,
                    draft_id=draft_id,
                    expected_version=expected_version,
                    title=title,
                    summary=summary,
                    key_points=key_points,
                    task_proposals=task_proposals,
                    now=self.clock.now(),
                    correlation_id=correlation_id,
                )
                return {"draft_id": str(updated.id)}

            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="update_journal_draft",
                key=idempotency_key,
                payload=payload,
                execute=execute,
            )
            return self.store.get_journal_draft(session, actor.user_id, UUID(result["draft_id"]))

        return self.store.transaction(operation)

    def reject_draft(
        self,
        actor: Actor,
        *,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> DraftReview:
        actor.require("journal:write")

        def operation(session: TxSession) -> DraftReview:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="reject_journal_draft",
                key=idempotency_key,
                payload={
                    "draft_id": str(draft_id),
                    "expected_version": expected_version,
                },
                execute=lambda: {
                    "draft_id": str(
                        self.store.reject_journal_draft(
                            session,
                            owner_id=actor.user_id,
                            draft_id=draft_id,
                            expected_version=expected_version,
                            now=self.clock.now(),
                            correlation_id=correlation_id,
                        ).id
                    )
                },
            )
            return self.store.get_journal_draft(session, actor.user_id, UUID(result["draft_id"]))

        return self.store.transaction(operation)


def validate_task_proposals(
    proposals: tuple[CreateTaskProposal | UpdateTaskProposal, ...],
    catalog: CandidateCatalog,
) -> None:
    project_ids = {item.id for item in catalog.projects}
    task_by_id = {item.id: item for item in catalog.tasks}
    contact_ids = {item.id for item in catalog.contacts}
    for proposal in proposals:
        if isinstance(proposal, CreateTaskProposal):
            if proposal.project_id is not None and proposal.project_id not in project_ids:
                raise ValidationError("proposal references an unknown project")
            if any(contact_id not in contact_ids for contact_id in proposal.contact_ids):
                raise ValidationError("proposal references an unknown contact")
        else:
            candidate = task_by_id.get(proposal.task_id)
            if candidate is None or candidate.version != proposal.expected_task_version:
                raise ValidationError("proposal references an unknown Task version")
            if (
                "project_id" in proposal.model_fields_set
                and proposal.project_id is not None
                and proposal.project_id not in project_ids
            ):
                raise ValidationError("proposal references an unknown project")


def validate_relation_selection(
    store: AnalysisStore,
    session: TxSession,
    owner_id: UUID,
    selection: dict[str, tuple[tuple[UUID, str], ...]],
    catalog: CandidateCatalog,
) -> None:
    snapshot_ids = {
        "projects": {item.id for item in catalog.projects},
        "tasks": {item.id for item in catalog.tasks},
        "contacts": {item.id for item in catalog.contacts},
    }
    getters: dict[str, Callable[..., Any]] = {
        "projects": store.get_project,
        "tasks": store.get_task,
        "contacts": store.get_contact,
    }
    for kind, values in selection.items():
        for identifier, origin in values:
            if origin == "model_suggested":
                if identifier not in snapshot_ids[kind]:
                    raise ValidationError("model suggestion is outside the immutable snapshot")
            elif origin == "user_selected":
                target = getters[kind](session, owner_id, identifier)
                if kind == "projects" and target.status is ProjectStatus.COMPLETED:
                    raise NotFoundError("relation target not found")
                if kind == "tasks" and target.status is TaskStatus.COMPLETED:
                    raise NotFoundError("relation target not found")
                if kind == "contacts" and target.archived:
                    raise NotFoundError("relation target not found")
            else:
                raise ValidationError("unknown relation origin")

"""The reviewed Journal draft effect boundary.

This module deliberately owns no database details.  It validates the closed package and delegates
one already-open transaction to the concrete store; FastAPI and MCP never call it through HTTP.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sidekick.contacts.domain.contact import Contact
from sidekick.journal.domain.analysis import CreateTaskProposal, TaskProposal
from sidekick.journal.domain.finalize import FinalizeCommand, FinalizeResult
from sidekick.journal.domain.review import CandidateCatalog, DraftReview
from sidekick.projects.domain import Project
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.types import Actor, Clock, IdempotentStore, TransactionalStore, TxSession
from sidekick.tasks.domain import Task
from sidekick.work.domain.planning import normalize_tag_selection

T = TypeVar("T")


class FinalizeStore(TransactionalStore, IdempotentStore, Protocol):
    def get_journal_draft(
        self, session: TxSession, owner_id: UUID, draft_id: UUID
    ) -> DraftReview: ...

    def get_project(self, session: TxSession, owner_id: UUID, project_id: UUID) -> Project: ...

    def get_task(self, session: TxSession, owner_id: UUID, task_id: UUID) -> Task: ...

    def get_contact(
        self, session: TxSession, owner_id: UUID, contact_id: UUID, include_archived: bool = False
    ) -> Contact: ...

    def finalize_journal_draft(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        command: FinalizeCommand,
        now: datetime,
        correlation_id: str | None,
    ) -> dict[str, Any]: ...

    def get_finalize_result(
        self, session: TxSession, owner_id: UUID, result: dict[str, Any]
    ) -> FinalizeResult: ...


class JournalFinalizeService:
    """Validate and commit exactly one reviewed effect package."""

    def __init__(self, store: FinalizeStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    def finalize(
        self,
        actor: Actor,
        *,
        command: FinalizeCommand,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> FinalizeResult:
        actor.require("journal:write")
        command = dataclasses.replace(command, tags=normalize_tag_selection(list(command.tags)))
        if command.relation_selection["projects"] or any(
            _proposal_project_ids(proposal) for proposal in command.task_proposals
        ):
            actor.require("projects:read")
        if command.relation_selection["tasks"]:
            actor.require("tasks:read")
        if command.relation_selection["contacts"] or any(
            _proposal_contact_ids(proposal) for proposal in command.task_proposals
        ):
            actor.require("contacts:read")
        if command.task_proposals:
            actor.require("tasks:write")

        payload = finalize_command_data(command)

        def operation(session: TxSession) -> FinalizeResult:
            def execute() -> dict[str, Any]:
                draft = self.store.get_journal_draft(session, actor.user_id, command.draft_id)
                catalog_ids = catalog_identifier_sets(draft.catalog)
                _validate_draft_state_and_version(draft, command.expected_version)
                validate_finalize_task_proposals(command.task_proposals, draft.catalog)
                live_targets = _load_live_targets(self.store, session, actor.user_id, command)
                validate_finalize_command(
                    command, catalog_ids=catalog_ids, live_targets=live_targets
                )
                return self.store.finalize_journal_draft(
                    session,
                    owner_id=actor.user_id,
                    command=command,
                    now=self.clock.now(),
                    correlation_id=correlation_id,
                )

            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="finalize_journal_draft",
                key=idempotency_key,
                payload=payload,
                execute=execute,
            )
            return self.store.get_finalize_result(session, actor.user_id, result)

        return self.store.transaction(operation)


def _validate_draft_state_and_version(draft: DraftReview, expected_version: int) -> None:
    state = draft.state.value if hasattr(draft.state, "value") else draft.state
    if state != "pending_review" or draft.version != expected_version:
        raise ConflictError("journal draft is no longer current")


def catalog_identifier_sets(catalog: CandidateCatalog) -> dict[str, set[UUID]]:
    return {
        "projects": {candidate.id for candidate in catalog.projects},
        "tasks": {candidate.id for candidate in catalog.tasks},
        "contacts": {candidate.id for candidate in catalog.contacts},
    }


def validate_finalize_task_proposals(
    proposals: tuple[TaskProposal, ...], catalog: CandidateCatalog
) -> None:
    """Check model-bound Task/project provenance while contacts remain live selections."""
    project_ids = {item.id for item in catalog.projects}
    task_versions = {item.id: item.version for item in catalog.tasks}
    for proposal in proposals:
        if isinstance(proposal, CreateTaskProposal):
            if proposal.project_id is not None and proposal.project_id not in project_ids:
                raise ValidationError("proposal references an unknown project")
        else:
            if task_versions.get(proposal.task_id) != proposal.expected_task_version:
                raise ValidationError("proposal references an unknown Task version")
            if (
                "project_id" in proposal.model_fields_set
                and proposal.project_id is not None
                and proposal.project_id not in project_ids
            ):
                raise ValidationError("proposal references an unknown project")


def _validate_relation_selection(
    command: FinalizeCommand,
    *,
    catalog_ids: dict[str, set[UUID]],
    live_targets: dict[str, dict[UUID, Any]],
) -> None:
    for kind in ("projects", "tasks", "contacts"):
        values = command.relation_selection.get(kind)
        if values is None or len(values) > 25 or len({item[0] for item in values}) != len(values):
            raise ValidationError("relation selection is invalid")
        for identifier, origin in values:
            if origin == "model_suggested":
                if identifier not in catalog_ids[kind]:
                    raise ValidationError("model suggestion is outside the immutable snapshot")
            elif origin == "user_selected":
                target = live_targets.get(kind, {}).get(identifier)
                if target is None or not _is_active(kind, target):
                    raise NotFoundError("relation target not found")
            else:
                raise ValidationError("unknown relation origin")


def validate_finalize_command(
    command: FinalizeCommand,
    *,
    catalog_ids: dict[str, set[UUID]],
    live_targets: dict[str, dict[UUID, Any]],
) -> None:
    """Validate provenance and active relation targets without exposing target details."""

    if command.expected_version < 1:
        raise ValidationError("expected draft version is invalid")
    _validate_relation_selection(command, catalog_ids=catalog_ids, live_targets=live_targets)

    for proposal in command.task_proposals:
        if isinstance(proposal, CreateTaskProposal):
            if proposal.project_id is not None:
                if proposal.project_id not in catalog_ids["projects"]:
                    raise ValidationError("proposal references an unknown project")
                project = live_targets.get("projects", {}).get(proposal.project_id)
                if project is None or not _is_active("projects", project):
                    raise NotFoundError("project not found")
            for contact_id in proposal.contact_ids:
                contact = live_targets.get("contacts", {}).get(contact_id)
                if contact is None or not _is_active("contacts", contact):
                    raise NotFoundError("contact not found")
        else:
            candidate = catalog_candidate(catalog_ids, proposal.task_id, "tasks")
            if candidate is None:
                raise ValidationError("proposal references an unknown Task")


def catalog_candidate(
    catalog_ids: dict[str, set[UUID]], identifier: UUID, kind: str
) -> UUID | None:
    return identifier if identifier in catalog_ids[kind] else None


def _is_active(kind: str, target: Any) -> bool:
    if kind == "contacts":
        return not target.archived
    status = target.status.value if hasattr(target.status, "value") else target.status
    return status != "completed"


def _load_live_targets(
    store: FinalizeStore, session: TxSession, owner_id: UUID, command: FinalizeCommand
) -> dict[str, dict[UUID, Any]]:
    identifiers: dict[str, set[UUID]] = {"projects": set(), "tasks": set(), "contacts": set()}
    for kind, values in command.relation_selection.items():
        identifiers[kind].update(
            identifier for identifier, origin in values if origin == "user_selected"
        )
    for proposal in command.task_proposals:
        if isinstance(proposal, CreateTaskProposal):
            if proposal.project_id is not None:
                identifiers["projects"].add(proposal.project_id)
            identifiers["contacts"].update(proposal.contact_ids)
    getters: dict[str, Callable[..., Any]] = {
        "projects": store.get_project,
        "tasks": store.get_task,
        "contacts": store.get_contact,
    }
    targets: dict[str, dict[UUID, Any]] = {"projects": {}, "tasks": {}, "contacts": {}}
    for kind in ("projects", "tasks", "contacts"):
        for identifier in sorted(identifiers[kind], key=lambda value: value.int):
            try:
                targets[kind][identifier] = getters[kind](session, owner_id, identifier)
            except (NotFoundError, KeyError):
                # The same safe not-found outcome is used for cross-owner and absent IDs.
                continue
    return targets


def _proposal_project_ids(proposal: TaskProposal) -> bool:
    if isinstance(proposal, CreateTaskProposal):
        return proposal.project_id is not None
    return "project_id" in proposal.model_fields_set and proposal.project_id is not None


def _proposal_contact_ids(proposal: TaskProposal) -> bool:
    return isinstance(proposal, CreateTaskProposal) and bool(proposal.contact_ids)


def finalize_command_data(command: FinalizeCommand) -> dict[str, Any]:
    data: dict[str, Any] = {
        "draft_id": str(command.draft_id),
        "expected_version": command.expected_version,
        "title": command.title,
        "summary": command.summary,
        "key_points": [point.model_dump(mode="json") for point in command.key_points],
        "relation_selection": {
            kind: [[str(identifier), origin] for identifier, origin in values]
            for kind, values in command.relation_selection.items()
        },
        "task_proposals": [
            proposal.model_dump(mode="json", exclude_unset=True)
            for proposal in command.task_proposals
        ],
    }
    if command.tags:
        data["tags"] = list(command.tags)
    return data

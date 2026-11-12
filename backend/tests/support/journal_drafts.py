"""Seeding of a pending AI Journal draft for review tests.

Drafts are produced by the connected assistant and persisted as pending proposals; the server no
longer runs a provider pipeline of its own, but drafts already stored (and the tables they live
in) are still reviewed, edited, rejected and finalized through the MCP review tools. These tests
therefore need a stored draft without any production path that creates one, so this module
writes the same rows the retired pipeline wrote: one succeeded processing run holding the
immutable candidate catalog, and one `pending_review` draft that points at it.
"""

import hashlib
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

from sidekick.api.app import Container
from sidekick.journal.domain.analysis import (
    CreateTaskProposal,
    KeyPoint,
    TaskPriority,
    UpdateTaskProposal,
)
from sidekick.journal.domain.entry import KeyPointKind
from sidekick.journal.domain.review import (
    CandidateCatalog,
    ContactCandidate,
    ProjectCandidate,
    TaskCandidate,
)
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.persistence.models import JournalDraftRow, JournalProcessingRunRow
from sidekick.shared.types import Actor, new_uuid7
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.domain import TaskStatus

PROVIDER = "fake"
MODEL_ID = "deterministic-journal-v1"
PROMPT_VERSION = "entry-draft-v1"
SCHEMA_VERSION = "journal-analysis-v1"
_OPEN_TASK_STATUS = {
    TaskStatus.TODO: "todo",
    TaskStatus.IN_PROGRESS: "in_progress",
    TaskStatus.BLOCKED: "blocked",
}


def _candidate_catalog(container: Container, session, owner_id: UUID) -> CandidateCatalog:  # type: ignore[no-untyped-def]
    """The visible, still-open records, the way the retired pipeline snapshotted them."""

    store = SqlAlchemyStore
    projects = [
        project
        for project in store.list_projects(session, owner_id, limit=51)
        if project.status is not ProjectStatus.COMPLETED
    ]
    tasks = [
        task
        for task in store.list_tasks(session, owner_id, limit=101)
        if task.status is not TaskStatus.COMPLETED
    ]
    contacts = store.list_contacts(session, owner_id, limit=50, include_archived=False)
    return CandidateCatalog(
        projects=[
            ProjectCandidate(
                id=project.id,
                label=project.title,
                status="active" if project.status is ProjectStatus.ACTIVE else "paused",
                version=project.version,
            )
            for project in projects
        ],
        tasks=[
            TaskCandidate(
                id=task.id,
                label=task.title,
                status=_OPEN_TASK_STATUS[task.status],  # type: ignore[arg-type]
                version=task.version,
                context=f"Priority {task.priority.value}",
            )
            for task in tasks
        ],
        contacts=[
            ContactCandidate(id=contact.id, label=contact.display_name, version=contact.version)
            for contact in contacts
        ],
    )


def seed_entry_draft(
    container: Container, actor: Actor, source_id: UUID, journal_date: date
) -> UUID:
    """Store a pending draft on `source_id` and return its id.

    The draft suggests the first open Task, Project or Contact in the owner's catalog and, when a
    Task exists, proposes a due date for it; with only a Project or Contact it proposes a
    follow-up Task instead.
    """

    store = container.journal_analysis.store
    now = datetime.now(UTC)
    run_id, draft_id = new_uuid7(), new_uuid7()
    fingerprint = hashlib.sha256(f"seed-draft:{source_id}".encode()).hexdigest()

    def operation(session) -> None:  # type: ignore[no-untyped-def]
        catalog = _candidate_catalog(container, session, actor.user_id)
        project = catalog.projects[0] if catalog.projects else None
        task = catalog.tasks[0] if catalog.tasks else None
        contact = catalog.contacts[0] if catalog.contacts else None
        proposal_id = UUID(hex=fingerprint[:32])
        proposals: list[CreateTaskProposal | UpdateTaskProposal] = []
        if task is not None:
            assert task.version is not None
            proposals.append(
                UpdateTaskProposal(
                    proposal_id=proposal_id,
                    type="update_task",
                    task_id=task.id,
                    expected_task_version=task.version,
                    due_at=datetime(2026, 7, 27, 9, tzinfo=timezone(timedelta(hours=2))),
                )
            )
        elif project is not None or contact is not None:
            proposals.append(
                CreateTaskProposal(
                    proposal_id=proposal_id,
                    type="create_task",
                    title="Följ upp journalanteckningen",
                    description=None,
                    project_id=project.id if project else None,
                    priority=TaskPriority.NORMAL,
                    due_at=None,
                    contact_ids=[contact.id] if contact else [],
                )
            )
        key_points = [
            KeyPoint(kind=KeyPointKind.DECISION, text="Ett beslut dokumenterades."),
            KeyPoint(kind=KeyPointKind.COMMITMENT, text="En uppföljning planerades."),
        ]
        session.add(
            JournalProcessingRunRow(
                id=run_id,
                owner_id=actor.user_id,
                source_id=source_id,
                operation="entry_draft",
                journal_date=journal_date,
                status="succeeded",
                provider=PROVIDER,
                model_id=MODEL_ID,
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                input_fingerprint=fingerprint,
                candidate_catalog=catalog.model_dump(mode="json"),
                provider_response_id=f"fake-{fingerprint[:24]}",
                failure_category=None,
                input_tokens=None,
                output_tokens=None,
                started_at=now,
                finished_at=now,
                lease_expires_at=None,
                attempt_count=1,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            JournalDraftRow(
                id=draft_id,
                owner_id=actor.user_id,
                source_id=source_id,
                processing_run_id=run_id,
                catalog_run_id=run_id,
                state="pending_review",
                title="Planering och uppföljning",
                summary="Anteckningen innehåller ett beslut och en planerad uppföljning.",
                key_points=[point.model_dump(mode="json") for point in key_points],
                relation_suggestions={
                    "projects": (
                        [{"project_id": str(project.id), "rationale": "Berör planeringen."}]
                        if project
                        else []
                    ),
                    "tasks": (
                        [{"task_id": str(task.id), "rationale": "Uppgiften ska följas upp."}]
                        if task
                        else []
                    ),
                    "contacts": (
                        [{"contact_id": str(contact.id), "rationale": "Kontakten är relevant."}]
                        if contact
                        else []
                    ),
                },
                task_proposals=[
                    proposal.model_dump(mode="json", exclude_unset=True) for proposal in proposals
                ],
                version=1,
                created_at=now,
                updated_at=now,
                lifecycle_at=None,
            )
        )
        session.flush()

    store.transaction(operation)
    return draft_id

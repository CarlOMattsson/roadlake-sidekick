"""What a caller's scopes leave of a Journal draft, decided without any framework or database."""

from typing import Any
from uuid import UUID, uuid4

import pytest

from sidekick.journal.domain.analysis import (
    CreateTaskProposal,
    DraftState,
    KeyPoint,
    TaskPriority,
    UpdateTaskProposal,
)
from sidekick.journal.domain.entry import KeyPointKind
from sidekick.journal.domain.review import (
    CandidateCatalog,
    DraftReview,
    ProjectCandidate,
    scope_draft,
)

JOURNAL_ONLY = frozenset({"journal:read"})
EVERYTHING = frozenset({"journal:read", "projects:read", "tasks:read", "contacts:read"})
PROJECT_ID = uuid4()
TASK_ID = uuid4()
CONTACT_ID = uuid4()


def _draft() -> DraftReview:
    # The suggestion items hold JSON values, as the store returns them: identifiers as text.
    create_with_project = CreateTaskProposal(
        proposal_id=uuid4(),
        type="create_task",
        title="Ring",
        description=None,
        project_id=PROJECT_ID,
        priority=TaskPriority.NORMAL,
        due_at=None,
        contact_ids=[],
    )
    create_plain = CreateTaskProposal(
        proposal_id=uuid4(),
        type="create_task",
        title="Skriv",
        description=None,
        project_id=None,
        priority=TaskPriority.NORMAL,
        due_at=None,
        contact_ids=[],
    )
    update = UpdateTaskProposal(
        proposal_id=uuid4(),
        type="update_task",
        task_id=TASK_ID,
        expected_task_version=1,
        title="Nytt",
    )
    placeholder: Any = None  # identity, source and run are not touched by the scope rules
    return DraftReview(
        id=uuid4(),
        owner_id=uuid4(),
        source=placeholder,
        state=DraftState.PENDING_REVIEW,
        title="Titel",
        summary="Sammanfattning",
        key_points=(KeyPoint(kind=KeyPointKind.FACT, text="En punkt"),),
        project_suggestions=({"project_id": str(PROJECT_ID), "rationale": "Passar"},),
        task_suggestions=({"task_id": str(TASK_ID), "rationale": "Samma"},),
        contact_suggestions=({"contact_id": str(CONTACT_ID), "rationale": "Nämnd"},),
        task_proposals=(create_with_project, create_plain, update),
        catalog=CandidateCatalog(
            projects=[ProjectCandidate(id=PROJECT_ID, label="Projekt", status="active")],
            tasks=[],
            contacts=[],
        ),
        run=placeholder,
        version=3,
    )


def test_a_caller_with_every_read_scope_sees_the_whole_draft() -> None:
    scoped = scope_draft(_draft(), EVERYTHING, include_content=True)

    assert scoped.summary == "Sammanfattning"
    assert [point.text for point in scoped.key_points] == ["En punkt"]
    assert [(link.id, link.rationale) for link in scoped.project_suggestions] == [
        (PROJECT_ID, "Passar")
    ]
    assert [link.id for link in scoped.task_suggestions] == [TASK_ID]
    assert [link.id for link in scoped.contact_suggestions] == [CONTACT_ID]
    assert len(scoped.task_proposals) == 3
    assert [candidate.id for candidate in scoped.catalog.projects] == [PROJECT_ID]


def test_without_the_related_read_scopes_the_draft_discloses_no_project_task_or_contact() -> None:
    scoped = scope_draft(_draft(), JOURNAL_ONLY, include_content=True)

    assert scoped.project_suggestions == scoped.task_suggestions == scoped.contact_suggestions == ()
    assert scoped.catalog == CandidateCatalog(projects=[], tasks=[], contacts=[])
    # Only the proposal that names neither a Project, a Task nor a Contact is left.
    assert [proposal.type for proposal in scoped.task_proposals] == ["create_task"]
    assert scoped.task_proposals[0].title == "Skriv"
    # The count is the draft's real count even when proposals are withheld.
    assert scoped.task_proposal_count == 3
    assert scoped.summary == "Sammanfattning"


def test_a_project_scope_alone_shows_the_project_proposal_but_not_the_task_update() -> None:
    scoped = scope_draft(_draft(), JOURNAL_ONLY | {"projects:read"}, include_content=True)

    assert sorted(p.title for p in scoped.task_proposals) == ["Ring", "Skriv"]


def test_without_include_content_only_identity_and_ids_remain() -> None:
    scoped = scope_draft(_draft(), EVERYTHING, include_content=False)

    assert scoped.summary is None
    assert scoped.key_points == ()
    assert scoped.task_proposals == ()
    assert scoped.catalog == CandidateCatalog(projects=[], tasks=[], contacts=[])
    assert [(link.id, link.rationale) for link in scoped.project_suggestions] == [
        (PROJECT_ID, None)
    ]
    assert scoped.task_proposal_count == 3
    assert scoped.draft.title == "Titel"


@pytest.mark.parametrize("scopes", [JOURNAL_ONLY, EVERYTHING])
def test_suggestion_identifiers_are_read_as_uuids(scopes: frozenset[str]) -> None:
    scoped = scope_draft(_draft(), scopes, include_content=True)

    assert all(isinstance(link.id, UUID) for link in scoped.project_suggestions)

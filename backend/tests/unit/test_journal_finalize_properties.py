"""Property-style tests for the reviewed Journal finalize boundary."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sidekick.journal.application.finalize import (
    JournalFinalizeService,
    validate_finalize_command,
)
from sidekick.journal.domain.analysis import CreateTaskProposal, UpdateTaskProposal
from sidekick.journal.domain.finalize import FinalizeCommand
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.types import Actor

OWNER = UUID("018af000-0000-7000-8000-000000000001")
PROJECT = UUID("01910000-0000-7000-8000-000000000011")
TASK = UUID("01910000-0000-7000-8000-000000000012")
CONTACT = UUID("01910000-0000-7000-8000-000000000013")
DRAFT = UUID("01910000-0000-7000-8000-000000000004")


def command(**overrides: object) -> FinalizeCommand:
    values: dict[str, object] = {
        "draft_id": DRAFT,
        "expected_version": 1,
        "title": "Planering",
        "summary": None,
        "key_points": (),
        "relation_selection": {
            "projects": ((PROJECT, "model_suggested"),),
            "tasks": ((TASK, "model_suggested"),),
            "contacts": ((CONTACT, "model_suggested"),),
        },
        "task_proposals": (),
    }
    values.update(overrides)
    return FinalizeCommand(**values)  # type: ignore[arg-type]


def test_model_bound_relations_must_come_from_the_immutable_catalog() -> None:
    with pytest.raises(ValidationError):
        validate_finalize_command(
            command(
                relation_selection={
                    "projects": ((UUID(int=99), "model_suggested"),),
                    "tasks": (),
                    "contacts": (),
                }
            ),
            catalog_ids={"projects": {PROJECT}, "tasks": {TASK}, "contacts": {CONTACT}},
            live_targets={},
        )


def test_user_selected_relations_are_live_and_owner_scoped() -> None:
    with pytest.raises(NotFoundError):
        validate_finalize_command(
            command(
                relation_selection={
                    "projects": (),
                    "tasks": (),
                    "contacts": ((CONTACT, "user_selected"),),
                }
            ),
            catalog_ids={"projects": {PROJECT}, "tasks": {TASK}, "contacts": {CONTACT}},
            live_targets={"contacts": {}},
        )


def test_update_task_preserves_omitted_fields_but_allows_explicit_null() -> None:
    proposal = UpdateTaskProposal.model_validate_json(
        """
        {"proposal_id":"01910000-0000-7000-8000-000000000014","type":"update_task",
         "task_id":"01910000-0000-7000-8000-000000000012","expected_task_version":3,
         "description":null}
        """
    )
    assert proposal.model_fields_set == {
        "proposal_id",
        "type",
        "task_id",
        "expected_task_version",
        "description",
    }
    assert "title" not in proposal.model_fields_set


def test_selected_create_and_update_effects_are_forwarded_exactly() -> None:
    create = CreateTaskProposal.model_validate_json(
        """
        {"proposal_id":"01910000-0000-7000-8000-000000000015","type":"create_task",
         "title":"Förbered underlag","description":"Exakt text",
         "project_id":"01910000-0000-7000-8000-000000000011","priority":"high",
         "due_at":"2026-07-28T10:30:00+02:00",
         "contact_ids":["01910000-0000-7000-8000-000000000013"]}
        """
    )
    update = UpdateTaskProposal.model_validate_json(
        """
        {"proposal_id":"01910000-0000-7000-8000-000000000016","type":"update_task",
         "task_id":"01910000-0000-7000-8000-000000000012","expected_task_version":3,
         "due_at":null}
        """
    )
    assert create.title == "Förbered underlag"
    assert create.description == "Exakt text"
    assert create.project_id == PROJECT
    assert create.contact_ids == [CONTACT]
    assert update.due_at is None and "due_at" in update.model_fields_set


class _ReplayStore:
    def __init__(self) -> None:
        self.operations: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
        self.effects = 0

    def transaction(self, operation):
        return operation(self)

    def idempotent(self, _session, *, actor_id, operation, key, payload, execute):
        identity = f"{actor_id}:{operation}:{key}"
        if identity in self.operations:
            old_payload, result = self.operations[identity]
            if old_payload != payload:
                raise ConflictError("idempotency conflict")
            return result
        result = execute()
        self.operations[identity] = (payload, result)
        return result

    def get_journal_draft(self, _session, _owner_id, _draft_id):
        return type(
            "Draft",
            (),
            {
                "catalog": type(
                    "Catalog",
                    (),
                    {
                        "projects": [type("Candidate", (), {"id": PROJECT})()],
                        "tasks": [type("Candidate", (), {"id": TASK, "version": 3})()],
                        "contacts": [type("Candidate", (), {"id": CONTACT})()],
                    },
                )(),
                "version": 1,
                "state": "pending_review",
            },
        )()

    def get_project(self, _session, _owner_id, identifier):
        if identifier != PROJECT:
            raise NotFoundError("project not found")
        return type("Project", (), {"status": "active"})()

    def get_task(self, _session, _owner_id, identifier):
        if identifier != TASK:
            raise NotFoundError("task not found")
        return type("Task", (), {"status": "todo"})()

    def get_contact(self, _session, _owner_id, identifier):
        if identifier != CONTACT:
            raise NotFoundError("contact not found")
        return type("Contact", (), {"archived": False})()

    def finalize_journal_draft(self, _session, **kwargs):
        self.effects += 1
        return {
            "entry_id": str(UUID("01910000-0000-7000-8000-000000000020")),
            "created_task_ids": [],
            "updated_task_ids": [],
        }

    def get_finalize_result(self, _session, _owner_id, result):
        return result


@given(st.sampled_from(["model_suggested", "user_selected"]))
def test_equal_replay_applies_one_logical_package(origin: str) -> None:
    store = _ReplayStore()
    service = JournalFinalizeService(
        store, clock=type("Clock", (), {"now": lambda self: datetime.now(UTC)})()
    )
    actor = Actor(
        user_id=OWNER,
        scopes=frozenset({"journal:write", "projects:read", "tasks:read", "contacts:read"}),
    )
    selection = {"projects": ((PROJECT, origin),), "tasks": (), "contacts": ()}
    if origin == "user_selected":
        store.get_project = lambda *_args: type("Project", (), {"status": "active"})()
    first = service.finalize(
        actor, command=command(relation_selection=selection), idempotency_key="same-key"
    )
    second = service.finalize(
        actor, command=command(relation_selection=selection), idempotency_key="same-key"
    )
    assert first == second
    assert store.effects == 1

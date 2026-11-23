"""Automations survive an export and a restore into another owner, with their references
rewritten and without the approval or the work in progress of the instance they came from."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container, create_container
from sidekick.automations.domain.automation import Automation, SuggestionCheck
from sidekick.automations.domain.spec import AutomationState, parse_spec, spec_digest
from sidekick.automations.domain.suggestion import DecidedBy, DecisionChannel, SuggestionState
from sidekick.automations.persistence import AutomationStore
from sidekick.owner_export.catalogue import COLLECTIONS_ADDED_IN_FORMAT_9
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan, verify_restorable
from sidekick.shared.persistence.models import (
    AutomationReportCursorRow,
    AutomationRunRow,
    ProjectRow,
    TaskRow,
)
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor, new_uuid7
from tests.db import database_factory
from tests.support.automation_rows import Sql, insert_datapoint, insert_run
from tests.support.automations import suggestion
from tests.support.older_export_formats import as_format_8
from tests.support.settings import make_settings

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
SCOPES = frozenset({"tasks:read", "tasks:write", "projects:read", "projects:write", "work:write"})
CANARY = "canary-automation-text"


class Source:
    """An owner with a project, a task, and one of everything the automation tables hold."""

    def __init__(self, factory: sessionmaker[Session], container: Container) -> None:
        self.factory = factory
        self.owner = container.auth.provision_user("restore-source", "Source")
        actor = Actor(self.owner, SCOPES)
        domain = container.contexts.create_domain(
            actor, name="Home", description=None, idempotency_key=f"domain-{uuid4()}"
        )
        self.project = container.projects.create(
            actor, title="Garden", domain_id=domain.id, idempotency_key=f"project-{uuid4()}"
        )
        self.task = container.tasks.create(
            actor, title="Plant", project_id=self.project.id, idempotency_key=f"task-{uuid4()}"
        )
        self.automation = self._automation()
        self.done_run, self.open_run, self.suggestion = self._seed()

    def _automation(self) -> Automation:
        spec = parse_spec(
            {
                "purpose": "Collect what the morning mail asks of me",
                "instruction": CANARY,
                "sources": ["mail"],
                "allowed_effects": ["create_task"],
            }
        )
        return Automation(
            id=new_uuid7(),
            owner_id=self.owner,
            title="Morning mail",
            spec=spec,
            state=AutomationState.ACTIVE,
            spec_digest=spec_digest(spec),
            approved_digest=spec_digest(spec),
            approved_at=NOW,
            last_run_at=NOW,
            version=3,
            created_at=NOW,
            updated_at=NOW,
        )

    def _seed(self) -> tuple[UUID, UUID, Any]:
        holder: dict[str, Any] = {}

        def write(session: Session) -> None:
            AutomationStore.save_automation(session, self.automation)
            session.flush()
            connection = session.connection()
            owner, automation = str(self.owner), str(self.automation.id)
            done = UUID(insert_run(connection, owner, automation, state="done", occurrence_key="a"))
            open_run = UUID(
                insert_run(
                    connection,
                    owner,
                    automation,
                    state="running",
                    occurrence_key="b",
                    worker_id="worker-1",
                    lease_until=Sql("now() + interval '5 minutes'"),
                    reserved_microusd=400_000,
                )
            )
            datapoint = UUID(insert_datapoint(connection, owner, automation, str(done)))
            applied = replace(
                suggestion(),
                id=new_uuid7(),
                owner_id=self.owner,
                automation_id=self.automation.id,
                run_id=done,
                dedupe_fingerprint="c" * 64,
                payload={"title": CANARY, "project_id": str(self.project.id)},
                proposed_payload={"title": CANARY, "project_id": str(self.project.id)},
                datapoint_ids=(datapoint,),
                state=SuggestionState.APPLIED,
                decided_at=NOW,
                decided_by=DecidedBy.YOU,
                decision_channel=DecisionChannel.APP,
                applied_kind="task",
                applied_id=self.task.id,
                applied_version=1,
            )
            AutomationStore.save_suggestion(session, applied, NOW)
            session.flush()
            AutomationStore.append_check(
                session,
                SuggestionCheck(
                    id=new_uuid7(),
                    owner_id=self.owner,
                    suggestion_id=applied.id,
                    run_id=done,
                    attempt=1,
                    checker="openai_compat",
                    model="checker",
                    verdict="ok",
                    confidence=97,
                    reason_codes=(),
                    checked_at=NOW,
                ),
            )
            session.add(
                AutomationReportCursorRow(
                    owner_id=self.owner, seen_until=NOW, version=1, updated_at=NOW
                )
            )
            holder.update(done=done, open=open_run, suggestion=applied)

        StoreBase(self.factory).transaction(write)
        return holder["done"], holder["open"], holder["suggestion"]


@pytest.fixture
def env() -> tuple[sessionmaker[Session], Container, Source, UUID]:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    source = Source(factory, container)
    target = container.auth.provision_user("restore-target", "Target")
    return factory, container, source, target


def _export(factory: sessionmaker[Session], owner: UUID) -> dict[str, Any]:
    return OwnerExportService(StoreBase(factory)).export(Actor(owner, frozenset()))


def _restore(factory: sessionmaker[Session], document: dict[str, Any], target: UUID) -> None:
    plan = build_restore_plan(document, target)
    assert plan.status == "ready", plan.unresolved_references
    OwnerRestoreService(StoreBase(factory)).restore(
        document, target_owner_id=target, expected_plan_checksum=plan.plan_checksum
    )


@pytest.mark.integration
def test_an_export_carries_every_automation_collection(
    env: tuple[sessionmaker[Session], Container, Source, UUID],
) -> None:
    factory, _, source, _ = env

    document = _export(factory, source.owner)

    counts = document["manifest"]["collection_counts"]
    assert {name: counts[name] for name in COLLECTIONS_ADDED_IN_FORMAT_9} == {
        "automations": 1,
        "automation_runs": 2,
        "automation_datapoints": 1,
        "automation_suggestions": 1,
        "automation_checks": 1,
        "automation_report_cursors": 1,
    }
    assert document["format_version"] == 9
    verify_restorable(document)


@pytest.mark.integration
def test_a_restore_into_another_owner_carries_the_automations_and_rewrites_their_references(
    env: tuple[sessionmaker[Session], Container, Source, UUID],
) -> None:
    factory, _, source, target = env
    before = _export(factory, source.owner)["collections"]

    _restore(factory, _export(factory, source.owner), target)

    with factory() as session:
        automation = AutomationStore.list_automations(session, target)[0]
        stored = AutomationStore.list_suggestions(session, target)[0]
        checks = AutomationStore.list_checks(session, target, stored.id)
        runs = {
            run.occurrence_key: run
            for run in session.scalars(
                select(AutomationRunRow).where(AutomationRunRow.owner_id == target)
            )
        }
        project = session.scalar(select(ProjectRow).where(ProjectRow.owner_id == target))
        task = session.scalar(select(TaskRow).where(TaskRow.owner_id == target))
        cursor = session.get(AutomationReportCursorRow, target)
    assert project is not None
    assert task is not None
    assert cursor is not None
    # The definition is the owner's own, but not approved on this instance.
    assert automation.spec == source.automation.spec
    assert automation.spec_digest == source.automation.spec_digest
    assert automation.state is AutomationState.ACTIVE
    assert (automation.approved_digest, automation.approved_at) == (None, None)
    assert automation.id != source.automation.id
    # The suggestion points at the target's own records.
    assert stored.automation_id == automation.id
    assert stored.payload["project_id"] == str(project.id)
    assert stored.proposed_payload["project_id"] == str(project.id)
    assert stored.applied_id == task.id
    assert stored.rationale == source.suggestion.rationale
    assert str(source.project.id) not in json.dumps(dict(stored.payload))
    assert {check.suggestion_id for check in checks} == {stored.id}
    assert cursor.seen_until == NOW
    # Work in progress is cancelled, a finished run is as it was.
    assert runs["a"].state == "done"
    assert runs["b"].state == "cancelled"
    assert (runs["b"].lease_until, runs["b"].worker_id, runs["b"].reserved_microusd) == (
        None,
        None,
        0,
    )
    assert {run.owner_id for run in runs.values()} == {target}
    # The source is as it was.
    assert _export(factory, source.owner)["collections"] == before


@pytest.mark.integration
def test_what_a_restore_wrote_exports_again_with_the_same_counts_and_restores_in_turn(
    env: tuple[sessionmaker[Session], Container, Source, UUID],
) -> None:
    factory, container, source, target = env
    _restore(factory, _export(factory, source.owner), target)
    again = _export(factory, target)
    third = container.auth.provision_user("restore-third", "Third")

    original = _export(factory, source.owner)["manifest"]["collection_counts"]
    assert again["manifest"]["collection_counts"] == original
    _restore(factory, again, third)

    with factory() as session:
        assert len(AutomationStore.list_automations(session, third)) == 1
        assert len(AutomationStore.list_suggestions(session, third)) == 1


@pytest.mark.integration
def test_a_format_8_export_restores_without_automations_and_leaves_the_target_empty(
    env: tuple[sessionmaker[Session], Container, Source, UUID],
) -> None:
    factory, _, source, target = env
    older = as_format_8(_export(factory, source.owner), "124_journal_attachment_details")

    _restore(factory, older, target)

    with factory() as session:
        assert not AutomationStore.list_automations(session, target)
        assert not AutomationStore.list_suggestions(session, target)
        assert session.get(AutomationReportCursorRow, target) is None
        assert session.scalar(select(TaskRow).where(TaskRow.owner_id == target)) is not None


@pytest.mark.integration
def test_the_automation_text_is_in_the_export_but_never_in_the_plan_or_the_restore_result(
    env: tuple[sessionmaker[Session], Container, Source, UUID],
) -> None:
    factory, _, source, target = env
    document = _export(factory, source.owner)
    assert CANARY in json.dumps(document)

    plan = build_restore_plan(document, target)
    result = OwnerRestoreService(StoreBase(factory)).restore(
        document, target_owner_id=target, expected_plan_checksum=plan.plan_checksum
    )

    assert CANARY not in json.dumps(plan.as_dict())
    assert CANARY not in repr(result)

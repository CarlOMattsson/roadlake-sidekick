"""Public data shapes of Domains, Processes and the Work records of lists, agendas and boards."""

from collections.abc import Sequence
from datetime import UTC, datetime, tzinfo
from typing import TypedDict
from uuid import UUID

from sidekick.projects.domain import Project
from sidekick.tasks.domain import Task
from sidekick.work.application.models import HierarchyNode, WorkRow
from sidekick.work.domain import Action, Domain, DomainStatus, Process, ProcessStatus, Step
from sidekick.work.domain.planning import is_actionable_now
from sidekick.work.listing import project_due_at, project_earliest_start


class DomainPublicData(TypedDict):
    """A Domain's public contract: no internal ownership fields."""

    id: str
    name: str
    description: str | None
    status: str
    created_at: str
    updated_at: str
    version: int
    review_cadence: str | None
    last_reviewed_at: str | None
    accent: str | None
    tags: list[str]


class ProcessPublicData(TypedDict):
    """A Process's public contract: no internal ownership fields."""

    id: str
    domain_id: str
    name: str
    description: str | None
    status: str
    created_at: str
    updated_at: str
    version: int
    cadence: str | None
    tags: list[str]


def domain_public_data(domain: Domain, tags: Sequence[str] = ()) -> DomainPublicData:
    return {
        "id": str(domain.id),
        "name": domain.name,
        "description": domain.description,
        "status": domain.status.value,
        "created_at": domain.created_at.isoformat(),
        "updated_at": domain.updated_at.isoformat(),
        "version": domain.version,
        "review_cadence": domain.review_cadence.value if domain.review_cadence else None,
        "last_reviewed_at": (
            domain.last_reviewed_at.isoformat() if domain.last_reviewed_at else None
        ),
        "accent": domain.accent,
        "tags": list(tags),
    }


def domain_hierarchy_node(domain: Domain) -> HierarchyNode:
    return HierarchyNode(
        kind="domain",
        id=domain.id,
        parent_id=None,
        title=domain.name,
        status=domain.status.value,
        version=domain.version,
        accent=domain.accent,
    )


def process_hierarchy_node(process: Process) -> HierarchyNode:
    """The hierarchy node of one Process; `hierarchy_page` and a Process-only read share it."""

    return HierarchyNode(
        kind="process",
        id=process.id,
        parent_id=process.domain_id,
        title=process.name,
        status=process.status.value,
        version=process.version,
    )


def project_hierarchy_node(project: Project) -> HierarchyNode:
    return HierarchyNode(
        kind="project",
        id=project.id,
        parent_id=project.domain_id,
        title=project.title,
        status=project.status.value,
        version=project.version,
    )


def process_public_data(process: Process, tags: Sequence[str] = ()) -> ProcessPublicData:
    return {
        "id": str(process.id),
        "domain_id": str(process.domain_id),
        "name": process.name,
        "description": process.description,
        "status": process.status.value,
        "created_at": process.created_at.isoformat(),
        "updated_at": process.updated_at.isoformat(),
        "version": process.version,
        "cadence": process.cadence.value if process.cadence else None,
        "tags": list(tags),
    }


MAX_PROJECT_TITLE_CHARS = 120


def clipped_project_title(title: str | None) -> str | None:
    """A Project title as a Work record names it: at most 120 characters, the last one `…`."""

    if title is None or len(title) <= MAX_PROJECT_TITLE_CHARS:
        return title
    return title[: MAX_PROJECT_TITLE_CHARS - 1] + "…"


def task_work_item(
    task: Task,
    parent_id: UUID | None,
    *,
    tags: tuple[str, ...] = (),
    now: datetime | None = None,
    project_title: str | None = None,
    domain_accent: str | None = None,
) -> WorkRow:
    at = now or datetime.now(UTC)
    return WorkRow(
        kind="task",
        id=task.id,
        parent_id=parent_id,
        title=task.title,
        status=task.status.value,
        priority=task.priority.value,
        due_at=task.due_at,
        attention_requested=task.attention_requested,
        version=task.version,
        archived=task.archived_at is not None,
        domain_id=task.domain_id,
        process_id=task.process_id,
        project_id=task.project_id,
        project_title=project_title,
        domain_accent=domain_accent,
        task_id=task.id,
        earliest_start=task.not_before,
        actionable_now=is_actionable_now(task.not_before, at),
        estimated_minutes=task.estimated_minutes,
        waiting=task.waiting,
        waiting_since=task.waiting_since,
        follow_up_at=task.follow_up_at,
        waiting_on_contact_id=task.waiting_on_contact_id,
        follow_up_due=task.follow_up_due(now=at),
        blocked_reminder_due=task.blocked_reminder_due(now=at),
        blocked_reminder_cadence=(
            task.blocked_reminder_cadence.value if task.blocked_reminder_cadence else None
        ),
        blocked_reminder_snoozed_until=task.blocked_reminder_snoozed_until,
        recurrence=task.recurrence.to_data() if task.recurrence else None,
        last_completed_at=task.last_completed_at,
        tags=tags,
    )


def domain_work_item(
    domain: Domain, *, tags: tuple[str, ...] = (), now: datetime | None = None
) -> WorkRow:
    at = now or datetime.now(UTC)
    return WorkRow(
        kind="domain",
        id=domain.id,
        parent_id=None,
        title=domain.name,
        status=domain.status.value,
        priority=None,
        due_at=None,
        attention_requested=False,
        version=domain.version,
        archived=domain.status is DomainStatus.ARCHIVED,
        domain_id=domain.id,
        review_cadence=domain.review_cadence.value if domain.review_cadence else None,
        review_due=domain.review_due(now=at),
        tags=tags,
    )


def process_work_item(process: Process, *, tags: tuple[str, ...] = ()) -> WorkRow:
    return WorkRow(
        kind="process",
        id=process.id,
        parent_id=process.domain_id,
        title=process.name,
        status=process.status.value,
        priority=None,
        due_at=None,
        attention_requested=False,
        version=process.version,
        archived=process.status is ProcessStatus.ARCHIVED,
        domain_id=process.domain_id,
        process_id=process.id,
        cadence=process.cadence.value if process.cadence else None,
        tags=tags,
    )


def project_work_item(
    project: Project,
    zone: tzinfo,
    *,
    tags: tuple[str, ...] = (),
    now: datetime | None = None,
    domain_accent: str | None = None,
) -> WorkRow:
    at = now or datetime.now(UTC)
    due_at = project_due_at(project.target_date, zone) if project.target_date is not None else None
    earliest_start = (
        project_earliest_start(project.start_date, zone) if project.start_date is not None else None
    )
    return WorkRow(
        kind="project",
        id=project.id,
        parent_id=project.domain_id,
        title=project.title,
        status=project.status.value,
        priority=None,
        due_at=due_at,
        attention_requested=False,
        version=project.version,
        archived=project.archived_at is not None,
        domain_id=project.domain_id,
        domain_accent=domain_accent,
        project_id=project.id,
        earliest_start=earliest_start,
        actionable_now=is_actionable_now(earliest_start, at),
        tags=tags,
    )


def step_work_item(step: Step, parent_id: UUID) -> WorkRow:
    return WorkRow(
        kind="step",
        id=step.id,
        parent_id=parent_id,
        title=step.title,
        status=step.status.value,
        priority=None,
        due_at=step.due_at,
        attention_requested=step.attention_requested,
        version=step.version,
        archived=step.archived_at is not None,
        task_id=step.task_id,
    )


def action_work_item(action: Action, parent_id: UUID) -> WorkRow:
    return WorkRow(
        kind="action",
        id=action.id,
        parent_id=parent_id,
        title=action.title,
        status=action.status.value,
        priority=None,
        due_at=action.due_at,
        attention_requested=action.attention_requested,
        version=action.version,
        archived=action.archived_at is not None,
    )

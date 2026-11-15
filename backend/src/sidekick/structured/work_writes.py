"""The structured content of the Task and Project writes that both the MCP tools and the
companion API call: create a Task, update a Project.

Each function calls the same application use case for both interfaces and returns the closed
record payload; the MCP tools add their card text on top. Updating a Task is
`sidekick.structured.work.update_task_structured`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sidekick.projects.application import UpdateProjectCommand
from sidekick.shared.types import Actor
from sidekick.structured.work import project_record, task_record
from sidekick.structured.work_records import (
    ProjectOutput,
    TaskOutput,
    end_of_day_due_at,
)
from sidekick.tasks.domain import Priority

if TYPE_CHECKING:
    from sidekick.composition import Container


def create_task_structured(
    container: Container,
    actor: Actor,
    *,
    title: str,
    idempotency_key: str,
    project_id: UUID | None = None,
    domain_id: UUID | None = None,
    process_id: UUID | None = None,
    contact_ids: Sequence[UUID] = (),
    description: str | None = None,
    priority: str = "normal",
    due_at: datetime | date | None = None,
    not_before: datetime | None = None,
    estimated_minutes: int | None = None,
    tags: Sequence[str] = (),
    correlation_id: str | None = None,
) -> TaskOutput:
    """Create one Task through `TaskService.create`; the structured content of `create_task`.

    A bare `due_at` date means the end of that day in the owner's zone. Task and Contact links
    share one transaction in the service: an unknown Contact fails the whole call and leaves no
    Task behind."""

    # The reply lists the tags (projects:read), so refuse before anything is written.
    container.work_tags.require_record_tags_readable(actor, "task")
    task = container.tasks.create(
        actor,
        title=title,
        idempotency_key=idempotency_key,
        project_id=project_id,
        domain_id=domain_id,
        process_id=process_id,
        description=description,
        priority=Priority(priority),
        due_at=end_of_day_due_at(due_at, container.settings.owner_zone),
        not_before=not_before,
        estimated_minutes=estimated_minutes,
        tags=tuple(tags),
        contact_ids=tuple(contact_ids),
        correlation_id=correlation_id,
    )
    slugs = [tag.slug for tag in container.work_tags.for_record(actor, "task", task.id)]
    return TaskOutput(task=task_record(task, slugs))


def update_project_structured(
    container: Container,
    actor: Actor,
    project_id: UUID,
    *,
    version: int,
    idempotency_key: str,
    command: UpdateProjectCommand,
    correlation_id: str | None = None,
) -> ProjectOutput:
    """Update one Project through `ProjectService.update`; the structured content of
    `update_project`."""

    # The reply lists the record's tags (projects:read); refuse before anything is written.
    container.work_tags.require_record_tags_readable(actor, "project")
    project = container.projects.update(
        actor,
        project_id,
        version=version,
        idempotency_key=idempotency_key,
        command=command,
        correlation_id=correlation_id,
    )
    slugs = [tag.slug for tag in container.work_tags.for_record(actor, "project", project_id)]
    return ProjectOutput(project=project_record(project, slugs))

"""Row to domain mappers for projects."""

from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.persistence.models import (
    ProjectRow,
)


def project_from_row(row: ProjectRow) -> Project:
    return Project(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        description=row.description,
        status=ProjectStatus(row.status),
        start_date=row.start_date,
        target_date=row.target_date,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
        domain_id=row.domain_id,
        archived_at=row.archived_at,
        definition_of_done=row.definition_of_done,
    )


def project_to_row(project: Project) -> ProjectRow:
    return ProjectRow(
        id=project.id,
        owner_id=project.owner_id,
        domain_id=project.domain_id,
        title=project.title,
        description=project.description,
        status=project.status.value,
        start_date=project.start_date,
        target_date=project.target_date,
        created_at=project.created_at,
        updated_at=project.updated_at,
        archived_at=project.archived_at,
        version=project.version,
        definition_of_done=project.definition_of_done,
    )

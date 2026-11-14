"""Plain-data serialisation of a Project, shared by the transports."""

from __future__ import annotations

from typing import TypedDict

from sidekick.projects.domain import Project


class ProjectPublicData(TypedDict):
    """A Project as the public contract carries it: JSON values, no ownership fields."""

    id: str
    title: str
    description: str | None
    status: str
    start_date: str | None
    target_date: str | None
    created_at: str
    updated_at: str
    version: int
    domain_id: str | None
    archived_at: str | None
    definition_of_done: str | None


def project_public_data(project: Project) -> ProjectPublicData:
    return {
        "id": str(project.id),
        "title": project.title,
        "description": project.description,
        "status": project.status.value,
        "start_date": project.start_date.isoformat() if project.start_date else None,
        "target_date": project.target_date.isoformat() if project.target_date else None,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "version": project.version,
        "domain_id": str(project.domain_id) if project.domain_id else None,
        "archived_at": project.archived_at.isoformat() if project.archived_at else None,
        "definition_of_done": project.definition_of_done,
    }

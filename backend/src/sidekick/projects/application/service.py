"""Transport-neutral Project commands and queries."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.errors import ConflictError, InvalidInputError
from sidekick.shared.replay import id_replay_record
from sidekick.shared.types import (
    TIMED_KEY,
    UNSET,
    Actor,
    AuditingStore,
    Clock,
    CursorCodec,
    IdempotentStore,
    KeyValue,
    Page,
    TransactionalStore,
    TxSession,
    UnsetType,
    new_uuid7,
    paginate,
    validate_limit,
)
from sidekick.work.domain import Domain
from sidekick.work.domain.planning import WorkTag
from sidekick.work.domain.tag_assignment import apply_record_tags

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class UpdateProjectCommand:
    """Explicit mutable Project fields; omitted and null remain distinct."""

    title: str | UnsetType = UNSET
    description: str | None | UnsetType = UNSET
    status: ProjectStatus | UnsetType = UNSET
    start_date: date | None | UnsetType = UNSET
    """The project's earliest start: the project-level counterpart of `not_before`."""
    target_date: date | None | UnsetType = UNSET
    domain_id: UUID | None | UnsetType = UNSET
    definition_of_done: str | None | UnsetType = UNSET
    tags: tuple[str, ...] | UnsetType = UNSET

    def changes(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "title": self.title,
                "description": self.description,
                "status": self.status,
                "start_date": self.start_date,
                "target_date": self.target_date,
                "domain_id": self.domain_id,
                "definition_of_done": self.definition_of_done,
            }.items()
            if value is not UNSET
        }

    def has_changes(self) -> bool:
        return bool(self.changes()) or self.tags is not UNSET


class ProjectStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    """Concrete port needed for atomic Project and idempotency operations."""

    def list_projects(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        status: ProjectStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Project]: ...
    def get_project(
        self, session: TxSession, owner_id: UUID, project_id: UUID, include_archived: bool = False
    ) -> Project: ...
    def find_work_tag_by_slug(
        self, session: TxSession, owner_id: UUID, slug: str
    ) -> WorkTag | None: ...
    def save_work_tag(
        self, session: TxSession, tag: Any, expected_version: int | None = None
    ) -> None: ...
    def replace_record_tags(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: str,
        record_id: UUID,
        tag_ids: tuple[UUID, ...],
    ) -> None: ...
    def get_domain(self, session: TxSession, owner_id: UUID, domain_id: UUID) -> Domain: ...
    def save_project(
        self, session: TxSession, project: Project, expected_version: int | None = None
    ) -> None: ...


class ProjectService:
    def __init__(self, store: ProjectStore, clock: Clock, cursor_codec: CursorCodec) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec

    def _replayed(self, session: TxSession, actor: Actor, record: dict[str, Any]) -> Project:
        """The Project a (possibly replayed) write refers to, re-read by id.

        The idempotency record keeps only the id, so a retry returns the Project as it is now,
        archived or not.
        """

        return self.store.get_project(
            session, actor.user_id, UUID(record["id"]), include_archived=True
        )

    def list(
        self,
        actor: Actor,
        *,
        limit: int = 25,
        status: ProjectStatus | None = None,
        cursor: str | None = None,
        include_archived: bool = False,
    ) -> Page[Project]:
        actor.require("projects:read")
        validate_limit(limit, maximum=100)
        query_key = (
            f"projects:v2:status={status.value if status else '*'}:archived={include_archived}"
        )
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=TIMED_KEY)
        projects = self.store.transaction(
            lambda session: self.store.list_projects(
                session, actor.user_id, limit + 1, status, after, include_archived
            )
        )
        return Page(
            *paginate(
                projects,
                limit,
                lambda last: self.cursor_codec.encode_keyset(
                    actor.user_id, (last.updated_at, last.id), query_key
                ),
            )
        )

    def get(self, actor: Actor, project_id: UUID) -> Project:
        actor.require("projects:read")
        return self.store.transaction(
            lambda session: self.store.get_project(session, actor.user_id, project_id)
        )

    def archive(
        self,
        actor: Actor,
        project_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Project:
        return self._set_archive(
            actor,
            project_id,
            version=version,
            archived=True,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def restore(
        self,
        actor: Actor,
        project_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Project:
        return self._set_archive(
            actor,
            project_id,
            version=version,
            archived=False,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def complete(
        self,
        actor: Actor,
        project_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Project:
        actor.require("projects:write")
        payload = {"project_id": str(project_id), "version": version}

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.get_project(
                session, actor.user_id, project_id, include_archived=True
            )
            if current.version != version:
                raise ConflictError("stale project version")
            updated = current.complete(now=self.clock.now())
            if updated is not current:
                self.store.save_project(session, updated, expected_version=version)
                self.store.append_audit(
                    session,
                    actor_id=actor.user_id,
                    event="project.completed",
                    outcome="success",
                    target_type="project",
                    target_id=project_id,
                    correlation_id=correlation_id,
                )
            return project_to_data(updated)

        return self.store.transaction(
            lambda session: self._replayed(
                session,
                actor,
                self.store.idempotent(
                    session,
                    actor_id=actor.user_id,
                    operation="complete_project",
                    key=idempotency_key,
                    payload=payload,
                    execute=lambda: operation(session),
                    replay=id_replay_record,
                ),
            )
        )

    def _set_archive(
        self,
        actor: Actor,
        project_id: UUID,
        *,
        version: int,
        archived: bool,
        idempotency_key: str,
        correlation_id: str | None,
    ) -> Project:
        actor.require("projects:write")
        payload = {"project_id": str(project_id), "version": version, "archived": archived}

        def operation(session: TxSession) -> dict[str, Any]:
            return self._archive_data(
                session,
                actor,
                project_id,
                version,
                archived=archived,
                correlation_id=correlation_id,
            )

        return self.store.transaction(
            lambda session: self._replayed(
                session,
                actor,
                self.store.idempotent(
                    session,
                    actor_id=actor.user_id,
                    operation="archive_project" if archived else "restore_project",
                    key=idempotency_key,
                    payload=payload,
                    execute=lambda: operation(session),
                    replay=id_replay_record,
                ),
            )
        )

    def _archive(
        self,
        session: TxSession,
        actor: Actor,
        project_id: UUID,
        version: int,
        correlation_id: str | None = None,
    ) -> Project:
        """Session-taking primitive for cross-service composition (revert, batch apply).

        Callers are responsible for their own `Actor.require` and idempotency, mirroring
        `TaskService._archive` and `StepsService._archive_step`.
        """

        return project_from_data(
            self._archive_data(
                session,
                actor,
                project_id,
                version,
                archived=True,
                correlation_id=correlation_id,
            )
        )

    def _archive_data(
        self,
        session: TxSession,
        actor: Actor,
        project_id: UUID,
        version: int,
        *,
        archived: bool,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        current = self.store.get_project(session, actor.user_id, project_id, include_archived=True)
        if current.version != version:
            raise ConflictError("stale project version")
        now = self.clock.now()
        updated = current.archive(now=now) if archived else current.restore(now=now)
        self.store.save_project(session, updated, expected_version=version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="project.archived" if archived else "project.restored",
            outcome="success",
            target_type="project",
            target_id=project_id,
            correlation_id=correlation_id,
        )
        return project_to_data(updated)

    def create(
        self,
        actor: Actor,
        *,
        title: str,
        description: str | None = None,
        start_date: date | None = None,
        target_date: date | None = None,
        domain_id: UUID,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Project:
        actor.require("projects:write")
        payload = {
            "title": title,
            "description": description,
            "start_date": start_date,
            "target_date": target_date,
            "domain_id": domain_id,
        }

        def operation(session: TxSession) -> Project:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_project",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._create(session, actor, payload, correlation_id),
                replay=id_replay_record,
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _create(
        self,
        session: TxSession,
        actor: Actor,
        payload: dict[str, Any],
        correlation_id: str | None,
    ) -> dict[str, Any]:
        domain_id = payload["domain_id"]
        if not isinstance(domain_id, UUID):
            raise ConflictError("project domain is required")
        get_domain = getattr(self.store, "get_domain", None)
        if callable(get_domain):
            get_domain(session, actor.user_id, domain_id)
        now = self.clock.now()
        project = Project(
            id=new_uuid7(),
            owner_id=actor.user_id,
            title=payload["title"],
            description=payload["description"],
            status=ProjectStatus.ACTIVE,
            start_date=payload["start_date"],
            target_date=payload["target_date"],
            domain_id=domain_id,
            created_at=now,
            updated_at=now,
        )
        self.store.save_project(session, project)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="project.created",
            outcome="success",
            target_type="project",
            target_id=project.id,
            correlation_id=correlation_id,
        )
        return project_to_data(project)

    def update(
        self,
        actor: Actor,
        project_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        command: UpdateProjectCommand,
        correlation_id: str | None = None,
    ) -> Project:
        actor.require("projects:write")
        changes = command.changes()
        if not command.has_changes():
            raise InvalidInputError("at least one change is required")
        payload: dict[str, Any] = {"project_id": str(project_id), "version": version, **changes}
        if command.tags is not UNSET:
            payload["tags"] = list(command.tags)

        def operation(session: TxSession) -> Project:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="update_project",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._update(
                    session, actor, project_id, version, command, correlation_id
                ),
                replay=id_replay_record,
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _update(
        self,
        session: TxSession,
        actor: Actor,
        project_id: UUID,
        version: int,
        command: UpdateProjectCommand,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        project = self.store.get_project(session, actor.user_id, project_id)
        changes = command.changes()
        new_domain = changes.get("domain_id")
        get_domain = getattr(self.store, "get_domain", None)
        if isinstance(new_domain, UUID) and callable(get_domain):
            # The target Domain must be the caller's own: another owner's id is `not_found`, as on
            # create, and never reaches the composite foreign key as an unexpected error.
            get_domain(session, actor.user_id, new_domain)
        now = self.clock.now()
        updated = project.update(now=now, **changes) if changes else project
        # Tags are relations but part of the Project's optimistic-concurrency surface, as for
        # Tasks: a tags-only update advances the version under the caller's expected version.
        if command.tags is not UNSET and updated is project:
            updated = replace(project, version=project.version + 1, updated_at=now)
        if updated is not project:
            self.store.save_project(session, updated, expected_version=version)
        if command.tags is not UNSET:
            apply_record_tags(
                self.store,
                session,
                owner_id=actor.user_id,
                kind="project",
                record_id=project_id,
                values=command.tags,
                now=now,
            )
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="project.updated",
            outcome="success",
            target_type="project",
            target_id=project.id,
            correlation_id=correlation_id,
        )
        return project_to_data(updated)


def project_to_data(project: Project) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "owner_id": str(project.owner_id),
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


def project_public_data(project: Project) -> dict[str, Any]:
    """Serialize the public contract without internal ownership fields."""

    data = project_to_data(project)
    data.pop("owner_id")
    return data


def project_from_data(data: dict[str, Any]) -> Project:
    return Project(
        id=UUID(data["id"]),
        owner_id=UUID(data["owner_id"]),
        title=data["title"],
        description=data["description"],
        status=ProjectStatus(data["status"]),
        start_date=date.fromisoformat(data["start_date"]) if data["start_date"] else None,
        target_date=date.fromisoformat(data["target_date"]) if data["target_date"] else None,
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        version=data["version"],
        domain_id=UUID(data["domain_id"]),
        archived_at=(
            datetime.fromisoformat(data["archived_at"]) if data.get("archived_at") else None
        ),
        definition_of_done=data.get("definition_of_done"),
    )

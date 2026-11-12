"""Framework-free test doubles for application use cases."""

import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, TypeVar
from uuid import UUID

from sidekick.contacts.domain.normalization import normalize_email, normalize_name, normalize_phone
from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.types import CursorCodec
from sidekick.tasks.domain import Task, TaskStatus, TaskStatusHistory

T = TypeVar("T")


def make_cursor_codec() -> CursorCodec:
    """A fresh codec with a random key: tests never share a constant signing secret."""

    return CursorCodec(secrets.token_urlsafe(32))


class InMemoryStore:
    def __init__(self) -> None:
        self.projects: dict[UUID, Project] = {}
        self.tasks: dict[UUID, Task] = {}
        self.contacts: dict[UUID, Any] = {}
        self.project_contacts: dict[tuple[UUID, UUID], Any] = {}
        self.task_contacts: dict[tuple[UUID, UUID], Any] = {}
        self.operations: dict[tuple[UUID, str, str], tuple[str, dict[str, Any]]] = {}
        self.audit_events: list[dict[str, Any]] = []
        self.task_status_history: list[TaskStatusHistory] = []

    def transaction(self, operation: Callable[["InMemoryStore"], T]) -> T:
        return operation(self)

    def idempotent(
        self,
        session: Any,
        *,
        actor_id: UUID,
        operation: str,
        key: str,
        payload: dict[str, Any],
        execute: Callable[[], dict[str, Any]],
        replay: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        del session
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        identity = (actor_id, operation, key)
        previous = self.operations.get(identity)
        if previous:
            if previous[0] != digest:
                raise ConflictError("idempotency conflict")
            return previous[1]
        result = execute()
        record = replay(result) if replay else result
        self.operations[identity] = (digest, record)
        return record

    def append_audit(
        self,
        session: Any,
        *,
        actor_id: UUID | None,
        event: str,
        outcome: str,
        target_type: str | None = None,
        target_id: UUID | None = None,
        related_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> None:
        del session
        self.audit_events.append(
            {
                "actor_id": actor_id,
                "event": event,
                "outcome": outcome,
                "target_type": target_type,
                "target_id": target_id,
                "related_id": related_id,
                "correlation_id": correlation_id,
            }
        )

    def list_projects(
        self,
        session: Any,
        owner_id: UUID,
        limit: int,
        status: Any = None,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[Project]:
        del session
        owned = [
            project
            for project in self.projects.values()
            if project.owner_id == owner_id and (include_archived or project.archived_at is None)
        ]
        if status is not None:
            owned = [project for project in owned if project.status is status]
        return sorted(owned, key=lambda project: (project.updated_at, project.id), reverse=True)[
            offset : offset + limit
        ]

    def get_project(
        self, session: Any, owner_id: UUID, project_id: UUID, include_archived: bool = False
    ) -> Project:
        del session
        project = self.projects.get(project_id)
        if (
            project is None
            or project.owner_id != owner_id
            or (not include_archived and project.archived_at is not None)
        ):
            raise NotFoundError("project not found")
        return project

    def project_domain_ids(
        self, session: Any, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]:
        del session
        return {
            project_id: self.projects[project_id].domain_id
            for project_id in project_ids
            if project_id in self.projects and self.projects[project_id].owner_id == owner_id
        }

    def process_domain_ids(
        self, session: Any, owner_id: UUID, process_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]:
        # The in-memory store holds no Processes, so no Process names a Domain.
        del session, owner_id, process_ids
        return {}

    def save_project(
        self, session: Any, project: Project, expected_version: int | None = None
    ) -> None:
        del session
        current = self.projects.get(project.id)
        if current and expected_version is not None and current.version != expected_version:
            raise ConflictError("stale project version")
        self.projects[project.id] = project

    def list_tasks(
        self,
        session: Any,
        owner_id: UUID,
        limit: int,
        project_id: UUID | None = None,
        status: TaskStatus | None = None,
        offset: int = 0,
        process_id: UUID | None = None,
        unsorted: bool = False,
    ) -> list[Task]:
        del session
        owned = [
            task
            for task in self.tasks.values()
            if task.owner_id == owner_id
            and (project_id is None or task.project_id == project_id)
            and (process_id is None or task.process_id == process_id)
            and (status is None or task.status is status)
            and (
                not unsorted
                or (task.domain_id is None and task.project_id is None and task.process_id is None)
            )
        ]
        return sorted(owned, key=lambda task: (task.updated_at, task.id), reverse=True)[
            offset : offset + limit
        ]

    def get_task(
        self,
        session: Any,
        owner_id: UUID,
        task_id: UUID,
        include_archived: bool = False,
        for_update: bool = False,
        include_hidden: bool = False,
    ) -> Task:
        del session, for_update, include_hidden
        task = self.tasks.get(task_id)
        if (
            task is None
            or task.owner_id != owner_id
            or (task.archived_at is not None and not include_archived)
        ):
            raise NotFoundError("task not found")
        return task

    def save_task(self, session: Any, task: Task, expected_version: int | None = None) -> None:
        del session
        current = self.tasks.get(task.id)
        if current and expected_version is not None and current.version != expected_version:
            raise ConflictError("stale task version", reason="stale_version")
        self.tasks[task.id] = task

    def append_task_status_history(
        self,
        session: Any,
        *,
        owner_id: UUID,
        task_id: UUID,
        from_status: TaskStatus | None,
        to_status: TaskStatus,
        changed_at: datetime,
        source: str,
    ) -> None:
        del session
        self.task_status_history.append(
            TaskStatusHistory(
                id=UUID(int=len(self.task_status_history) + 1),
                owner_id=owner_id,
                task_id=task_id,
                from_status=from_status,
                to_status=to_status,
                changed_at=changed_at,
                source=source,
            )
        )

    def list_task_status_history(
        self, session: Any, owner_id: UUID, task_id: UUID, limit: int
    ) -> list[TaskStatusHistory]:
        del session
        return [
            item
            for item in reversed(self.task_status_history)
            if item.owner_id == owner_id and item.task_id == task_id
        ][:limit]

    def list_contacts(
        self,
        session: Any,
        owner_id: UUID,
        limit: int,
        q: str | None = None,
        include_archived: bool = False,
        offset: int = 0,
    ) -> list[Any]:
        del session
        results = []
        for contact in self.contacts.values():
            if contact.owner_id != owner_id:
                continue
            if not include_archived and contact.archived:
                continue
            if q:
                norm_q = normalize_name(q)[1]
                match_display = norm_q in contact.display_name_key
                match_alias = any(
                    norm_q in normalize_name(alias.value)[1] for alias in contact.aliases
                )
                email_key = normalize_email(q)[1] if "@" in q else None
                try:
                    phone_key = normalize_phone(q)[1]
                except ValidationError:
                    phone_key = None
                if not (
                    match_display
                    or match_alias
                    or email_key == contact.email_key
                    or phone_key == contact.phone_key
                ):
                    continue
            results.append(contact)
        results.sort(key=lambda x: (normalize_name(x.display_name)[1], x.id))
        return results[offset : offset + limit]

    def get_contact(
        self, session: Any, owner_id: UUID, contact_id: UUID, include_archived: bool = False
    ) -> Any:
        del session
        contact = self.contacts.get(contact_id)
        if (
            contact is None
            or contact.owner_id != owner_id
            or (contact.archived and not include_archived)
        ):
            raise NotFoundError("contact not found")
        return contact

    def save_contact(self, session: Any, contact: Any, expected_version: int | None = None) -> None:
        del session
        current = self.contacts.get(contact.id)
        if current and expected_version is not None and current.version != expected_version:
            raise ConflictError("stale contact version")
        self.contacts[contact.id] = contact

    def link_project_contact(
        self, session: Any, owner_id: UUID, project_id: UUID, contact_id: UUID
    ) -> None:
        del session
        project = self.projects.get(project_id)
        contact = self.contacts.get(contact_id)
        if not project or project.owner_id != owner_id:
            raise NotFoundError("project not found")
        if not contact or contact.owner_id != owner_id:
            raise NotFoundError("contact not found")
        if project.status is ProjectStatus.COMPLETED or contact.archived:
            raise ValidationError("project or contact is inactive")
        self.project_contacts[(project_id, contact_id)] = {
            "owner_id": owner_id,
            "project_id": project_id,
            "contact_id": contact_id,
            "created_at": datetime.now(UTC),
        }

    def unlink_project_contact(
        self, session: Any, owner_id: UUID, project_id: UUID, contact_id: UUID
    ) -> None:
        del session
        self.project_contacts.pop((project_id, contact_id), None)

    def list_project_contacts(
        self, session: Any, owner_id: UUID, project_id: UUID, limit: int, offset: int = 0
    ) -> list[Any]:
        del session
        results = []
        for (p_id, c_id), pc in self.project_contacts.items():
            if p_id == project_id and pc["owner_id"] == owner_id:
                contact = self.contacts.get(c_id)
                if contact and not contact.archived:
                    results.append(contact)
        results.sort(key=lambda x: (normalize_name(x.display_name)[1], x.id))
        return results[offset : offset + limit]

    def link_task_contact(
        self, session: Any, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> None:
        del session
        task = self.tasks.get(task_id)
        contact = self.contacts.get(contact_id)
        if not task or task.owner_id != owner_id:
            raise NotFoundError("task not found")
        if not contact or contact.owner_id != owner_id:
            raise NotFoundError("contact not found")
        if task.status is TaskStatus.COMPLETED or contact.archived:
            raise ValidationError("task or contact is inactive")
        self.task_contacts[(task_id, contact_id)] = {
            "owner_id": owner_id,
            "task_id": task_id,
            "contact_id": contact_id,
            "created_at": datetime.now(UTC),
        }

    def unlink_task_contact(
        self, session: Any, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> None:
        del session
        self.task_contacts.pop((task_id, contact_id), None)

    def list_task_contacts(
        self, session: Any, owner_id: UUID, task_id: UUID, limit: int, offset: int = 0
    ) -> list[Any]:
        del session
        results = []
        for (t_id, c_id), tc in self.task_contacts.items():
            if t_id == task_id and tc["owner_id"] == owner_id:
                contact = self.contacts.get(c_id)
                if contact and not contact.archived:
                    results.append(contact)
        results.sort(key=lambda x: (normalize_name(x.display_name)[1], x.id))
        return results[offset : offset + limit]


@dataclass(frozen=True, slots=True)
class FakeContactAlias:
    id: UUID
    value: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FakeContact:
    id: UUID
    owner_id: UUID
    display_name: str
    context_note: str | None
    email: str | None
    phone: str | None
    aliases: list[FakeContactAlias]
    archived: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int = 1


# Seeded sensitive strings for telemetry redaction tests
SENSITIVE_NAME = "SECRET_CONTACT_NAME_12345"
SENSITIVE_ALIAS = "SECRET_CONTACT_ALIAS_abcde"
SENSITIVE_EMAIL = "secret_contact_email_98765@example.com"
SENSITIVE_PHONE = "+46123456789"
SENSITIVE_NOTE = "SECRET_CONTACT_NOTE_containing_confidential_data"
SENSITIVE_QUERY = "SECRET_SEARCH_QUERY"
SENSITIVE_TITLE = "SECRET_WORK_TITLE"

OWNER_ONE = UUID("018af000-0000-7000-8000-000000000001")
OWNER_TWO = UUID("018af000-0000-7000-8000-000000000002")


class ContactBuilder:
    def __init__(self, owner_id: UUID = OWNER_ONE) -> None:
        self._id = UUID("01900000-0000-7000-8000-000000000001")
        self._owner_id = owner_id
        self._display_name = "Rasmus"
        self._context_note = None
        self._email = None
        self._phone = None
        self._aliases = []
        self._archived = False
        self._created_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        self._updated_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        self._archived_at = None
        self._version = 1

    def with_id(self, id: UUID) -> "ContactBuilder":
        self._id = id
        return self

    def with_owner(self, owner_id: UUID) -> "ContactBuilder":
        self._owner_id = owner_id
        return self

    def with_display_name(self, name: str) -> "ContactBuilder":
        self._display_name = name
        return self

    def with_email(self, email: str | None) -> "ContactBuilder":
        self._email = email
        return self

    def with_phone(self, phone: str | None) -> "ContactBuilder":
        self._phone = phone
        return self

    def with_context_note(self, note: str | None) -> "ContactBuilder":
        self._context_note = note
        return self

    def with_aliases(self, aliases: list[Any]) -> "ContactBuilder":
        self._aliases = aliases
        return self

    def archived(self, archived: bool = True) -> "ContactBuilder":
        self._archived = archived
        if archived:
            self._archived_at = datetime(2026, 7, 19, 13, 0, tzinfo=UTC)
        else:
            self._archived_at = None
        return self

    def build_fake(self) -> FakeContact:
        return FakeContact(
            id=self._id,
            owner_id=self._owner_id,
            display_name=self._display_name,
            context_note=self._context_note,
            email=self._email,
            phone=self._phone,
            aliases=self._aliases,
            archived=self._archived,
            created_at=self._created_at,
            updated_at=self._updated_at,
            archived_at=self._archived_at,
            version=self._version,
        )


class AliasBuilder:
    def __init__(self, contact_id: UUID, owner_id: UUID = OWNER_ONE) -> None:
        self._id = UUID("01900000-0000-7000-8000-000000000002")
        self._owner_id = owner_id
        self._contact_id = contact_id
        self._value = "Raz"
        self._created_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)

    def with_value(self, value: str) -> "AliasBuilder":
        self._value = value
        return self

    def build_fake(self) -> FakeContactAlias:
        return FakeContactAlias(
            id=self._id,
            value=self._value,
            created_at=self._created_at,
        )


# The Journal tests use only synthetic Swedish content and fixed identifiers.
JOURNAL_SOURCE_TEXT = (
    "Jag sammanfattade planeringen och bestämde att följa upp uppgiften på fredag."
)
JOURNAL_REPLACEMENT_TEXT = (
    "Rättelse: Jag sammanfattade planeringen och bestämde att följa upp på måndag."
)
JOURNAL_REDACTION_SENTINEL_ONE = "JOURNAL_SECRET_OWNER_ONE_7f4c2a"
JOURNAL_REDACTION_SENTINEL_TWO = "JOURNAL_SECRET_OWNER_TWO_9d1b8e"

JOURNAL_SOURCE_ID = UUID("01910000-0000-7000-8000-000000000001")
JOURNAL_REPLACEMENT_SOURCE_ID = UUID("01910000-0000-7000-8000-000000000002")
JOURNAL_ENTRY_ID = UUID("01910000-0000-7000-8000-000000000003")
JOURNAL_DRAFT_ID = UUID("01910000-0000-7000-8000-000000000004")
JOURNAL_SUMMARY_ID = UUID("01910000-0000-7000-8000-000000000005")
JOURNAL_PROJECT_ID = UUID("01910000-0000-7000-8000-000000000011")
JOURNAL_TASK_ID = UUID("01910000-0000-7000-8000-000000000012")
JOURNAL_CONTACT_ID = UUID("01910000-0000-7000-8000-000000000013")
JOURNAL_TASK_PROPOSAL_ID = UUID("01910000-0000-7000-8000-000000000014")


def journal_candidate_snapshot() -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    """Build a deeply immutable minimal candidate snapshot."""

    return MappingProxyType(
        {
            "projects": (
                MappingProxyType(
                    {
                        "id": str(JOURNAL_PROJECT_ID),
                        "kind": "project",
                        "label": "Planering",
                        "status": "active",
                        "version": 2,
                        "context": "Nästa steg denna vecka",
                    }
                ),
            ),
            "tasks": (
                MappingProxyType(
                    {
                        "id": str(JOURNAL_TASK_ID),
                        "kind": "task",
                        "label": "Följ upp beslut",
                        "status": "todo",
                        "version": 3,
                        "context": "Prioritet normal",
                    }
                ),
            ),
            "contacts": (
                MappingProxyType(
                    {
                        "id": str(JOURNAL_CONTACT_ID),
                        "kind": "contact",
                        "label": "Testkontakt",
                        "status": "active",
                        "version": 1,
                        "context": "Deltog i planeringen",
                    }
                ),
            ),
        }
    )


def deterministic_entry_draft_output() -> dict[str, Any]:
    return {
        "kind": "entry_draft",
        "title": "Planering och uppföljning",
        "summary": "Ett beslut fattades och en uppföljning planerades.",
        "key_points": [
            {"kind": "decision", "text": "Uppföljning sker på måndag."},
            {"kind": "commitment", "text": "Förbered underlaget."},
        ],
        "project_suggestions": [
            {"project_id": str(JOURNAL_PROJECT_ID), "rationale": "Berör planeringen."}
        ],
        "task_suggestions": [
            {"task_id": str(JOURNAL_TASK_ID), "rationale": "Uppgiften ska följas upp."}
        ],
        "contact_suggestions": [
            {"contact_id": str(JOURNAL_CONTACT_ID), "rationale": "Kontakten deltog."}
        ],
        "task_proposals": [
            {
                "proposal_id": str(JOURNAL_TASK_PROPOSAL_ID),
                "type": "update_task",
                "task_id": str(JOURNAL_TASK_ID),
                "expected_task_version": 3,
                "due_at": "2026-07-27T09:00:00+02:00",
            }
        ],
    }


def deterministic_daily_summary_output() -> dict[str, Any]:
    statement = {
        "text": "Uppföljningen planerades.",
        "perspective": "fact",
        "entry_ids": [str(JOURNAL_ENTRY_ID)],
    }
    return {
        "kind": "daily_summary",
        "overview": "Dagen handlade om planering och uppföljning.",
        "overview_entry_ids": [str(JOURNAL_ENTRY_ID)],
        "themes": [
            {
                "title": "Planering",
                "summary": "Nästa steg tydliggjordes.",
                "perspective": "interpretation",
                "entry_ids": [str(JOURNAL_ENTRY_ID)],
            }
        ],
        "important_events": [statement],
        "decisions": [],
        "commitments": [],
        "open_questions": [],
        "unresolved_items": [],
        "contradictions": [],
    }


@dataclass
class JournalProviderSpy:
    """Deterministic provider test double; production provider wiring is deliberately absent."""

    entry_output: dict[str, Any] | None = None
    summary_output: dict[str, Any] | None = None
    calls: list[tuple[str, str]] | None = None

    def __post_init__(self) -> None:
        if self.entry_output is None:
            self.entry_output = deterministic_entry_draft_output()
        if self.summary_output is None:
            self.summary_output = deterministic_daily_summary_output()
        if self.calls is None:
            self.calls = []

    def analyze_entry(self, input_fingerprint: str) -> dict[str, Any]:
        assert self.calls is not None and self.entry_output is not None
        self.calls.append(("entry_draft", input_fingerprint))
        return self.entry_output

    def summarize_day(self, input_fingerprint: str) -> dict[str, Any]:
        assert self.calls is not None and self.summary_output is not None
        self.calls.append(("daily_summary", input_fingerprint))
        return self.summary_output

"""Contact links to Projects and Tasks, and the context read around one Contact."""

from typing import Any
from uuid import UUID

from sidekick.contacts.application.models import (
    JOURNAL_CONTEXT_LIMIT,
    LinkedJournalEntries,
    LinkedJournalEntry,
)
from sidekick.contacts.application.paging import contact_cursor
from sidekick.contacts.application.store import ContactStore
from sidekick.contacts.domain.contact import Contact
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.errors import NotFoundError, ValidationError
from sidekick.shared.types import (
    NAMED_KEY,
    TIMED_KEY,
    Actor,
    Clock,
    CursorCodec,
    Page,
    TxSession,
    paginate,
    validate_limit,
)
from sidekick.tasks.domain import TaskStatus


class ContactRelationService:
    def __init__(self, store: ContactStore, clock: Clock, cursor_codec: CursorCodec) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec

    def link_project(
        self,
        actor: Actor,
        contact_id: UUID,
        project_id: UUID,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        actor.require("contacts:write")
        actor.require("projects:read")
        payload = {"contact_id": str(contact_id), "project_id": str(project_id)}

        def operation(session: TxSession) -> dict[str, Any]:
            return self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="link_contact_to_project",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._link_project(
                    session, actor, contact_id, project_id, correlation_id
                ),
            )

        return self.store.transaction(operation)

    def _link_project(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        project_id: UUID,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        self.store.get_contact(session, actor.user_id, contact_id)
        project = self.store.get_project(session, actor.user_id, project_id)
        if project.status is ProjectStatus.COMPLETED:
            raise NotFoundError("project not found")

        created_at = self.store.link_project_contact(session, actor.user_id, project_id, contact_id)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.project_linked",
            outcome="success",
            target_type="project_contact",
            target_id=contact_id,
            related_id=project_id,
            correlation_id=correlation_id,
        )
        return {
            "contact_id": str(contact_id),
            "project_id": str(project_id),
            "linked": True,
            "relation_created_at": created_at.isoformat() if created_at else None,
        }

    def unlink_project(
        self,
        actor: Actor,
        contact_id: UUID,
        project_id: UUID,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        actor.require("contacts:write")
        actor.require("projects:read")
        payload = {"contact_id": str(contact_id), "project_id": str(project_id)}

        def operation(session: TxSession) -> dict[str, Any]:
            return self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="unlink_contact_from_project",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._unlink_project(
                    session, actor, contact_id, project_id, correlation_id
                ),
            )

        return self.store.transaction(operation)

    def _unlink_project(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        project_id: UUID,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        self.store.get_contact(session, actor.user_id, contact_id)
        project = self.store.get_project(session, actor.user_id, project_id)
        if project.status is ProjectStatus.COMPLETED:
            raise NotFoundError("project not found")
        self.store.unlink_project_contact(session, actor.user_id, project_id, contact_id)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.project_unlinked",
            outcome="success",
            target_type="project_contact",
            target_id=contact_id,
            related_id=project_id,
            correlation_id=correlation_id,
        )
        return {"contact_id": str(contact_id), "project_id": str(project_id), "linked": False}

    def link_task(
        self,
        actor: Actor,
        contact_id: UUID,
        task_id: UUID,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        actor.require("contacts:write")
        actor.require("tasks:read")
        payload = {"contact_id": str(contact_id), "task_id": str(task_id)}

        def operation(session: TxSession) -> dict[str, Any]:
            return self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="link_contact_to_task",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._link_task(
                    session, actor, contact_id, task_id, correlation_id
                ),
            )

        return self.store.transaction(operation)

    def _link_task(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        task_id: UUID,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        self.store.get_contact(session, actor.user_id, contact_id)
        task = self.store.get_task(session, actor.user_id, task_id)
        if task.status is TaskStatus.COMPLETED:
            raise NotFoundError("task not found")

        created_at = self.store.link_task_contact(session, actor.user_id, task_id, contact_id)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.task_linked",
            outcome="success",
            target_type="task_contact",
            target_id=contact_id,
            related_id=task_id,
            correlation_id=correlation_id,
        )
        return {
            "contact_id": str(contact_id),
            "task_id": str(task_id),
            "linked": True,
            "relation_created_at": created_at.isoformat() if created_at else None,
        }

    def unlink_task(
        self,
        actor: Actor,
        contact_id: UUID,
        task_id: UUID,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        actor.require("contacts:write")
        actor.require("tasks:read")
        payload = {"contact_id": str(contact_id), "task_id": str(task_id)}

        def operation(session: TxSession) -> dict[str, Any]:
            return self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="unlink_contact_from_task",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._unlink_task(
                    session, actor, contact_id, task_id, correlation_id
                ),
            )

        return self.store.transaction(operation)

    def _unlink_task(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        task_id: UUID,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        self.store.get_contact(session, actor.user_id, contact_id)
        task = self.store.get_task(session, actor.user_id, task_id)
        if task.status is TaskStatus.COMPLETED:
            raise NotFoundError("task not found")
        self.store.unlink_task_contact(session, actor.user_id, task_id, contact_id)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.task_unlinked",
            outcome="success",
            target_type="task_contact",
            target_id=contact_id,
            related_id=task_id,
            correlation_id=correlation_id,
        )
        return {"contact_id": str(contact_id), "task_id": str(task_id), "linked": False}

    def list_project_contacts(
        self,
        actor: Actor,
        project_id: UUID,
        limit: int = 25,
        cursor: str | None = None,
    ) -> Page[Contact]:
        actor.require("contacts:read")
        actor.require("projects:read")
        validate_limit(limit, maximum=100)

        query_key = f"project:{project_id}:contacts"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=NAMED_KEY)

        def operation(session: TxSession) -> list[Contact]:
            self.store.get_project(session, actor.user_id, project_id)
            return self.store.list_project_contacts(
                session, actor.user_id, project_id, limit + 1, after
            )

        contacts = self.store.transaction(operation)
        return Page(
            *paginate(
                contacts,
                limit,
                lambda last: contact_cursor(self.cursor_codec, actor, last, query_key),
            )
        )

    def list_task_contacts(
        self,
        actor: Actor,
        task_id: UUID,
        limit: int = 25,
        cursor: str | None = None,
    ) -> Page[Contact]:
        actor.require("contacts:read")
        actor.require("tasks:read")
        validate_limit(limit, maximum=100)

        query_key = f"task:{task_id}:contacts"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=NAMED_KEY)

        def operation(session: TxSession) -> list[Contact]:
            self.store.get_task(session, actor.user_id, task_id)
            return self.store.list_task_contacts(session, actor.user_id, task_id, limit + 1, after)

        contacts = self.store.transaction(operation)
        return Page(
            *paginate(
                contacts,
                limit,
                lambda last: contact_cursor(self.cursor_codec, actor, last, query_key),
            )
        )

    def get_contact_context(
        self,
        actor: Actor,
        contact_id: UUID,
        *,
        project_limit: int = 10,
        project_cursor: str | None = None,
        task_limit: int = 10,
        task_cursor: str | None = None,
        include_completed: bool = False,
    ) -> dict[str, Any]:
        actor.require("contacts:read")
        actor.require("projects:read")
        actor.require("tasks:read")
        for context_limit in (project_limit, task_limit):
            validate_limit(
                context_limit, maximum=25, message="context limits must be between 1 and 25"
            )

        project_query_key = f"contact-context:{contact_id}:projects:completed={include_completed}"
        task_query_key = f"contact-context:{contact_id}:tasks:completed={include_completed}"

        project_after = self.cursor_codec.decode_keyset(
            actor.user_id, project_cursor, project_query_key, kinds=TIMED_KEY
        )
        task_after = self.cursor_codec.decode_keyset(
            actor.user_id, task_cursor, task_query_key, kinds=TIMED_KEY
        )

        def operation(session: TxSession) -> dict[str, Any]:
            contact = self.store.get_contact(session, actor.user_id, contact_id)
            if contact.archived:
                raise ValidationError("contact is archived")

            projects = self.store.list_linked_projects(
                session,
                actor.user_id,
                contact_id,
                limit=project_limit + 1,
                after=project_after,
                include_completed=include_completed,
            )
            tasks = self.store.list_linked_tasks(
                session,
                actor.user_id,
                contact_id,
                limit=task_limit + 1,
                after=task_after,
                include_completed=include_completed,
            )

            project_page = Page(
                *paginate(
                    projects,
                    project_limit,
                    lambda last: self.cursor_codec.encode_keyset(
                        actor.user_id, (last.updated_at, last.id), project_query_key
                    ),
                )
            )
            task_page = Page(
                *paginate(
                    tasks,
                    task_limit,
                    lambda last: self.cursor_codec.encode_keyset(
                        actor.user_id, (last.updated_at, last.id), task_query_key
                    ),
                )
            )

            readable = "journal:read" in actor.scopes
            journal_rows = (
                self.store.list_linked_journal_entries(
                    session,
                    actor.user_id,
                    contact_id,
                    limit=JOURNAL_CONTEXT_LIMIT + 1,
                )
                if readable
                else []
            )
            linked, more = paginate(journal_rows, JOURNAL_CONTEXT_LIMIT, lambda _: True)
            journal_entries = LinkedJournalEntries(
                items=[
                    LinkedJournalEntry(id=entry_id, journal_date=entry_date, title=title)
                    for entry_id, entry_date, title in linked
                ],
                has_more=bool(more),
                readable=readable,
            )

            now = self.clock.now()
            marks = {
                task.id: {
                    # A Task waiting on *this* Contact is the only claim made here.
                    # Any other linked Task is linked work, never an inferred promise.
                    "waiting_on_contact": task.waiting_on_contact_id == contact_id and task.waiting,
                    "waiting_since": task.waiting_since,
                    "follow_up_at": task.follow_up_at,
                    "follow_up_due": (
                        task.waiting_on_contact_id == contact_id and task.follow_up_due(now=now)
                    ),
                }
                for task in task_page.items
            }
            return {
                "contact": contact,
                "projects": project_page,
                "tasks": task_page,
                "task_marks": marks,
                "journal_entries": journal_entries,
            }

        return self.store.transaction(operation)

"""Transport-neutral Contact commands and queries."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sidekick.contacts.domain.contact import Contact, ContactAlias
from sidekick.contacts.domain.normalization import (
    normalize_context_note,
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_profile_text,
)
from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.errors import InvalidInputError, NotFoundError, ValidationError
from sidekick.shared.replay import id_replay_record
from sidekick.shared.types import (
    NAMED_KEY,
    SORT_KEY_CHARS,
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
)
from sidekick.tasks.domain import Task, TaskStatus

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CreateContactCommand:
    display_name: str
    context_note: str | None = None
    email: str | None = None
    phone: str | None = None
    aliases: list[str] | None = None
    relationship: str | None = None
    organization: str | None = None
    role: str | None = None
    address: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateContactCommand:
    display_name: str | UnsetType = UNSET
    context_note: str | None | UnsetType = UNSET
    email: str | None | UnsetType = UNSET
    phone: str | None | UnsetType = UNSET
    relationship: str | None | UnsetType = UNSET
    organization: str | None | UnsetType = UNSET
    role: str | None | UnsetType = UNSET
    address: str | None | UnsetType = UNSET

    def changes(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "display_name": self.display_name,
                "context_note": self.context_note,
                "email": self.email,
                "phone": self.phone,
                "relationship": self.relationship,
                "organization": self.organization,
                "role": self.role,
                "address": self.address,
            }.items()
            if value is not UNSET
        }


JOURNAL_CONTEXT_LIMIT = 10


@dataclass(frozen=True, slots=True)
class LinkedJournalEntry:
    """A Journal entry linked to a Contact: identity, date and title, never content."""

    id: UUID
    journal_date: date
    title: str


@dataclass(frozen=True, slots=True)
class LinkedJournalEntries:
    """Newest linked entries, at most JOURNAL_CONTEXT_LIMIT, empty when not readable."""

    items: list[LinkedJournalEntry]
    has_more: bool
    readable: bool


class ContactStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    """Concrete port needed for atomic Contact and idempotency operations."""

    def contact_display_names(
        self, session: TxSession, owner_id: UUID, contact_ids: tuple[UUID, ...]
    ) -> dict[UUID, tuple[str, bool]]: ...
    def list_contacts(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        q: str | None = None,
        include_archived: bool = False,
        after: tuple[KeyValue, ...] | None = None,
    ) -> list[Contact]: ...
    def phonetic_contacts(
        self,
        session: TxSession,
        owner_id: UUID,
        query: str,
        *,
        include_archived: bool = False,
        limit: int = 25,
    ) -> list[Contact]: ...
    def get_contact(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        include_archived: bool = False,
    ) -> Contact: ...
    def save_contact(
        self, session: TxSession, contact: Contact, expected_version: int | None = None
    ) -> None: ...
    def get_project(self, session: TxSession, owner_id: UUID, project_id: UUID) -> Project: ...
    def get_task(self, session: TxSession, owner_id: UUID, task_id: UUID) -> Task: ...
    def link_project_contact(
        self, session: TxSession, owner_id: UUID, project_id: UUID, contact_id: UUID
    ) -> datetime | None: ...
    def unlink_project_contact(
        self, session: TxSession, owner_id: UUID, project_id: UUID, contact_id: UUID
    ) -> None: ...
    def list_project_contacts(
        self,
        session: TxSession,
        owner_id: UUID,
        project_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
    ) -> list[Contact]: ...
    def link_task_contact(
        self, session: TxSession, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> datetime | None: ...
    def unlink_task_contact(
        self, session: TxSession, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> None: ...
    def list_task_contacts(
        self,
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
    ) -> list[Contact]: ...
    def list_linked_projects(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_completed: bool = False,
    ) -> list[Project]: ...
    def list_linked_tasks(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_completed: bool = False,
    ) -> list[Task]: ...
    def list_linked_journal_entries(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        limit: int,
    ) -> list[tuple[UUID, date, str]]: ...


class ContactService:
    def __init__(self, store: ContactStore, clock: Clock, cursor_codec: CursorCodec) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec

    def _replayed(self, session: TxSession, actor: Actor, result: dict[str, Any]) -> Contact:
        """The Contact a (possibly replayed) write refers to, re-read by id.

        The idempotency record keeps only the id (`id_replay_record`), so a retry returns the
        Contact as it is now, archived or not, rather than a stored copy of its text.
        """

        return self.store.get_contact(
            session, actor.user_id, UUID(result["id"]), include_archived=True
        )

    def list(
        self,
        actor: Actor,
        *,
        q: str | None = None,
        include_archived: bool = False,
        limit: int = 25,
        cursor: str | None = None,
    ) -> Page[Contact]:
        actor.require("contacts:read")
        if not 1 <= limit <= 100:
            raise InvalidInputError("limit must be between 1 and 100")

        normalized_query = normalize_name(q)[1] if q else "*"
        query_fingerprint = hashlib.sha256(normalized_query.encode()).hexdigest()
        query_key = f"contacts:v2:q={query_fingerprint}:archived={include_archived}"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=NAMED_KEY)

        contacts = self.store.transaction(
            lambda session: self.store.list_contacts(
                session, actor.user_id, limit + 1, q, include_archived, after
            )
        )
        if q and not contacts and after is None:
            # A misheard name ("Shell" for "Kjell") finds nothing by name or alias: one bounded
            # phonetic page, without a cursor, so the list never pages through fallback hits.
            phonetic = self.store.transaction(
                lambda session: self.store.phonetic_contacts(
                    session, actor.user_id, q, include_archived=include_archived, limit=limit
                )
            )
            return Page(items=phonetic, next_cursor=None)
        return Page(
            items=contacts[:limit],
            next_cursor=self._contact_cursor(actor, contacts, limit, query_key),
        )

    def _contact_cursor(
        self, actor: Actor, contacts: Sequence[Contact], limit: int, query_key: str
    ) -> str | None:
        """The cursor after the last Contact served (name key, id), or None on the last page."""

        if len(contacts) <= limit:
            return None
        last = contacts[limit - 1]
        return self.cursor_codec.encode_keyset(
            actor.user_id, (last.display_name_key[:SORT_KEY_CHARS], last.id), query_key
        )

    def get(self, actor: Actor, contact_id: UUID) -> Contact:
        actor.require("contacts:read")
        return self.store.transaction(
            # Detail is also the restore surface. A deliberately requested archived
            # record must remain readable so the owner can recover it from the list.
            lambda session: self.store.get_contact(
                session, actor.user_id, contact_id, include_archived=True
            )
        )

    def create(
        self,
        actor: Actor,
        command: CreateContactCommand,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {
            "display_name": command.display_name,
            "context_note": command.context_note,
            "email": command.email,
            "phone": command.phone,
            "aliases": command.aliases,
        }
        # Only set profile fields are hashed, so a replay recorded before they existed matches.
        for field in ("relationship", "organization", "role", "address"):
            if getattr(command, field) is not None:
                payload[field] = getattr(command, field)

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_contact",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._create(session, actor, command, correlation_id),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _create(
        self,
        session: TxSession,
        actor: Actor,
        command: CreateContactCommand,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        now = self.clock.now()
        disp_val, key_val = normalize_name(command.display_name)
        email_val, email_key = normalize_email(command.email)
        phone_val, phone_key = normalize_phone(command.phone)
        note_val = normalize_context_note(command.context_note)
        relationship_val = normalize_profile_text(command.relationship, "relationship")
        organization_val = normalize_profile_text(command.organization, "organization")
        role_val = normalize_profile_text(command.role, "role")
        address_val = normalize_profile_text(command.address, "address")

        aliases_list: list[ContactAlias] = []
        aliases = command.aliases or []
        if len(aliases) > 20:
            raise ValidationError("maximum of 20 aliases is allowed")
        alias_keys: set[str] = set()
        for value in aliases:
            norm_val, norm_key = normalize_name(value)
            if norm_key in alias_keys:
                raise ValidationError("alias already exists on this contact")
            alias_keys.add(norm_key)
            aliases_list.append(
                ContactAlias(
                    id=new_uuid7(),
                    value=norm_val,
                    created_at=now,
                )
            )

        contact = Contact(
            id=new_uuid7(),
            owner_id=actor.user_id,
            display_name=disp_val,
            display_name_key=key_val,
            context_note=note_val,
            email=email_val,
            email_key=email_key,
            phone=phone_val,
            phone_key=phone_key,
            relationship=relationship_val,
            organization=organization_val,
            role=role_val,
            address=address_val,
            aliases=aliases_list,
            archived=False,
            created_at=now,
            updated_at=now,
            archived_at=None,
            version=1,
        )
        self.store.save_contact(session, contact)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.created",
            outcome="success",
            target_type="contact",
            target_id=contact.id,
            correlation_id=correlation_id,
        )
        return contact_to_data(contact)

    def update(
        self,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        command: UpdateContactCommand,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        changes = command.changes()
        payload = {"contact_id": str(contact_id), "expected_version": expected_version, **changes}

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="update_contact",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._update(
                    session, actor, contact_id, expected_version, command, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _update(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        command: UpdateContactCommand,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id)
        updated = contact.update(now=self.clock.now(), **command.changes())
        self.store.save_contact(session, updated, expected_version=expected_version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.updated",
            outcome="success",
            target_type="contact",
            target_id=contact.id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

    def archive(
        self,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {"contact_id": str(contact_id), "expected_version": expected_version}

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="archive_contact",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._archive(
                    session, actor, contact_id, expected_version, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _archive(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id)
        updated = contact.archive(now=self.clock.now())
        self.store.save_contact(session, updated, expected_version=expected_version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.archived",
            outcome="success",
            target_type="contact",
            target_id=contact.id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

    def restore(
        self,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {"contact_id": str(contact_id), "expected_version": expected_version}

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="restore_contact",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._restore(
                    session, actor, contact_id, expected_version, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _restore(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id, include_archived=True)
        if not contact.archived:
            raise NotFoundError("contact not found")
        updated = contact.restore(now=self.clock.now())
        self.store.save_contact(session, updated, expected_version=expected_version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.restored",
            outcome="success",
            target_type="contact",
            target_id=contact.id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

    def add_alias(
        self,
        actor: Actor,
        contact_id: UUID,
        value: str,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {
            "contact_id": str(contact_id),
            "value": value,
            "expected_version": expected_version,
        }

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="add_contact_alias",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._add_alias(
                    session, actor, contact_id, value, expected_version, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _add_alias(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        value: str,
        expected_version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id)
        alias_id = new_uuid7()
        updated = contact.add_alias(now=self.clock.now(), value=value, alias_id=alias_id)
        self.store.save_contact(session, updated, expected_version=expected_version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.alias_added",
            outcome="success",
            target_type="contact_alias",
            target_id=alias_id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

    def remove_alias(
        self,
        actor: Actor,
        contact_id: UUID,
        alias_id: UUID,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {
            "contact_id": str(contact_id),
            "alias_id": str(alias_id),
            "expected_version": expected_version,
        }

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="remove_contact_alias",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._remove_alias(
                    session, actor, contact_id, alias_id, expected_version, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _remove_alias(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        alias_id: UUID,
        expected_version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id)
        if all(alias.id != alias_id for alias in contact.aliases):
            # An id that is not this Contact's alias (another owner's, another Contact's or made
            # up) removes nothing and must not be recorded as a removal in the audit trail.
            raise NotFoundError("contact alias not found")
        updated = contact.remove_alias(now=self.clock.now(), alias_id=alias_id)
        self.store.save_contact(session, updated, expected_version=expected_version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.alias_removed",
            outcome="success",
            target_type="contact_alias",
            target_id=alias_id,
            related_id=contact_id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

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
        if not 1 <= limit <= 100:
            raise InvalidInputError("limit must be between 1 and 100")

        query_key = f"project:{project_id}:contacts"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=NAMED_KEY)

        def operation(session: TxSession) -> list[Contact]:
            self.store.get_project(session, actor.user_id, project_id)
            return self.store.list_project_contacts(
                session, actor.user_id, project_id, limit + 1, after
            )

        contacts = self.store.transaction(operation)
        return Page(
            items=contacts[:limit],
            next_cursor=self._contact_cursor(actor, contacts, limit, query_key),
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
        if not 1 <= limit <= 100:
            raise InvalidInputError("limit must be between 1 and 100")

        query_key = f"task:{task_id}:contacts"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=NAMED_KEY)

        def operation(session: TxSession) -> list[Contact]:
            self.store.get_task(session, actor.user_id, task_id)
            return self.store.list_task_contacts(session, actor.user_id, task_id, limit + 1, after)

        contacts = self.store.transaction(operation)
        return Page(
            items=contacts[:limit],
            next_cursor=self._contact_cursor(actor, contacts, limit, query_key),
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
        if not 1 <= project_limit <= 25 or not 1 <= task_limit <= 25:
            raise InvalidInputError("context limits must be between 1 and 25")

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
                items=projects[:project_limit],
                next_cursor=self.cursor_codec.encode_keyset(
                    actor.user_id,
                    (projects[project_limit - 1].updated_at, projects[project_limit - 1].id),
                    project_query_key,
                )
                if len(projects) > project_limit
                else None,
            )
            task_page = Page(
                items=tasks[:task_limit],
                next_cursor=self.cursor_codec.encode_keyset(
                    actor.user_id,
                    (tasks[task_limit - 1].updated_at, tasks[task_limit - 1].id),
                    task_query_key,
                )
                if len(tasks) > task_limit
                else None,
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
            journal_entries = LinkedJournalEntries(
                items=[
                    LinkedJournalEntry(id=entry_id, journal_date=entry_date, title=title)
                    for entry_id, entry_date, title in journal_rows[:JOURNAL_CONTEXT_LIMIT]
                ],
                has_more=len(journal_rows) > JOURNAL_CONTEXT_LIMIT,
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

    def waiting_contact_names(self, actor: Actor, contact_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Display names of several waiting Contacts, archived ones included, in one query."""

        actor.require("contacts:read")
        ids = tuple(dict.fromkeys(contact_ids))
        if not ids:
            return {}
        found = self.store.transaction(
            lambda session: self.store.contact_display_names(session, actor.user_id, ids)
        )
        return {contact_id: name for contact_id, (name, _archived) in found.items()}


def contact_to_data(contact: Contact) -> dict[str, Any]:
    return {
        "id": str(contact.id),
        "owner_id": str(contact.owner_id),
        "display_name": contact.display_name,
        "display_name_key": contact.display_name_key,
        "context_note": contact.context_note,
        "email": contact.email,
        "email_key": contact.email_key,
        "phone": contact.phone,
        "phone_key": contact.phone_key,
        "relationship": contact.relationship,
        "organization": contact.organization,
        "role": contact.role,
        "address": contact.address,
        "aliases": [
            {
                "id": str(alias.id),
                "value": alias.value,
                "created_at": alias.created_at.isoformat(),
            }
            for alias in contact.aliases
        ],
        "archived": contact.archived,
        "created_at": contact.created_at.isoformat(),
        "updated_at": contact.updated_at.isoformat(),
        "archived_at": contact.archived_at.isoformat() if contact.archived_at else None,
        "version": contact.version,
    }


def contact_public_data(contact: Contact) -> dict[str, Any]:
    data = contact_to_data(contact)
    data.pop("owner_id")
    data.pop("display_name_key")
    data.pop("email_key")
    data.pop("phone_key")
    return data

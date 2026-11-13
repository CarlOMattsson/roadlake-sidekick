"""Contacts, aliases, and Contact links to Projects, Tasks and journal entries."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from sidekick.contacts.application.models import TaskProgress
from sidekick.contacts.domain.contact import Contact, ContactAlias
from sidekick.contacts.domain.normalization import normalize_email, normalize_name, normalize_phone
from sidekick.contacts.domain.phonetic import phonetic_match
from sidekick.projects.domain import Project
from sidekick.projects.persistence import project_from_row
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sidekick.shared.persistence.models import (
    ContactAliasRow,
    ContactRow,
    JournalEntryContactRow,
    JournalEntryRow,
    JournalSourceRow,
    ProjectContactRow,
    ProjectRow,
    TaskContactRow,
    TaskRow,
)
from sidekick.shared.persistence.stores.keyset import rows_after, text_key
from sidekick.shared.types import KeyValue, utc_now
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.tasks.persistence import task_from_row
from sidekick.work.persistence.tags import tag_condition


def contact_from_row(row: ContactRow, aliases: list[ContactAliasRow]) -> Contact:
    return Contact(
        id=row.id,
        owner_id=row.owner_id,
        display_name=row.display_name,
        display_name_key=row.display_name_key,
        context_note=row.context_note,
        email=row.email,
        email_key=row.email_key,
        phone=row.phone,
        phone_key=row.phone_key,
        relationship=row.relationship,
        organization=row.organization,
        role=row.role,
        address=row.address,
        aliases=[
            ContactAlias(id=a.id, value=a.display_value, created_at=a.created_at) for a in aliases
        ],
        archived=row.archived,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
        version=row.version,
    )


PHONETIC_CANDIDATE_LIMIT = 200
"""Most owned Contacts compared in Python by the phonetic fallback (bounded read)."""


class ContactStore:
    """Contacts, aliases, and Contact links to Projects, Tasks and journal entries.

    Mixin composed into ``SqlAlchemyStore``; methods are static and owner-filtered.
    """

    @staticmethod
    def contact_display_names(
        session: Session, owner_id: UUID, contact_ids: tuple[UUID, ...]
    ) -> dict[UUID, tuple[str, bool]]:
        """Display name and archived flag of the owner's live Contacts, archived ones included."""

        if not contact_ids:
            return {}
        rows = session.execute(
            select(ContactRow.id, ContactRow.display_name, ContactRow.archived).where(
                ContactRow.owner_id == owner_id,
                ContactRow.id.in_(contact_ids),
                ContactRow.trashed_at.is_(None),
            )
        ).all()
        return {row[0]: (row[1], bool(row[2])) for row in rows}

    @staticmethod
    def get_contact(
        session: Session,
        owner_id: UUID,
        contact_id: UUID,
        include_archived: bool = False,
    ) -> Contact:
        statement = select(ContactRow).where(
            ContactRow.id == contact_id,
            ContactRow.owner_id == owner_id,
        )
        statement = statement.where(ContactRow.trashed_at.is_(None))
        if not include_archived:
            statement = statement.where(ContactRow.archived.is_(False))
        row = session.scalar(statement)
        if row is None:
            raise NotFoundError("contact not found")
        aliases = list(
            session.scalars(
                select(ContactAliasRow)
                .where(
                    ContactAliasRow.contact_id == contact_id,
                    ContactAliasRow.owner_id == owner_id,
                )
                .order_by(ContactAliasRow.created_at.asc(), ContactAliasRow.id.asc())
            )
        )
        return contact_from_row(row, aliases)

    @staticmethod
    def phonetic_contacts(
        session: Session,
        owner_id: UUID,
        query: str,
        *,
        include_archived: bool = False,
        limit: int = 25,
    ) -> list[Contact]:
        """Fallback for a misheard name when the normal matches found nothing.

        Compares the Swedish phonetic key of `query` with the display name and alias values of the
        owner's newest PHONETIC_CANDIDATE_LIMIT Contacts. Read-only, owner-scoped and bounded;
        returns at most `limit` Contacts and never reveals which alias matched.
        """
        statement = select(ContactRow).where(
            ContactRow.owner_id == owner_id,
            ContactRow.trashed_at.is_(None),
        )
        if not include_archived:
            statement = statement.where(ContactRow.archived.is_(False))
        candidates = list(
            session.scalars(
                statement.order_by(ContactRow.updated_at.desc(), ContactRow.id.asc()).limit(
                    PHONETIC_CANDIDATE_LIMIT
                )
            )
        )
        if not candidates:
            return []
        alias_rows = session.scalars(
            select(ContactAliasRow)
            .where(
                ContactAliasRow.owner_id == owner_id,
                ContactAliasRow.contact_id.in_([row.id for row in candidates]),
            )
            .order_by(ContactAliasRow.created_at.asc(), ContactAliasRow.id.asc())
        )
        aliases_by_contact: dict[UUID, list[ContactAliasRow]] = {}
        for alias_row in alias_rows:
            aliases_by_contact.setdefault(alias_row.contact_id, []).append(alias_row)

        matches: list[Contact] = []
        for row in candidates:
            aliases = aliases_by_contact.get(row.id, [])
            names = [row.display_name, *(alias.display_value for alias in aliases)]
            if any(phonetic_match(query, name) for name in names):
                matches.append(contact_from_row(row, aliases))
                if len(matches) == limit:
                    break
        return matches

    @staticmethod
    def list_contacts(
        session: Session,
        owner_id: UUID,
        limit: int,
        q: str | None = None,
        include_archived: bool = False,
        after: tuple[KeyValue, ...] | None = None,
        tags: tuple[str, ...] = (),
        tag_match: str = "any",
    ) -> list[Contact]:
        """By name; `after` is the (display_name_key, id) of the last Contact already read.

        With `tags` only Contacts carrying any (or, with `tag_match="all"`, every) tag are listed.
        """

        statement = select(ContactRow).where(ContactRow.owner_id == owner_id)
        statement = statement.where(ContactRow.trashed_at.is_(None))
        if not include_archived:
            statement = statement.where(ContactRow.archived.is_(False))

        if q:
            norm_q = normalize_name(q)[1]
            alias_sub = (
                select(ContactAliasRow.contact_id)
                .where(
                    ContactAliasRow.owner_id == owner_id,
                    ContactAliasRow.normalized_key.contains(norm_q),
                )
                .scalar_subquery()
            )
            predicates = [
                ContactRow.display_name_key.contains(norm_q),
                ContactRow.id.in_(alias_sub),
            ]
            try:
                email_key = normalize_email(q)[1]
                if email_key is not None:
                    predicates.append(ContactRow.email_key == email_key)
            except ValidationError:
                pass
            try:
                phone_key = normalize_phone(q)[1]
                if phone_key is not None:
                    predicates.append(ContactRow.phone_key == phone_key)
            except ValidationError:
                pass
            statement = statement.where(or_(*predicates))
        if tags:
            statement = statement.where(
                tag_condition("contact", ContactRow.id, owner_id, tags, tag_match)
            )

        if after is not None:
            statement = statement.where(
                rows_after(
                    (text_key(ContactRow.display_name_key), ContactRow.id), after, descending=False
                )
            )
        rows = session.scalars(
            statement.order_by(
                text_key(ContactRow.display_name_key).asc(), ContactRow.id.asc()
            ).limit(limit)
        )

        results: list[Contact] = []
        for row in rows:
            aliases = list(
                session.scalars(
                    select(ContactAliasRow)
                    .where(
                        ContactAliasRow.contact_id == row.id,
                        ContactAliasRow.owner_id == owner_id,
                    )
                    .order_by(ContactAliasRow.created_at.asc(), ContactAliasRow.id.asc())
                )
            )
            results.append(contact_from_row(row, aliases))
        return results

    @staticmethod
    def save_contact(
        session: Session, contact: Contact, expected_version: int | None = None
    ) -> None:
        row = session.scalar(
            select(ContactRow).where(ContactRow.id == contact.id).with_for_update()
        )
        if row is None:
            session.add(
                ContactRow(
                    id=contact.id,
                    owner_id=contact.owner_id,
                    display_name=contact.display_name,
                    display_name_key=contact.display_name_key,
                    context_note=contact.context_note,
                    email=contact.email,
                    email_key=contact.email_key,
                    phone=contact.phone,
                    phone_key=contact.phone_key,
                    relationship=contact.relationship,
                    organization=contact.organization,
                    role=contact.role,
                    address=contact.address,
                    created_at=contact.created_at,
                    updated_at=contact.updated_at,
                    archived_at=contact.archived_at,
                    archived=contact.archived,
                    version=contact.version,
                )
            )
            session.flush()
            for a in contact.aliases:
                session.add(
                    ContactAliasRow(
                        id=a.id,
                        owner_id=contact.owner_id,
                        contact_id=contact.id,
                        display_value=a.value,
                        normalized_key=normalize_name(a.value)[1],
                        created_at=a.created_at,
                    )
                )
            return

        if row.owner_id != contact.owner_id:
            raise NotFoundError("contact not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale contact version")

        for field in (
            "display_name",
            "display_name_key",
            "context_note",
            "email",
            "email_key",
            "phone",
            "phone_key",
            "relationship",
            "organization",
            "role",
            "address",
            "updated_at",
            "archived_at",
            "archived",
            "version",
        ):
            setattr(row, field, getattr(contact, field))

        session.execute(
            text(
                "DELETE FROM sidekick.contact_aliases WHERE contact_id = :cid AND owner_id = :oid"
            ),
            {"cid": contact.id, "oid": contact.owner_id},
        )
        for a in contact.aliases:
            session.add(
                ContactAliasRow(
                    id=a.id,
                    owner_id=contact.owner_id,
                    contact_id=contact.id,
                    display_value=a.value,
                    normalized_key=normalize_name(a.value)[1],
                    created_at=a.created_at,
                )
            )

    @staticmethod
    def link_project_contact(
        session: Session, owner_id: UUID, project_id: UUID, contact_id: UUID
    ) -> datetime | None:
        existing = session.scalar(
            select(ProjectContactRow).where(
                ProjectContactRow.owner_id == owner_id,
                ProjectContactRow.project_id == project_id,
                ProjectContactRow.contact_id == contact_id,
            )
        )
        if existing is not None:
            return None
        created_at = utc_now()
        session.add(
            ProjectContactRow(
                owner_id=owner_id,
                project_id=project_id,
                contact_id=contact_id,
                created_at=created_at,
            )
        )
        return created_at

    @staticmethod
    def unlink_project_contact(
        session: Session, owner_id: UUID, project_id: UUID, contact_id: UUID
    ) -> None:
        session.execute(
            delete(ProjectContactRow).where(
                ProjectContactRow.owner_id == owner_id,
                ProjectContactRow.project_id == project_id,
                ProjectContactRow.contact_id == contact_id,
            )
        )

    @staticmethod
    def list_project_contacts(
        session: Session,
        owner_id: UUID,
        project_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
    ) -> list[Contact]:
        # Active contacts involved in project
        statement = (
            select(ContactRow)
            .join(
                ProjectContactRow,
                (ProjectContactRow.contact_id == ContactRow.id)
                & (ProjectContactRow.owner_id == ContactRow.owner_id),
            )
            .where(
                ProjectContactRow.owner_id == owner_id,
                ProjectContactRow.project_id == project_id,
                ContactRow.archived.is_(False),
                ContactRow.trashed_at.is_(None),
            )
            .order_by(text_key(ContactRow.display_name_key).asc(), ContactRow.id.asc())
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(
                rows_after(
                    (text_key(ContactRow.display_name_key), ContactRow.id), after, descending=False
                )
            )
        rows = session.scalars(statement)
        results: list[Contact] = []
        for row in rows:
            aliases = list(
                session.scalars(
                    select(ContactAliasRow)
                    .where(
                        ContactAliasRow.contact_id == row.id,
                        ContactAliasRow.owner_id == owner_id,
                    )
                    .order_by(ContactAliasRow.created_at.asc(), ContactAliasRow.id.asc())
                )
            )
            results.append(contact_from_row(row, aliases))
        return results

    @staticmethod
    def link_task_contact(
        session: Session, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> datetime | None:
        existing = session.scalar(
            select(TaskContactRow).where(
                TaskContactRow.owner_id == owner_id,
                TaskContactRow.task_id == task_id,
                TaskContactRow.contact_id == contact_id,
            )
        )
        if existing is not None:
            return None
        created_at = utc_now()
        session.add(
            TaskContactRow(
                owner_id=owner_id,
                task_id=task_id,
                contact_id=contact_id,
                created_at=created_at,
            )
        )
        return created_at

    @staticmethod
    def unlink_task_contact(
        session: Session, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> None:
        session.execute(
            delete(TaskContactRow).where(
                TaskContactRow.owner_id == owner_id,
                TaskContactRow.task_id == task_id,
                TaskContactRow.contact_id == contact_id,
            )
        )

    @staticmethod
    def list_task_contacts(
        session: Session,
        owner_id: UUID,
        task_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
    ) -> list[Contact]:
        # Active contacts concerning task
        statement = (
            select(ContactRow)
            .join(
                TaskContactRow,
                (TaskContactRow.contact_id == ContactRow.id)
                & (TaskContactRow.owner_id == ContactRow.owner_id),
            )
            .where(
                TaskContactRow.owner_id == owner_id,
                TaskContactRow.task_id == task_id,
                ContactRow.archived.is_(False),
                ContactRow.trashed_at.is_(None),
            )
            .order_by(text_key(ContactRow.display_name_key).asc(), ContactRow.id.asc())
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(
                rows_after(
                    (text_key(ContactRow.display_name_key), ContactRow.id), after, descending=False
                )
            )
        rows = session.scalars(statement)
        results: list[Contact] = []
        for row in rows:
            aliases = list(
                session.scalars(
                    select(ContactAliasRow)
                    .where(
                        ContactAliasRow.contact_id == row.id,
                        ContactAliasRow.owner_id == owner_id,
                    )
                    .order_by(ContactAliasRow.created_at.asc(), ContactAliasRow.id.asc())
                )
            )
            results.append(contact_from_row(row, aliases))
        return results

    @staticmethod
    def list_linked_projects(
        session: Session,
        owner_id: UUID,
        contact_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_completed: bool = False,
    ) -> list[Project]:
        statement = (
            select(ProjectRow)
            .join(
                ProjectContactRow,
                (ProjectContactRow.project_id == ProjectRow.id)
                & (ProjectContactRow.owner_id == ProjectRow.owner_id),
            )
            .where(
                ProjectContactRow.owner_id == owner_id,
                ProjectContactRow.contact_id == contact_id,
                ProjectRow.archived_at.is_(None),
                ProjectRow.trashed_at.is_(None),
            )
        )
        if not include_completed:
            statement = statement.where(ProjectRow.status != "completed")

        if after is not None:
            statement = statement.where(
                rows_after((ProjectRow.updated_at, ProjectRow.id), after, descending=True)
            )
        rows = session.scalars(
            statement.order_by(ProjectRow.updated_at.desc(), ProjectRow.id.desc()).limit(limit)
        )
        return [project_from_row(row) for row in rows]

    @staticmethod
    def project_task_progress(
        session: Session, owner_id: UUID, project_ids: list[UUID]
    ) -> dict[UUID, TaskProgress]:
        """Total and completed active Tasks of several Projects, in one grouped read.

        Archived and trashed Tasks are left out. A Project without Tasks has no entry.
        """

        rows = session.execute(
            select(
                TaskRow.project_id,
                func.count(TaskRow.id),
                func.count(TaskRow.id).filter(TaskRow.status == TaskStatus.COMPLETED.value),
            )
            .where(
                TaskRow.owner_id == owner_id,
                TaskRow.project_id.in_(project_ids),
                TaskRow.archived_at.is_(None),
                TaskRow.trashed_at.is_(None),
            )
            .group_by(TaskRow.project_id)
        )
        return {
            project_id: TaskProgress(total=int(total), done=int(done))
            for project_id, total, done in rows
            if project_id is not None
        }

    @staticmethod
    def list_linked_tasks(
        session: Session,
        owner_id: UUID,
        contact_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_completed: bool = False,
    ) -> list[Task]:
        # A Task that waits on the Contact belongs to its context even when it is not linked.
        linked = (
            select(TaskContactRow.task_id)
            .where(
                TaskContactRow.owner_id == owner_id,
                TaskContactRow.contact_id == contact_id,
            )
            .scalar_subquery()
        )
        statement = select(TaskRow).where(
            TaskRow.owner_id == owner_id,
            or_(TaskRow.id.in_(linked), TaskRow.waiting_on_contact_id == contact_id),
            TaskRow.archived_at.is_(None),
            TaskRow.trashed_at.is_(None),
        )
        if not include_completed:
            statement = statement.where(TaskRow.status != "completed")

        if after is not None:
            statement = statement.where(
                rows_after((TaskRow.updated_at, TaskRow.id), after, descending=True)
            )
        rows = session.scalars(
            statement.order_by(TaskRow.updated_at.desc(), TaskRow.id.desc()).limit(limit)
        )
        return [task_from_row(row) for row in rows]

    @staticmethod
    def list_linked_journal_entries(
        session: Session,
        owner_id: UUID,
        contact_id: UUID,
        limit: int,
    ) -> list[tuple[UUID, date, str]]:
        """Newest-first (id, journal_date, title) of active entries linked to a Contact.

        Only identity, date and title are selected, so entry content never leaves the database.
        """
        rows = session.execute(
            select(JournalEntryRow.id, JournalEntryRow.journal_date, JournalEntryRow.title)
            .join(
                JournalEntryContactRow,
                (JournalEntryContactRow.entry_id == JournalEntryRow.id)
                & (JournalEntryContactRow.owner_id == JournalEntryRow.owner_id),
            )
            .join(
                JournalSourceRow,
                (JournalSourceRow.id == JournalEntryRow.source_id)
                & (JournalSourceRow.owner_id == JournalEntryRow.owner_id),
            )
            .where(
                JournalEntryContactRow.owner_id == owner_id,
                JournalEntryContactRow.contact_id == contact_id,
                JournalEntryRow.archived_at.is_(None),
                JournalEntryRow.trashed_at.is_(None),
                JournalSourceRow.trashed_at.is_(None),
            )
            .order_by(
                JournalEntryRow.journal_date.desc(),
                JournalEntryRow.created_at.desc(),
                JournalEntryRow.id.desc(),
            )
            .limit(limit)
        ).all()
        return [(row.id, row.journal_date, row.title) for row in rows]

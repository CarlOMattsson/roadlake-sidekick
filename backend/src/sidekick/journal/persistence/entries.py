"""Journal sources, entries, pending items and entry relations."""

from datetime import date
from uuid import UUID

from sqlalchemy import case, delete, func, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, joinedload

from sidekick.journal.domain.entry import NO_OCCURRENCE, EntryHead, JournalEntry
from sidekick.journal.domain.records import EntryRelations, PendingJournalItem, RelationLabels
from sidekick.journal.domain.source import JournalSource, SourceType
from sidekick.journal.persistence.mappers import journal_entry_from_row, journal_source_from_row
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
)
from sidekick.shared.persistence.models import (
    ContactRow,
    JournalDraftRow,
    JournalEntryContactRow,
    JournalEntryProjectRow,
    JournalEntryRow,
    JournalEntryTaskRow,
    JournalSourceRow,
    ProjectRow,
)
from sidekick.shared.persistence.stores.keyset import rows_after
from sidekick.shared.types import KeyValue, utc_now
from sidekick.work.persistence.tags import tag_condition


class JournalEntryStore:
    """Journal sources, entries, pending items and entry relations.

    Mixin composed into ``SqlAlchemyStore``; methods are static and owner-filtered.
    """

    @staticmethod
    def save_journal_source(session: Session, source: JournalSource) -> None:
        session.add(
            JournalSourceRow(
                id=source.id,
                owner_id=source.owner_id,
                source_type=source.source_type.value,
                journal_date=source.journal_date,
                occurred_at=source.occurred_at,
                source_recorded_at=source.source_recorded_at,
                raw_text=source.raw_text,
                content_fingerprint=source.content_fingerprint,
                language=source.language,
                replaces_source_id=source.replaces_source_id,
                created_at=source.created_at,
            )
        )
        try:
            session.flush()
        except IntegrityError as error:
            raise ConflictError("journal source could not be created") from error

    @staticmethod
    def get_journal_source(session: Session, owner_id: UUID, source_id: UUID) -> JournalSource:
        row = session.scalar(
            select(JournalSourceRow).where(
                JournalSourceRow.id == source_id,
                JournalSourceRow.owner_id == owner_id,
                JournalSourceRow.trashed_at.is_(None),
            )
        )
        if row is None:
            raise NotFoundError("journal source not found")
        return journal_source_from_row(row)

    @staticmethod
    def save_journal_entry(session: Session, entry: JournalEntry) -> None:
        session.add(
            JournalEntryRow(
                id=entry.id,
                owner_id=entry.owner_id,
                source_id=entry.source_id,
                journal_date=entry.journal_date,
                occurred_at=entry.occurred_at,
                title=entry.title,
                summary=entry.summary,
                key_points=[
                    {"kind": point.kind.value, "text": point.text} for point in entry.key_points
                ],
                version=entry.version,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
                archived_at=entry.archived_at,
            )
        )
        try:
            session.flush()
        except IntegrityError as error:
            raise ConflictError("journal source already has an entry") from error

    @staticmethod
    def update_journal_entry(
        session: Session,
        *,
        owner_id: UUID,
        entry: JournalEntry,
        expected_version: int,
    ) -> JournalEntry:
        row = session.scalar(
            select(JournalEntryRow)
            .where(JournalEntryRow.id == entry.id, JournalEntryRow.owner_id == owner_id)
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("journal entry not found")
        if row.version != expected_version:
            raise ConflictError("stale entry version")
        row.title = entry.title
        row.summary = entry.summary
        row.key_points = [
            {"kind": point.kind.value, "text": point.text} for point in entry.key_points
        ]
        row.archived_at = entry.archived_at
        row.version = entry.version
        row.updated_at = entry.updated_at
        if row.source_id != entry.source_id:
            # An appended entry moves to the source that replaces its current one.
            row.source_id = entry.source_id
            session.flush()
            session.expire(row, ["source"])
        session.flush()
        return entry

    @staticmethod
    def get_journal_entry(session: Session, owner_id: UUID, entry_id: UUID) -> JournalEntry:
        row = session.scalar(
            select(JournalEntryRow)
            .join(
                JournalSourceRow,
                (JournalSourceRow.id == JournalEntryRow.source_id)
                & (JournalSourceRow.owner_id == JournalEntryRow.owner_id),
            )
            .options(joinedload(JournalEntryRow.source))
            .where(
                JournalEntryRow.id == entry_id,
                JournalEntryRow.owner_id == owner_id,
                JournalEntryRow.trashed_at.is_(None),
                JournalSourceRow.trashed_at.is_(None),
            )
        )
        if row is None:
            raise NotFoundError("journal entry not found")
        return journal_entry_from_row(row)

    @staticmethod
    def list_journal_entries(
        session: Session,
        owner_id: UUID,
        *,
        start_date: date,
        end_date: date,
        include_archived: bool = False,
        limit: int = 100,
        after: tuple[KeyValue, ...] | None = None,
        tags: tuple[str, ...] = (),
        tag_match: str = "any",
    ) -> list[JournalEntry]:
        """Entries in day order; `after` is the `entry_page_key` of the last entry already read.

        With `tags` only entries carrying any (or, with `tag_match="all"`, every) tag are listed.
        """

        # An entry with neither time sorts last: the sentinel replaces NULL so the whole key is
        # non-null and a keyset position can be compared against it.
        explicit_at = func.coalesce(
            JournalEntryRow.occurred_at,
            JournalSourceRow.source_recorded_at,
            literal(NO_OCCURRENCE, JournalEntryRow.occurred_at.type),
        )
        fallback_rank = case(
            (JournalEntryRow.occurred_at.is_not(None), 0),
            (JournalSourceRow.source_recorded_at.is_not(None), 1),
            else_=2,
        )
        statement = (
            select(JournalEntryRow)
            .join(
                JournalSourceRow,
                (JournalSourceRow.id == JournalEntryRow.source_id)
                & (JournalSourceRow.owner_id == JournalEntryRow.owner_id),
            )
            .options(joinedload(JournalEntryRow.source))
            .where(
                JournalEntryRow.owner_id == owner_id,
                JournalEntryRow.journal_date >= start_date,
                JournalEntryRow.journal_date <= end_date,
                JournalEntryRow.trashed_at.is_(None),
                JournalSourceRow.trashed_at.is_(None),
            )
        )
        if not include_archived:
            statement = statement.where(JournalEntryRow.archived_at.is_(None))
        if tags:
            statement = statement.where(
                tag_condition("journal_entry", JournalEntryRow.id, owner_id, tags, tag_match)
            )
        if after is not None:
            statement = statement.where(
                rows_after(
                    (explicit_at, fallback_rank, JournalEntryRow.created_at, JournalEntryRow.id),
                    after,
                    descending=False,
                )
            )
        rows = session.scalars(
            statement.order_by(
                explicit_at.asc(),
                fallback_rank.asc(),
                JournalEntryRow.created_at.asc(),
                JournalEntryRow.id.asc(),
            ).limit(limit)
        )
        return [journal_entry_from_row(row) for row in rows]

    @staticmethod
    def list_pending_journal_items(
        session: Session,
        owner_id: UUID,
        *,
        start_date: date,
        end_date: date,
        limit: int = 100,
    ) -> list[PendingJournalItem]:
        latest_pending_draft_id = (
            select(JournalDraftRow.id)
            .where(
                JournalDraftRow.owner_id == owner_id,
                JournalDraftRow.source_id == JournalSourceRow.id,
                JournalDraftRow.state == "pending_review",
            )
            .order_by(JournalDraftRow.created_at.desc(), JournalDraftRow.id.desc())
            .limit(1)
            .correlate(JournalSourceRow)
            .scalar_subquery()
        )
        entry_exists = (
            select(JournalEntryRow.id)
            .where(
                JournalEntryRow.owner_id == owner_id,
                JournalEntryRow.source_id == JournalSourceRow.id,
            )
            .correlate(JournalSourceRow)
            .exists()
        )
        # A source that a live source replaces (an append, or a replacement source) is history, not
        # pending work: the entry points at the replacement.
        replacement = aliased(JournalSourceRow)
        replaced = (
            select(replacement.id)
            .where(
                replacement.owner_id == owner_id,
                replacement.replaces_source_id == JournalSourceRow.id,
                replacement.trashed_at.is_(None),
            )
            .correlate(JournalSourceRow)
            .exists()
        )
        rows = session.execute(
            select(
                JournalSourceRow,
                JournalDraftRow.id,
                JournalDraftRow.title,
            )
            .outerjoin(JournalDraftRow, JournalDraftRow.id == latest_pending_draft_id)
            .where(
                JournalSourceRow.owner_id == owner_id,
                JournalSourceRow.journal_date >= start_date,
                JournalSourceRow.journal_date <= end_date,
                ~entry_exists,
                ~replaced,
            )
            .order_by(JournalSourceRow.created_at.desc(), JournalSourceRow.id.desc())
            .limit(limit)
        )
        return [
            PendingJournalItem(
                source_id=source.id,
                journal_date=source.journal_date,
                source_type=SourceType(source.source_type),
                source_created_at=source.created_at,
                character_count=len(source.raw_text),
                draft_id=draft_id,
                draft_title=draft_title,
            )
            for source, draft_id, draft_title in rows
        ]

    @staticmethod
    def add_journal_entry_relations(
        session: Session,
        *,
        owner_id: UUID,
        entry_id: UUID,
        project_ids: tuple[UUID, ...],
        task_ids: tuple[UUID, ...],
        contact_ids: tuple[UUID, ...],
    ) -> None:
        created_at = utc_now()
        session.add_all(
            [
                JournalEntryProjectRow(
                    owner_id=owner_id,
                    entry_id=entry_id,
                    project_id=project_id,
                    created_at=created_at,
                )
                for project_id in project_ids
            ]
            + [
                JournalEntryTaskRow(
                    owner_id=owner_id,
                    entry_id=entry_id,
                    task_id=task_id,
                    created_at=created_at,
                )
                for task_id in task_ids
            ]
            + [
                JournalEntryContactRow(
                    owner_id=owner_id,
                    entry_id=entry_id,
                    contact_id=contact_id,
                    created_at=created_at,
                )
                for contact_id in contact_ids
            ]
        )
        try:
            session.flush()
        except IntegrityError as error:
            raise ConflictError("journal entry relations could not be created") from error

    @staticmethod
    def remove_journal_entry_relations(
        session: Session,
        *,
        owner_id: UUID,
        entry_id: UUID,
        project_ids: tuple[UUID, ...],
        contact_ids: tuple[UUID, ...],
    ) -> None:
        if project_ids:
            session.execute(
                delete(JournalEntryProjectRow).where(
                    JournalEntryProjectRow.owner_id == owner_id,
                    JournalEntryProjectRow.entry_id == entry_id,
                    JournalEntryProjectRow.project_id.in_(project_ids),
                )
            )
        if contact_ids:
            session.execute(
                delete(JournalEntryContactRow).where(
                    JournalEntryContactRow.owner_id == owner_id,
                    JournalEntryContactRow.entry_id == entry_id,
                    JournalEntryContactRow.contact_id.in_(contact_ids),
                )
            )
        session.flush()

    @staticmethod
    def get_journal_relation_labels(
        session: Session,
        owner_id: UUID,
        project_ids: tuple[UUID, ...],
        contact_ids: tuple[UUID, ...],
    ) -> RelationLabels:
        """Names of linked records the owner still has; a trashed record gets no name."""

        projects = (
            {
                row.id: row.title
                for row in session.execute(
                    select(ProjectRow.id, ProjectRow.title).where(
                        ProjectRow.owner_id == owner_id,
                        ProjectRow.id.in_(project_ids),
                        ProjectRow.trashed_at.is_(None),
                    )
                )
            }
            if project_ids
            else {}
        )
        contacts = (
            {
                row.id: row.display_name
                for row in session.execute(
                    select(ContactRow.id, ContactRow.display_name).where(
                        ContactRow.owner_id == owner_id,
                        ContactRow.id.in_(contact_ids),
                        ContactRow.trashed_at.is_(None),
                    )
                )
            }
            if contact_ids
            else {}
        )
        return RelationLabels(projects=projects, contacts=contacts)

    @staticmethod
    def get_journal_entry_relations(
        session: Session, owner_id: UUID, entry_id: UUID
    ) -> EntryRelations:
        project_ids = tuple(
            session.scalars(
                select(JournalEntryProjectRow.project_id)
                .where(
                    JournalEntryProjectRow.owner_id == owner_id,
                    JournalEntryProjectRow.entry_id == entry_id,
                )
                .order_by(JournalEntryProjectRow.project_id.asc())
            )
        )
        task_ids = tuple(
            session.scalars(
                select(JournalEntryTaskRow.task_id)
                .where(
                    JournalEntryTaskRow.owner_id == owner_id,
                    JournalEntryTaskRow.entry_id == entry_id,
                )
                .order_by(JournalEntryTaskRow.task_id.asc())
            )
        )
        contact_ids = tuple(
            session.scalars(
                select(JournalEntryContactRow.contact_id)
                .where(
                    JournalEntryContactRow.owner_id == owner_id,
                    JournalEntryContactRow.entry_id == entry_id,
                )
                .order_by(JournalEntryContactRow.contact_id.asc())
            )
        )
        return EntryRelations(
            project_ids=project_ids,
            task_ids=task_ids,
            contact_ids=contact_ids,
        )

    @staticmethod
    def get_journal_entries_relations(
        session: Session, owner_id: UUID, entry_ids: tuple[UUID, ...]
    ) -> dict[UUID, EntryRelations]:
        """Project, Task and Contact links of several entries in three queries, id-ordered
        within each entry like `get_journal_entry_relations`."""

        if not entry_ids:
            return {}
        projects: dict[UUID, list[UUID]] = {}
        for entry_id, project_id in session.execute(
            select(JournalEntryProjectRow.entry_id, JournalEntryProjectRow.project_id)
            .where(
                JournalEntryProjectRow.owner_id == owner_id,
                JournalEntryProjectRow.entry_id.in_(entry_ids),
            )
            .order_by(JournalEntryProjectRow.project_id.asc())
        ):
            projects.setdefault(entry_id, []).append(project_id)
        tasks: dict[UUID, list[UUID]] = {}
        for entry_id, task_id in session.execute(
            select(JournalEntryTaskRow.entry_id, JournalEntryTaskRow.task_id)
            .where(
                JournalEntryTaskRow.owner_id == owner_id,
                JournalEntryTaskRow.entry_id.in_(entry_ids),
            )
            .order_by(JournalEntryTaskRow.task_id.asc())
        ):
            tasks.setdefault(entry_id, []).append(task_id)
        contacts: dict[UUID, list[UUID]] = {}
        for entry_id, contact_id in session.execute(
            select(JournalEntryContactRow.entry_id, JournalEntryContactRow.contact_id)
            .where(
                JournalEntryContactRow.owner_id == owner_id,
                JournalEntryContactRow.entry_id.in_(entry_ids),
            )
            .order_by(JournalEntryContactRow.contact_id.asc())
        ):
            contacts.setdefault(entry_id, []).append(contact_id)
        return {
            entry_id: EntryRelations(
                project_ids=tuple(projects.get(entry_id, ())),
                task_ids=tuple(tasks.get(entry_id, ())),
                contact_ids=tuple(contacts.get(entry_id, ())),
            )
            for entry_id in entry_ids
        }

    @staticmethod
    def list_active_journal_entry_heads(
        session: Session, owner_id: UUID, journal_date: date
    ) -> list[EntryHead]:
        """The day's active entries as id, version and ordering fields only, in occurrence
        order: the fingerprint and the summary status need no entry text."""

        rows = session.execute(
            select(
                JournalEntryRow.id,
                JournalEntryRow.version,
                JournalEntryRow.occurred_at,
                JournalSourceRow.source_recorded_at,
                JournalEntryRow.created_at,
            )
            .join(
                JournalSourceRow,
                (JournalSourceRow.id == JournalEntryRow.source_id)
                & (JournalSourceRow.owner_id == JournalEntryRow.owner_id),
            )
            .where(
                JournalEntryRow.owner_id == owner_id,
                JournalEntryRow.journal_date == journal_date,
                JournalEntryRow.archived_at.is_(None),
                JournalEntryRow.trashed_at.is_(None),
                JournalSourceRow.trashed_at.is_(None),
            )
            .order_by(
                func.coalesce(JournalEntryRow.occurred_at, JournalSourceRow.source_recorded_at)
                .asc()
                .nulls_last(),
                JournalEntryRow.created_at.asc(),
                JournalEntryRow.id.asc(),
            )
        )
        return [EntryHead(*row) for row in rows]

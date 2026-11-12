"""SQLAlchemy implementation of `MemoryStore`: every statement the memory use cases run.

The statements moved here unchanged from the application modules; the rules about when to run them
stay in `sidekick.memory.application`. Each method filters by owner itself.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, tzinfo
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    CursorResult,
    Engine,
    and_,
    case,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased, sessionmaker

from sidekick.memory.application.queries import DEFAULT_PAGE_SIZE, MemoryCandidate, MemoryTombstone
from sidekick.memory.application.records import MemorySettingsRecord, MemorySourceRecord
from sidekick.memory.application.store import (
    CitedRecord,
    DailyUsage,
    LiveSource,
    OwnerLockPort,
    RecordTitle,
    SourceCountRow,
    SourceFlags,
    SourceRef,
)
from sidekick.memory.application.sync import (
    FAILED,
    PARKED,
    PENDING,
    REMOVED_CATEGORY,
    RETAINED,
    SUBMITTED,
)
from sidekick.memory.domain import MEMORY_PIPELINE_VERSION, MemoryKind
from sidekick.memory.infrastructure import candidates
from sidekick.memory.infrastructure.lock import OwnerLock
from sidekick.shared.persistence.models import (
    ContactRow,
    JournalEntryRow,
    JournalSourceRow,
    MemorySettingsRow,
    MemorySourceRow,
    MemoryUsageDailyRow,
    ProjectRow,
    TaskRow,
    UserRow,
)
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import new_uuid7

#: The fingerprint of a marker row: no document was ever computed for it.
_PLACEHOLDER_FINGERPRINT = "0" * 64


def _settings_record(row: MemorySettingsRow | None) -> MemorySettingsRecord | None:
    """The row as the use cases' record type: a type checker sees `Mapped[...]`, an instance holds
    plain values, so the cast changes nothing at run time."""

    return cast("MemorySettingsRecord | None", row)


def _source_record(row: MemorySourceRow) -> MemorySourceRecord:
    """The row as the use cases' record type (see `_settings_record`)."""

    return cast("MemorySourceRecord", row)


class SqlAlchemyMemoryStore:
    """`MemoryStore` over a `sessionmaker` bound to the application engine."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    # -- units of work --

    def read(self) -> AbstractContextManager[Session]:
        return self._factory()

    def begin(self) -> AbstractContextManager[Session]:
        return self._factory.begin()

    def owner_lock(self, owner_id: UUID) -> OwnerLockPort:
        with self._factory() as session:
            bind = session.get_bind()
        if not isinstance(bind, Engine):
            raise TypeError("memory sync needs a session factory bound to an engine")
        return OwnerLock(bind, owner_id)

    # -- audit --

    @staticmethod
    def append_audit(
        session: Session,
        *,
        actor_id: UUID | None,
        event: str,
        outcome: str,
        target_type: str | None = None,
        target_id: UUID | None = None,
        related_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> None:
        StoreBase.append_audit(
            session,
            actor_id=actor_id,
            event=event,
            outcome=outcome,
            target_type=target_type,
            target_id=target_id,
            related_id=related_id,
            correlation_id=correlation_id,
        )

    # -- settings --

    @staticmethod
    def settings(
        session: Session, owner_id: UUID, *, fresh: bool = False
    ) -> MemorySettingsRecord | None:
        if not fresh:
            return _settings_record(session.get(MemorySettingsRow, owner_id))
        return _settings_record(
            session.scalar(
                select(MemorySettingsRow)
                .where(MemorySettingsRow.owner_id == owner_id)
                .execution_options(populate_existing=True)
            )
        )

    @staticmethod
    def settings_for_update(session: Session, owner_id: UUID) -> MemorySettingsRecord | None:
        return _settings_record(
            session.scalar(
                select(MemorySettingsRow)
                .where(MemorySettingsRow.owner_id == owner_id)
                .with_for_update()
            )
        )

    @staticmethod
    def insert_default_settings(session: Session, owner_id: UUID, now: datetime) -> None:
        session.execute(
            pg_insert(MemorySettingsRow)
            .values(owner_id=owner_id, version=1, created_at=now, updated_at=now)
            .on_conflict_do_nothing(index_elements=[MemorySettingsRow.owner_id])
        )

    @staticmethod
    def create_settings(
        session: Session,
        owner_id: UUID,
        *,
        journal: bool,
        contacts: bool,
        projects: bool,
        tasks: bool,
        paused: bool,
        now: datetime,
    ) -> bool:
        inserted = session.execute(
            pg_insert(MemorySettingsRow)
            .values(
                owner_id=owner_id,
                journal=journal,
                contacts=contacts,
                projects=projects,
                tasks=tasks,
                paused=paused,
                version=1,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[MemorySettingsRow.owner_id])
            .returning(MemorySettingsRow.owner_id)
        )
        return inserted.first() is not None

    # -- sources --

    @staticmethod
    def source_counts(
        session: Session, owner_id: UUID, kinds: list[MemoryKind]
    ) -> list[SourceCountRow]:
        marker = case(
            (
                (MemorySourceRow.status == PARKED)
                & (MemorySourceRow.failure_category == REMOVED_CATEGORY),
                True,
            ),
            else_=False,
        )
        rows = session.execute(
            select(
                MemorySourceRow.source_kind,
                MemorySourceRow.status,
                MemorySourceRow.excluded,
                marker,
                func.count(),
            )
            .where(
                MemorySourceRow.owner_id == owner_id,
                MemorySourceRow.source_kind.in_([kind.value for kind in kinds]),
            )
            .group_by(
                MemorySourceRow.source_kind,
                MemorySourceRow.status,
                MemorySourceRow.excluded,
                marker,
            )
        ).all()
        return [
            SourceCountRow(source_kind, status, excluded, is_marker, count)
            for source_kind, status, excluded, is_marker, count in rows
        ]

    @staticmethod
    def retained_document_count(session: Session, owner_id: UUID, kind: MemoryKind) -> int:
        count = session.scalar(
            select(func.count())
            .select_from(MemorySourceRow)
            .where(
                MemorySourceRow.owner_id == owner_id,
                MemorySourceRow.source_kind == kind.value,
                MemorySourceRow.status == RETAINED,
                MemorySourceRow.excluded.is_(False),
            )
        )
        return int(count or 0)

    @staticmethod
    def record_title(
        session: Session, owner_id: UUID, kind: MemoryKind, source_id: UUID
    ) -> RecordTitle | None:
        if kind is MemoryKind.JOURNAL_ENTRY:
            statement = select(JournalEntryRow.title).where(
                JournalEntryRow.id == source_id,
                JournalEntryRow.owner_id == owner_id,
                JournalEntryRow.trashed_at.is_(None),
            )
        elif kind is MemoryKind.CONTACT:
            statement = select(ContactRow.display_name).where(
                ContactRow.id == source_id,
                ContactRow.owner_id == owner_id,
                ContactRow.trashed_at.is_(None),
            )
        elif kind is MemoryKind.PROJECT:
            statement = select(ProjectRow.title).where(
                ProjectRow.id == source_id,
                ProjectRow.owner_id == owner_id,
                ProjectRow.trashed_at.is_(None),
            )
        else:
            statement = select(TaskRow.title).where(
                TaskRow.id == source_id,
                TaskRow.owner_id == owner_id,
                TaskRow.trashed_at.is_(None),
            )
        found = session.execute(statement).all()
        if not found:
            return None
        return RecordTitle(found[0][0])

    @staticmethod
    def add_source(
        session: Session,
        *,
        owner_id: UUID,
        kind: MemoryKind,
        source_id: UUID,
        doc_key: str,
        fingerprint: str,
        pipeline_version: int,
        status: str,
        source_updated_at: datetime,
    ) -> MemorySourceRecord:
        row = MemorySourceRow(
            id=new_uuid7(),
            owner_id=owner_id,
            source_kind=kind.value,
            source_id=source_id,
            doc_key=doc_key,
            fingerprint=fingerprint,
            pipeline_version=pipeline_version,
            status=status,
            attempts=0,
            next_attempt_at=None,
            operation_id=None,
            source_updated_at=source_updated_at,
            retained_at=None,
            failure_category=None,
            excluded=False,
        )
        session.add(row)
        return _source_record(row)

    @staticmethod
    def source_row_for_update(
        session: Session, owner_id: UUID, kind: MemoryKind, source_id: UUID
    ) -> MemorySourceRecord | None:
        row = session.scalar(
            select(MemorySourceRow)
            .where(
                MemorySourceRow.owner_id == owner_id,
                MemorySourceRow.source_kind == kind.value,
                MemorySourceRow.source_id == source_id,
            )
            .with_for_update()
        )
        return None if row is None else _source_record(row)

    @staticmethod
    def upsert_exclusion_marker(
        session: Session,
        owner_id: UUID,
        kind: MemoryKind,
        source_id: UUID,
        *,
        doc_key: str,
        now: datetime,
    ) -> None:
        marker = pg_insert(MemorySourceRow).values(
            id=new_uuid7(),
            owner_id=owner_id,
            source_kind=kind.value,
            source_id=source_id,
            doc_key=doc_key,
            fingerprint=_PLACEHOLDER_FINGERPRINT,
            pipeline_version=MEMORY_PIPELINE_VERSION,
            status=PARKED,
            attempts=0,
            next_attempt_at=None,
            operation_id=None,
            source_updated_at=now,
            retained_at=None,
            failure_category=REMOVED_CATEGORY,
            excluded=True,
        )
        session.execute(
            marker.on_conflict_do_update(
                constraint="uq_memory_sources_source", set_={"excluded": True}
            )
        )

    @staticmethod
    def sources_for_documents(
        session: Session, owner_id: UUID, doc_keys: set[str]
    ) -> list[SourceRef]:
        rows = session.execute(
            select(
                MemorySourceRow.doc_key,
                MemorySourceRow.source_kind,
                MemorySourceRow.source_id,
                MemorySourceRow.status,
                MemorySourceRow.source_updated_at,
                MemorySourceRow.retained_at,
                MemorySourceRow.failure_category,
            ).where(
                MemorySourceRow.owner_id == owner_id,
                MemorySourceRow.doc_key.in_(sorted(doc_keys)),
                MemorySourceRow.excluded.is_(False),
            )
        ).all()
        return [
            SourceRef(
                doc_key,
                source_kind,
                source_id,
                status,
                source_updated_at,
                retained_at,
                removed_marker=status == PARKED and failure_category == REMOVED_CATEGORY,
            )
            for (
                doc_key,
                source_kind,
                source_id,
                status,
                source_updated_at,
                retained_at,
                failure_category,
            ) in rows
        ]

    @classmethod
    def live_sources(
        cls, session: Session, owner_id: UUID, kind: MemoryKind, source_ids: set[UUID]
    ) -> dict[UUID, LiveSource]:
        if kind is MemoryKind.JOURNAL_ENTRY:
            return cls._live_journal_entries(session, owner_id, source_ids)
        model: type[ContactRow] | type[ProjectRow] | type[TaskRow]
        if kind is MemoryKind.CONTACT:
            model = ContactRow
        elif kind is MemoryKind.PROJECT:
            model = ProjectRow
        else:
            model = TaskRow
        rows = session.execute(
            select(model.id, model.archived_at, model.updated_at).where(
                model.owner_id == owner_id,
                model.id.in_(sorted(source_ids)),
                model.trashed_at.is_(None),
            )
        ).all()
        return {
            row_id: LiveSource(archived_at is not None, updated_at)
            for row_id, archived_at, updated_at in rows
        }

    @staticmethod
    def _live_journal_entries(
        session: Session, owner_id: UUID, entry_ids: set[UUID]
    ) -> dict[UUID, LiveSource]:
        """Entries whose entry and source are untrashed and not replaced by a live source."""

        replacement = aliased(JournalSourceRow)
        replaced = (
            select(replacement.id)
            .where(
                replacement.owner_id == owner_id,
                replacement.replaces_source_id == JournalSourceRow.id,
                replacement.trashed_at.is_(None),
            )
            .exists()
        )
        rows = session.execute(
            select(JournalEntryRow.id, JournalEntryRow.archived_at, JournalEntryRow.updated_at)
            .select_from(JournalEntryRow)
            .join(
                JournalSourceRow,
                and_(
                    JournalSourceRow.id == JournalEntryRow.source_id,
                    JournalSourceRow.owner_id == JournalEntryRow.owner_id,
                ),
            )
            .where(
                JournalEntryRow.owner_id == owner_id,
                JournalEntryRow.id.in_(sorted(entry_ids)),
                JournalEntryRow.trashed_at.is_(None),
                JournalSourceRow.trashed_at.is_(None),
                ~replaced,
            )
        ).all()
        return {
            row_id: LiveSource(archived_at is not None, updated_at)
            for row_id, archived_at, updated_at in rows
        }

    @staticmethod
    def cited_records(
        session: Session, owner_id: UUID, kind: MemoryKind, record_ids: list[UUID]
    ) -> list[CitedRecord]:
        if kind is MemoryKind.JOURNAL_ENTRY:
            journal_rows = session.execute(
                select(
                    JournalEntryRow.id, JournalEntryRow.title, JournalEntryRow.journal_date
                ).where(
                    JournalEntryRow.owner_id == owner_id,
                    JournalEntryRow.id.in_(record_ids),
                    JournalEntryRow.trashed_at.is_(None),
                )
            ).all()
            return [CitedRecord(row_id, title, day) for row_id, title, day in journal_rows]
        if kind is MemoryKind.CONTACT:
            contact_rows = session.execute(
                select(ContactRow.id, ContactRow.display_name).where(
                    ContactRow.owner_id == owner_id,
                    ContactRow.id.in_(record_ids),
                    ContactRow.trashed_at.is_(None),
                )
            ).all()
            return [CitedRecord(row_id, name, None) for row_id, name in contact_rows]
        if kind is MemoryKind.PROJECT:
            project_rows = session.execute(
                select(ProjectRow.id, ProjectRow.title, ProjectRow.start_date).where(
                    ProjectRow.owner_id == owner_id,
                    ProjectRow.id.in_(record_ids),
                    ProjectRow.trashed_at.is_(None),
                )
            ).all()
            return [CitedRecord(row_id, title, day) for row_id, title, day in project_rows]
        task_rows = session.execute(
            select(TaskRow.id, TaskRow.title, TaskRow.completed_at).where(
                TaskRow.owner_id == owner_id,
                TaskRow.id.in_(record_ids),
                TaskRow.trashed_at.is_(None),
            )
        ).all()
        # The memory domain dates a Task by its completion day in UTC (the owner time zone for now).
        return [
            CitedRecord(
                row_id, title, None if completed is None else completed.astimezone(UTC).date()
            )
            for row_id, title, completed in task_rows
        ]

    # -- sync pass --

    @staticmethod
    def owner_ids(session: Session) -> list[UUID]:
        rows = session.execute(
            select(MemorySettingsRow.owner_id).union(select(MemorySourceRow.owner_id))
        ).all()
        return [row[0] for row in rows]

    @staticmethod
    def submitted_operations(
        session: Session, owner_id: UUID
    ) -> list[tuple[str | None, datetime | None]]:
        rows = session.execute(
            select(MemorySourceRow.operation_id, MemorySourceRow.next_attempt_at)
            .where(
                MemorySourceRow.owner_id == owner_id,
                MemorySourceRow.status == SUBMITTED,
                MemorySourceRow.operation_id.is_not(None),
            )
            .order_by(MemorySourceRow.id)
        ).all()
        return [(operation_id, deadline) for operation_id, deadline in rows]

    @staticmethod
    def submitted_rows_for_update(
        session: Session, owner_id: UUID, operation_id: str
    ) -> list[MemorySourceRecord]:
        return list(
            map(
                _source_record,
                session.scalars(
                    select(MemorySourceRow)
                    .where(
                        MemorySourceRow.owner_id == owner_id,
                        MemorySourceRow.operation_id == operation_id,
                        MemorySourceRow.status == SUBMITTED,
                    )
                    .with_for_update()
                ).all(),
            )
        )

    @staticmethod
    def candidate_page(
        session: Session,
        owner_id: UUID,
        kind: MemoryKind,
        *,
        owner_timezone: tzinfo,
        after: UUID | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[MemoryCandidate]:
        return candidates.candidate_page(
            session, owner_id, kind, owner_timezone=owner_timezone, after=after, limit=limit
        )

    @staticmethod
    def tombstone_page(
        session: Session,
        owner_id: UUID,
        kind: MemoryKind,
        *,
        after: UUID | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[MemoryTombstone]:
        return candidates.tombstone_page(session, owner_id, kind, after=after, limit=limit)

    @staticmethod
    def source_rows_by_id(
        session: Session, owner_id: UUID, row_ids: list[UUID]
    ) -> dict[UUID, MemorySourceRecord]:
        return {
            row.id: _source_record(row)
            for row in session.scalars(
                select(MemorySourceRow).where(
                    MemorySourceRow.owner_id == owner_id, MemorySourceRow.id.in_(row_ids)
                )
            )
        }

    @staticmethod
    def source_rows_by_record(
        session: Session, owner_id: UUID, kind: MemoryKind, source_ids: list[UUID]
    ) -> dict[UUID, MemorySourceRecord]:
        return {
            row.source_id: _source_record(row)
            for row in session.scalars(
                select(MemorySourceRow).where(
                    MemorySourceRow.owner_id == owner_id,
                    MemorySourceRow.source_kind == kind.value,
                    MemorySourceRow.source_id.in_(source_ids),
                )
            )
        }

    @staticmethod
    def source_rows_for_update(
        session: Session, owner_id: UUID, row_ids: list[UUID]
    ) -> dict[UUID, MemorySourceRecord]:
        return {
            row.id: _source_record(row)
            for row in session.scalars(
                select(MemorySourceRow)
                .where(MemorySourceRow.owner_id == owner_id, MemorySourceRow.id.in_(row_ids))
                .with_for_update()
            )
        }

    @staticmethod
    def settle_removed_row(
        session: Session,
        *,
        row_id: UUID,
        doc_key: str,
        excluded: bool,
        hold_until: datetime | None,
    ) -> bool:
        if excluded or hold_until is not None:
            session.execute(
                update(MemorySourceRow)
                .where(MemorySourceRow.id == row_id, MemorySourceRow.doc_key == doc_key)
                .values(
                    status=PARKED,
                    failure_category=REMOVED_CATEGORY,
                    operation_id=None,
                    next_attempt_at=hold_until,
                    attempts=0,
                )
            )
            return True
        session.execute(
            delete(MemorySourceRow).where(
                MemorySourceRow.id == row_id, MemorySourceRow.doc_key == doc_key
            )
        )
        return False

    @staticmethod
    def source_flags(session: Session, owner_id: UUID, row_ids: list[UUID]) -> list[SourceFlags]:
        rows = session.execute(
            select(MemorySourceRow.id, MemorySourceRow.source_kind, MemorySourceRow.excluded).where(
                MemorySourceRow.owner_id == owner_id,
                MemorySourceRow.id.in_(row_ids),
            )
        ).all()
        return [SourceFlags(row_id, kind, excluded) for row_id, kind, excluded in rows]

    @staticmethod
    def mark_submitted(
        session: Session, row_ids: list[UUID], *, operation_id: str, deadline: datetime
    ) -> None:
        session.execute(
            update(MemorySourceRow)
            .where(
                MemorySourceRow.id.in_(row_ids),
                MemorySourceRow.status.in_([PENDING, FAILED]),
            )
            .values(
                status=SUBMITTED,
                operation_id=operation_id,
                next_attempt_at=deadline,
                failure_category=None,
            )
        )

    @staticmethod
    def daily_usage(session: Session, owner_id: UUID, day: date) -> DailyUsage:
        usage = session.get(MemoryUsageDailyRow, (owner_id, day))
        if usage is None:
            return DailyUsage()
        return DailyUsage(usage.retain_documents, usage.backfill_documents, usage.characters)

    @staticmethod
    def charge_usage(
        session: Session,
        owner_id: UUID,
        day: date,
        *,
        live: int,
        backfill: int,
        characters: int,
        live_cap: int,
        backfill_cap: int,
        char_cap: int,
        single_document: bool,
    ) -> bool:
        fits: ColumnElement[bool] = MemoryUsageDailyRow.characters + characters <= char_cap
        if single_document:
            # A single document longer than the whole cap is only allowed on a day with nothing
            # sent.
            fits = or_(fits, MemoryUsageDailyRow.characters == 0)
        statement = pg_insert(MemoryUsageDailyRow).values(
            owner_id=owner_id,
            usage_date=day,
            retain_documents=live,
            backfill_documents=backfill,
            characters=characters,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[MemoryUsageDailyRow.owner_id, MemoryUsageDailyRow.usage_date],
            set_={
                "retain_documents": MemoryUsageDailyRow.retain_documents + live,
                "backfill_documents": MemoryUsageDailyRow.backfill_documents + backfill,
                "characters": MemoryUsageDailyRow.characters + characters,
            },
            where=and_(
                MemoryUsageDailyRow.retain_documents + live <= live_cap,
                MemoryUsageDailyRow.backfill_documents + backfill <= backfill_cap,
                fits,
            ),
        ).returning(MemoryUsageDailyRow.owner_id)
        return session.execute(statement).first() is not None

    @staticmethod
    def refund_usage(
        session: Session,
        owner_id: UUID,
        day: date,
        *,
        live: int,
        backfill: int,
        characters: int,
    ) -> None:
        session.execute(
            update(MemoryUsageDailyRow)
            .where(
                MemoryUsageDailyRow.owner_id == owner_id,
                MemoryUsageDailyRow.usage_date == day,
            )
            .values(
                retain_documents=func.greatest(MemoryUsageDailyRow.retain_documents - live, 0),
                backfill_documents=func.greatest(
                    MemoryUsageDailyRow.backfill_documents - backfill, 0
                ),
                characters=func.greatest(MemoryUsageDailyRow.characters - characters, 0),
            )
        )

    # -- bank lifecycle --

    @staticmethod
    def owners_with_retained_rows(session: Session) -> list[UUID]:
        return list(
            session.scalars(
                select(MemorySourceRow.owner_id)
                .join(UserRow, UserRow.id == MemorySourceRow.owner_id)
                .where(MemorySourceRow.status == RETAINED, MemorySourceRow.excluded.is_(False))
                .distinct()
                .order_by(MemorySourceRow.owner_id)
            ).all()
        )

    @staticmethod
    def living_owner_ids(session: Session) -> list[UUID]:
        return list(session.scalars(select(UserRow.id)).all())

    @staticmethod
    def owners_expecting_banks(session: Session) -> set[UUID]:
        return set(
            session.scalars(
                select(MemorySourceRow.owner_id)
                .where(MemorySourceRow.status == RETAINED, MemorySourceRow.excluded.is_(False))
                .distinct()
            ).all()
        )

    @staticmethod
    def reset_retained_rows(session: Session, owner_id: UUID) -> int:
        reset = session.execute(
            update(MemorySourceRow)
            .where(
                MemorySourceRow.owner_id == owner_id,
                MemorySourceRow.status == RETAINED,
                MemorySourceRow.excluded.is_(False),
            )
            .values(
                status=PENDING,
                attempts=0,
                next_attempt_at=None,
                operation_id=None,
                failure_category=None,
            )
        )
        return cast(CursorResult[Any], reset).rowcount

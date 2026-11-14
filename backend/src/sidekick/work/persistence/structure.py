"""Domains, saved views, Processes, Process runs and the run outbox."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sidekick.shared.cadence import Cadence
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sidekick.shared.persistence.models import (
    DomainRow,
    ProcessRow,
    ProcessRunOutboxRow,
    ProcessRunRow,
    ProcessRunTemplateRow,
    SavedViewRow,
)
from sidekick.shared.persistence.stores.keyset import rows_after
from sidekick.shared.types import KeyValue, new_uuid7
from sidekick.work.domain import (
    Domain,
    DomainStatus,
    Process,
    ProcessRun,
    ProcessRunOutbox,
    ProcessRunTemplate,
    ProcessStatus,
)
from sidekick.work.domain.saved_view import SavedView, SavedViewDefinition
from sidekick.work.persistence.mappers import (
    domain_from_row,
    domain_to_row,
    process_from_row,
    process_run_from_row,
    process_run_outbox_from_row,
    process_run_template_from_row,
    process_to_row,
)


def _saved_view_from_row(row: SavedViewRow) -> SavedView:
    # The definition was checked by `validate_definition` before it was stored.
    return SavedView(
        row.id,
        row.owner_id,
        row.name,
        cast("SavedViewDefinition", row.definition),
        row.version,
        row.archived_at,
    )


class WorkStructureStore:
    """Domains, saved views, Processes, Process runs and the run outbox.

    The operations are static and owner-filtered; `SqlWorkStore` adds the transaction boundary.
    """

    @staticmethod
    def get_domain(session: Session, owner_id: UUID, domain_id: UUID) -> Domain:
        row = session.scalar(
            select(DomainRow).where(
                DomainRow.id == domain_id,
                DomainRow.owner_id == owner_id,
                DomainRow.trashed_at.is_(None),
            )
        )
        if row is None:
            raise NotFoundError("domain not found")
        return domain_from_row(row)

    @staticmethod
    def list_saved_views(
        session: Session, owner_id: UUID, include_archived: bool = False
    ) -> list[SavedView]:
        statement = select(SavedViewRow).where(SavedViewRow.owner_id == owner_id)
        if not include_archived:
            statement = statement.where(SavedViewRow.archived_at.is_(None))
        rows = session.scalars(statement.order_by(SavedViewRow.name.asc(), SavedViewRow.id.asc()))
        return [_saved_view_from_row(row) for row in rows]

    @staticmethod
    def get_saved_view(session: Session, owner_id: UUID, view_id: UUID) -> SavedView:
        row = session.scalar(
            select(SavedViewRow).where(
                SavedViewRow.id == view_id, SavedViewRow.owner_id == owner_id
            )
        )
        if row is None:
            raise NotFoundError("saved view not found")
        return _saved_view_from_row(row)

    @staticmethod
    def save_saved_view(
        session: Session, item: SavedView, expected_version: int | None = None
    ) -> None:
        row = session.scalar(
            select(SavedViewRow).where(SavedViewRow.id == item.id).with_for_update()
        )
        if row is None:
            session.add(
                SavedViewRow(
                    id=item.id,
                    owner_id=item.owner_id,
                    name=item.name,
                    definition=dict(item.definition),
                    version=item.version,
                    archived_at=item.archived_at,
                )
            )
            return
        if row.owner_id != item.owner_id:
            raise NotFoundError("saved view not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale saved view version")
        row.name, row.definition, row.version, row.archived_at = (
            item.name,
            dict(item.definition),
            item.version,
            item.archived_at,
        )

    @staticmethod
    def list_domains(
        session: Session,
        owner_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Domain]:
        statement = select(DomainRow).where(
            DomainRow.owner_id == owner_id, DomainRow.trashed_at.is_(None)
        )
        if not include_archived:
            statement = statement.where(DomainRow.status != DomainStatus.ARCHIVED.value)
        if after is not None:
            statement = statement.where(
                rows_after((DomainRow.updated_at, DomainRow.id), after, descending=True)
            )
        rows = session.scalars(
            statement.order_by(DomainRow.updated_at.desc(), DomainRow.id.desc()).limit(limit)
        )
        return [domain_from_row(row) for row in rows]

    @staticmethod
    def save_domain(session: Session, domain: Domain, expected_version: int | None = None) -> None:
        row = session.scalar(select(DomainRow).where(DomainRow.id == domain.id).with_for_update())
        if row is None:
            session.add(domain_to_row(domain))
            return
        if row.owner_id != domain.owner_id:
            raise NotFoundError("domain not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale domain version")
        for field in (
            "name",
            "description",
            "status",
            "review_cadence",
            "last_reviewed_at",
            "accent",
            "updated_at",
            "version",
        ):
            value = getattr(domain, field)
            setattr(
                row, field, value.value if isinstance(value, (DomainStatus, Cadence)) else value
            )

    @staticmethod
    def get_process(session: Session, owner_id: UUID, process_id: UUID) -> Process:
        row = session.scalar(
            select(ProcessRow).where(
                ProcessRow.id == process_id,
                ProcessRow.owner_id == owner_id,
                ProcessRow.trashed_at.is_(None),
            )
        )
        if row is None:
            raise NotFoundError("process not found")
        return process_from_row(row)

    @staticmethod
    def list_processes(
        session: Session,
        owner_id: UUID,
        limit: int,
        domain_id: UUID | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Process]:
        statement = select(ProcessRow).where(
            ProcessRow.owner_id == owner_id, ProcessRow.trashed_at.is_(None)
        )
        if not include_archived:
            statement = statement.where(ProcessRow.status != ProcessStatus.ARCHIVED.value)
        if domain_id is not None:
            statement = statement.where(ProcessRow.domain_id == domain_id)
        if after is not None:
            statement = statement.where(
                rows_after((ProcessRow.updated_at, ProcessRow.id), after, descending=True)
            )
        rows = session.scalars(
            statement.order_by(ProcessRow.updated_at.desc(), ProcessRow.id.desc()).limit(limit)
        )
        return [process_from_row(row) for row in rows]

    @staticmethod
    def save_process(
        session: Session, process: Process, expected_version: int | None = None
    ) -> None:
        row = session.scalar(
            select(ProcessRow).where(ProcessRow.id == process.id).with_for_update()
        )
        if row is None:
            session.add(process_to_row(process))
            return
        if row.owner_id != process.owner_id:
            raise NotFoundError("process not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale process version")
        for field in (
            "domain_id",
            "name",
            "description",
            "status",
            "cadence",
            "next_expected_run_at",
            "updated_at",
            "version",
        ):
            value = getattr(process, field)
            setattr(
                row, field, value.value if isinstance(value, (ProcessStatus, Cadence)) else value
            )

    @staticmethod
    def claim_due_process(session: Session, now: datetime) -> Process | None:
        """Claim one due active Process while keeping the owner transaction locked."""

        row = session.scalar(
            select(ProcessRow)
            .where(
                ProcessRow.status == ProcessStatus.ACTIVE.value,
                ProcessRow.cadence.is_not(None),
                ProcessRow.next_expected_run_at.is_not(None),
                ProcessRow.next_expected_run_at <= now,
                ProcessRow.trashed_at.is_(None),
            )
            .order_by(ProcessRow.next_expected_run_at.asc(), ProcessRow.id.asc())
            .with_for_update(skip_locked=True)
        )
        return process_from_row(row) if row is not None else None

    @staticmethod
    def claim_process_run_outbox(
        session: Session,
        *,
        owner_id: UUID,
        process_id: UUID,
        scheduled_for: datetime,
        worker_id: str,
        now: datetime,
    ) -> ProcessRunOutbox | None:
        """Create or claim the one intent represented by the Process marker."""

        row = session.scalar(
            select(ProcessRunOutboxRow)
            .where(
                ProcessRunOutboxRow.owner_id == owner_id,
                ProcessRunOutboxRow.process_id == process_id,
                ProcessRunOutboxRow.scheduled_for == scheduled_for,
            )
            .with_for_update()
        )
        if row is None:
            row = ProcessRunOutboxRow(
                id=new_uuid7(),
                owner_id=owner_id,
                process_id=process_id,
                scheduled_for=scheduled_for,
                status="queued",
                attempts=0,
                created_at=now,
            )
            session.add(row)
            session.flush()
        if row.status == "delivered":
            return None
        if row.status == "processing":
            return None
        row.status = "processing"
        row.attempts += 1
        row.worker_id = worker_id[:120]
        row.claimed_at = now
        row.last_error = None
        return process_run_outbox_from_row(row)

    @staticmethod
    def complete_process_run_outbox(
        session: Session, *, outbox_id: UUID, worker_id: str, process_run_id: UUID, now: datetime
    ) -> None:
        row = session.scalar(
            select(ProcessRunOutboxRow).where(ProcessRunOutboxRow.id == outbox_id).with_for_update()
        )
        if row is None or row.status != "processing" or row.worker_id != worker_id[:120]:
            raise ValidationError("process run outbox claim is no longer active")
        row.status = "delivered"
        row.process_run_id = process_run_id
        row.processed_at = now
        row.claimed_at = None
        row.worker_id = None

    @staticmethod
    def recover_stalled_process_run_outbox(session: Session, *, now: datetime) -> int:
        cutoff = now - timedelta(minutes=10)
        rows = session.scalars(
            select(ProcessRunOutboxRow)
            .where(
                ProcessRunOutboxRow.status == "processing",
                ProcessRunOutboxRow.claimed_at < cutoff,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            row.status = "queued"
            row.worker_id = None
            row.claimed_at = None
            row.last_error = "stalled_recovered"
        return len(rows)

    @staticmethod
    def enqueue_process_run_outbox(
        session: Session,
        *,
        owner_id: UUID,
        process_id: UUID,
        scheduled_for: datetime,
        now: datetime,
    ) -> None:
        exists = session.scalar(
            select(ProcessRunOutboxRow.id).where(
                ProcessRunOutboxRow.owner_id == owner_id,
                ProcessRunOutboxRow.process_id == process_id,
                ProcessRunOutboxRow.scheduled_for == scheduled_for,
            )
        )
        if exists is None:
            session.add(
                ProcessRunOutboxRow(
                    id=new_uuid7(),
                    owner_id=owner_id,
                    process_id=process_id,
                    scheduled_for=scheduled_for,
                    status="queued",
                    attempts=0,
                    created_at=now,
                )
            )

    @staticmethod
    def get_process_run_template(
        session: Session, owner_id: UUID, process_id: UUID
    ) -> ProcessRunTemplate | None:
        row = session.scalar(
            select(ProcessRunTemplateRow).where(
                ProcessRunTemplateRow.owner_id == owner_id,
                ProcessRunTemplateRow.process_id == process_id,
            )
        )
        return process_run_template_from_row(row) if row is not None else None

    @staticmethod
    def list_process_runs(
        session: Session, owner_id: UUID, process_id: UUID, limit: int
    ) -> list[ProcessRun]:
        rows = session.scalars(
            select(ProcessRunRow)
            .where(
                ProcessRunRow.owner_id == owner_id,
                ProcessRunRow.process_id == process_id,
            )
            .order_by(ProcessRunRow.scheduled_for.desc(), ProcessRunRow.id.desc())
            .limit(limit)
        )
        return [process_run_from_row(row) for row in rows]

    @staticmethod
    def get_process_runs(
        session: Session, owner_id: UUID, run_ids: Sequence[UUID]
    ) -> list[ProcessRun]:
        """The owner's runs with these ids, in the order given; a run that is gone is skipped."""

        rows = session.scalars(
            select(ProcessRunRow).where(
                ProcessRunRow.owner_id == owner_id, ProcessRunRow.id.in_(run_ids)
            )
        )
        by_id = {row.id: process_run_from_row(row) for row in rows}
        return [by_id[run_id] for run_id in run_ids if run_id in by_id]

    @staticmethod
    def add_process_run(session: Session, run: ProcessRun) -> None:
        session.add(
            ProcessRunRow(
                id=run.id,
                owner_id=run.owner_id,
                process_id=run.process_id,
                task_id=run.task_id,
                scheduled_for=run.scheduled_for,
                template_version=run.template_version,
                created_at=run.created_at,
            )
        )

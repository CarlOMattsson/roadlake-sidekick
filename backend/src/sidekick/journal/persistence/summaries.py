"""Daily journal summaries and the per-day done list."""

from datetime import date, datetime, tzinfo
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from sidekick.journal.domain.day_done import DayDone
from sidekick.journal.domain.entry import EntryHead
from sidekick.journal.domain.records import DaySummaryStatus
from sidekick.journal.domain.review import ProcessingStatus
from sidekick.journal.domain.summary import (
    DailySummary,
    SummaryContent,
    SummaryOrigin,
    SummaryState,
    changed_entry_count,
    entry_fingerprint,
)
from sidekick.journal.persistence.day_done import read_day_done
from sidekick.journal.persistence.entries import JournalEntryStore
from sidekick.journal.persistence.mappers import daily_summary_from_row
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
)
from sidekick.shared.persistence.models import (
    DailyJournalSummaryEntryRow,
    DailyJournalSummaryRow,
    JournalProcessingRunRow,
)
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor, new_uuid7, utc_now


class _Unread:
    """Marks a daily summary the caller has not read yet (None means it was read and is absent)."""


_UNREAD = _Unread()


class JournalSummaryStore:
    """Daily journal summaries and the per-day done list.

    The operations are static and owner-filtered; `SqlJournalStore` adds the transaction boundary.
    """

    @staticmethod
    def get_daily_summary(
        session: Session, owner_id: UUID, summary_or_date: UUID | date
    ) -> DailySummary | None:
        statement = select(DailyJournalSummaryRow).where(
            DailyJournalSummaryRow.owner_id == owner_id
        )
        if isinstance(summary_or_date, date):
            statement = statement.where(DailyJournalSummaryRow.journal_date == summary_or_date)
        else:
            statement = statement.where(DailyJournalSummaryRow.id == summary_or_date)
        row = session.scalar(statement)
        return daily_summary_from_row(session, row) if row is not None else None

    @staticmethod
    def read_day_done(session: Session, actor: Actor, journal_date: date, zone: tzinfo) -> DayDone:
        """What the owner completed or bought on one calendar day, for the diary day read."""

        return read_day_done(session, actor, journal_date, zone)

    @staticmethod
    def get_daily_summary_status(
        session: Session,
        owner_id: UUID,
        journal_date: date,
        *,
        summary: DailySummary | None | _Unread = _UNREAD,
        active: list[EntryHead] | None = None,
    ) -> DaySummaryStatus:
        """The summary's state; a caller that already read the summary or the day's active
        entries passes them in so the same rows are not read twice."""

        if isinstance(summary, _Unread):
            summary = JournalSummaryStore.get_daily_summary(session, owner_id, journal_date)
        if summary is None:
            latest_run = session.scalar(
                select(JournalProcessingRunRow)
                .where(
                    JournalProcessingRunRow.owner_id == owner_id,
                    JournalProcessingRunRow.operation == "daily_summary",
                    JournalProcessingRunRow.journal_date == journal_date,
                )
                .order_by(
                    JournalProcessingRunRow.created_at.desc(), JournalProcessingRunRow.id.desc()
                )
            )
            if latest_run is not None and latest_run.status == ProcessingStatus.FAILED.value:
                return DaySummaryStatus(state="failed")
            return DaySummaryStatus()
        if active is None:
            active = JournalEntryStore.list_active_journal_entry_heads(
                session, owner_id, journal_date
            )
        current_versions = {entry.id: entry.version for entry in active}
        provenance = session.scalars(
            select(DailyJournalSummaryEntryRow).where(
                DailyJournalSummaryEntryRow.owner_id == owner_id,
                DailyJournalSummaryEntryRow.summary_id == summary.id,
            )
        )
        stored_versions = {row.entry_id: row.entry_version for row in provenance}
        return DaySummaryStatus(
            state=summary.state.value,
            summary_id=summary.id,
            version=summary.version,
            changed_entry_count=changed_entry_count(stored_versions, current_versions),
        )

    @staticmethod
    def upsert_manual_daily_summary(
        session: Session,
        *,
        owner_id: UUID,
        journal_date: date,
        content: SummaryContent,
        expected_entry_fingerprint: str,
        expected_summary_version: int | None,
        now: datetime,
        correlation_id: str | None = None,
    ) -> DailySummary:
        entries = JournalEntryStore.list_active_journal_entry_heads(session, owner_id, journal_date)
        if not entries:
            raise NotFoundError("journal day not found")
        actual_fingerprint = entry_fingerprint(entries)
        if actual_fingerprint != expected_entry_fingerprint:
            raise ConflictError(
                "journal entries changed since the summary was read", reason="stale_version"
            )
        entry_ids = {entry.id for entry in entries}
        from sidekick.journal.domain.summary import validate_content_references

        validate_content_references(content, entry_ids)
        row = session.scalar(
            select(DailyJournalSummaryRow)
            .where(
                DailyJournalSummaryRow.owner_id == owner_id,
                DailyJournalSummaryRow.journal_date == journal_date,
            )
            .with_for_update()
        )
        if row is None:
            if expected_summary_version is not None:
                raise ConflictError("daily summary version is stale", reason="stale_version")
            row = DailyJournalSummaryRow(
                id=new_uuid7(),
                owner_id=owner_id,
                journal_date=journal_date,
                origin=SummaryOrigin.MANUAL.value,
                status=SummaryState.CURRENT.value,
                overview=content.overview,
                content=content.model_dump(mode="json"),
                source_fingerprint=actual_fingerprint,
                processing_run_id=None,
                accepted_proposal_id=None,
                version=1,
                generated_at=now,
                updated_at=now,
                manual_edited_at=now,
            )
            session.add(row)
            session.flush()
        else:
            if row.version != expected_summary_version:
                raise ConflictError("daily summary version is stale", reason="stale_version")
            row.origin = SummaryOrigin.MANUAL.value
            row.status = SummaryState.CURRENT.value
            row.overview = content.overview
            row.content = content.model_dump(mode="json")
            row.source_fingerprint = actual_fingerprint
            row.processing_run_id = None
            row.accepted_proposal_id = None
            row.version += 1
            row.updated_at = now
            row.manual_edited_at = now
            session.execute(
                text(
                    "DELETE FROM sidekick.daily_journal_summary_entries "
                    "WHERE owner_id = :owner_id AND summary_id = :summary_id"
                ),
                {"owner_id": owner_id, "summary_id": row.id},
            )
        session.add_all(
            [
                DailyJournalSummaryEntryRow(
                    owner_id=owner_id,
                    summary_id=row.id,
                    entry_id=entry.id,
                    entry_version=entry.version,
                    ordinal=ordinal,
                )
                for ordinal, entry in enumerate(entries)
            ]
        )
        session.flush()
        StoreBase.append_audit(
            session,
            actor_id=owner_id,
            event="journal.summary_saved",
            outcome="success",
            target_type="journal_summary",
            target_id=row.id,
            correlation_id=correlation_id,
        )
        return daily_summary_from_row(session, row)

    @staticmethod
    def mark_daily_journal_summary_stale(
        session: Session, owner_id: UUID, journal_date: date
    ) -> None:
        session.execute(
            update(DailyJournalSummaryRow)
            .where(
                DailyJournalSummaryRow.owner_id == owner_id,
                DailyJournalSummaryRow.journal_date == journal_date,
                DailyJournalSummaryRow.status == "current",
            )
            .values(status="stale", updated_at=utc_now())
        )

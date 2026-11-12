"""One Journal day and its summary: reads and the manual summary write."""

from datetime import date, tzinfo
from uuid import UUID

from sidekick.journal.application.models import JournalDay
from sidekick.journal.application.paging import (
    decode_cursor,
    entry_cursor,
    journal_day_cursor_key,
)
from sidekick.journal.application.store import JournalStore
from sidekick.journal.domain.day_done import DayDone
from sidekick.journal.domain.entry import EntryHead, JournalEntry
from sidekick.journal.domain.records import DaySummaryStatus
from sidekick.journal.domain.summary import DailySummary, SummaryContent, entry_fingerprint
from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE, parse_owner_timezone
from sidekick.shared.errors import NotFoundError, ValidationError
from sidekick.shared.types import Actor, Clock, CursorCodec, TxSession

DEFAULT_OWNER_ZONE = parse_owner_timezone(DEFAULT_OWNER_TIMEZONE)


class JournalDayService:
    def __init__(
        self,
        store: JournalStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        owner_timezone: tzinfo = DEFAULT_OWNER_ZONE,
    ) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec
        self.owner_timezone = owner_timezone

    def put_manual_summary(
        self,
        actor: Actor,
        *,
        journal_date: date,
        expected_entry_fingerprint: str,
        expected_summary_version: int | None,
        content: SummaryContent,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> DailySummary:
        actor.require("journal:write")
        payload = {
            "journal_date": journal_date.isoformat(),
            "expected_entry_fingerprint": expected_entry_fingerprint,
            "expected_summary_version": expected_summary_version,
            "content": content.model_dump(mode="json"),
        }

        def operation(session: TxSession) -> DailySummary:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="put_manual_daily_summary",
                key=idempotency_key,
                payload=payload,
                execute=lambda: {
                    "summary_id": str(
                        self.store.upsert_manual_daily_summary(
                            session,
                            owner_id=actor.user_id,
                            journal_date=journal_date,
                            content=content,
                            expected_entry_fingerprint=expected_entry_fingerprint,
                            expected_summary_version=expected_summary_version,
                            now=self.clock.now(),
                            correlation_id=correlation_id,
                        ).id
                    )
                },
            )
            summary = self.store.get_daily_summary(
                session,
                actor.user_id,
                UUID(result["summary_id"]) if "summary_id" in result else journal_date,
            )
            if summary is None:
                raise NotFoundError("daily summary not found")
            return summary

        return self.store.transaction(operation)

    def get_summary(
        self, actor: Actor, journal_date: date
    ) -> tuple[DaySummaryStatus, DailySummary | None]:
        actor.require("journal:read")
        status_reader = getattr(self.store, "get_daily_summary_status", None)
        summary_reader = getattr(self.store, "get_daily_summary", None)
        if status_reader is None or summary_reader is None:
            return DaySummaryStatus(), None
        return self.store.transaction(
            lambda session: (
                status_reader(session, actor.user_id, journal_date),
                summary_reader(session, actor.user_id, journal_date),
            )
        )

    def get_day(
        self,
        actor: Actor,
        *,
        journal_date: date,
        include_archived: bool = False,
        limit: int = 100,
        cursor: str | None = None,
        include_done: bool = True,
    ) -> JournalDay:
        """One diary day. `include_done` false skips the done read for callers that ignore it."""

        actor.require("journal:read")
        if not 1 <= limit <= 100:
            raise ValidationError("limit must be between 1 and 100")
        query_key = journal_day_cursor_key(journal_date, include_archived)
        after = decode_cursor(self.cursor_codec, actor.user_id, cursor, query_key)

        def read(
            session: TxSession,
        ) -> tuple[
            list[JournalEntry],
            DaySummaryStatus,
            DailySummary | None,
            list[EntryHead],
            DayDone,
        ]:
            entries = self.store.list_journal_entries(
                session,
                actor.user_id,
                start_date=journal_date,
                end_date=journal_date,
                include_archived=include_archived,
                limit=limit + 1,
                after=after,
            )
            # A day without entries is still a day: what was done on it is shown all the same,
            # and the answer is the same whether the date is empty or belongs to nobody.
            # Over all active entries of the day, not the page: put_manual_summary validates this
            # value against the same full set, so a paged fingerprint would be wrong for days over
            # one page.
            active = self.store.list_active_journal_entry_heads(
                session, actor.user_id, journal_date
            )
            status_reader = getattr(self.store, "get_daily_summary_status", None)
            summary_reader = getattr(self.store, "get_daily_summary", None)
            summary = (
                summary_reader(session, actor.user_id, journal_date)
                if summary_reader is not None
                else None
            )
            summary_status = (
                status_reader(session, actor.user_id, journal_date, summary=summary, active=active)
                if status_reader is not None
                else DaySummaryStatus()
            )
            done = (
                self.store.read_day_done(session, actor, journal_date, self.owner_timezone)
                if include_done
                else DayDone()
            )
            return entries, summary_status, summary, active, done

        entries, summary_status, summary, active, done = self.store.transaction(read)
        return JournalDay(
            journal_date=journal_date,
            entries=tuple(entries[:limit]),
            next_cursor=entry_cursor(self.cursor_codec, actor, entries[limit - 1], query_key)
            if len(entries) > limit
            else None,
            summary_status=summary_status,
            entry_fingerprint=entry_fingerprint(active),
            summary=summary,
            done=done,
        )

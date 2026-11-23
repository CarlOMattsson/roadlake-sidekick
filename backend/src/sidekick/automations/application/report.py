"""The automation report: reading what the automations did, and marking it as seen.

Reading needs `automation:read`, marking needs `automation:write`; both are owner-filtered in the
store. The report holds counts, ids and closed codes, plus the title of an automation and the
summary a failed run wrote about itself; nothing a run read or proposed. Marking it as seen moves
one cursor, and the Start view reads that cursor to show what happened since.
"""

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any, Protocol
from uuid import UUID

from sidekick.automations.domain.automation import ReportCursor
from sidekick.automations.domain.report import (
    DEFAULT_HIGHLIGHTS,
    MAX_REPORT_AUTOMATIONS,
    AutomationReport,
    Highlight,
    ReportRow,
    next_cursor,
    ranked,
    resolve_window,
    select_highlights,
    totals_of,
)
from sidekick.automations.report_html import render_report_html
from sidekick.shared.errors import ConflictError
from sidekick.shared.locale import AppLocale
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    Clock,
    IdempotentStore,
    TransactionalStore,
    TxSession,
)

READ_SCOPE = "automation:read"
WRITE_SCOPE = "automation:write"


class AutomationReportStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def get_report_cursor(self, session: TxSession, owner_id: UUID) -> ReportCursor | None: ...
    def save_report_cursor(
        self, session: TxSession, cursor: ReportCursor, expected_version: int | None = None
    ) -> None: ...
    def report_rows(
        self, session: TxSession, owner_id: UUID, since: datetime, until: datetime
    ) -> list[ReportRow]: ...
    def report_highlights(
        self, session: TxSession, owner_id: UUID, since: datetime, until: datetime, limit: int
    ) -> list[Highlight]: ...


@dataclass(frozen=True, slots=True)
class ReportPage:
    report: AutomationReport
    html: str


class AutomationReportService:
    def __init__(self, store: AutomationReportStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    def report(
        self,
        actor: Actor,
        *,
        since: datetime | None = None,
        limit: int = DEFAULT_HIGHLIGHTS,
    ) -> AutomationReport:
        """What the automations did since `since`, or since the owner last marked it as seen.

        The window ends now; the owner passes that end to `mark_seen`.
        """

        actor.require(READ_SCOPE)

        def read(session: TxSession) -> AutomationReport:
            cursor = self.store.get_report_cursor(session, actor.user_id)
            window = resolve_window(since=since, cursor=cursor, now=self.clock.now())
            rows = ranked(
                self.store.report_rows(session, actor.user_id, window.since, window.until)
            )
            highlights = select_highlights(
                self.store.report_highlights(
                    session, actor.user_id, window.since, window.until, limit
                ),
                limit,
            )
            return AutomationReport(
                window=window,
                rows=rows[:MAX_REPORT_AUTOMATIONS],
                omitted_automations=max(0, len(rows) - MAX_REPORT_AUTOMATIONS),
                totals=totals_of(rows),
                highlights=highlights,
                version=cursor.version if cursor else 0,
            )

        return self.store.transaction(read)

    def export_html(
        self,
        actor: Actor,
        *,
        since: datetime | None,
        locale: AppLocale,
        zone: tzinfo,
        limit: int = DEFAULT_HIGHLIGHTS,
    ) -> ReportPage:
        """The report, and the same report as one self-contained page with its text escaped."""

        report = self.report(actor, since=since, limit=limit)
        return ReportPage(report, render_report_html(report, locale, zone))

    def mark_seen(
        self,
        actor: Actor,
        *,
        seen_until: datetime,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> ReportCursor:
        """The owner has seen the report up to `seen_until`, at `expected_version` of the cursor.

        Version 0 is "never marked". A cursor that moved since is refused, so two screens cannot
        silently overwrite each other. A retry with the same key returns the cursor as it is now.
        """

        actor.require(WRITE_SCOPE)

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.get_report_cursor(session, actor.user_id)
            if (current.version if current else 0) != expected_version:
                raise ConflictError("stale report version", reason="stale_version")
            now = self.clock.now()
            moved = next_cursor(current, owner_id=actor.user_id, seen_until=seen_until, now=now)
            self.store.save_report_cursor(session, moved, current.version if current else None)
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="automation.report_seen",
                outcome="success",
                target_type="automation_report",
                correlation_id=correlation_id,
            )
            return {"seen_until": moved.seen_until.isoformat()}

        def run(session: TxSession) -> ReportCursor:
            self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="mark_automation_report_seen",
                key=idempotency_key,
                payload={
                    "seen_until": seen_until.isoformat(),
                    "expected_version": expected_version,
                },
                execute=lambda: operation(session),
                replay=lambda result: result,
            )
            cursor = self.store.get_report_cursor(session, actor.user_id)
            if cursor is None:
                raise ConflictError("report cursor missing", reason="stale_version")
            return cursor

        return self.store.transaction(run)

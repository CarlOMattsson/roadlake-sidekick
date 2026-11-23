"""What the automation report reads: counts per automation and the few cards worth a look.

Owner-filtered like the automation store it extends, and nothing here logs. The counts cover the
window `(since, until]`; only what waits for a decision is counted as it is now. Only the closed
columns of a run and a suggestion are read, and of the text a run wrote only its summary.
"""

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker

from sidekick.automations.domain.report import Highlight, HighlightKind, ReportRow
from sidekick.automations.domain.runs import RunState
from sidekick.automations.domain.spec import AutomationState, ModelTier
from sidekick.automations.domain.suggestion import DecidedBy, SuggestionState, Verdict
from sidekick.automations.persistence import AutomationStore
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.persistence.models import (
    AutomationRow,
    AutomationRunRow,
    AutomationSuggestionRow,
)
from sidekick.shared.persistence.stores.base import StoreBase

_Suggestion = AutomationSuggestionRow
_Run = AutomationRunRow


def _windowed(
    column: InstrumentedAttribute[datetime] | InstrumentedAttribute[datetime | None],
    since: datetime,
    until: datetime,
) -> ColumnElement[bool]:
    return and_(column > since, column <= until)


class ReportStore(AutomationStore):
    """The automation operations plus the reads of the report."""

    @staticmethod
    def report_rows(
        session: Session, owner_id: UUID, since: datetime, until: datetime
    ) -> list[ReportRow]:
        """One row for each automation that ran, was suggested from or still waits, unsorted."""

        counts: dict[UUID, dict[str, int]] = defaultdict(dict)
        run_rows = session.execute(
            select(
                _Run.automation_id,
                func.count(),
                func.count().filter(_Run.state == RunState.DONE.value),
                func.count().filter(_Run.state == RunState.FAILED.value),
                func.coalesce(func.sum(_Run.cost_microusd), 0),
            )
            .where(_Run.owner_id == owner_id, _Run.created_at > since, _Run.created_at <= until)
            .group_by(_Run.automation_id)
        )
        for automation_id, runs, ok_runs, failed_runs, cost in run_rows:
            counts[automation_id].update(
                runs=runs, ok_runs=ok_runs, failed_runs=failed_runs, cost_microusd=int(cost)
            )

        created = _windowed(_Suggestion.created_at, since, until)
        decided = _windowed(_Suggestion.decided_at, since, until)
        pending = _Suggestion.state == SuggestionState.PENDING.value
        flagged = or_(
            func.cardinality(_Suggestion.screening_flags) > 0,
            _Suggestion.verdict == Verdict.SUSPICIOUS.value,
        )
        suggestion_rows = session.execute(
            select(
                _Suggestion.automation_id,
                func.count().filter(created),
                func.count().filter(decided, _Suggestion.state == SuggestionState.APPLIED.value),
                func.count().filter(decided, _Suggestion.state == SuggestionState.DISMISSED.value),
                func.count().filter(created, flagged),
                func.count().filter(decided, _Suggestion.decided_by == DecidedBy.POLICY.value),
                func.count().filter(pending),
            )
            .where(_Suggestion.owner_id == owner_id, or_(created, decided, pending))
            .group_by(_Suggestion.automation_id)
        )
        for automation_id, made, applied, dismissed, flags, automatic, waiting in suggestion_rows:
            counts[automation_id].update(
                suggestions_created=made,
                applied=applied,
                dismissed=dismissed,
                flagged=flags,
                auto_applied=automatic,
                pending=waiting,
            )
        if not counts:
            return []

        automations = session.execute(
            select(
                AutomationRow.id, AutomationRow.title, AutomationRow.state, AutomationRow.model_tier
            ).where(AutomationRow.owner_id == owner_id, AutomationRow.id.in_(counts))
        )
        return [
            ReportRow(
                automation_id=automation_id,
                title=title,
                state=AutomationState(state),
                model_tier=ModelTier(tier),
                runs=found.get("runs", 0),
                ok_runs=found.get("ok_runs", 0),
                failed_runs=found.get("failed_runs", 0),
                suggestions_created=found.get("suggestions_created", 0),
                applied=found.get("applied", 0),
                dismissed=found.get("dismissed", 0),
                flagged=found.get("flagged", 0),
                auto_applied=found.get("auto_applied", 0),
                pending=found.get("pending", 0),
                cost_microusd=found.get("cost_microusd", 0),
            )
            for automation_id, title, state, tier in automations
            for found in (counts[automation_id],)
        ]

    @staticmethod
    def report_highlights(
        session: Session, owner_id: UUID, since: datetime, until: datetime, limit: int
    ) -> list[Highlight]:
        """Up to `limit` of each kind of card worth a look, newest first; the caller ranks them."""

        failed_at = func.coalesce(_Run.finished_at, _Run.created_at)
        failed = session.execute(
            select(
                _Run.id,
                _Run.automation_id,
                AutomationRow.title,
                failed_at,
                _Run.outcome,
                _Run.summary,
            )
            .join(
                AutomationRow,
                and_(
                    AutomationRow.id == _Run.automation_id, AutomationRow.owner_id == _Run.owner_id
                ),
            )
            .where(
                _Run.owner_id == owner_id,
                _Run.state == RunState.FAILED.value,
                _Run.created_at > since,
                _Run.created_at <= until,
            )
            .order_by(failed_at.desc(), _Run.id)
            .limit(limit)
        )
        found = [
            Highlight(
                kind=HighlightKind.RUN_FAILED,
                automation_id=automation_id,
                automation_title=title,
                at=at,
                run_id=run_id,
                outcome=outcome,
                summary=summary,
            )
            for run_id, automation_id, title, at, outcome, summary in failed
        ]

        flagged = or_(
            func.cardinality(_Suggestion.screening_flags) > 0,
            _Suggestion.verdict == Verdict.SUSPICIOUS.value,
        )
        found += _suggestion_cards(
            session,
            owner_id,
            HighlightKind.SUGGESTION_FLAGGED,
            _Suggestion.created_at,
            and_(_windowed(_Suggestion.created_at, since, until), flagged),
            limit,
        )
        found += _suggestion_cards(
            session,
            owner_id,
            HighlightKind.SUGGESTION_AUTO_APPLIED,
            _Suggestion.decided_at,
            and_(
                _windowed(_Suggestion.decided_at, since, until),
                _Suggestion.decided_by == DecidedBy.POLICY.value,
            ),
            limit,
        )
        return found


def _suggestion_cards(
    session: Session,
    owner_id: UUID,
    kind: HighlightKind,
    at_column: InstrumentedAttribute[datetime] | InstrumentedAttribute[datetime | None],
    condition: ColumnElement[bool],
    limit: int,
) -> list[Highlight]:
    rows = session.execute(
        select(
            _Suggestion.id,
            _Suggestion.run_id,
            _Suggestion.automation_id,
            AutomationRow.title,
            at_column,
            _Suggestion.effect,
            _Suggestion.screening_flags,
            _Suggestion.verdict,
        )
        .join(
            AutomationRow,
            and_(
                AutomationRow.id == _Suggestion.automation_id,
                AutomationRow.owner_id == _Suggestion.owner_id,
            ),
        )
        .where(_Suggestion.owner_id == owner_id, condition)
        .order_by(at_column.desc(), _Suggestion.id)
        .limit(limit)
    )
    return [
        Highlight(
            kind=kind,
            automation_id=automation_id,
            automation_title=title,
            at=at,
            run_id=run_id,
            suggestion_id=suggestion_id,
            effect=effect,
            flags=tuple(flags or ()),
            verdict=verdict,
        )
        for suggestion_id, run_id, automation_id, title, at, effect, flags, verdict in rows
        if at is not None
    ]


class SqlReportStore(ReportStore, StoreBase):
    """The report operations with the transaction, idempotency and audit of `StoreBase`."""

    def __init__(
        self, session_factory: sessionmaker[Session], telemetry: TelemetryPort | None = None
    ) -> None:
        super().__init__(session_factory, telemetry)

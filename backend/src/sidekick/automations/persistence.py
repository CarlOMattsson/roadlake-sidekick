"""The automation registry, its runs, datapoints, suggestions and checks, read and written
owner-filtered.

Every statement names the owner, and a row of another owner answers as not found, so no id
reveals whether a row exists. A check is appended and never changed: the application role has no
UPDATE on `automation_checks`, and this store has no operation that would try. Text columns are
the owner's data or text an AI wrote; nothing here logs them.
"""

from collections.abc import Collection, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.automations.domain.activity import PendingSuggestions, RunFacts, WindowCounts
from sidekick.automations.domain.automation import Automation, ReportCursor, SuggestionCheck
from sidekick.automations.domain.datapoints import Datapoint, DatapointKind, SourceKind
from sidekick.automations.domain.effects import EffectKind
from sidekick.automations.domain.runs import (
    AutomationRun,
    CredentialKind,
    RunOutcome,
    RunRunner,
    RunState,
    scheduled_day,
)
from sidekick.automations.domain.screening import ScreeningFlag
from sidekick.automations.domain.spec import (
    AutomationSpecV1,
    AutomationState,
    parse_spec,
)
from sidekick.automations.domain.suggestion import (
    ApplyError,
    CheckState,
    DecidedBy,
    DecisionChannel,
    Suggestion,
    SuggestionState,
    Verdict,
)
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.persistence.models import (
    AutomationCheckRow,
    AutomationDatapointRow,
    AutomationReportCursorRow,
    AutomationRow,
    AutomationRunRow,
    AutomationSuggestionRow,
    Base,
    ContactAliasRow,
    ContactRow,
    JournalEntryContactRow,
    ProjectContactRow,
    ProjectRow,
    StepRow,
    TaskContactRow,
    TaskRow,
)
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import validate_limit
from sidekick.tasks.domain import TaskStatus
from sidekick.work.domain.ai_runs import AiUsage, CostSource
from sidekick.work.persistence.ai_runs import AiRunStore, automation_run_cost_query

MAX_LIST_ROWS = 200
"""The most rows one list read returns."""


def spec_columns(spec: AutomationSpecV1) -> dict[str, object]:
    """The registry columns a spec fills. No cadence is stored as an empty object."""

    values = spec.model_dump(mode="json", exclude={"spec_version"})
    values["cadence"] = values["cadence"] or {}
    return values


def spec_from_columns(row: AutomationRow) -> AutomationSpecV1:
    return parse_spec(
        {
            "purpose": row.purpose,
            "instruction": row.instruction,
            "sources": row.sources,
            "runner": row.runner,
            "cadence": row.cadence or None,
            "allowed_effects": row.allowed_effects,
            "apply_mode": row.apply_mode,
            "auto_effects": row.auto_effects,
            "bulk_threshold": row.bulk_threshold,
            "auto_threshold": row.auto_threshold,
            "max_suggestions_per_run": row.max_suggestions_per_run,
            "run_budget_microusd": row.run_budget_microusd,
            "model_tier": row.model_tier,
        }
    )


def automation_from_row(row: AutomationRow) -> Automation:
    return Automation(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        spec=spec_from_columns(row),
        state=AutomationState(row.state),
        spec_digest=row.spec_digest,
        approved_digest=row.approved_digest,
        approved_at=row.approved_at,
        last_run_at=row.last_run_at,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply_automation(row: AutomationRow, automation: Automation) -> None:
    for column, value in spec_columns(automation.spec).items():
        setattr(row, column, value)
    row.title = automation.title
    row.state = automation.state.value
    row.spec_digest = automation.spec_digest
    row.approved_digest = automation.approved_digest
    row.approved_at = automation.approved_at
    row.last_run_at = automation.last_run_at
    row.updated_at = automation.updated_at
    row.version = automation.version


def suggestion_from_row(row: AutomationSuggestionRow) -> Suggestion:
    """A purged payload (kept as NULL with `payload_purged_at`) reads as an empty one."""

    return Suggestion(
        id=row.id,
        owner_id=row.owner_id,
        automation_id=row.automation_id,
        run_id=row.run_id,
        effect=EffectKind(row.effect),
        effect_version=row.effect_version,
        payload=row.payload or {},
        proposed_payload=row.proposed_payload or {},
        rationale=row.rationale or "",
        datapoint_ids=tuple(row.datapoint_ids),
        dedupe_fingerprint=row.dedupe_fingerprint,
        state=SuggestionState(row.state),
        expires_at=row.expires_at,
        screening_flags=tuple(ScreeningFlag(flag) for flag in row.screening_flags),
        check_state=CheckState(row.check_state),
        verdict=Verdict(row.verdict) if row.verdict else None,
        confidence=row.confidence,
        bulk_eligible=row.bulk_eligible,
        decided_at=row.decided_at,
        decided_by=DecidedBy(row.decided_by) if row.decided_by else None,
        decision_channel=DecisionChannel(row.decision_channel) if row.decision_channel else None,
        applied_kind=row.applied_kind,
        applied_id=row.applied_id,
        applied_version=row.applied_version,
        undone_at=row.undone_at,
        apply_error=ApplyError(row.apply_error) if row.apply_error else None,
        version=row.version,
    )


def _apply_suggestion(row: AutomationSuggestionRow, suggestion: Suggestion, now: datetime) -> None:
    """Copies every changeable field. A purged payload is never written back."""

    if row.payload_purged_at is None:
        row.payload = dict(suggestion.payload)
        row.proposed_payload = dict(suggestion.proposed_payload)
    row.rationale = suggestion.rationale or None
    row.datapoint_ids = list(suggestion.datapoint_ids)
    row.state = suggestion.state.value
    row.screening_flags = [flag.value for flag in suggestion.screening_flags]
    row.check_state = suggestion.check_state.value
    row.verdict = suggestion.verdict.value if suggestion.verdict else None
    row.confidence = suggestion.confidence
    row.bulk_eligible = suggestion.bulk_eligible
    row.decided_at = suggestion.decided_at
    row.decided_by = suggestion.decided_by.value if suggestion.decided_by else None
    row.decision_channel = (
        suggestion.decision_channel.value if suggestion.decision_channel else None
    )
    row.applied_kind = suggestion.applied_kind
    row.applied_id = suggestion.applied_id
    row.applied_version = suggestion.applied_version
    row.undone_at = suggestion.undone_at
    row.apply_error = suggestion.apply_error.value if suggestion.apply_error else None
    row.expires_at = suggestion.expires_at
    row.updated_at = now
    row.version = suggestion.version


def check_from_row(row: AutomationCheckRow) -> SuggestionCheck:
    return SuggestionCheck(
        id=row.id,
        owner_id=row.owner_id,
        suggestion_id=row.suggestion_id,
        run_id=row.run_id,
        attempt=row.attempt,
        checker=row.checker,
        model=row.model,
        verdict=row.verdict,
        confidence=row.confidence,
        reason_codes=tuple(row.reason_codes),
        checked_at=row.checked_at,
    )


def run_from_row(row: AutomationRunRow) -> AutomationRun:
    return AutomationRun(
        id=row.id,
        owner_id=row.owner_id,
        automation_id=row.automation_id,
        occurrence_key=row.occurrence_key,
        attempt=row.attempt,
        runner=RunRunner(row.runner),
        state=RunState(row.state),
        spec_digest=row.spec_digest,
        credential_kind=CredentialKind(row.credential_kind),
        created_at=row.created_at,
        updated_at=row.updated_at,
        stage=row.stage,
        session_digest=row.session_digest,
        worker_id=row.worker_id,
        lease_until=row.lease_until,
        queued_at=row.queued_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        datapoint_count=row.datapoint_count,
        suggestion_count=row.suggestion_count,
        rejected_count=row.rejected_count,
        flagged_count=row.flagged_count,
        auto_applied_count=row.auto_applied_count,
        summary=row.summary,
        outcome=RunOutcome(row.outcome) if row.outcome else None,
        checker_model=row.checker_model,
        usage=AiUsage(
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cache_read_tokens=row.cache_read_tokens,
            cache_write_tokens=row.cache_write_tokens,
            reserved_microusd=row.reserved_microusd,
            cost_microusd=row.cost_microusd,
            cost_source=CostSource(row.cost_source),
            model=row.model,
        ),
        version=row.version,
    )


def _apply_run(row: AutomationRunRow, run: AutomationRun) -> None:
    row.state = run.state.value
    row.stage = run.stage
    row.worker_id = run.worker_id
    row.lease_until = run.lease_until
    row.queued_at = run.queued_at
    row.started_at = run.started_at
    row.finished_at = run.finished_at
    row.datapoint_count = run.datapoint_count
    row.suggestion_count = run.suggestion_count
    row.rejected_count = run.rejected_count
    row.flagged_count = run.flagged_count
    row.auto_applied_count = run.auto_applied_count
    row.summary = run.summary
    row.outcome = run.outcome.value if run.outcome else None
    row.model = run.usage.model
    row.checker_model = run.checker_model
    row.input_tokens = run.usage.input_tokens
    row.output_tokens = run.usage.output_tokens
    row.cache_read_tokens = run.usage.cache_read_tokens
    row.cache_write_tokens = run.usage.cache_write_tokens
    row.reserved_microusd = run.usage.reserved_microusd
    row.cost_microusd = run.usage.cost_microusd
    row.cost_source = run.usage.cost_source.value
    row.updated_at = run.updated_at
    row.version = run.version


def datapoint_from_row(row: AutomationDatapointRow) -> Datapoint:
    return Datapoint(
        id=row.id,
        owner_id=row.owner_id,
        run_id=row.run_id,
        automation_id=row.automation_id,
        kind=DatapointKind(row.kind),
        fields=row.fields,
        source_kind=SourceKind(row.source_kind),
        source_fingerprint=row.source_fingerprint,
        source_label=row.source_label,
        source_received_at=row.source_received_at,
        created_at=row.created_at,
        purge_after=row.purge_after,
        purged_at=row.purged_at,
    )


def _insert(session: Session, row: Base, primary_key: str, not_found: str) -> None:
    """Add the row. An id that another owner already holds answers as not found.

    The lookup before it names the owner, so no foreign row is locked or read; only the
    primary key can reveal a clash, and it is reported exactly as a missing row is. Any other
    constraint failure (a run or automation of another owner, say) stays an `IntegrityError`.
    """

    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as error:
        diag = getattr(error.orig, "diag", None)
        if getattr(diag, "constraint_name", None) == primary_key:
            raise NotFoundError(not_found) from None
        raise


def unattended_conditions(now: datetime, idle_since: datetime | None) -> list[ColumnElement[bool]]:
    """Runs that wait for their check and that no worker holds: none ever took them, or the lease
    of the one that did has run out. `idle_since` keeps only runs not touched since then."""

    conditions = [
        AutomationRunRow.state == RunState.CHECKING.value,
        or_(AutomationRunRow.lease_until.is_(None), AutomationRunRow.lease_until <= now),
    ]
    if idle_since is not None:
        conditions.append(AutomationRunRow.updated_at <= idle_since)
    return conditions


class AutomationStore:
    """Automations, suggestions and their checks.

    The operations are static and owner-filtered; a store that adds the transaction boundary
    (`StoreBase`) is built on them.
    """

    @staticmethod
    def get_automation(
        session: Session, owner_id: UUID, automation_id: UUID, *, lock: bool = False
    ) -> Automation:
        statement = select(AutomationRow).where(
            AutomationRow.id == automation_id, AutomationRow.owner_id == owner_id
        )
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise NotFoundError("automation not found")
        return automation_from_row(row)

    @staticmethod
    def list_automations(
        session: Session,
        owner_id: UUID,
        *,
        states: Collection[AutomationState] | None = None,
        limit: int = MAX_LIST_ROWS,
        offset: int = 0,
    ) -> list[Automation]:
        statement = select(AutomationRow).where(AutomationRow.owner_id == owner_id)
        if states is not None:
            statement = statement.where(AutomationRow.state.in_([item.value for item in states]))
        rows = session.scalars(
            statement.order_by(AutomationRow.created_at, AutomationRow.id)
            .offset(offset)
            .limit(validate_limit(limit, maximum=MAX_LIST_ROWS))
        )
        return [automation_from_row(row) for row in rows]

    @staticmethod
    def pending_suggestion_counts(
        session: Session, owner_id: UUID, automation_ids: Collection[UUID]
    ) -> dict[UUID, int]:
        """How many suggestions of each automation wait for a decision; none counts as absent."""

        rows = session.execute(
            select(AutomationSuggestionRow.automation_id, func.count())
            .where(
                AutomationSuggestionRow.owner_id == owner_id,
                AutomationSuggestionRow.automation_id.in_(automation_ids),
                AutomationSuggestionRow.state == SuggestionState.PENDING.value,
            )
            .group_by(AutomationSuggestionRow.automation_id)
        )
        return {automation_id: count for automation_id, count in rows}

    @staticmethod
    def pending_suggestion_overview(session: Session, owner_id: UUID) -> PendingSuggestions:
        """Every suggestion that waits for a decision, and how many automations they come from."""

        total, automations = session.execute(
            select(
                func.count(), func.count(AutomationSuggestionRow.automation_id.distinct())
            ).where(
                AutomationSuggestionRow.owner_id == owner_id,
                AutomationSuggestionRow.state == SuggestionState.PENDING.value,
            )
        ).one()
        return PendingSuggestions(total=total, automations=automations)

    @staticmethod
    def recent_run_facts(session: Session, owner_id: UUID, day_start: datetime) -> RunFacts:
        """Failed runs since `day_start`, the newest failing automation and the latest summary."""

        failed_today = (
            session.scalar(
                select(func.count())
                .select_from(AutomationRunRow)
                .join(AutomationRow, AutomationRow.id == AutomationRunRow.automation_id)
                .where(
                    AutomationRunRow.owner_id == owner_id,
                    AutomationRow.owner_id == owner_id,
                    AutomationRow.state != AutomationState.ARCHIVED.value,
                    AutomationRunRow.state == RunState.FAILED.value,
                    func.coalesce(AutomationRunRow.finished_at, AutomationRunRow.updated_at)
                    >= day_start,
                )
            )
            or 0
        )
        finished = (RunState.DONE.value, RunState.FAILED.value)
        latest = (
            select(
                AutomationRunRow.automation_id,
                AutomationRunRow.state,
                AutomationRunRow.finished_at,
            )
            .where(AutomationRunRow.owner_id == owner_id, AutomationRunRow.state.in_(finished))
            .distinct(AutomationRunRow.automation_id)
            .order_by(
                AutomationRunRow.automation_id,
                AutomationRunRow.created_at.desc(),
                AutomationRunRow.attempt.desc(),
            )
            .subquery()
        )
        failed_automation = session.scalar(
            select(AutomationRow.title)
            .join(latest, latest.c.automation_id == AutomationRow.id)
            .where(
                AutomationRow.owner_id == owner_id,
                AutomationRow.state != AutomationState.ARCHIVED.value,
                latest.c.state == RunState.FAILED.value,
            )
            .order_by(latest.c.finished_at.desc().nulls_last(), AutomationRow.id)
            .limit(1)
        )
        latest_summary = session.scalar(
            select(AutomationRunRow.summary)
            .where(
                AutomationRunRow.owner_id == owner_id,
                AutomationRunRow.state == RunState.DONE.value,
                AutomationRunRow.summary.is_not(None),
            )
            .order_by(AutomationRunRow.finished_at.desc().nulls_last(), AutomationRunRow.id.desc())
            .limit(1)
        )
        return RunFacts(
            failed_today=failed_today,
            failed_automation=failed_automation,
            latest_summary=latest_summary,
        )

    @staticmethod
    def window_counts(
        session: Session, owner_id: UUID, since: datetime, until: datetime
    ) -> WindowCounts:
        """Runs and suggestions that appeared, and suggestions decided, in `(since, until]`."""

        in_window = (AutomationRunRow.created_at > since, AutomationRunRow.created_at <= until)
        runs, failed = session.execute(
            select(
                func.count(),
                func.count().filter(AutomationRunRow.state == RunState.FAILED.value),
            ).where(AutomationRunRow.owner_id == owner_id, *in_window)
        ).one()
        created, decided = session.execute(
            select(
                func.count().filter(
                    AutomationSuggestionRow.created_at > since,
                    AutomationSuggestionRow.created_at <= until,
                ),
                func.count().filter(
                    AutomationSuggestionRow.decided_at > since,
                    AutomationSuggestionRow.decided_at <= until,
                ),
            ).where(AutomationSuggestionRow.owner_id == owner_id)
        ).one()
        return WindowCounts(
            since=since,
            until=until,
            runs=runs,
            failed_runs=failed,
            suggestions_created=created,
            suggestions_decided=decided,
        )

    @staticmethod
    def save_automation(
        session: Session, automation: Automation, expected_version: int | None = None
    ) -> None:
        """Insert the automation, or update it when the stored version is `expected_version`."""

        row = session.scalar(
            select(AutomationRow)
            .where(AutomationRow.id == automation.id, AutomationRow.owner_id == automation.owner_id)
            .with_for_update()
        )
        if row is None:
            row = AutomationRow(
                id=automation.id,
                owner_id=automation.owner_id,
                created_at=automation.created_at,
            )
            _apply_automation(row, automation)
            _insert(session, row, "automations_pkey", "automation not found")
            return
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale automation version", reason="stale_version")
        _apply_automation(row, automation)

    @staticmethod
    def get_suggestion(
        session: Session, owner_id: UUID, suggestion_id: UUID, *, lock: bool = False
    ) -> Suggestion:
        statement = select(AutomationSuggestionRow).where(
            AutomationSuggestionRow.id == suggestion_id,
            AutomationSuggestionRow.owner_id == owner_id,
        )
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise NotFoundError("suggestion not found")
        return suggestion_from_row(row)

    @staticmethod
    def list_suggestions(
        session: Session,
        owner_id: UUID,
        *,
        states: Collection[SuggestionState] | None = None,
        automation_id: UUID | None = None,
        run_id: UUID | None = None,
        bulk_eligible: bool | None = None,
        expires_after: datetime | None = None,
        limit: int = MAX_LIST_ROWS,
        offset: int = 0,
    ) -> list[Suggestion]:
        statement = select(AutomationSuggestionRow).where(
            AutomationSuggestionRow.owner_id == owner_id
        )
        if bulk_eligible is not None:
            statement = statement.where(AutomationSuggestionRow.bulk_eligible == bulk_eligible)
        if expires_after is not None:
            statement = statement.where(AutomationSuggestionRow.expires_at > expires_after)
        if states is not None:
            statement = statement.where(
                AutomationSuggestionRow.state.in_([item.value for item in states])
            )
        if automation_id is not None:
            statement = statement.where(AutomationSuggestionRow.automation_id == automation_id)
        if run_id is not None:
            statement = statement.where(AutomationSuggestionRow.run_id == run_id)
        rows = session.scalars(
            statement.order_by(AutomationSuggestionRow.created_at, AutomationSuggestionRow.id)
            .offset(offset)
            .limit(validate_limit(limit, maximum=MAX_LIST_ROWS))
        )
        return [suggestion_from_row(row) for row in rows]

    @staticmethod
    def known_fingerprints(session: Session, owner_id: UUID, automation_id: UUID) -> frozenset[str]:
        """Every dedupe fingerprint the automation has ever had, in any state."""

        return frozenset(
            session.scalars(
                select(AutomationSuggestionRow.dedupe_fingerprint).where(
                    AutomationSuggestionRow.owner_id == owner_id,
                    AutomationSuggestionRow.automation_id == automation_id,
                )
            )
        )

    @staticmethod
    def save_suggestion(
        session: Session,
        suggestion: Suggestion,
        now: datetime,
        expected_version: int | None = None,
    ) -> None:
        """Insert the suggestion, or update it when the stored version is `expected_version`.

        The run and the automation it names must be the owner's: the composite foreign key
        refuses any other pair.
        """

        row = session.scalar(
            select(AutomationSuggestionRow)
            .where(
                AutomationSuggestionRow.id == suggestion.id,
                AutomationSuggestionRow.owner_id == suggestion.owner_id,
            )
            .with_for_update()
        )
        if row is None:
            row = AutomationSuggestionRow(
                id=suggestion.id,
                owner_id=suggestion.owner_id,
                automation_id=suggestion.automation_id,
                run_id=suggestion.run_id,
                effect=suggestion.effect.value,
                effect_version=suggestion.effect_version,
                dedupe_fingerprint=suggestion.dedupe_fingerprint,
                created_at=now,
            )
            _apply_suggestion(row, suggestion, now)
            _insert(session, row, "automation_suggestions_pkey", "suggestion not found")
            return
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale suggestion version", reason="stale_version")
        _apply_suggestion(row, suggestion, now)

    @staticmethod
    def append_check(session: Session, check: SuggestionCheck) -> None:
        """Add one check. There is no way to change or remove one."""

        session.add(
            AutomationCheckRow(
                id=check.id,
                owner_id=check.owner_id,
                suggestion_id=check.suggestion_id,
                run_id=check.run_id,
                attempt=check.attempt,
                checker=check.checker,
                model=check.model,
                verdict=check.verdict,
                confidence=check.confidence,
                reason_codes=list(check.reason_codes),
                checked_at=check.checked_at,
            )
        )

    @staticmethod
    def list_checks(session: Session, owner_id: UUID, suggestion_id: UUID) -> list[SuggestionCheck]:
        rows = session.scalars(
            select(AutomationCheckRow)
            .where(
                AutomationCheckRow.owner_id == owner_id,
                AutomationCheckRow.suggestion_id == suggestion_id,
            )
            .order_by(AutomationCheckRow.attempt)
        )
        return [check_from_row(row) for row in rows]

    # --- runs ---------------------------------------------------------------------------------

    @staticmethod
    def get_run(
        session: Session, owner_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> AutomationRun:
        statement = select(AutomationRunRow).where(
            AutomationRunRow.id == run_id, AutomationRunRow.owner_id == owner_id
        )
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise NotFoundError("run not found")
        return run_from_row(row)

    @staticmethod
    def list_occurrence_runs(
        session: Session, owner_id: UUID, automation_id: UUID, occurrence_key: str
    ) -> list[AutomationRun]:
        """The attempts at one occurrence, the first one first."""

        rows = session.scalars(
            select(AutomationRunRow)
            .where(
                AutomationRunRow.owner_id == owner_id,
                AutomationRunRow.automation_id == automation_id,
                AutomationRunRow.occurrence_key == occurrence_key,
            )
            .order_by(AutomationRunRow.attempt)
        )
        return [run_from_row(row) for row in rows]

    @staticmethod
    def list_unattended_runs(
        session: Session, owner_id: UUID, now: datetime, *, idle_since: datetime | None
    ) -> list[AutomationRun]:
        """The owner's runs that wait for a check no worker holds, the longest waiting first.

        See `unattended_conditions`. At most `MAX_LIST_ROWS`; a later call takes the rest."""

        rows = session.scalars(
            select(AutomationRunRow)
            .where(
                AutomationRunRow.owner_id == owner_id,
                *unattended_conditions(now, idle_since),
            )
            .order_by(AutomationRunRow.updated_at, AutomationRunRow.id)
            .limit(MAX_LIST_ROWS)
        )
        return [run_from_row(row) for row in rows]

    @staticmethod
    def latest_scheduled_day(session: Session, owner_id: UUID, automation_id: UUID) -> date | None:
        """The day of the latest scheduled occurrence the automation has had, in any state."""

        key = session.scalar(
            select(func.max(AutomationRunRow.occurrence_key)).where(
                AutomationRunRow.owner_id == owner_id,
                AutomationRunRow.automation_id == automation_id,
                AutomationRunRow.occurrence_key.like("d:%"),
            )
        )
        return scheduled_day(key) if key else None

    @staticmethod
    def count_runs_since(session: Session, owner_id: UUID, since: datetime) -> int:
        """How many runs of any automation were created from `since` on."""

        return (
            session.scalar(
                select(func.count())
                .select_from(AutomationRunRow)
                .where(AutomationRunRow.owner_id == owner_id, AutomationRunRow.created_at >= since)
            )
            or 0
        )

    @staticmethod
    def sum_automation_cost_since(
        session: Session, owner_id: UUID, since: datetime, sources: Collection[CostSource]
    ) -> int:
        """Millionths of a dollar the automation runs created from `since` on cost, with what a
        call in flight has reserved, for these cost sources."""

        total = session.scalar(
            automation_run_cost_query(owner_id, since, [source.value for source in sources])
        )
        return int(total or 0)

    @staticmethod
    def save_run(session: Session, run: AutomationRun, expected_version: int | None = None) -> None:
        """Insert the run, or update it when the stored version is `expected_version`."""

        row = session.scalar(
            select(AutomationRunRow)
            .where(AutomationRunRow.id == run.id, AutomationRunRow.owner_id == run.owner_id)
            .with_for_update()
        )
        if row is None:
            row = AutomationRunRow(
                id=run.id,
                owner_id=run.owner_id,
                automation_id=run.automation_id,
                occurrence_key=run.occurrence_key,
                attempt=run.attempt,
                runner=run.runner.value,
                spec_digest=run.spec_digest,
                session_digest=run.session_digest,
                credential_kind=run.credential_kind.value,
                created_at=run.created_at,
            )
            _apply_run(row, run)
            _insert(session, row, "automation_runs_pkey", "run not found")
            return
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale run version", reason="stale_version")
        _apply_run(row, run)

    @staticmethod
    def touch_last_run(session: Session, owner_id: UUID, automation_id: UUID, at: datetime) -> None:
        """Note that the automation ran. The version is not raised: a run is not an edit, so the
        owner's next change is not refused as stale."""

        session.execute(
            update(AutomationRow)
            .where(AutomationRow.id == automation_id, AutomationRow.owner_id == owner_id)
            .values(last_run_at=at)
        )

    # --- datapoints ---------------------------------------------------------------------------

    @staticmethod
    def list_run_datapoints(session: Session, owner_id: UUID, run_id: UUID) -> list[Datapoint]:
        rows = session.scalars(
            select(AutomationDatapointRow)
            .where(
                AutomationDatapointRow.owner_id == owner_id,
                AutomationDatapointRow.run_id == run_id,
            )
            .order_by(AutomationDatapointRow.created_at, AutomationDatapointRow.id)
        )
        return [datapoint_from_row(row) for row in rows]

    @staticmethod
    def get_datapoints(
        session: Session, owner_id: UUID, datapoint_ids: Collection[UUID]
    ) -> list[Datapoint]:
        """The owner's datapoints with these ids, oldest first; another owner's are left out."""

        if not datapoint_ids:
            return []
        rows = session.scalars(
            select(AutomationDatapointRow)
            .where(
                AutomationDatapointRow.owner_id == owner_id,
                AutomationDatapointRow.id.in_(datapoint_ids),
            )
            .order_by(AutomationDatapointRow.created_at, AutomationDatapointRow.id)
        )
        return [datapoint_from_row(row) for row in rows]

    @staticmethod
    def add_datapoints(session: Session, datapoints: Sequence[Datapoint]) -> None:
        """Add datapoints. The run and the automation they name must be the owner's: the composite
        foreign key refuses any other pair."""

        for item in datapoints:
            _insert(
                session,
                AutomationDatapointRow(
                    id=item.id,
                    owner_id=item.owner_id,
                    run_id=item.run_id,
                    automation_id=item.automation_id,
                    kind=item.kind.value,
                    fields=dict(item.fields) if item.fields is not None else None,
                    source_kind=item.source_kind.value,
                    source_fingerprint=item.source_fingerprint,
                    source_label=item.source_label,
                    source_received_at=item.source_received_at,
                    created_at=item.created_at,
                    purge_after=item.purge_after,
                    purged_at=item.purged_at,
                ),
                "automation_datapoints_pkey",
                "datapoint not found",
            )

    # --- what a proposal may refer to ---------------------------------------------------------

    @staticmethod
    def usable_project_ids(
        session: Session, owner_id: UUID, project_ids: Collection[UUID]
    ) -> frozenset[UUID]:
        """Of these, the projects that are the owner's and neither archived nor in the trash."""

        if not project_ids:
            return frozenset()
        return frozenset(
            session.scalars(
                select(ProjectRow.id).where(
                    ProjectRow.owner_id == owner_id,
                    ProjectRow.id.in_(project_ids),
                    ProjectRow.trashed_at.is_(None),
                    ProjectRow.archived_at.is_(None),
                )
            )
        )

    @staticmethod
    def existing_contact_email_keys(
        session: Session, owner_id: UUID, email_keys: Collection[str]
    ) -> frozenset[str]:
        """Of these e-mail keys, the ones a contact of the owner already has."""

        if not email_keys:
            return frozenset()
        return frozenset(
            key
            for key in session.scalars(
                select(ContactRow.email_key).where(
                    ContactRow.owner_id == owner_id,
                    ContactRow.email_key.in_(email_keys),
                    ContactRow.trashed_at.is_(None),
                )
            )
            if key is not None
        )

    @staticmethod
    def open_task_titles(
        session: Session, owner_id: UUID, lowered_titles: Collection[str]
    ) -> list[str]:
        """The titles of open tasks that equal one of these titles in lower case."""

        if not lowered_titles:
            return []
        return list(
            session.scalars(
                select(TaskRow.title).where(
                    TaskRow.owner_id == owner_id,
                    func.lower(TaskRow.title).in_(lowered_titles),
                    TaskRow.status != TaskStatus.COMPLETED.value,
                    TaskRow.trashed_at.is_(None),
                    TaskRow.archived_at.is_(None),
                )
            )
        )

    @staticmethod
    def has_attachments(session: Session, owner_id: UUID, kind: str, record_id: UUID) -> bool:
        """Whether something was added to a task or a contact that does not raise its version:
        a step or a contact link on a task; an alias or a link to a task, project or entry on a
        contact."""

        attached: tuple[tuple[Any, Any], ...] = {
            "task": ((StepRow, StepRow.task_id), (TaskContactRow, TaskContactRow.task_id)),
            "contact": (
                (ContactAliasRow, ContactAliasRow.contact_id),
                (TaskContactRow, TaskContactRow.contact_id),
                (ProjectContactRow, ProjectContactRow.contact_id),
                (JournalEntryContactRow, JournalEntryContactRow.contact_id),
            ),
        }.get(kind, ())
        return any(
            session.scalar(
                select(select(row).where(row.owner_id == owner_id, column == record_id).exists())
            )
            for row, column in attached
        )

    # --- the report cursor --------------------------------------------------------------------

    @staticmethod
    def get_report_cursor(session: Session, owner_id: UUID) -> ReportCursor | None:
        row = session.scalar(
            select(AutomationReportCursorRow).where(AutomationReportCursorRow.owner_id == owner_id)
        )
        if row is None:
            return None
        return ReportCursor(row.owner_id, row.seen_until, row.version, row.updated_at)

    @staticmethod
    def save_report_cursor(
        session: Session, cursor: ReportCursor, expected_version: int | None = None
    ) -> None:
        """Insert the cursor, or move it when the stored version is `expected_version`."""

        row = session.scalar(
            select(AutomationReportCursorRow)
            .where(AutomationReportCursorRow.owner_id == cursor.owner_id)
            .with_for_update()
        )
        if row is None:
            _insert(
                session,
                AutomationReportCursorRow(
                    owner_id=cursor.owner_id,
                    seen_until=cursor.seen_until,
                    version=cursor.version,
                    updated_at=cursor.updated_at,
                ),
                "automation_report_cursors_pkey",
                "report cursor not found",
            )
            return
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale report cursor version", reason="stale_version")
        row.seen_until = cursor.seen_until
        row.version = cursor.version
        row.updated_at = cursor.updated_at

    # The owner's spend is one lock for every kind of AI run (`ai-spend:{owner}`), so a cap holds
    # while an AI step and an automation run are decided side by side.
    lock_owner_spend = staticmethod(AiRunStore.lock_owner_spend)
    sum_ai_cost_since = staticmethod(AiRunStore.sum_ai_cost_since)


class SqlAutomationStore(AutomationStore, StoreBase):
    """The automation operations with the transaction, idempotency and audit of `StoreBase`."""

    def __init__(
        self, session_factory: sessionmaker[Session], telemetry: TelemetryPort | None = None
    ) -> None:
        super().__init__(session_factory, telemetry)

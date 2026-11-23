"""Running an automation: claiming an occurrence, and recording what the runner found.

The owner's Claude (or Claude Code) starts a run of an approved automation and gets a brief. It
reads its own sources and records facts (datapoints) and proposals (suggestions) here, once or a few
times, the last time with `final`. The server screens every proposal, applies the caps, drops what
it has seen before and parks each card for the owner; it never applies anything. A run can start
only for an active automation whose current spec is the one the owner approved, and the same
occurrence started twice gives the same run.

Text in a run (a datapoint, a rationale, a summary) is untrusted. It is stored, shown escaped, and
never written to a log, a metric or an audit event: those hold ids and closed codes only.
"""

import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sidekick.automations.application.check_release import release_stale_checks
from sidekick.automations.domain.automation import Automation
from sidekick.automations.domain.brief import BriefSource, effect_schemas, render_brief
from sidekick.automations.domain.datapoints import (
    DATAPOINT_RETENTION,
    MAX_DATAPOINTS_PER_CALL,
    MAX_DATAPOINTS_PER_RUN,
    MAX_REF_KEY_CHARS,
    MAX_SOURCE_REF_CHARS,
    Datapoint,
    SubmittedDatapoint,
    clean_source_label,
    counts_by_source,
    parse_fields,
    source_fingerprint,
    source_infos,
)
from sidekick.automations.domain.fingerprints import (
    DEDUPE_PURPOSE,
    SESSION_PURPOSE,
    SOURCE_PURPOSE,
    derive_key,
    keyed_hash,
)
from sidekick.automations.domain.runs import (
    DEFAULT_CHECK_LEASE,
    DEFAULT_CHECK_RELEASE_AFTER,
    MAX_SUGGESTIONS_PER_CALL,
    SUGGESTION_LIFETIME,
    AutomationRun,
    CredentialKind,
    NothingDueReason,
    OccurrenceKind,
    RunOutcome,
    RunRunner,
    RunState,
    StartAction,
    check_lease,
    manual_key,
    plan_start,
    scheduled_key,
    scheduled_run_is_due,
)
from sidekick.automations.domain.screening import (
    Proposal,
    Rejection,
    RejectionCode,
    Screened,
    ScreeningContext,
    screen_proposals,
)
from sidekick.automations.domain.spec import (
    NotRunnableCause,
    NotRunnableError,
    Runner,
    require_runnable,
)
from sidekick.automations.domain.suggestion import (
    Suggestion,
    SuggestionState,
    dedupe_fingerprint,
    fresh_indexes,
)
from sidekick.automations.domain.text import match_key, normalise_line
from sidekick.contacts.domain.normalization import normalize_email
from sidekick.shared.config import Settings
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.observability import TelemetryPort, safe_log_fields
from sidekick.shared.owner_day import day_start, month_start
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    Clock,
    IdempotentStore,
    TransactionalStore,
    TxSession,
    new_uuid7,
)
from sidekick.work.domain.ai_runs import AiUsage, CostSource, MoneyCaps

LOGGER = logging.getLogger("sidekick.automations.runs")

RUN_SCOPE = "automation:run"
MICROUSD_PER_USD = 1_000_000
_REJECTION_ORDER = tuple(RejectionCode)
_NOTHING_DUE_ORDER = tuple(NothingDueReason)
_UUID_TEXT_LENGTH = 36


class AutomationRunStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def get_automation(
        self, session: TxSession, owner_id: UUID, automation_id: UUID, *, lock: bool = False
    ) -> Automation: ...
    def get_run(
        self, session: TxSession, owner_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> AutomationRun: ...
    def list_unattended_runs(
        self, session: TxSession, owner_id: UUID, now: datetime, *, idle_since: datetime | None
    ) -> list[AutomationRun]: ...
    def list_occurrence_runs(
        self, session: TxSession, owner_id: UUID, automation_id: UUID, occurrence_key: str
    ) -> list[AutomationRun]: ...
    def latest_scheduled_day(
        self, session: TxSession, owner_id: UUID, automation_id: UUID
    ) -> date | None: ...
    def count_runs_since(self, session: TxSession, owner_id: UUID, since: datetime) -> int: ...
    def sum_automation_cost_since(
        self, session: TxSession, owner_id: UUID, since: datetime, sources: Collection[CostSource]
    ) -> int: ...
    def sum_ai_cost_since(
        self,
        session: TxSession,
        owner_id: UUID,
        since: datetime,
        sources: Collection[CostSource],
        task_id: UUID | None = None,
    ) -> int: ...
    def lock_owner_spend(self, session: TxSession, owner_id: UUID) -> None: ...
    def save_run(
        self, session: TxSession, run: AutomationRun, expected_version: int | None = None
    ) -> None: ...
    def touch_last_run(
        self, session: TxSession, owner_id: UUID, automation_id: UUID, at: datetime
    ) -> None: ...
    def list_run_datapoints(
        self, session: TxSession, owner_id: UUID, run_id: UUID
    ) -> list[Datapoint]: ...
    def add_datapoints(self, session: TxSession, datapoints: Sequence[Datapoint]) -> None: ...
    def usable_project_ids(
        self, session: TxSession, owner_id: UUID, project_ids: Collection[UUID]
    ) -> frozenset[UUID]: ...
    def existing_contact_email_keys(
        self, session: TxSession, owner_id: UUID, email_keys: Collection[str]
    ) -> frozenset[str]: ...
    def open_task_titles(
        self, session: TxSession, owner_id: UUID, lowered_titles: Collection[str]
    ) -> list[str]: ...
    def known_fingerprints(
        self, session: TxSession, owner_id: UUID, automation_id: UUID
    ) -> frozenset[str]: ...
    def list_suggestions(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        states: Collection[SuggestionState] | None = None,
        automation_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = ...,
    ) -> list[Suggestion]: ...
    def save_suggestion(
        self,
        session: TxSession,
        suggestion: Suggestion,
        now: datetime,
        expected_version: int | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AutomationRunLimits:
    """What bounds the runs, in millionths of a dollar where money is meant."""

    runs_per_day: int
    automation_monthly_cap_microusd: int
    monthly_cap_microusd: int
    local_models_exempt: bool
    checker_enabled: bool
    """A check of every proposal is configured: the run then waits for it before it is done."""
    check_lease: timedelta = DEFAULT_CHECK_LEASE
    """How long a worker may be silent while it checks a run before another takes it over."""
    check_release_after: timedelta = DEFAULT_CHECK_RELEASE_AFTER
    """How long a run may wait for its check, untaken, before its cards are shown as not checked."""

    @classmethod
    def from_settings(cls, settings: Settings) -> "AutomationRunLimits":
        return cls(
            runs_per_day=settings.ai_automation_runs_per_day,
            automation_monthly_cap_microusd=round(
                settings.ai_automation_monthly_cap_usd * MICROUSD_PER_USD
            ),
            monthly_cap_microusd=round(settings.ai_monthly_cap_usd * MICROUSD_PER_USD),
            local_models_exempt=settings.ai_local_models_exempt_from_cap,
            checker_enabled=settings.ai_check_provider != "off",
            check_lease=check_lease(settings.ai_request_timeout_seconds),
            check_release_after=timedelta(minutes=settings.ai_check_release_after_minutes),
        )

    def counted_sources(self) -> list[CostSource]:
        """The cost sources that count toward the monthly caps; a client's estimate never does."""

        caps = MoneyCaps(
            task_microusd=0,
            month_microusd=self.monthly_cap_microusd,
            local_models_exempt=self.local_models_exempt,
        )
        return [source for source in CostSource if caps.counts(source)]


@dataclass(frozen=True, slots=True)
class RunKeys:
    """The keys of the hashes a run keeps instead of the thing hashed."""

    source: bytes
    dedupe: bytes
    session: bytes

    @classmethod
    def from_secret(cls, secret: str) -> "RunKeys":
        return cls(
            source=derive_key(secret, SOURCE_PURPOSE),
            dedupe=derive_key(secret, DEDUPE_PURPOSE),
            session=derive_key(secret, SESSION_PURPOSE),
        )


@dataclass(frozen=True, slots=True)
class SubmittedSuggestion:
    """One proposal as a runner sent it, before it is screened."""

    effect: str
    payload: object
    rationale: str
    datapoint_refs: Sequence[str] = ()
    """The key of a datapoint of the same call, or the id of one the run already holds."""


@dataclass(frozen=True, slots=True)
class StartedRun:
    run: AutomationRun
    automation: Automation
    brief: str
    effect_schemas: Mapping[str, Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class NothingDue:
    reason: NothingDueReason


type StartOutcome = StartedRun | NothingDue


@dataclass(frozen=True, slots=True)
class IndexedId:
    index: int
    id: UUID


@dataclass(frozen=True, slots=True)
class IndexedRejection:
    index: int
    code: RejectionCode


@dataclass(frozen=True, slots=True)
class RecordedResults:
    run: AutomationRun
    datapoints: tuple[IndexedId, ...]
    rejected_datapoints: tuple[IndexedRejection, ...]
    suggestions: tuple[IndexedId, ...]
    rejected_suggestions: tuple[IndexedRejection, ...]
    already_known: int
    """Proposals the automation has had before, in any state: skipped, not stored again."""


class AutomationRunService:
    def __init__(
        self,
        store: AutomationRunStore,
        clock: Clock,
        limits: AutomationRunLimits,
        keys: RunKeys,
        *,
        owner_timezone: tzinfo,
        telemetry: TelemetryPort,
    ) -> None:
        self.store = store
        self.clock = clock
        self.limits = limits
        self.keys = keys
        self.owner_timezone = owner_timezone
        self.telemetry = telemetry

    @classmethod
    def from_settings(
        cls,
        store: AutomationRunStore,
        clock: Clock,
        settings: Settings,
        telemetry: TelemetryPort,
    ) -> "AutomationRunService":
        return cls(
            store,
            clock,
            AutomationRunLimits.from_settings(settings),
            RunKeys.from_secret(settings.token_pepper),
            owner_timezone=settings.owner_zone,
            telemetry=telemetry,
        )

    # --- start --------------------------------------------------------------------------------

    def start(
        self,
        actor: Actor,
        automation_id: UUID,
        *,
        runner: RunRunner,
        occurrence: OccurrenceKind,
        idempotency_key: str,
        session_id: str | None,
        credential_kind: CredentialKind,
        correlation_id: str | None = None,
    ) -> StartOutcome:
        """Claim the occurrence and return its brief, or say that nothing is due.

        Refused unless the automation is active and its current spec is the one the owner approved
        (`NotRunnableError`), and unless a daily or monthly cap leaves room for a new run. Asking
        again for an occurrence that is running returns the same run.
        """

        actor.require(RUN_SCOPE)
        if runner is RunRunner.SERVER:
            raise ValidationError("a client cannot start a server run")

        def operation(session: TxSession) -> dict[str, Any]:
            outcome = self._claim(
                session,
                actor,
                automation_id,
                runner=runner,
                occurrence=occurrence,
                session_id=session_id,
                credential_kind=credential_kind,
                correlation_id=correlation_id,
            )
            if isinstance(outcome, NothingDue):
                return {"id": None, "reason": _NOTHING_DUE_ORDER.index(outcome.reason)}
            return {"id": str(outcome.id), "reason": None}

        def run(session: TxSession) -> StartOutcome:
            record = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="start_automation_run",
                key=idempotency_key,
                payload={
                    "automation_id": str(automation_id),
                    "runner": runner.value,
                    "occurrence": occurrence.value,
                },
                execute=lambda: operation(session),
                replay=lambda result: result,
            )
            if record["id"] is None:
                return NothingDue(_NOTHING_DUE_ORDER[cast(int, record["reason"])])
            return self._started(session, actor, automation_id, UUID(str(record["id"])))

        return self.store.transaction(run)

    def _claim(
        self,
        session: TxSession,
        actor: Actor,
        automation_id: UUID,
        *,
        runner: RunRunner,
        occurrence: OccurrenceKind,
        session_id: str | None,
        credential_kind: CredentialKind,
        correlation_id: str | None,
    ) -> AutomationRun | NothingDue:
        owner_id = actor.user_id
        now = self.clock.now()
        # One start at a time per automation: the occurrence's runs are read and written under it.
        automation = self.store.get_automation(session, owner_id, automation_id, lock=True)
        _require_runnable_by(automation, runner)
        scheduled = occurrence is OccurrenceKind.SCHEDULED
        zone = self.owner_timezone
        today = now.astimezone(zone).date()
        key = scheduled_key(today) if scheduled else manual_key(new_uuid7().hex)
        self._release_stale_checks(session, owner_id, now)
        attempts = (
            self.store.list_occurrence_runs(session, owner_id, automation_id, key)
            if scheduled
            else []
        )
        plan = plan_start(attempts, spec_digest=automation.spec_digest, now=now)
        if plan.action is StartAction.NOTHING_DUE and plan.reason is not None:
            return NothingDue(plan.reason)
        if plan.action is StartAction.RETURN_EXISTING and plan.run is not None:
            return plan.run
        if scheduled and not attempts:
            not_due = scheduled_run_is_due(
                automation.spec.cadence,
                last_day=self.store.latest_scheduled_day(session, owner_id, automation_id),
                today=today,
                zone=zone,
            )
            if not_due is not None:
                return NothingDue(not_due)
        self._require_room(session, owner_id, now)
        if plan.run is not None and plan.end_as is not None:
            ended = plan.run.ended(plan.end_as, now)
            self.store.save_run(session, ended, expected_version=plan.run.version)
            self._audit(session, ended, "automation.run_ended", correlation_id)
        run = AutomationRun.claim(
            run_id=new_uuid7(),
            owner_id=owner_id,
            automation_id=automation_id,
            occurrence_key=key,
            attempt=plan.attempt,
            runner=runner,
            spec_digest=automation.spec_digest,
            session_digest=(
                keyed_hash(self.keys.session, session_id) if session_id is not None else None
            ),
            credential_kind=credential_kind,
            now=now,
        )
        self.store.save_run(session, run)
        self.store.touch_last_run(session, owner_id, automation_id, now)
        self._audit(session, run, "automation.run_started", correlation_id)
        self.telemetry.count(
            "sidekick.automations.runs", {"ai.runner": run.runner.value, "outcome": "started"}
        )
        LOGGER.info(
            "automation_run_started",
            extra=safe_log_fields({"automation_run_id": str(run.id), "outcome": "started"}),
        )
        return run

    def release_stale_checks(self, owner_id: UUID) -> int:
        """End the wait of the owner's runs for a check that nobody does, so that their proposals
        can be decided. Called wherever the owner meets proposals and when a run is started."""

        return self.store.transaction(
            lambda session: self._release_stale_checks(session, owner_id, self.clock.now())
        )

    def _release_stale_checks(self, session: TxSession, owner_id: UUID, now: datetime) -> int:
        return release_stale_checks(
            self.store,
            session,
            owner_id,
            now=now,
            checker_enabled=self.limits.checker_enabled,
            release_after=self.limits.check_release_after,
        )

    def _require_room(self, session: TxSession, owner_id: UUID, now: datetime) -> None:
        """Refuse a new run past the day's run cap, or when the month's spending is used up."""

        zone = self.owner_timezone
        # One lock for every kind of AI spend, taken before anything is counted: starts of other
        # automations of the same owner run side by side, and each must see the others' runs.
        self.store.lock_owner_spend(session, owner_id)
        if (
            self.store.count_runs_since(session, owner_id, day_start(now, zone))
            >= self.limits.runs_per_day
        ):
            raise ConflictError(
                "the daily limit of automation runs is reached", reason="ai_limit_reached"
            )
        since = month_start(now, zone)
        counted = self.limits.counted_sources()
        automation_spent = self.store.sum_automation_cost_since(session, owner_id, since, counted)
        total_spent = self.store.sum_ai_cost_since(session, owner_id, since, counted)
        if (
            automation_spent >= self.limits.automation_monthly_cap_microusd
            or total_spent >= self.limits.monthly_cap_microusd
        ):
            raise ConflictError(
                "the monthly cap for automations is reached", reason="ai_budget_reached"
            )

    def _started(
        self, session: TxSession, actor: Actor, automation_id: UUID, run_id: UUID
    ) -> StartOutcome:
        """The brief of an open run, read again so that a retry sees the automation as it is now."""

        run = self.store.get_run(session, actor.user_id, run_id)
        if run.state is RunState.CHECKING:
            return NothingDue(NothingDueReason.CHECKING)
        if run.state is RunState.DONE:
            return NothingDue(NothingDueReason.ALREADY_DONE)
        if not run.open and run.state is not RunState.QUEUED:
            raise ConflictError("the run has ended", reason="run_not_open")
        automation = self.store.get_automation(session, actor.user_id, automation_id)
        _require_runnable_by(automation, run.runner)
        if run.spec_digest != automation.spec_digest:
            raise NotRunnableError(NotRunnableCause.CHANGED_SINCE_APPROVAL)
        brief = render_brief(
            BriefSource(
                title=automation.title,
                spec=automation.spec,
                run_id=str(run.id),
                occurrence_key=run.occurrence_key,
                attempt=run.attempt,
                lease_until=run.lease_until,
            )
        )
        return StartedRun(run, automation, brief, effect_schemas(automation.spec))

    # --- record -------------------------------------------------------------------------------

    def record(
        self,
        actor: Actor,
        run_id: UUID,
        *,
        datapoints: Sequence[SubmittedDatapoint],
        suggestions: Sequence[SubmittedSuggestion],
        final: bool,
        outcome: RunOutcome | None,
        summary: str | None,
        usage: AiUsage | None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> RecordedResults:
        """Take what the runner found: screen every proposal, apply the caps, park the cards.

        Every index is answered: kept, or refused with a closed code. A refused item never fails
        the call. The last call (`final`) ends the run. Refused unless the automation is still
        active and approved at the spec the run followed.
        """

        actor.require(RUN_SCOPE)
        if len(datapoints) > MAX_DATAPOINTS_PER_CALL or len(suggestions) > MAX_SUGGESTIONS_PER_CALL:
            raise ValidationError("too many items in one call")
        if not final and (outcome is not None or summary is not None or usage is not None):
            raise ValidationError("an outcome, a summary and usage belong to the final call")

        def operation(session: TxSession) -> dict[str, Any]:
            return self._record(
                session,
                actor,
                run_id,
                datapoints=datapoints,
                suggestions=suggestions,
                final=final,
                outcome=outcome,
                summary=summary,
                usage=usage or AiUsage(),
                correlation_id=correlation_id,
            )

        def run(session: TxSession) -> RecordedResults:
            record = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="record_automation_results",
                key=idempotency_key,
                payload={
                    "run_id": str(run_id),
                    "datapoints": [asdict(item) for item in datapoints],
                    "suggestions": [asdict(item) for item in suggestions],
                    "final": final,
                    "outcome": outcome.value if outcome else None,
                    "summary": summary,
                    "usage": asdict(usage) if usage else None,
                },
                execute=lambda: operation(session),
                replay=lambda result: result,
            )
            return _results_from(record, self.store.get_run(session, actor.user_id, run_id))

        return self.store.transaction(run)

    def _record(
        self,
        session: TxSession,
        actor: Actor,
        run_id: UUID,
        *,
        datapoints: Sequence[SubmittedDatapoint],
        suggestions: Sequence[SubmittedSuggestion],
        final: bool,
        outcome: RunOutcome | None,
        summary: str | None,
        usage: AiUsage,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        owner_id = actor.user_id
        now = self.clock.now()
        # The automation first, then the run: the order every writer of a run takes its locks in.
        automation_id = self.store.get_run(session, owner_id, run_id).automation_id
        automation = self.store.get_automation(session, owner_id, automation_id, lock=True)
        run = self.store.get_run(session, owner_id, run_id, lock=True)
        if run.open:
            require_runnable(automation.state, automation.spec_digest, automation.approved_digest)
            if run.spec_digest != automation.spec_digest:
                raise NotRunnableError(NotRunnableCause.CHANGED_SINCE_APPROVAL)

        accepted_points, rejected_points, key_to_id = self._admit_datapoints(datapoints, run, now)
        known_points = self.store.list_run_datapoints(session, owner_id, run.id)
        all_points = [*known_points, *(point for _, point in accepted_points)]
        screened = screen_proposals(
            [_proposal(item, key_to_id) for item in suggestions],
            self._context(session, automation, run, suggestions, all_points),
        )
        fingerprints = [
            dedupe_fingerprint(
                self.keys.dedupe, automation.id, item.parsed, item.source_fingerprints
            )
            for item in screened.accepted
        ]
        known = self.store.known_fingerprints(session, owner_id, automation.id)
        fresh = fresh_indexes(fingerprints, known)
        created = [
            self._park(automation, run, screened.accepted[position], fingerprints[position], now)
            for position in fresh
        ]

        new_points = [point for _, point in accepted_points]
        if new_points:
            self.store.add_datapoints(session, new_points)
        for card in created:
            self.store.save_suggestion(session, card, now)
        updated = self._advance(
            run,
            datapoints=len(accepted_points),
            suggestions=len(created),
            rejected=len(screened.rejected),
            flagged=sum(1 for card in created if card.screening_flags),
            final=final,
            outcome=outcome,
            summary=summary,
            usage=usage,
            now=now,
        )
        if updated is not run:
            self.store.save_run(session, updated, expected_version=run.version)
            self._audit(session, updated, "automation.run_recorded", correlation_id)
            if updated.state is not RunState.RUNNING:
                self._audit(session, updated, "automation.run_finished", correlation_id)
                self._count_finished(updated)
        return {
            "id": str(run.id),
            "datapoints": [{"index": index, "id": str(item.id)} for index, item in accepted_points],
            "rejected_datapoints": [_rejection_record(item) for item in rejected_points],
            "suggestions": [
                {"index": screened.accepted[position].index, "id": str(card.id)}
                for position, card in zip(fresh, created, strict=True)
            ],
            "rejected": [_rejection_record(item) for item in screened.rejected],
            "known": len(screened.accepted) - len(fresh),
        }

    def _admit_datapoints(
        self, submitted: Sequence[SubmittedDatapoint], run: AutomationRun, now: datetime
    ) -> tuple[list[tuple[int, Datapoint]], list[Rejection], dict[str, UUID]]:
        """The datapoints kept, in order with their index, those refused, and the call's keys."""

        kept: list[tuple[int, Datapoint]] = []
        refused: list[Rejection] = []
        keys: dict[str, UUID] = {}
        room = max(MAX_DATAPOINTS_PER_RUN - run.datapoint_count, 0)
        for index, item in enumerate(submitted):
            if not run.open:
                refused.append(Rejection(index, RejectionCode.RUN_NOT_RUNNING))
                continue
            if len(kept) >= room:
                refused.append(Rejection(index, RejectionCode.OVER_RUN_CAP))
                continue
            point = self._datapoint(item, run, now)
            key = item.key
            if isinstance(point, RejectionCode) or (key is not None and key in keys):
                refused.append(
                    Rejection(
                        index,
                        point if isinstance(point, RejectionCode) else RejectionCode.SCHEMA_INVALID,
                    )
                )
                continue
            if key is not None:
                keys[key] = point.id
            kept.append((index, point))
        return kept, refused, keys

    def _datapoint(
        self, item: SubmittedDatapoint, run: AutomationRun, now: datetime
    ) -> Datapoint | RejectionCode:
        fields = parse_fields(item.kind, item.fields)
        if isinstance(fields, RejectionCode):
            return fields
        reference = normalise_line(item.source_ref)
        if not reference or len(reference) > MAX_SOURCE_REF_CHARS:
            return RejectionCode.SCHEMA_INVALID
        if item.key is not None and not 0 < len(item.key) <= MAX_REF_KEY_CHARS:
            return RejectionCode.SCHEMA_INVALID
        return Datapoint(
            id=new_uuid7(),
            owner_id=run.owner_id,
            run_id=run.id,
            automation_id=run.automation_id,
            kind=item.kind,
            fields=fields,
            source_kind=item.source_kind,
            source_fingerprint=source_fingerprint(self.keys.source, item.source_kind, reference),
            source_label=clean_source_label(item.source_label),
            source_received_at=item.source_received_at,
            created_at=now,
            purge_after=now + DATAPOINT_RETENTION,
        )

    def _context(
        self,
        session: TxSession,
        automation: Automation,
        run: AutomationRun,
        suggestions: Sequence[SubmittedSuggestion],
        points: Sequence[Datapoint],
    ) -> ScreeningContext:
        """What screening needs to know about the owner's records and this run, looked up once."""

        owner_id = automation.owner_id
        payloads = [mapping for item in suggestions if (mapping := _payload_mapping(item.payload))]
        project_ids = {
            parsed for item in payloads if (parsed := _uuid_or_none(item.get("project_id")))
        }
        emails = {key for item in payloads if (key := _email_key(item.get("email")))}
        titles = {
            normalise_line(value).lower()
            for item in payloads
            if isinstance(value := item.get("title"), str)
        }
        earlier = self.store.list_suggestions(session, owner_id, run_id=run.id)
        return ScreeningContext(
            allowed_effects=frozenset(automation.spec.allowed_effects),
            run_open=run.open,
            max_suggestions=automation.spec.max_suggestions_per_run,
            already_recorded=run.suggestion_count,
            datapoint_sources=source_infos(points),
            usable_project_ids=self.store.usable_project_ids(session, owner_id, project_ids),
            existing_contact_email_keys=self.store.existing_contact_email_keys(
                session, owner_id, emails
            ),
            open_task_title_keys=frozenset(
                match_key(title) for title in self.store.open_task_titles(session, owner_id, titles)
            ),
            recorded_by_source=counts_by_source([item.datapoint_ids for item in earlier], points),
        )

    def _park(
        self,
        automation: Automation,
        run: AutomationRun,
        screened: Screened,
        fingerprint: str,
        now: datetime,
    ) -> Suggestion:
        """A screened proposal as a card: waiting for the check when one is configured."""

        received = Suggestion.received(
            screened,
            id=new_uuid7(),
            owner_id=automation.owner_id,
            automation_id=automation.id,
            run_id=run.id,
            dedupe_fingerprint=fingerprint,
            expires_at=now + SUGGESTION_LIFETIME,
        )
        return received.screened(
            checker_enabled=self.limits.checker_enabled, expected_version=received.version
        )

    def _advance(
        self,
        run: AutomationRun,
        *,
        datapoints: int,
        suggestions: int,
        rejected: int,
        flagged: int,
        final: bool,
        outcome: RunOutcome | None,
        summary: str | None,
        usage: AiUsage,
        now: datetime,
    ) -> AutomationRun:
        """The run after this call. A run that is not open stays as it is."""

        if not run.open:
            return run
        recorded = run.recorded(
            datapoints=datapoints,
            suggestions=suggestions,
            rejected=rejected,
            flagged=flagged,
            now=now,
        )
        if not final:
            return recorded
        found = recorded.datapoint_count + recorded.suggestion_count
        return recorded.finished(
            outcome=outcome or (RunOutcome.OK if found else RunOutcome.NOTHING_FOUND),
            summary=summary,
            usage=_client_usage(usage),
            checker_enabled=self.limits.checker_enabled,
            now=now,
        )

    # --- shared -------------------------------------------------------------------------------

    def _audit(
        self, session: TxSession, run: AutomationRun, event: str, correlation_id: str | None
    ) -> None:
        """One audit event by ids only, never any text of the run."""

        self.store.append_audit(
            session,
            actor_id=run.owner_id,
            event=event,
            outcome="success",
            target_type="automation_run",
            target_id=run.id,
            related_id=run.automation_id,
            correlation_id=correlation_id,
        )

    def _count_finished(self, run: AutomationRun) -> None:
        outcome = run.outcome.value if run.outcome else run.state.value
        self.telemetry.count(
            "sidekick.automations.runs", {"ai.runner": run.runner.value, "outcome": outcome}
        )
        LOGGER.info(
            "automation_run_finished",
            extra=safe_log_fields({"automation_run_id": str(run.id), "outcome": outcome}),
        )


def _require_runnable_by(automation: Automation, runner: RunRunner) -> None:
    """The automation is active and approved at its current spec, and meant for this runner."""

    require_runnable(automation.state, automation.spec_digest, automation.approved_digest)
    chosen = automation.spec.runner
    if chosen is not Runner.ANY and chosen.value != runner.value:
        raise NotRunnableError(NotRunnableCause.OTHER_RUNNER)


def _client_usage(usage: AiUsage) -> AiUsage:
    """What a client reports is its own estimate, so it counts toward no money cap."""

    if usage.cost_microusd == 0 and usage.cost_source is CostSource.NONE:
        return usage
    return AiUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_microusd=usage.cost_microusd,
        cost_source=CostSource.CLIENT_ESTIMATE,
        model=usage.model,
    )


def _proposal(item: SubmittedSuggestion, key_to_id: Mapping[str, UUID]) -> Proposal:
    """The proposal with its datapoint references as ids; one that names nothing the run has gets
    an id nobody holds, so screening refuses it with the one code for that."""

    refs = tuple(_resolve_ref(ref, key_to_id) for ref in item.datapoint_refs)
    return Proposal(item.effect, item.payload, item.rationale, refs)


def _resolve_ref(ref: str, key_to_id: Mapping[str, UUID]) -> UUID:
    if ref in key_to_id:
        return key_to_id[ref]
    return _uuid_or_none(ref) or uuid4()


def _payload_mapping(payload: object) -> Mapping[str, object] | None:
    return cast("Mapping[str, object]", payload) if isinstance(payload, Mapping) else None


def _uuid_or_none(value: object) -> UUID | None:
    if not isinstance(value, str) or len(value) != _UUID_TEXT_LENGTH:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _email_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return normalize_email(value)[1]
    except ValidationError:
        return None


def _rejection_record(item: Rejection) -> dict[str, int]:
    """A refusal as a replay record keeps it: the index and the code's place in the closed list."""

    return {"index": item.index, "code": _REJECTION_ORDER.index(item.code)}


def _results_from(record: Mapping[str, Any], run: AutomationRun) -> RecordedResults:
    def ids(key: str) -> tuple[IndexedId, ...]:
        return tuple(IndexedId(int(item["index"]), UUID(str(item["id"]))) for item in record[key])

    def rejections(key: str) -> tuple[IndexedRejection, ...]:
        return tuple(
            IndexedRejection(int(item["index"]), _REJECTION_ORDER[int(item["code"])])
            for item in record[key]
        )

    return RecordedResults(
        run=run,
        datapoints=ids("datapoints"),
        rejected_datapoints=rejections("rejected_datapoints"),
        suggestions=ids("suggestions"),
        rejected_suggestions=rejections("rejected"),
        already_known=int(record["known"]),
    )

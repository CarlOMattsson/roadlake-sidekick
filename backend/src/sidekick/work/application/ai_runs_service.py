"""AI Step runs: what may run, starting a step, reporting its result and the owner's review."""

from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime, tzinfo
from typing import Literal
from uuid import UUID

from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.owner_day import day_start, month_start
from sidekick.shared.replay import id_replay_record, id_result, record_id
from sidekick.shared.types import (
    UNSET,
    Actor,
    Clock,
    CursorCodec,
    TxSession,
    new_uuid7,
    paginate,
    validate_limit,
)
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.work.application.ai_plans import load_plan_view
from sidekick.work.application.ai_run_support import (
    flag_attention,
    record_run_event,
    render_run_brief,
    replayed_run,
    require_spec,
    require_startable,
)
from sidekick.work.application.ai_store import (
    AiLimits,
    AiPlanStepView,
    AiStepEntry,
    AiStepPage,
    AiStepsStore,
    AiUsageSummary,
    StartedAiStep,
)
from sidekick.work.domain.ai_plan import (
    STARTABLE,
    AiStepStatus,
    PlanState,
    runs_on,
)
from sidekick.work.domain.ai_runs import (
    AiRunResult,
    AiRunState,
    AiStepRun,
    AiUsage,
    CostSource,
    FailureCategory,
    RunnerKind,
)
from sidekick.work.domain.run_ports import RunActivityRecorder

ReportOutcome = Literal["result", "question", "failed"]
ReviewDecision = Literal["accept", "redo", "reject", "answer"]
ListState = Literal["ready", "running", "to_review", "needs_input", "failed"]
TASK_BATCH = 200
NO_USAGE = AiUsage()
_STATUS_OF_STATE: dict[str, AiStepStatus] = {
    "running": AiStepStatus.RUNNING,
    "to_review": AiStepStatus.TO_REVIEW,
    "needs_input": AiStepStatus.NEEDS_INPUT,
    "failed": AiStepStatus.FAILED,
}


class AiRunService:
    def __init__(
        self,
        store: AiStepsStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        limits: AiLimits,
        *,
        owner_timezone: tzinfo,
        telemetry: TelemetryPort,
        activity: RunActivityRecorder | None = None,
    ) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec
        self.limits = limits
        self.owner_timezone = owner_timezone
        self.telemetry = telemetry
        self.activity = activity

    # Reads

    def list_steps(
        self,
        actor: Actor,
        *,
        state: ListState | None = None,
        task_id: UUID | None = None,
        limit: int = 25,
        cursor: str | None = None,
    ) -> AiStepPage:
        """AI steps of approved plans, by task and position; none for a plan that changed."""

        if "ai:run" not in actor.scopes:
            actor.require("tasks:read")
        validate_limit(limit, maximum=50)
        query_key = f"ai-steps:v1:state={state}:task={task_id}"
        after = self.cursor_codec.decode_position(actor.user_id, cursor, query_key)

        def read(session: TxSession) -> list[AiStepEntry]:
            return self._entries(session, actor, state, task_id, after, limit + 1)

        entries = self.store.transaction(read)
        page, next_cursor = paginate(
            entries,
            limit,
            lambda last: self.cursor_codec.encode_position(
                actor.user_id, _position_key(last), query_key
            ),
        )
        return AiStepPage(page, next_cursor)

    def _entries(
        self,
        session: TxSession,
        actor: Actor,
        state: ListState | None,
        task_id: UUID | None,
        after: str | None,
        count: int,
    ) -> list[AiStepEntry]:
        now = self.clock.now()
        entries: list[AiStepEntry] = []
        for task in self._tasks_to_scan(session, actor, task_id, after):
            view = load_plan_view(self.store, session, task, limits=self.limits, now=now)
            if view.state is not PlanState.APPROVED:
                continue
            for item in view.steps:
                entry = _entry(task, item)
                if entry is None or not _matches(entry, state):
                    continue
                if after is not None and _position_key(entry) <= after:
                    continue
                entries.append(entry)
                if len(entries) >= count:
                    return entries
        return entries

    def _tasks_to_scan(
        self, session: TxSession, actor: Actor, task_id: UUID | None, after: str | None
    ) -> Iterator[Task]:
        """One Task when named, else every Task with an approved plan, in id order, in batches."""

        if task_id is not None:
            yield self.store.get_task(session, actor.user_id, task_id)
            return
        start = UUID(after.split(":", 1)[0]) if after is not None else None
        skip: UUID | None = None
        while True:
            batch = self.store.list_tasks_with_approved_plans(
                session, actor.user_id, TASK_BATCH, start
            )
            yield from (task for task in batch if task.id != skip)
            if len(batch) < TASK_BATCH:
                return
            # The next batch starts at the last Task, which was just read.
            skip = start = batch[-1].id

    def get_run(self, actor: Actor, run_id: UUID) -> AiStepRun:
        actor.require("tasks:read")
        return self.store.transaction(lambda s: self.store.get_ai_run(s, actor.user_id, run_id))

    def usage(self, actor: Actor) -> AiUsageSummary:
        """This month's AI cost against the monthly cap, and today's Claude Code starts."""

        actor.require("tasks:read")

        def read(session: TxSession) -> AiUsageSummary:
            now = self.clock.now()
            since = month_start(now, self.owner_timezone)
            caps = self.limits.money_caps()
            counted = [source for source in CostSource if caps.counts(source)]
            return AiUsageSummary(
                month_starts_at=since,
                spent_microusd=self.store.sum_ai_cost_since(session, actor.user_id, since, counted),
                client_estimate_microusd=self.store.sum_ai_cost_since(
                    session, actor.user_id, since, [CostSource.CLIENT_ESTIMATE]
                ),
                monthly_cap_microusd=self.limits.monthly_cap_microusd,
                starts_today=self._starts_today(session, actor.user_id, now),
                starts_per_day_cap=self.limits.claude_code_starts_per_day,
            )

        return self.store.transaction(read)

    # Start

    def start_step(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> StartedAiStep:
        """Start a ready step of an approved plan; the brief is what the run then follows."""

        actor.require("ai:run")

        def operation(session: TxSession) -> dict[str, str]:
            return id_result(self._start(session, actor, step_id, correlation_id).id)

        def replayed(session: TxSession) -> StartedAiStep:
            record = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="start_ai_step",
                key=idempotency_key,
                payload={"step_id": str(step_id)},
                execute=lambda: operation(session),
                replay=id_replay_record,
            )
            run = self.store.get_ai_run(session, actor.user_id, record_id(record))
            return self._started(session, actor, run)

        return self.store.transaction(replayed)

    def _start(
        self, session: TxSession, actor: Actor, step_id: UUID, correlation_id: str | None
    ) -> AiStepRun:
        owner_id = actor.user_id
        # Lock before reading the Task and its Steps, so a withdrawal or an edit that is
        # committing now is seen and not raced past.
        task_id = self.store.step_task_id(session, owner_id, step_id)
        self.store.lock_step_order(session, owner_id, task_id)
        task = self.store.get_task(session, owner_id, task_id)
        now = self.clock.now()
        view = load_plan_view(self.store, session, task, limits=self.limits, now=now)
        item = require_startable(view, step_id)
        spec = require_spec(item.step)
        if not runs_on(spec, RunnerKind.CLAUDE_CODE):
            raise ValidationError("this step is not meant for Claude Code")
        latest = item.history.latest
        if latest is not None and latest.is_stale(now):
            self.store.save_ai_run(session, latest.cancel(now=now), expected_version=latest.version)
        if self._starts_today(session, owner_id, now) >= self.limits.claude_code_starts_per_day:
            raise ConflictError(
                "the daily limit of AI starts is reached", reason="ai_limit_reached"
            )
        run = AiStepRun.start(
            run_id=new_uuid7(),
            owner_id=owner_id,
            task_id=task.id,
            step_id=step_id,
            attempt=item.history.last_attempt + 1,
            runner=RunnerKind.CLAUDE_CODE,
            plan_digest=view.digest,
            now=now,
        )
        self.store.save_ai_run(session, run)
        self._record(session, run, "ai.run_started", correlation_id)
        return run

    def _starts_today(self, session: TxSession, owner_id: UUID, now: datetime) -> int:
        since = day_start(now, self.owner_timezone)
        return self.store.count_ai_runs_since(session, owner_id, RunnerKind.CLAUDE_CODE, since)

    def _started(self, session: TxSession, actor: Actor, run: AiStepRun) -> StartedAiStep:
        step = self.store.get_step(session, actor.user_id, run.step_id)
        task = self.store.get_task(session, actor.user_id, run.task_id)
        spec = require_spec(step)
        brief = render_run_brief(
            self.store,
            session,
            run=run,
            task=task,
            step=step,
            spec=spec,
            scopes=actor.scopes,
            runner=RunnerKind.CLAUDE_CODE,
        )
        return StartedAiStep(
            run=run,
            step=step,
            brief=brief,
            budget_microusd=spec.budget_microusd(),
            max_turns=spec.budget.max_turns,
        )

    # Report

    def report(
        self,
        actor: Actor,
        run_id: UUID,
        *,
        run_version: int,
        outcome: ReportOutcome,
        result: AiRunResult | None = None,
        question: str | None = None,
        failure: FailureCategory | None = None,
        usage: AiUsage | None = None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> AiStepRun:
        """Record how a started run ended. A result or a question waits for the owner."""

        actor.require("ai:run")

        def operation(session: TxSession) -> dict[str, str]:
            run = self.store.get_ai_run(session, actor.user_id, run_id)
            if run.runner is not RunnerKind.CLAUDE_CODE:
                raise ConflictError(
                    "only the client that started a run reports it", reason="run_not_open"
                )
            if run.version != run_version:
                raise ConflictError("stale run version", reason="stale_version")
            reported = self._reported(
                session, actor, run, outcome, result, question, failure, usage or NO_USAGE
            )
            self.store.save_ai_run(session, reported, expected_version=run_version)
            if reported.state in (AiRunState.TO_REVIEW, AiRunState.NEEDS_INPUT):
                flag_attention(self.store, session, reported, self.clock.now())
            self._record(session, reported, "ai.run_reported", correlation_id)
            self.telemetry.count(
                "sidekick.ai_runs", {"ai.runner": reported.runner.value, "outcome": outcome}
            )
            return id_result(reported.id)

        return replayed_run(
            self.store,
            actor,
            "report_ai_step_result",
            idempotency_key,
            {
                "run_id": str(run_id),
                "run_version": run_version,
                "outcome": outcome,
                "result": asdict(result) if result is not None else None,
                "question": question,
                "failure": failure.value if failure is not None else None,
                "usage": asdict(usage) if usage is not None else None,
            },
            operation,
        )

    def _reported(
        self,
        session: TxSession,
        actor: Actor,
        run: AiStepRun,
        outcome: ReportOutcome,
        result: AiRunResult | None,
        question: str | None,
        failure: FailureCategory | None,
        usage: AiUsage,
    ) -> AiStepRun:
        now = self.clock.now()
        if outcome == "result":
            if result is None:
                raise ValidationError("a result needs its content")
            self._check_result(session, actor, run, result)
            return run.report_result(result, usage, now=now)
        if outcome == "question":
            if question is None:
                raise ValidationError("a question needs its text")
            return run.report_question(question, usage, now=now)
        return run.report_failure(failure or FailureCategory.OTHER, usage, now=now)

    def _check_result(
        self, session: TxSession, actor: Actor, run: AiStepRun, result: AiRunResult
    ) -> None:
        step = self.store.get_step(session, actor.user_id, run.step_id)
        spec = require_spec(step)
        if result.format is not spec.output.format:
            raise ValidationError("the result is not in the format the step asked for")
        if len(result.text) > spec.output.max_chars:
            raise ValidationError("the result is longer than the step allows")
        actions = {
            action.id for action in self.store.list_actions(session, actor.user_id, step.id, 1000)
        }
        if any(item.action_id not in actions for item in result.checklist):
            raise ValidationError("the checklist names an action that is not in the step")

    # Review

    def review(
        self,
        actor: Actor,
        run_id: UUID,
        *,
        run_version: int,
        decision: ReviewDecision,
        comment: str | None = None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> AiStepRun:
        """The owner's decision on a run: accept (completes the step), redo, reject or answer."""

        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, str]:
            run = self.store.get_ai_run(session, actor.user_id, run_id)
            if run.version != run_version:
                raise ConflictError("stale run version", reason="stale_version")
            reviewed = self._decided(run, decision, comment)
            if decision == "accept":
                self._require_current_plan(session, actor, run)
            self.store.save_ai_run(session, reviewed, expected_version=run_version)
            self._apply_to_step(session, actor, reviewed, decision)
            self._record(session, reviewed, f"ai.run_{reviewed.state.value}", correlation_id)
            self.telemetry.count(
                "sidekick.ai_reviews", {"ai.runner": reviewed.runner.value, "outcome": decision}
            )
            return id_result(reviewed.id)

        return replayed_run(
            self.store,
            actor,
            "review_ai_step_result",
            idempotency_key,
            {
                "run_id": str(run_id),
                "run_version": run_version,
                "decision": decision,
                "comment": comment,
            },
            operation,
        )

    def _require_current_plan(self, session: TxSession, actor: Actor, run: AiStepRun) -> None:
        """Accepting needs the plan the run followed to still be the approved one."""

        self.store.lock_step_order(session, actor.user_id, run.task_id)
        task = self.store.get_task(session, actor.user_id, run.task_id)
        view = load_plan_view(self.store, session, task, limits=self.limits, now=self.clock.now())
        if view.state is PlanState.CHANGED_SINCE_APPROVAL or (
            view.state is PlanState.APPROVED and run.plan_digest != task.ai_plan_digest
        ):
            raise ConflictError(
                "the plan changed since the run started; review it again", reason="plan_changed"
            )
        if view.state is not PlanState.APPROVED:
            raise ConflictError("the plan is not approved", reason="plan_not_approved")

    def _decided(self, run: AiStepRun, decision: ReviewDecision, comment: str | None) -> AiStepRun:
        now = self.clock.now()
        if decision == "accept":
            return run.accept(now=now)
        if decision == "redo":
            return run.request_redo(comment, now=now)
        if decision == "reject":
            return run.reject(comment, now=now)
        if comment is None:
            raise ValidationError("an answer needs its text")
        return run.answer_question(comment, now=now)

    def _apply_to_step(
        self, session: TxSession, actor: Actor, run: AiStepRun, decision: ReviewDecision
    ) -> None:
        """Accepting completes the step and ticks the Actions the result reported as done."""

        now = self.clock.now()
        step = self.store.get_step(session, actor.user_id, run.step_id)
        if decision == "accept" and run.result is not None:
            done = {item.action_id for item in run.result.checklist if item.done}
            for action in self.store.list_actions(session, actor.user_id, step.id, 1000):
                if action.id in done and action.complete(now=now) is not action:
                    self.store.save_action(
                        session, action.complete(now=now), expected_version=action.version
                    )
        status = TaskStatus.COMPLETED if decision == "accept" else UNSET
        updated = step.update(now=now, attention_requested=False, status=status)
        if updated is not step:
            self.store.save_step(session, updated, expected_version=step.version)

    # Audit

    def _record(
        self,
        session: TxSession,
        run: AiStepRun,
        event: str,
        correlation_id: str | None,
    ) -> None:
        record_run_event(
            self.store,
            self.activity,
            session,
            run,
            event,
            actor_type="user",
            now=self.clock.now(),
            correlation_id=correlation_id,
        )


def _entry(task: Task, item: AiPlanStepView) -> AiStepEntry | None:
    spec = item.step.ai_spec
    if item.status is None or spec is None:
        return None
    startable = item.status in STARTABLE and runs_on(spec, RunnerKind.CLAUDE_CODE)
    return AiStepEntry(task, item.step, item.status, item.history, startable)


def _matches(entry: AiStepEntry, state: ListState | None) -> bool:
    if state is None:
        return entry.status is not AiStepStatus.DONE
    if state == "ready":
        return entry.startable
    return entry.status is _STATUS_OF_STATE[state]


def _position_key(entry: AiStepEntry) -> str:
    return f"{entry.task.id}:{entry.step.position:08d}:{entry.step.id}"

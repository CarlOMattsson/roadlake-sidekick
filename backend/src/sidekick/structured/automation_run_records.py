"""The closed records of the automation run tools: what a runner sends and what it is told back.

What a runner sends is untrusted: strings and numbers with bounds, no more. What it is told back is
ids, counts and closed codes. The summary a run ends with is AI-written text; it is never sent back
to a model, only shown to the owner escaped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from sidekick.automations.application.runs import (
    IndexedId,
    IndexedRejection,
    NothingDue,
    RecordedResults,
    StartedRun,
    SubmittedSuggestion,
)
from sidekick.automations.domain.datapoints import (
    MAX_DATAPOINTS_PER_CALL,
    MAX_DATAPOINTS_PER_RUN,
    MAX_REF_KEY_CHARS,
    MAX_SOURCE_REF_CHARS,
    DatapointKind,
    SourceKind,
    SubmittedDatapoint,
)
from sidekick.automations.domain.effects import MAX_DATAPOINT_REFS
from sidekick.automations.domain.runs import (
    MAX_SUGGESTIONS_PER_CALL,
    AutomationRun,
    NothingDueReason,
    RunOutcome,
    RunRunner,
    RunState,
)
from sidekick.automations.domain.screening import RejectionCode
from sidekick.automations.domain.spec import MICROUSD_PER_USD
from sidekick.structured.base import Output

_FieldValue = Annotated[str, Field(max_length=2_000)] | bool


class DatapointInput(Output):
    """A fact the runner read. The brief lists the fields each kind may carry."""

    kind: DatapointKind
    fields: Annotated[
        dict[str, _FieldValue],
        Field(max_length=16, description="Closed fields per kind, as the brief lists them."),
    ]
    source_kind: SourceKind
    source_ref: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MAX_SOURCE_REF_CHARS,
            description="Your own reference to the source (a message id). Kept only as a hash.",
        ),
    ]
    key: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=MAX_REF_KEY_CHARS,
            description="A name for it, so a suggestion of this call can point at it.",
        ),
    ] = None
    source_label: Annotated[str | None, Field(max_length=400)] = None
    source_received_at: datetime | None = None

    def to_submitted(self) -> SubmittedDatapoint:
        return SubmittedDatapoint(
            kind=self.kind,
            fields=self.fields,
            source_kind=self.source_kind,
            source_ref=self.source_ref,
            key=self.key,
            source_label=self.source_label,
            source_received_at=self.source_received_at,
        )


class SuggestionInput(Output):
    """A proposal. The owner decides; the server screens it and may refuse it."""

    effect: Annotated[str, Field(min_length=1, max_length=40)]
    payload: Annotated[dict[str, Any], Field(max_length=24)]
    rationale: Annotated[str, Field(max_length=2_000, description="Why, in one short sentence.")]
    datapoint_refs: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=MAX_REF_KEY_CHARS)]],
        Field(
            max_length=MAX_DATAPOINT_REFS + 10,
            description="The key of a datapoint of this call, or the id of an earlier one.",
        ),
    ] = Field(default_factory=list[str])

    def to_submitted(self) -> SubmittedSuggestion:
        return SubmittedSuggestion(
            effect=self.effect,
            payload=self.payload,
            rationale=self.rationale,
            datapoint_refs=tuple(self.datapoint_refs),
        )


DatapointsInput = Annotated[list[DatapointInput], Field(max_length=MAX_DATAPOINTS_PER_CALL)]
SuggestionsInput = Annotated[list[SuggestionInput], Field(max_length=MAX_SUGGESTIONS_PER_CALL)]


class RunRecord(Output):
    """A run: where it stands and what it holds, without any text it carries."""

    id: UUID
    automation_id: UUID
    occurrence: str
    attempt: int
    runner: RunRunner
    state: RunState
    outcome: RunOutcome | None = None
    lease_until: datetime | None = None
    datapoints: int
    suggestions: int
    rejected: int
    flagged: int
    version: int


class RunLimits(Output):
    max_suggestions_per_run: int
    max_suggestions_per_call: int
    max_datapoints_per_run: int
    max_datapoints_per_call: int
    budget_usd: float


class StartedRunOutput(Output):
    status: Literal["started", "nothing_due"]
    run: RunRecord | None = None
    brief: str | None = None
    effect_schemas: dict[str, dict[str, Any]] | None = None
    limits: RunLimits | None = None
    reason: NothingDueReason | None = None


class IndexedIdRecord(Output):
    index: int
    id: UUID


class RejectionRecord(Output):
    index: int
    code: RejectionCode


class RecordedResultsOutput(Output):
    run: RunRecord
    datapoints: list[IndexedIdRecord]
    rejected_datapoints: list[RejectionRecord]
    suggestions: list[IndexedIdRecord]
    rejected: list[RejectionRecord]
    already_known: int


def run_record(run: AutomationRun) -> RunRecord:
    return RunRecord(
        id=run.id,
        automation_id=run.automation_id,
        occurrence=run.occurrence_key,
        attempt=run.attempt,
        runner=run.runner,
        state=run.state,
        outcome=run.outcome,
        lease_until=run.lease_until,
        datapoints=run.datapoint_count,
        suggestions=run.suggestion_count,
        rejected=run.rejected_count,
        flagged=run.flagged_count,
        version=run.version,
    )


def started_output(outcome: StartedRun | NothingDue) -> StartedRunOutput:
    if isinstance(outcome, NothingDue):
        return StartedRunOutput(status="nothing_due", reason=outcome.reason)
    spec = outcome.automation.spec
    return StartedRunOutput(
        status="started",
        run=run_record(outcome.run),
        brief=outcome.brief,
        effect_schemas={label: dict(schema) for label, schema in outcome.effect_schemas.items()},
        limits=RunLimits(
            max_suggestions_per_run=spec.max_suggestions_per_run,
            max_suggestions_per_call=MAX_SUGGESTIONS_PER_CALL,
            max_datapoints_per_run=MAX_DATAPOINTS_PER_RUN,
            max_datapoints_per_call=MAX_DATAPOINTS_PER_CALL,
            budget_usd=spec.run_budget_microusd / MICROUSD_PER_USD,
        ),
    )


def _ids(items: tuple[IndexedId, ...]) -> list[IndexedIdRecord]:
    return [IndexedIdRecord(index=item.index, id=item.id) for item in items]


def _rejections(items: tuple[IndexedRejection, ...]) -> list[RejectionRecord]:
    return [RejectionRecord(index=item.index, code=item.code) for item in items]


def recorded_output(results: RecordedResults) -> RecordedResultsOutput:
    return RecordedResultsOutput(
        run=run_record(results.run),
        datapoints=_ids(results.datapoints),
        rejected_datapoints=_rejections(results.rejected_datapoints),
        suggestions=_ids(results.suggestions),
        rejected=_rejections(results.rejected_suggestions),
        already_known=results.already_known,
    )

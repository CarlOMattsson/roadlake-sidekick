"""The closed records of the automation tools: the registry's read model and what a write changes.

An automation's text (its purpose and instruction) is the owner's own and trusted; it is in the
record of one automation and never in a list. Nothing here carries text an AI wrote, because a run
writes nothing yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from sidekick.automations.application.registry import AutomationView
from sidekick.automations.domain.effects import EffectKind
from sidekick.automations.domain.spec import (
    MICROUSD_PER_USD,
    ApplyMode,
    ApprovalState,
    AutomationState,
    Cadence,
    ModelTier,
    Runner,
    Source,
    approval_state,
    is_runnable,
)
from sidekick.structured.base import Output, WithIgnoredNulls


class AutomationSummary(Output):
    """One automation in a list: where it stands, without its text."""

    id: UUID
    title: str
    state: AutomationState
    runner: Runner
    model_tier: ModelTier
    approval: ApprovalState
    changed_since_approval: bool
    runnable: bool = Field(description="Active and approved at exactly its current spec.")
    pending_suggestions: int
    last_run_at: datetime | None = None
    version: int


class AutomationRecord(AutomationSummary):
    """One automation in full: the spec the owner approves and the digest that binds it."""

    purpose: str
    instruction: str
    sources: list[Source]
    cadence: Cadence | None = None
    allowed_effects: list[EffectKind]
    apply_mode: ApplyMode
    auto_effects: list[EffectKind]
    bulk_threshold: int
    auto_threshold: int
    max_suggestions_per_run: int
    run_budget_usd: float
    spec_digest: Annotated[str, Field(min_length=64, max_length=64)]
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AutomationPageOutput(Output):
    items: Annotated[list[AutomationSummary], Field(max_length=50)]
    next_cursor: str | None = None


class AutomationOutput(Output):
    automation: AutomationRecord


class SavedAutomationOutput(AutomationOutput, WithIgnoredNulls):
    """The reply of `save_automation`: the record, and the nulls that were read as not sent."""


def _summary_fields(view: AutomationView) -> dict[str, object]:
    item = view.automation
    approval = approval_state(item.spec_digest, item.approved_digest)
    return {
        "id": item.id,
        "title": item.title,
        "state": item.state,
        "runner": item.spec.runner,
        "model_tier": item.spec.model_tier,
        "approval": approval,
        "changed_since_approval": approval is ApprovalState.CHANGED_SINCE_APPROVAL,
        "runnable": is_runnable(item.state, item.spec_digest, item.approved_digest),
        "pending_suggestions": view.pending_suggestions,
        "last_run_at": item.last_run_at,
        "version": item.version,
    }


def summary_record(view: AutomationView) -> AutomationSummary:
    return AutomationSummary.model_validate(_summary_fields(view))


def automation_record(view: AutomationView) -> AutomationRecord:
    item = view.automation
    spec = item.spec
    return AutomationRecord.model_validate(
        {
            **_summary_fields(view),
            "purpose": spec.purpose,
            "instruction": spec.instruction,
            "sources": spec.sources,
            "cadence": spec.cadence,
            "allowed_effects": spec.allowed_effects,
            "apply_mode": spec.apply_mode,
            "auto_effects": spec.auto_effects,
            "bulk_threshold": spec.bulk_threshold,
            "auto_threshold": spec.auto_threshold,
            "max_suggestions_per_run": spec.max_suggestions_per_run,
            "run_budget_usd": spec.run_budget_microusd / MICROUSD_PER_USD,
            "spec_digest": item.spec_digest,
            "approved_at": item.approved_at,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
    )

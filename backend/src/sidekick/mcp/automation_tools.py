"""The automation registry tools (ADR-013): list, read, draft and approve an automation.

The owner's Claude drafts an automation (`save_automation`) and the owner approves it in the app
(`approve_automation`, hidden from the model and always confirmed by a person). The approval is
bound to the digest of the exact spec, so a change made afterwards, by anyone, is not run until the
owner approves it again. These tools never run an automation.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

import pydantic_core
from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.automations.application.registry import AutomationView
from sidekick.automations.domain.effects import EffectKind
from sidekick.automations.domain.registry import RegistryChange
from sidekick.automations.domain.spec import (
    AUTO_THRESHOLD_RANGE,
    BULK_THRESHOLD_RANGE,
    MAX_INSTRUCTION_CHARS,
    MAX_PURPOSE_CHARS,
    MAX_SUGGESTIONS_PER_RUN,
    MAX_TITLE_CHARS,
    MICROUSD_PER_USD,
    ApplyMode,
    AutomationState,
    Cadence,
    ModelTier,
    Runner,
    Source,
)
from sidekick.mcp.annotations import READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.patch import CLEAR_SENTENCE, ignored_nulls_note
from sidekick.mcp.results import output_schema
from sidekick.mcp.results import result as tool_result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.tool_context import ToolContext
from sidekick.mcp.work_text import cell, found_sentence, spoken_line
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.automation_records import (
    AutomationOutput,
    AutomationPageOutput,
    SavedAutomationOutput,
    automation_record,
    summary_record,
)
from sidekick.structured.base import CLEAR_FIELDS, PartialChanges
from sidekick.work.domain.ai_spec import MAX_SPEC_BUDGET_USD

_Version = Annotated[int, Field(ge=1)]
_Cursor = Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)]
_OPENS_APP = AppConfig(resource_uri=SIDEKICK_APP_URI)
_Digest = Annotated[str, Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")]

LIST_DESCRIPTION = (
    "List the owner's automations (drafts, active and paused ones unless state is given): title, "
    "state, runner, model tier, whether the approved spec still matches the current one, and how "
    "many suggestions wait. Use the id and version with get_automation and save_automation."
)
GET_DESCRIPTION = (
    "Read one automation in full: its spec (instruction, sources, allowed effects, thresholds, run "
    "budget, model tier), the digest the owner approves, its approval state, whether that "
    "approval confirmed applying without a click, and the caps on that. Only an active "
    "automation approved at exactly its current spec can run."
)
SAVE_DESCRIPTION = (
    "Draft a new automation (leave out automation_id; needs title, purpose and instruction) or "
    "change one at expected_version. A proposal: any change to the spec withdraws the owner's "
    "approval and an active automation returns to draft; only the owner approves it, in the app. "
    "An automation only proposes changes the owner decides. " + CLEAR_SENTENCE
)
APPROVE_DESCRIPTION = (
    "App-only. The owner approves the automation whose spec has this digest. The approval holds "
    "only for exactly that spec, model tier included: a spec changed afterwards is not run until "
    "approved again. Needs the write scope of every effect the automation may propose. A spec "
    "that applies suggestions without a click needs auto_apply_confirmed."
)


class AutomationChanges(PartialChanges):
    """Fields to change: omitted or null stays; to empty a field, list it in clear."""

    fixed_fields = frozenset(
        {
            "title",
            "purpose",
            "instruction",
            "sources",
            "runner",
            "allowed_effects",
            "apply_mode",
            "auto_effects",
            "bulk_threshold",
            "auto_threshold",
            "max_suggestions_per_run",
            "run_budget_usd",
            "model_tier",
            "paused",
            "archived",
        }
    )

    title: Annotated[str | None, Field(min_length=1, max_length=MAX_TITLE_CHARS)] = None
    purpose: Annotated[str | None, Field(min_length=1, max_length=MAX_PURPOSE_CHARS)] = None
    instruction: Annotated[str | None, Field(min_length=1, max_length=MAX_INSTRUCTION_CHARS)] = None
    sources: list[Source] | None = None
    runner: Runner | None = None
    cadence: Annotated[
        Cadence | None, Field(description="When it is due. Clear it for owner-started runs only.")
    ] = None
    allowed_effects: Annotated[
        list[EffectKind] | None, Field(description="What a suggestion may propose.")
    ] = None
    apply_mode: ApplyMode | None = None
    auto_effects: list[EffectKind] | None = None
    bulk_threshold: Annotated[
        int | None, Field(ge=BULK_THRESHOLD_RANGE[0], le=BULK_THRESHOLD_RANGE[1])
    ] = None
    auto_threshold: Annotated[
        int | None, Field(ge=AUTO_THRESHOLD_RANGE[0], le=AUTO_THRESHOLD_RANGE[1])
    ] = None
    max_suggestions_per_run: Annotated[int | None, Field(ge=1, le=MAX_SUGGESTIONS_PER_RUN)] = None
    run_budget_usd: Annotated[float | None, Field(gt=0, le=MAX_SPEC_BUDGET_USD)] = None
    model_tier: ModelTier | None = None
    paused: bool | None = None
    archived: Annotated[bool | None, Field(description="True archives it, false restores it.")] = (
        None
    )


AutomationClear = Literal["cadence"]

_NOT_SPEC = frozenset({"title", "paused", "archived"})


def _requested(changes: AutomationChanges) -> RegistryChange:
    """The sent fields as the registry takes them: spec fields as plain values, `None` empties."""

    fields: dict[str, object] = {}
    for name in changes.model_fields_set - _NOT_SPEC:
        value = getattr(changes, name)
        if name == "run_budget_usd":
            fields["run_budget_microusd"] = round(value * MICROUSD_PER_USD)
        else:
            fields[name] = pydantic_core.to_jsonable_python(value)
    return RegistryChange(
        title=changes.title,
        spec_fields=fields,
        paused=changes.paused,
        archived=changes.archived,
    )


def _reply(sentence: str, view: AutomationView) -> str:
    item = view.automation
    record = automation_record(view)
    ref = (
        f"automation {item.id} v{item.version}: {cell(item.title)}; {record.state.value}, "
        f"{record.approval.value}, tier {record.model_tier.value}; digest {item.spec_digest}"
    )
    return spoken_line(sentence, ref)


def _register_list_automations(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_automations",
        description=LIST_DESCRIPTION,
        output_schema=output_schema(AutomationPageOutput),
        annotations=READ,
        app=_OPENS_APP,
    )
    @ctx.instrument("list_automations")
    def list_automations(
        state: AutomationState | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 25,
        cursor: _Cursor = None,
    ) -> ToolResult:
        page = ctx.container.automation_registry.list(
            ctx.actor_provider(), state=state, limit=limit, cursor=cursor
        )
        output = AutomationPageOutput(
            items=[summary_record(view) for view in page.items], next_cursor=page.next_cursor
        )
        rows = [
            f"- {item.id} | {cell(item.title)} | v{item.version} | {item.state.value} | "
            f"{item.approval.value} | tier {item.model_tier.value} | "
            f"{item.pending_suggestions} waiting"
            for item in output.items
        ]
        head = found_sentence(
            len(output.items),
            "automation",
            "automations",
            [item.title for item in output.items],
        )
        return tool_result(output.model_dump(mode="json"), "\n".join([head, *rows]))


def _register_get_automation(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="get_automation",
        description=GET_DESCRIPTION,
        output_schema=output_schema(AutomationOutput),
        annotations=READ,
        app=_OPENS_APP,
    )
    @ctx.instrument("get_automation")
    def get_automation(automation_id: UUID) -> ToolResult:
        view = ctx.container.automation_registry.get(ctx.actor_provider(), automation_id)
        output = AutomationOutput(automation=automation_record(view))
        return tool_result(output.model_dump(mode="json"), _reply("Automation.", view))


def _register_save_automation(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="save_automation",
        description=SAVE_DESCRIPTION,
        output_schema=output_schema(SavedAutomationOutput),
        annotations=WRITE,
    )
    @ctx.instrument("save_automation")
    def save_automation(
        idempotency_key: IdempotencyKey,
        changes: AutomationChanges,
        automation_id: UUID | None = None,
        expected_version: _Version | None = None,
        clear: Annotated[list[AutomationClear], CLEAR_FIELDS] | None = None,
    ) -> ToolResult:
        changes.resolve(clear or ())
        view = ctx.container.automation_registry.save(
            ctx.actor_provider(),
            automation_id,
            expected_version=expected_version,
            requested=_requested(changes),
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        output = SavedAutomationOutput(
            automation=automation_record(view), ignored_nulls=changes.ignored_nulls
        )
        sentence = (
            f"Saved the automation {cell(view.automation.title)}."
            f"{ignored_nulls_note(changes.ignored_nulls)}"
        )
        return tool_result(output.model_dump(mode="json"), _reply(sentence, view))


def _register_approve_automation(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="approve_automation",
        description=APPROVE_DESCRIPTION,
        output_schema=output_schema(AutomationOutput),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
        # Claude Code asks a person at every call, also in its permissive modes.
        meta={"anthropic/requiresUserInteraction": True},
    )
    @ctx.instrument("approve_automation")
    def approve_automation(
        automation_id: UUID,
        spec_digest: _Digest,
        idempotency_key: IdempotencyKey,
        auto_apply_confirmed: Annotated[
            bool, Field(description="The owner confirmed that suggestions apply without a click.")
        ] = False,
    ) -> ToolResult:
        view = ctx.container.automation_registry.approve(
            ctx.actor_provider(),
            automation_id,
            spec_digest=spec_digest,
            idempotency_key=idempotency_key,
            auto_apply_confirmed=auto_apply_confirmed,
            correlation_id=request_correlation_id_or_new(),
        )
        output = AutomationOutput(automation=automation_record(view))
        sentence = f"Approved the automation {cell(view.automation.title)}."
        return tool_result(output.model_dump(mode="json"), _reply(sentence, view))


_REGISTRARS = (
    _register_list_automations,
    _register_get_automation,
    _register_save_automation,
    _register_approve_automation,
)


def register_automation_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the automation registry tools."""
    for register in _REGISTRARS:
        register(mcp, ctx)

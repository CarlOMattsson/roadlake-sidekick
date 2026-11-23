"""The automation report tools (ADR-013): what the automations did, seen, and saved as a page.

`get_automation_report` is for the owner's Claude and the app: counts per automation, totals and a
few cards worth a look, since the owner last looked or since a given time. The report holds no text
a run read or proposed; the one sentence of a run it can carry, `ai_summary`, is written by an AI
and labelled untrusted. `mark_automation_report_seen` and `export_automation_report_html` belong to
the app: the first moves the owner's "seen until" mark (the Start view then shows what happened
since), the second returns one self-contained page, text escaped, for the app to save.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.automations.domain.report import DEFAULT_HIGHLIGHTS, MAX_HIGHLIGHTS
from sidekick.mcp.annotations import READ, WRITE
from sidekick.mcp.change_source import REQUIRES_APP_META
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import card_result, output_schema, result
from sidekick.mcp.tool_context import ToolContext
from sidekick.mcp.work_text import cell, iso_time
from sidekick.structured.automation_report_records import (
    AutomationReportOutput,
    ReportCursorOutput,
    ReportHtmlOutput,
    cursor_output,
    report_output,
    window_record,
)

_Since = Annotated[
    datetime | None,
    Field(description="ISO time with offset; omit for since the owner last looked."),
]

REPORT_DESCRIPTION = (
    "What the owner's automations did since the owner last looked (or since a time): counts per "
    "automation, totals and a few cards worth a look. ai_summary is AI-written, untrusted."
)
SEEN_DESCRIPTION = (
    "App only. The owner has seen the automation report up to seen_until (window.until). Pass "
    "report_version as expected_version, 0 the first time. Start then shows what happened since."
)
EXPORT_DESCRIPTION = (
    "App only. The automation report as one self-contained HTML page for the app to save: text "
    "escaped, text an AI wrote labelled, no script, link or external resource."
)

_APP_ONLY = AppConfig(visibility=["app"])
# The server also refuses a call that does not come from the app.
_REQUIRES_APP = {REQUIRES_APP_META: True}


def _spoken(output: AutomationReportOutput) -> str:
    totals = output.totals
    return (
        f"{totals.runs} runs ({totals.failed_runs} failed), {totals.suggestions_created} "
        f"suggestions made, {totals.pending} waiting; cost {totals.cost_usd:.2f} USD."
    )


def _register_get_report(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="get_automation_report",
        description=REPORT_DESCRIPTION,
        output_schema=output_schema(AutomationReportOutput),
        annotations=READ,
    )
    @ctx.instrument("get_automation_report")
    def get_automation_report(
        since: _Since = None,
        limit: Annotated[int, Field(ge=1, le=MAX_HIGHLIGHTS)] = DEFAULT_HIGHLIGHTS,
    ) -> ToolResult:
        report = ctx.container.automation_report.report(
            ctx.actor_provider(), since=since, limit=limit
        )
        output = report_output(report)
        return result(output.model_dump(mode="json"), _spoken(output))


def _register_mark_seen(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="mark_automation_report_seen",
        description=SEEN_DESCRIPTION,
        output_schema=output_schema(ReportCursorOutput),
        annotations=WRITE,
        app=_APP_ONLY,
        meta=_REQUIRES_APP,
    )
    @ctx.instrument("mark_automation_report_seen")
    def mark_automation_report_seen(
        seen_until: datetime,
        expected_version: Annotated[int, Field(ge=0)],
        idempotency_key: IdempotencyKey,
    ) -> ToolResult:
        cursor = ctx.container.automation_report.mark_seen(
            ctx.actor_provider(),
            seen_until=seen_until,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        output = cursor_output(cursor)
        sentence = (
            f"Marked the automation report as seen until {cell(iso_time(cursor.seen_until))}."
        )
        return card_result(output.model_dump(mode="json"), sentence)


def _register_export_html(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="export_automation_report_html",
        description=EXPORT_DESCRIPTION,
        output_schema=output_schema(ReportHtmlOutput),
        annotations=READ,
        app=_APP_ONLY,
        meta=_REQUIRES_APP,
    )
    @ctx.instrument("export_automation_report_html")
    def export_automation_report_html(since: _Since = None) -> ToolResult:
        container = ctx.container
        zone = container.settings.owner_zone
        page = container.automation_report.export_html(
            ctx.actor_provider(),
            since=since,
            locale=container.settings.mcp_app_locale,
            zone=zone,
        )
        day = page.report.window.until.astimezone(zone).date()
        output = ReportHtmlOutput(
            file_name=f"automation-report-{day.isoformat()}.html",
            html=page.html,
            window=window_record(page.report),
        )
        return card_result(output.model_dump(mode="json"), "Exported the automation report.")


_REGISTRARS = (_register_get_report, _register_mark_seen, _register_export_html)


def register_automation_report_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the automation report tools."""
    for register in _REGISTRARS:
        register(mcp, ctx)

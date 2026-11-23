"""The automation report as one self-contained HTML page the owner can save and open anywhere.

The page is built from the report's values by one function that escapes every piece of text, so no
text of an automation or of a run can become markup. Two kinds of text reach it: the title of an
automation (the owner's own) and the summary a failed run wrote about itself, which an AI wrote and
which is shown inside a box that says so. Nothing a run read or proposed is in the report, so there
is no payload, rationale or source text to render.

The page holds no script, no external resource, no link, no image and no form. Its Content Security
Policy refuses everything except its own inline style, so a browser that is handed a markup
mistake still runs nothing and fetches nothing.
"""

import html
from dataclasses import dataclass
from datetime import datetime, tzinfo

from sidekick.automations.domain.report import (
    AutomationReport,
    Highlight,
    HighlightKind,
    ReportRow,
    WindowBasis,
)
from sidekick.automations.domain.spec import MICROUSD_PER_USD
from sidekick.shared.locale import AppLocale
from sidekick.work.domain.ai_spec import clean_text

MAX_HTML_BYTES = 256 * 1024
"""What a host's download accepts; the report's own caps keep the page far below it."""
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
)

_STYLE = (
    "body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;"
    "color:#1b1b1f;background:#fff}"
    "h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:2rem}"
    "table{border-collapse:collapse;width:100%}"
    "th,td{padding:.35rem .6rem;border-bottom:1px solid #d6d6dc;text-align:right}"
    "th:first-child,td:first-child{text-align:left}"
    "li{margin:.6rem 0}"
    ".ai{margin:.3rem 0 0;padding:.4rem .7rem;border-left:4px solid #b26a00;background:#fff4e0}"
    ".label{font-weight:600}.muted{color:#55555f}"
    "@media (prefers-color-scheme:dark){body{color:#ececf1;background:#17171a}"
    "th,td{border-color:#3a3a42}.ai{background:#2a2118;border-color:#d89a3c}"
    ".muted{color:#a8a8b3}}"
)


@dataclass(frozen=True, slots=True)
class _Words:
    title: str
    window: dict[WindowBasis, str]
    totals: str
    columns: tuple[str, ...]
    worth_a_look: str
    kinds: dict[HighlightKind, str]
    ai_label: str
    omitted: str
    tier: str
    nothing: str
    footer: str


_WORDS: dict[AppLocale, _Words] = {
    "sv": _Words(
        title="Automationsrapport",
        window={
            WindowBasis.LAST_SEEN: "Sedan du senast tittade",
            WindowBasis.FIRST_LOOK: "Senaste veckan",
            WindowBasis.GIVEN: "Vald period",
        },
        totals="Totalt",
        columns=(
            "Automation",
            "Körningar",
            "Lyckade",
            "Misslyckade",
            "Förslag",
            "Tillämpade",
            "Avvisade",
            "Flaggade",
            "Automatiskt",
            "Väntar",
            "Kostnad (USD)",
        ),
        worth_a_look="Värt en titt",
        kinds={
            HighlightKind.RUN_FAILED: "Körning misslyckades",
            HighlightKind.SUGGESTION_FLAGGED: "Förslag flaggat",
            HighlightKind.SUGGESTION_AUTO_APPLIED: "Tillämpat automatiskt",
        },
        ai_label="Skrivet av en AI, ej verifierat:",
        omitted="{count} automationer till visas inte, men ingår i totalen.",
        tier="modellnivå",
        nothing="Inget hände under perioden.",
        footer="Bara antal och koder. Inget en körning läste eller föreslog ingår.",
    ),
    "en": _Words(
        title="Automation report",
        window={
            WindowBasis.LAST_SEEN: "Since you last looked",
            WindowBasis.FIRST_LOOK: "The last week",
            WindowBasis.GIVEN: "Chosen period",
        },
        totals="Total",
        columns=(
            "Automation",
            "Runs",
            "Succeeded",
            "Failed",
            "Suggestions",
            "Applied",
            "Dismissed",
            "Flagged",
            "Automatic",
            "Waiting",
            "Cost (USD)",
        ),
        worth_a_look="Worth a look",
        kinds={
            HighlightKind.RUN_FAILED: "Run failed",
            HighlightKind.SUGGESTION_FLAGGED: "Suggestion flagged",
            HighlightKind.SUGGESTION_AUTO_APPLIED: "Applied automatically",
        },
        ai_label="Written by an AI, unverified:",
        omitted="{count} more automations are not shown but are in the total.",
        tier="model tier",
        nothing="Nothing happened in the period.",
        footer="Counts and codes only. Nothing a run read or proposed is included.",
    ),
}


def esc(value: object) -> str:
    """Text for an element's content or attribute: invisible characters removed, markup escaped.

    The one place text becomes HTML. Every value that is not a number the page computes itself
    goes through it.
    """

    return html.escape(clean_text(str(value)), quote=True)


def _usd(microusd: int) -> str:
    return f"{microusd / MICROUSD_PER_USD:.4f}"


def _when(value: datetime, zone: tzinfo) -> str:
    return value.astimezone(zone).strftime("%Y-%m-%d %H:%M")


def _row(cells: list[str], tag: str = "td") -> str:
    return "<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>"


def _counts(row: ReportRow, label: str) -> list[str]:
    return [
        label,
        str(row.runs),
        str(row.ok_runs),
        str(row.failed_runs),
        str(row.suggestions_created),
        str(row.applied),
        str(row.dismissed),
        str(row.flagged),
        str(row.auto_applied),
        str(row.pending),
        _usd(row.cost_microusd),
    ]


def _highlight(item: Highlight, words: _Words, zone: tzinfo) -> str:
    codes = [code for code in (item.outcome, item.effect, item.verdict, *item.flags) if code]
    detail = esc(_when(item.at, zone) + (" · " + ", ".join(codes) if codes else ""))
    line = (
        f"<strong>{esc(words.kinds[item.kind])}</strong> · {esc(item.automation_title)} · "
        f'<span class="muted">{detail}</span>'
    )
    if item.summary:
        line += (
            f'<p class="ai"><span class="label">{esc(words.ai_label)}</span> '
            f"{esc(item.summary)}</p>"
        )
    return f"<li>{line}</li>"


def _table(report: AutomationReport, words: _Words) -> str:
    totals = report.totals
    rows = [_row([esc(name) for name in words.columns], "th")]
    for row in report.rows:
        label = (
            f'{esc(row.title)} <span class="muted">({esc(words.tier)} {esc(row.model_tier)})</span>'
        )
        rows.append(_row(_counts(row, label)))
    rows.append(
        _row(
            [
                f"<strong>{esc(words.totals)}</strong>",
                str(totals.runs),
                str(totals.ok_runs),
                str(totals.failed_runs),
                str(totals.suggestions_created),
                str(totals.applied),
                str(totals.dismissed),
                str(totals.flagged),
                str(totals.auto_applied),
                str(totals.pending),
                _usd(totals.cost_microusd),
            ]
        )
    )
    return "<table>" + "".join(rows) + "</table>"


def render_report_html(report: AutomationReport, locale: AppLocale, zone: tzinfo) -> str:
    """The whole page for `report`, times shown in `zone`."""

    words = _WORDS[locale]
    window = report.window
    body = [
        f"<h1>{esc(words.title)}</h1>",
        f'<p class="muted">{esc(words.window[window.basis])}: '
        f"{esc(_when(window.since, zone))} - {esc(_when(window.until, zone))}</p>",
    ]
    if not report.rows and not report.highlights:
        body.append(f"<p>{esc(words.nothing)}</p>")
    else:
        body.append(_table(report, words))
        if report.omitted_automations:
            omitted = words.omitted.format(count=report.omitted_automations)
            body.append(f'<p class="muted">{esc(omitted)}</p>')
    if report.highlights:
        items = "".join(_highlight(item, words, zone) for item in report.highlights)
        body.append(f"<h2>{esc(words.worth_a_look)}</h2><ul>{items}</ul>")
    body.append(f'<p class="muted">{esc(words.footer)}</p>')
    page = (
        "<!doctype html>"
        f'<html lang="{locale}"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(words.title)}</title><style>{_STYLE}</style></head>"
        f"<body>{''.join(body)}</body></html>"
    )
    if len(page.encode()) > MAX_HTML_BYTES:
        raise ValueError("the report page is larger than a download may be")
    return page

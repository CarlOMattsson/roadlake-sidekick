"""The insight on Start: one sentence from a closed catalogue, chosen by priority.

An insight is never free text. Each code has a Swedish and an English template and names the
fields the template may fill (a name, a count); nothing else from the owner's data can reach the
sentence. The only sentence a model wrote is the latest automation run's summary: it ranks below
every deterministic code, is cleaned like any untrusted text, and is flagged `written_by = "ai"`
so the page can say who wrote it.

The catalogue is computed on read from facts the caller gathers; nothing is stored and no clock is
read here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from sidekick.automations.domain.text import normalise_line
from sidekick.shared.locale import AppLocale

InsightCode = Literal[
    "automation_failed",
    "overdue_backlog",
    "waiting_long",
    "tomorrow_heavy",
    "automation_summary",
]
WrittenBy = Literal["system", "ai"]

OVERDUE_BACKLOG_COUNT: Final = 5
"""Tasks overdue for more than `OVERDUE_BACKLOG_DAYS` days that make a backlog."""
OVERDUE_BACKLOG_DAYS: Final = 7
WAITING_LONG_DAYS: Final = 7
TOMORROW_HEAVY_FACTOR: Final = 3
TOMORROW_HEAVY_MINIMUM: Final = 3
"""Tomorrow needs at least this many tasks, so one task against none is not heavy."""
NAME_LIMIT: Final = 60
SUMMARY_LIMIT: Final = 160


@dataclass(frozen=True, slots=True)
class Template:
    """One catalogue entry: the words in each language and the fields the words may name."""

    code: InsightCode
    priority: int
    """Lower comes first."""
    written_by: WrittenBy
    text: Mapping[AppLocale, str]
    fields: frozenset[str]


CATALOGUE: Final[tuple[Template, ...]] = (
    Template(
        code="automation_failed",
        priority=10,
        written_by="system",
        text={
            "sv": "{automation} misslyckades senast.",
            "en": "{automation} failed on its last run.",
        },
        fields=frozenset({"automation"}),
    ),
    Template(
        code="overdue_backlog",
        priority=20,
        written_by="system",
        text={
            "sv": "{count} uppgifter har varit försenade i över en vecka.",
            "en": "{count} tasks have been overdue for more than a week.",
        },
        fields=frozenset({"count"}),
    ),
    Template(
        code="waiting_long",
        priority=30,
        written_by="system",
        text={
            "sv": "Du har väntat på {contact} i {days} dagar.",
            "en": "You have been waiting for {contact} for {days} days.",
        },
        fields=frozenset({"contact", "days"}),
    ),
    Template(
        code="tomorrow_heavy",
        priority=40,
        written_by="system",
        text={
            "sv": "Imorgon har du {count} uppgifter, mycket mer än idag.",
            "en": "Tomorrow you have {count} tasks, far more than today.",
        },
        fields=frozenset({"count"}),
    ),
    Template(
        code="automation_summary",
        priority=90,
        written_by="ai",
        text={"sv": "{summary}", "en": "{summary}"},
        fields=frozenset({"summary"}),
    ),
)
_BY_CODE: Final[Mapping[InsightCode, Template]] = {item.code: item for item in CATALOGUE}


@dataclass(frozen=True, slots=True)
class InsightFacts:
    """What the caller found out about the day; every field defaults to "nothing to say"."""

    failed_automation: str | None = None
    """The name of an automation whose latest run failed."""
    overdue_for_a_week: int = 0
    """Tasks overdue for more than `OVERDUE_BACKLOG_DAYS` days."""
    longest_waiting_contact: str | None = None
    """The display name of the contact a task has waited on the longest."""
    longest_waiting_days: int = 0
    today_tasks: int = 0
    tomorrow_tasks: int = 0
    automation_summary: str | None = None
    """What the latest automation run wrote about itself: model-written, untrusted."""


@dataclass(frozen=True, slots=True)
class Insight:
    code: InsightCode
    priority: int
    written_by: WrittenBy
    text: str


def _name(value: str | None, limit: int) -> str | None:
    """`value` as one clean line of at most `limit` characters, or None when nothing is left."""

    if value is None:
        return None
    line = normalise_line(value)
    if not line:
        return None
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _fields(facts: InsightFacts) -> dict[InsightCode, dict[str, str]]:
    """The fields of every code whose facts call for it. Names are cleaned and bounded here."""

    found: dict[InsightCode, dict[str, str]] = {}
    automation = _name(facts.failed_automation, NAME_LIMIT)
    if automation is not None:
        found["automation_failed"] = {"automation": automation}
    if facts.overdue_for_a_week >= OVERDUE_BACKLOG_COUNT:
        found["overdue_backlog"] = {"count": str(facts.overdue_for_a_week)}
    contact = _name(facts.longest_waiting_contact, NAME_LIMIT)
    if contact is not None and facts.longest_waiting_days >= WAITING_LONG_DAYS:
        found["waiting_long"] = {"contact": contact, "days": str(facts.longest_waiting_days)}
    if (
        facts.tomorrow_tasks >= TOMORROW_HEAVY_MINIMUM
        and facts.tomorrow_tasks >= TOMORROW_HEAVY_FACTOR * facts.today_tasks
    ):
        found["tomorrow_heavy"] = {"count": str(facts.tomorrow_tasks)}
    summary = _name(facts.automation_summary, SUMMARY_LIMIT)
    if summary is not None:
        found["automation_summary"] = {"summary": summary}
    return found


def render(template: Template, fields: Mapping[str, str], locale: AppLocale) -> str:
    """The sentence of `template` in `locale`; only the fields the template names are used."""

    return template.text[locale].format(**{name: fields[name] for name in template.fields})


def applicable_insights(facts: InsightFacts, locale: AppLocale) -> list[Insight]:
    """Every insight the facts call for, first by priority."""

    found = _fields(facts)
    templates = sorted((_BY_CODE[code] for code in found), key=lambda item: item.priority)
    return [
        Insight(
            code=template.code,
            priority=template.priority,
            written_by=template.written_by,
            text=render(template, found[template.code], locale),
        )
        for template in templates
    ]


def choose_insight(facts: InsightFacts, locale: AppLocale) -> Insight | None:
    """The one insight Start shows, or None when the day has nothing to say."""

    insights = applicable_insights(facts, locale)
    return insights[0] if insights else None

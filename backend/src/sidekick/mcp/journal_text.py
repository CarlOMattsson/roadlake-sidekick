"""Speakable text of the Journal tool results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sidekick.journal.domain.day_done import owner_today
from sidekick.journal.domain.records import EntryRelations
from sidekick.journal.domain.summary import SummaryContent
from sidekick.mcp.text import count_phrase, flat, rows_text, spoken_date
from sidekick.mcp.tool_context import ToolContext
from sidekick.structured.journal import (
    DayDoneRecord,
    JournalEntryRecord,
    JournalEntryResult,
    JournalSummaryRecord,
)

# Block 2 of every Journal tool result is the full structuredContent (D-060: the host model may
# read the owner's own content):
# Claude may read all Journal information in tool results, titles, summaries, key points, raw
# text, drafts and rationales alike. Logs, audit, SQL telemetry and error surfaces never carry
# journal text; see tests/contract/test_journal_telemetry_redaction.py.


def _appended_line(points: int, with_text: bool, where: str) -> str:
    """Line 1 of an add: "Added 2 points to today's journal." with no id and no version."""

    parts: list[str] = []
    if points:
        parts.append(count_phrase(points, "point", "points"))
    if with_text:
        parts.append("your words")
    return f"Added {' and '.join(parts)} to {where}."


_LINK_NAMES_SHOWN = 6


def links_row(record: JournalEntryRecord) -> list[str]:
    """One plain row naming what the entry is linked to, so Claude can say it aloud."""

    names = [flat(link.label, 60) for link in record.links if link.label]
    if not names:
        return []
    shown = names[:_LINK_NAMES_SHOWN]
    text = ", ".join(shown[:-1]) + (" and " if len(shown) > 1 else "") + shown[-1]
    if len(names) > len(shown):
        text += f" and {len(names) - len(shown)} more"
    return [f"Linked to {text}."]


def tags_row(record: JournalEntryRecord) -> list[str]:
    """One plain row with the entry's tags, so Claude can read and repeat them."""

    tags = [flat(tag, 60) for tag in record.tags]
    return [f"Tags: {', '.join(tags)}."] if tags else []


def _relation_change_phrase(added: int, removed: int) -> str:
    """Words for a change of links, like Added 2 links and removed 1 link; empty for none."""

    parts: list[str] = []
    if added:
        parts.append(f"added {count_phrase(added, 'link', 'links')}")
    if removed:
        parts.append(f"removed {count_phrase(removed, 'link', 'links')}")
    return f"{' and '.join(parts).capitalize()}." if parts else ""


def entry_row(entry: JournalEntryRecord, *, include_content: bool) -> str:
    """One row: id, date, status and version; the title unless include_content is false."""

    status = "archived" if entry.archived else "active"
    row = f"- {entry.id} | {entry.journal_date} | {status} | v{entry.version}"
    if include_content:
        row += f" | {flat(entry.title)}"
    tags = [flat(tag, 60) for tag in entry.tags]
    return f"{row} | tags: {', '.join(tags)}" if tags else row


SPOKEN_TITLE_LIMIT = 80
DRAFT_STATE_WORDS = {
    "pending_review": "waiting for review",
    "finalized": "finalized",
    "rejected": "rejected",
    "superseded": "superseded",
}


def counted(count: int, one: str, many: str, *, partial: bool = False) -> str:
    """`N` with its noun; `at least N` when the page is only part of the result."""

    prefix = "at least " if partial else ""
    return f"{prefix}{count_phrase(count, one, many)}"


def done_row(done: DayDoneRecord) -> list[str]:
    """One counts-only line about what was done that day; nothing when nothing was."""

    counts = done.counts
    if not (counts.tasks or counts.steps or counts.purchases):
        return []
    return [
        f"Done that day (owner's zone): {counts.tasks} tasks, {counts.steps} steps, "
        f"{counts.purchases} purchases" + ("; lists are cut at 50." if done.truncated else ".")
    ]


def summary_phrase(summary: JournalSummaryRecord) -> str:
    """The daily summary's state for line 1 of get_journal_day."""

    if not summary.exists:
        return "without a daily summary"
    if summary.status is None:
        return "with a daily summary"
    return f"with a {summary.status} daily summary"


@dataclass(frozen=True, slots=True)
class JournalToolContext(ToolContext):
    """The shared tool context plus the journal's speakable day helpers."""

    def _today(self) -> date:
        return owner_today(self.container.journal.clock.now(), self.container.settings.owner_zone)

    def spoken_day(self, day: date) -> str:
        """A journal day for line 1, such as "21 July"; the ISO date stays on later lines."""

        return spoken_date(day, self._today())

    def journal_phrase(self, day: date) -> str:
        """ "today's journal" for today, otherwise "the journal from 21 July"."""

        if day == self._today():
            return "today's journal"
        return f"the journal from {self.spoken_day(day)}"


def update_entry_text(
    ctx: JournalToolContext,
    structured: JournalEntryResult,
    before: EntryRelations | None,
    *,
    appended_points: int,
    appended_text: bool,
    edited_fields: bool,
) -> str:
    """The speakable text of an entry update: what changed, the entry, and the link changes."""

    updated = structured.entry
    if appended_points or appended_text:
        first_line = _appended_line(
            appended_points, appended_text, ctx.journal_phrase(updated.journal_date)
        )
    elif not edited_fields:
        day = ctx.spoken_day(updated.journal_date)
        first_line = f"Changed the links or tags of the journal entry from {day}."
    else:
        first_line = f"Updated the journal entry from {ctx.spoken_day(updated.journal_date)}."
    rows = [f"Entry {updated.id} v{updated.version}."]
    if before is not None:
        was = {*before.project_ids, *before.contact_ids}
        now = {link.id for link in updated.links}
        changed = _relation_change_phrase(len(now - was), len(was - now))
        rows.append(changed or "No link changed.")
    rows.extend(links_row(updated))
    rows.extend(tags_row(updated))
    return rows_text(first_line, rows)


def empty_summary_content(overview: str) -> SummaryContent:
    """Only the overview is model text; the structured sections stay empty."""

    return SummaryContent(
        overview=overview,
        overview_entry_ids=[],
        themes=[],
        important_events=[],
        decisions=[],
        commitments=[],
        open_questions=[],
        unresolved_items=[],
        contradictions=[],
    )

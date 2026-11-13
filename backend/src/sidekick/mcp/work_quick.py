"""Text for the agenda read that asks "what fits in N minutes" or includes undated Tasks.

The ordinary agenda text groups by deadline, so an undated Task (no `due_at`) has no row there.
This view answers the other question: which open Tasks can be done now, with their estimate.
Line 1 is the sentence voice mode reads: no id, no version, no ISO time. Rows after it carry the
id and version for the next call.
"""

from collections.abc import Sequence

from sidekick.mcp.results import spoken_names
from sidekick.mcp.text import CARD_NOTE, MAX_ROWS, card_row, card_rows, count_phrase
from sidekick.mcp.work_text import iso_time
from sidekick.structured.work_records import WorkItemRecord


def quick_agenda_sentence(
    items: Sequence[WorkItemRecord], next_cursor: str | None, *, max_minutes: int | None
) -> str:
    """Line 1: how many Tasks, within how many minutes, and the first few titles."""

    fit = (
        f" that fit in {count_phrase(max_minutes, 'minute', 'minutes')}"
        if max_minutes is not None
        else ""
    )
    if not items:
        return f"No open tasks{fit}."
    page = "" if next_cursor is None else " on this page (more follow)"
    noun = count_phrase(len(items), "task", "tasks") + page
    names = spoken_names([item.title for item in items], len(items))
    return f"{noun}{fit}: {names}."


def quick_agenda_text(
    items: Sequence[WorkItemRecord], next_cursor: str | None, *, max_minutes: int | None
) -> str:
    """Return the sentence, then one row per Task: id and version, title, estimate and due date."""

    rows: list[str] = []
    for item in items:
        minutes = item.estimated_minutes
        rows.append(
            card_row(
                f"{item.id} v{item.version}",
                item.title,
                f"{minutes} min" if minutes is not None else "no estimate",
                f"due {iso_time(item.due_at)}" if item.due_at else "no date",
            )
        )
    lines = [quick_agenda_sentence(items, next_cursor, max_minutes=max_minutes)]
    lines.extend(card_rows("Tasks, soonest due first:", rows, limit=MAX_ROWS)[1:] if rows else [])
    if next_cursor is not None:
        lines.append(f"More: next_cursor {next_cursor}.")
    lines.append(CARD_NOTE)
    return "\n".join(lines)

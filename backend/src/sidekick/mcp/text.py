"""Helpers for the model-facing summary line (block 1) of MCP tool results."""

from collections.abc import Sequence
from datetime import date

MAX_ROWS = 50


def flat(value: str, limit: int | None = None) -> str:
    """Owner text on one line, so it cannot break an id row; `|` is the row separator."""

    collapsed = " ".join(value.split()).replace("|", "/")
    if limit is not None and len(collapsed) > limit:
        return collapsed[: limit - 1] + "…"
    return collapsed


def rows_text(header: str, rows: Sequence[str]) -> str:
    """A header line, then at most MAX_ROWS rows, then `… N till` for the rows not shown."""

    lines = [header, *rows[:MAX_ROWS]]
    if len(rows) > MAX_ROWS:
        lines.append(f"… {len(rows) - MAX_ROWS} till")
    return "\n".join(lines)


CARD_NOTE = "The card shows the full list; do not repeat it."
CONTACT_CARD_NOTE = "The card shows this contact; do not repeat it."
RECORD_CARD_NOTE = "The card shows this record; do not repeat it."
CARD_EXAMPLES = 5
_CARD_TITLE_LIMIT = 80
AGENDA_ROW_LIMIT = 30
AGENDA_UPCOMING_DAYS = 7
AGENDA_NOTE = "Use this list to answer questions about overdue, today's or the next 7 days' tasks."
BOARD_ROW_LIMIT = 8
BOARD_EMPTY_NOTE = "The board card is empty: no tasks match these filters."
EMPTY_WORK_NOTE = "No Work records yet; create a Domain, then Projects or Tasks."


def card_row(item_id: str, title: str, *details: str | None) -> str:
    """Return one `- <id> | <title> | <details>` row for a card list.

    The title and each detail are flattened and cut like `card_text` titles, so the row stays on
    one line. A detail that is None is left out.
    """

    parts = [item_id, flat(title, _CARD_TITLE_LIMIT)]
    parts.extend(flat(detail, _CARD_TITLE_LIMIT) for detail in details if detail)
    return "- " + " | ".join(parts)


def card_rows(head: str, rows: Sequence[str], *, limit: int) -> list[str]:
    """Return `head`, then at most `limit` rows, then `… N more` when rows were left out."""

    lines = [head, *rows[:limit]]
    if len(rows) > limit:
        lines.append(f"… {len(rows) - limit} more")
    return lines


def card_text(head: str, examples: Sequence[tuple[str, str]], *, tail: str | None = None) -> str:
    """Return one short line for a tool whose result is shown as an app card.

    `head` gives the counts, then up to CARD_EXAMPLES `<id> <title>` pairs name the ids a model
    may need next, then an optional `tail` (for example next_cursor), then the card note. Titles
    are flattened and cut, and no descriptions are included.
    """

    parts = [head]
    if examples:
        shown = "; ".join(
            f"{item_id} {flat(title, _CARD_TITLE_LIMIT)}"
            for item_id, title in examples[:CARD_EXAMPLES]
        )
        parts.append(f"Examples: {shown}.")
    if tail is not None:
        parts.append(tail)
    parts.append(CARD_NOTE)
    return " ".join(parts)


MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_STATUS_WORDS = {"todo": "to do"}


def count_phrase(number: int, singular: str, plural: str) -> str:
    """A count with its noun, singular for exactly one, so a spoken line reads right."""

    return f"{number} {singular if number == 1 else plural}"


def spoken_status(status: str) -> str:
    """A status key in words for voice: `in_progress` reads as "in progress", `todo` as "to do"."""

    return _STATUS_WORDS.get(status, status.replace("_", " "))


def spoken_date(day: date, today: date) -> str:
    """A calendar day in words, such as "2 November"; the year is added only for other years."""

    text = f"{day.day} {MONTH_NAMES[day.month - 1]}"
    return text if day.year == today.year else f"{text} {day.year}"

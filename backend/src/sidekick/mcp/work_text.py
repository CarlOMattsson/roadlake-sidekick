"""Card and sentence text for the Work tools: what Claude reads and says aloud."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from sidekick.mcp.results import spoken_names
from sidekick.mcp.text import (
    AGENDA_NOTE,
    AGENDA_ROW_LIMIT,
    AGENDA_UPCOMING_DAYS,
    BOARD_EMPTY_NOTE,
    BOARD_ROW_LIMIT,
    CARD_NOTE,
    EMPTY_WORK_NOTE,
    MAX_ROWS,
    RECORD_CARD_NOTE,
    card_row,
    card_rows,
    count_phrase,
    flat,
    spoken_date,
    spoken_status,
)
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale, LocalizedText, localized
from sidekick.structured.work import RECORD_STEP_LIMIT
from sidekick.work.domain import Step

_MAX_SUMMARY_ROWS = 50


def cell(value: Any) -> str:
    """Return one summary cell: dates as ISO text, no line breaks, no repeated spaces."""

    if isinstance(value, datetime | date):
        value = value.isoformat()
    return " ".join(str(value).split())


def _rows(
    items: Sequence[Mapping[str, Any]],
    *,
    title_key: str = "title",
    indents: Sequence[int] | None = None,
) -> list[str]:
    """Return `- <id> | [kind |] <title> | [v<version> |] [<status> |] [due <due>]` lines.

    Optional fields appear only when the record has them. `indents` gives each row's nesting
    level, two spaces per level, for hierarchies.
    """

    lines: list[str] = []
    for index, item in enumerate(items):
        parts = [cell(item["id"])]
        if item.get("kind") is not None:
            parts.append(cell(item["kind"]))
        parts.append(cell(item[title_key]))
        if item.get("version") is not None:
            parts.append(f"v{item['version']}")
        if item.get("status") is not None:
            parts.append(cell(item["status"]))
        if item.get("due_at") is not None:
            parts.append(f"due {cell(item['due_at'])}")
        level = indents[index] if indents is not None else 0
        lines.append("  " * level + "- " + " | ".join(parts))
    return lines


_MORE_ROWS: LocalizedText = {
    "sv": "… {count} till (använd cursor)",
    "en": "… {count} more (use cursor)",
}


def list_text(
    head: str,
    items: Sequence[Mapping[str, Any]],
    *,
    title_key: str = "title",
    indents: Sequence[int] | None = None,
    locale: AppLocale = DEFAULT_LOCALE,
) -> str:
    """Return the `Found N ...` line followed by at most 50 row lines.

    When rows were left out, the last line says how many, in the app language. The full page is
    still in the JSON block, so block 1 only needs to name the ids a model is likely to use next.
    """

    rows = _rows(items, title_key=title_key, indents=indents)
    lines = [head, *rows[:_MAX_SUMMARY_ROWS]]
    if len(rows) > _MAX_SUMMARY_ROWS:
        lines.append(localized(_MORE_ROWS, locale).format(count=len(rows) - _MAX_SUMMARY_ROWS))
    return "\n".join(lines)


def _more_text(name: str, value: Any) -> str | None:
    """Return `More: <name> <value>.` when a next page exists, so the model can ask for it."""

    return None if value is None else f"More: {name} {value}."


def found_sentence(
    count: int, one: str, many: str, names: Sequence[str], *, lead: str = "Found"
) -> str:
    """Line 1 of a list: `Found 5 tasks: A, B, C and 2 more.`, the count alone when no names."""

    head = f"{lead} {count_phrase(count, one, many)}"
    spoken = spoken_names(names, count)
    return f"{head}: {spoken}." if spoken else f"{head}."


def _on_page(next_cursor: str | None) -> str:
    """Return the page qualifier for a count: with more pages to come, it counts this page only."""

    return "" if next_cursor is None else " on this page (more follow)"


def agenda_sentence(items: Sequence[Mapping[str, Any]], next_cursor: str | None) -> str:
    """Return line 1 of the agenda card: the item count, then overdue and due-today counts."""

    counts = Counter(item["agenda_group"] for item in items)
    noun = count_phrase(len(items), "agenda item", "agenda items") + _on_page(next_cursor)
    return f"{noun}: {counts['overdue']} overdue, {counts['today']} due today."


def _is_task(item: Mapping[str, Any]) -> bool:
    """True for a Task record; a board record without a kind counts as a Task."""

    return item.get("kind", "task") == "task"


def _other_kinds_phrase(columns: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    """The Projects and Domains on a board page in words ("2 projects, 1 domain"), or empty."""

    kinds = Counter(
        str(item["kind"]) for items in columns.values() for item in items if not _is_task(item)
    )
    return ", ".join(count_phrase(count, kind, f"{kind}s") for kind, count in kinds.items())


def board_sentence(
    columns: Mapping[str, Sequence[Mapping[str, Any]]], next_cursor: str | None
) -> str:
    """Return line 1 of the board card: the Task count, then the Tasks per status in words.

    Projects and Domains share the board's columns but are not Tasks, so they are never counted
    in the Task total or in a status; a trailing clause names them apart.
    """

    total = sum(len(items) for items in columns.values())
    if total == 0:
        return "The Work board has no records."
    per_status = ", ".join(
        f"{count} {spoken_status(key)}"
        for key, items in columns.items()
        if (count := sum(1 for item in items if _is_task(item)))
    )
    tasks = sum(1 for items in columns.values() for item in items if _is_task(item))
    noun = count_phrase(tasks, "task", "tasks") + _on_page(next_cursor)
    sentence = f"The Work board has {noun}"
    sentence += f": {per_status}." if per_status else "."
    others = _other_kinds_phrase(columns)
    return f"{sentence} Also listed: {others}." if others else sentence


def work_item_sentence(
    kind: str,
    title: Any,
    status: str,
    day: date | None,
    *,
    label: str,
    today: date,
) -> str:
    """Return line 1 for one Task or Project: title, status and date in words, no ids."""

    when = f"{label} {spoken_date(day, today)}" if day is not None else f"no {label}"
    return f"{kind} {cell(title)}: {spoken_status(status)}, {when}."


_AGENDA_GROUPS = ("overdue", "today", "upcoming", "scheduled_later")


_AGENDA_LIST_GROUPS = ("overdue", "today")


def _agenda_row(item: Mapping[str, Any]) -> str:
    return card_row(
        f"{item['id']} v{item['version']}",
        item["title"],
        f"due {item['due_at']}" if item["due_at"] else None,
        f"project {item['project_title']}" if item["project_title"] else None,
    )


def agenda_card_text(
    items: Sequence[Mapping[str, Any]], next_cursor: str | None, *, now: datetime
) -> str:
    """Return the agenda card's text: a count per group, then the overdue and today rows.

    The model answers "what is overdue, due today or coming up" from these rows. Each row has
    its id and version, title, ISO due time and Project title when it has one. Overdue and today
    come first, then upcoming records due within AGENDA_UPCOMING_DAYS, earliest first. Together
    they are cut at AGENDA_ROW_LIMIT rows. Later upcoming and scheduled records are counted only.
    """

    counts = Counter(item["agenda_group"] for item in items)
    counted = ", ".join(f"{group} {counts[group]}" for group in _AGENDA_GROUPS)
    head = f"Work agenda card shown: {len(items)} items ({counted})."
    window_end = now + timedelta(days=AGENDA_UPCOMING_DAYS)
    listed = [
        item for group in _AGENDA_LIST_GROUPS for item in items if item["agenda_group"] == group
    ]
    # The page's due_at is ISO text here (JSON mode), so it is parsed before comparing. Undated
    # upcoming records (waiting tasks without a due time) are counted only, never parsed.
    upcoming = sorted(
        (
            item
            for item in items
            if item["agenda_group"] == "upcoming"
            and item.get("due_at")
            and datetime.fromisoformat(str(item["due_at"])) <= window_end
        ),
        key=lambda item: datetime.fromisoformat(str(item["due_at"])),
    )
    rows = [_agenda_row(item) for item in [*listed, *upcoming]]
    lines = card_rows(head, rows, limit=AGENDA_ROW_LIMIT)
    more = _more_text("next_cursor", next_cursor)
    if more is not None:
        lines.append(more)
    lines.append(f"{CARD_NOTE} {AGENDA_NOTE}")
    return "\n".join(lines)


_WAITING_REMIND_DAYS = 7


def _waiting_days(since: datetime, now: datetime, zone: tzinfo) -> int:
    """Return the calendar days from `since` to `now` in the owner's zone, never below zero."""

    return max(0, (now.astimezone(zone).date() - since.astimezone(zone).date()).days)


def _waiting_days_phrase(days: int) -> str:
    """Return how long a wait has lasted in words: "for 9 days", "for 1 day", "since today"."""

    if days == 0:
        return "since today"
    return f"for {days} {'day' if days == 1 else 'days'}"


def _waiting_sentence(
    first: Mapping[str, Any],
    days: int | None,
    *,
    total: int,
    next_cursor: str | None,
) -> str:
    """Return line 1 of the waiting view: who the longest wait is on, for how long, and what for.

    `first` is the longest wait (or, with no dated wait, the first record). With one record the
    sentence reads "You are waiting on Anna Berg for 9 days: Förbered demo."; with several it
    counts them and names the longest. It holds no id, version or ISO time (D-072).
    """

    name = first.get("waiting_on_contact_name")
    who = f" on {cell(name)}" if name else ""
    how_long = f" {_waiting_days_phrase(days)}" if days is not None else ""
    title = cell(first["title"])
    if total == 1:
        return f"You are waiting{who}{how_long}: {title}."
    count = f"{total} things{_on_page(next_cursor)}"
    if days is None:
        return f"You are waiting on {count}, among them: {title}."
    return f"You are waiting on {count}, longest{who}{how_long}: {title}."


def waiting_agenda_text(
    items: Sequence[Mapping[str, Any]],
    next_cursor: str | None,
    *,
    now: datetime,
    zone: tzinfo,
) -> str:
    """Return the waiting view's text: the longest wait first, with the days each has waited.

    Line 1 is the sentence voice mode reads and holds no id (see `_waiting_sentence`). Each row
    after it names the id and version, the title, who is waited on (when known) and the days waited
    in the owner's zone; a wait of seven days or more also carries `remind`. Records without a
    waiting date come last, with no day count.
    """

    # The page's waiting_since is ISO text here (JSON mode), so it is parsed before comparing.
    dated = sorted(
        (
            (datetime.fromisoformat(str(item["waiting_since"])), item)
            for item in items
            if item["waiting_since"] is not None
        ),
        key=lambda pair: pair[0],
    )
    undated = [item for item in items if item["waiting_since"] is None]
    rows: list[str] = []
    first_days: int | None = None
    for since, item in dated:
        days = _waiting_days(since, now, zone)
        if first_days is None:
            first_days = days
        unit = "day" if days == 1 else "days"
        details = [item.get("waiting_on_contact_name"), f"waited {days} {unit}"]
        if days >= _WAITING_REMIND_DAYS:
            details.append("remind")
        rows.append(card_row(f"{item['id']} v{item['version']}", item["title"], *details))
    rows.extend(
        card_row(
            f"{item['id']} v{item['version']}", item["title"], item.get("waiting_on_contact_name")
        )
        for item in undated
    )
    lines = card_rows("Waiting, longest first:", rows, limit=AGENDA_ROW_LIMIT)
    more = _more_text("next_cursor", next_cursor)
    if more is not None:
        lines.append(more)
    lines.append(CARD_NOTE)
    if not items:
        return spoken_line("You are not waiting on anyone.", "\n".join(lines))
    first = dated[0][1] if dated else undated[0]
    sentence = _waiting_sentence(first, first_days, total=len(items), next_cursor=next_cursor)
    return spoken_line(sentence, "\n".join(lines))


def board_card_text(
    columns: Mapping[str, Sequence[Mapping[str, Any]]],
    next_cursor: str | None,
    *,
    filtered: bool,
) -> str:
    """Return the board card's text: Task counts per column, then up to BOARD_ROW_LIMIT rows each.

    Each row names the record's id and version, so a follow-up write needs no extra read. Only
    Tasks are counted in the head and in the column headings; Projects and Domains, which share
    the board's columns, are named apart ("also 2 projects") and listed in one section of their
    own. An empty board says no Work records exist yet when no filter was applied, and that no
    records match when one was.
    """

    total = sum(len(items) for items in columns.values())
    task_columns = {
        key: [item for item in items if _is_task(item)] for key, items in columns.items()
    }
    other = [item for items in columns.values() for item in items if not _is_task(item)]
    tasks = sum(len(items) for items in task_columns.values())
    counts = ", ".join(f"{key} {len(items)}" for key, items in task_columns.items() if items)
    if total == 0:
        head = "Work board card shown: 0 records."
    else:
        head = f"Work board card shown: {count_phrase(tasks, 'task', 'tasks')}"
        head += f" ({counts})" if counts else ""
        others = _other_kinds_phrase(columns)
        head += f", also {others}." if others else "."
    lines = [head]
    if total == 0:
        lines.append(BOARD_EMPTY_NOTE if filtered else EMPTY_WORK_NOTE)
    for key, items in task_columns.items():
        if not items:
            continue
        rows = [card_row(f"{item['id']} v{item['version']}", item["title"]) for item in items]
        lines.extend(card_rows(f"{key} {len(items)}:", rows, limit=BOARD_ROW_LIMIT))
    if other:
        rows = [
            card_row(f"{item['id']} v{item['version']}", item["title"], str(item["kind"]))
            for item in other
        ]
        lines.extend(card_rows(f"not tasks {len(other)}:", rows, limit=BOARD_ROW_LIMIT))
    more = _more_text("next_cursor", next_cursor)
    if more is not None:
        lines.append(more)
    lines.append(CARD_NOTE)
    return "\n".join(lines)


_NODE_KIND_NOUNS = {
    "domain": ("domain", "domains"),
    "process": ("process", "processes"),
    "project": ("project", "projects"),
}


def hierarchy_sentence(
    nodes: Sequence[Mapping[str, Any]],
    *,
    task_count: int | None = None,
    step_count: int | None = None,
    next_cursor: str | None = None,
) -> str:
    """Line 1 of the hierarchy: what is there by kind, then up to three names, no ids.

    `task_count` and `step_count` are given only when the tasks are included. With a
    `next_cursor` the sentence says this is one page and how to get the rest.
    """

    kinds = Counter(node["kind"] for node in nodes)
    parts = [
        count_phrase(kinds[kind], one, many)
        for kind, (one, many) in _NODE_KIND_NOUNS.items()
        if kinds[kind]
    ]
    if task_count:
        parts.append(count_phrase(task_count, "task", "tasks"))
    if step_count:
        parts.append(count_phrase(step_count, "step", "steps"))
    if not parts:
        return "Nothing is set up in Work yet."
    joined = f"{', '.join(parts[:-1])} and {parts[-1]}" if len(parts) > 1 else parts[0]
    names = spoken_names([node["title"] for node in nodes], len(nodes))
    sentence = f"Found {joined}: {names}." if names else f"Found {joined}."
    if next_cursor is not None:
        sentence += " More nodes follow; call again with cursor=next_cursor."
    return sentence


def hierarchy_indents(nodes: Sequence[Mapping[str, Any]]) -> list[int]:
    """Return each hierarchy node's nesting level from its parent_id chain.

    A parent that is not on this page does not count, so that node is shown at level 0.
    """

    parents: dict[str, str | None] = {
        cell(node["id"]): (cell(node["parent_id"]) if node.get("parent_id") else None)
        for node in nodes
    }
    indents: list[int] = []
    for node in nodes:
        level = 0
        parent = parents[cell(node["id"])]
        while parent is not None and parent in parents and level < len(nodes):
            level += 1
            parent = parents[parent]
        indents.append(level)
    return indents


def hierarchy_text_items(
    nodes: Sequence[Mapping[str, Any]], tasks: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Flatten nodes, Tasks and Steps into one parent-linked list for the text summary."""

    items: list[dict[str, Any]] = [dict(node) for node in nodes]
    for task in tasks:
        items.append(
            {
                "kind": "task",
                "id": task["id"],
                "parent_id": task["parent_id"],
                "title": task["title"],
                "status": task["status"],
                "version": task["version"],
                "due_at": task["due_at"],
            }
        )
        items.extend(
            {
                "kind": "step",
                "id": step["id"],
                "parent_id": task["id"],
                "title": step["title"],
                "status": step["status"],
            }
            for step in task["steps"]
        )
    return items


def _hierarchy_row(item: Mapping[str, Any], level: int) -> str:
    """One hierarchy row: `<id> v<version> | <title> | <kind> | <status>`, indented by level."""

    version = item.get("version")
    ident = cell(item["id"]) if version is None else f"{cell(item['id'])} v{version}"
    due = item.get("due_at")
    row = card_row(
        ident,
        item["title"],
        item.get("kind"),
        item.get("status"),
        None if due is None else f"due {cell(due)}",
    )
    return "  " * level + row


def hierarchy_card_text(items: Sequence[Mapping[str, Any]], indents: Sequence[int]) -> str:
    """Return the hierarchy card's rows, one per node, Task or Step, then the card note.

    Each row names the id, so a follow-up call needs no extra read; nesting is two spaces per
    level. Rows past MAX_ROWS are counted only, as on the other card lists.
    """

    rows = [_hierarchy_row(item, level) for item, level in zip(items, indents, strict=True)]
    lines = rows[:MAX_ROWS]
    if len(rows) > MAX_ROWS:
        lines.append(f"… {len(rows) - MAX_ROWS} more")
    lines.append(CARD_NOTE)
    return "\n".join(lines)


def record_ref(
    record: Mapping[str, Any],
    *,
    title_key: str = "title",
    parent: tuple[str, Any] | None = None,
) -> str:
    """Return `<id> v<version>: <title>`, plus ` in <label> <id>` when the parent id is set."""

    text = f"{cell(record['id'])} v{record['version']}: {cell(record[title_key])}"
    if parent is not None and parent[1] is not None:
        text += f" in {parent[0]} {cell(parent[1])}"
    return text


def spoken_line(sentence: str, rest: str) -> str:
    """Return `sentence` as line 1, the one sentence voice mode reads, then `rest` on later lines.

    Voice mode reads only line 1, so no id or version goes there. `rest` (usually `record_ref`)
    keeps them on the following lines, where the model still finds them for the next call.
    """

    return f"{sentence}\n{rest}"


_RECORD_DESCRIPTION_LIMIT = 1500


_RECORD_STEP_TITLE_LIMIT = 80


def _record_detail_lines(record: Mapping[str, Any]) -> list[str]:
    """The description and tags of one record, each on one short line, when it has them.

    The description is flattened to one line and cut at _RECORD_DESCRIPTION_LIMIT characters, so
    the model can answer questions about the record without the JSON block.
    """

    lines: list[str] = []
    description = flat(record["description"] or "", _RECORD_DESCRIPTION_LIMIT)
    if description:
        lines.append(f"Description: {description}")
    if record.get("tags"):
        lines.append(f"Tags: {', '.join(record['tags'])}.")
    return lines


def task_detail_lines(record: Mapping[str, Any], steps: Sequence[Step]) -> list[str]:
    """Description, tags, estimate, then the Steps as `N of M done` and one title line each."""

    lines = _record_detail_lines(record)
    if record.get("estimated_minutes") is not None:
        lines.append(f"Estimate: {record['estimated_minutes']} min.")
    if steps:
        shown = steps[:RECORD_STEP_LIMIT]
        done = sum(1 for step in shown if step.status.value == "completed")
        cut = f" (first {RECORD_STEP_LIMIT} shown)" if len(steps) > RECORD_STEP_LIMIT else ""
        lines.append(f"Steps: {done} of {len(shown)} done{cut}.")
        lines.extend(
            f"- {flat(step.title, _RECORD_STEP_TITLE_LIMIT)} | {spoken_status(step.status.value)}"
            for step in shown
        )
    return lines


def project_detail_lines(record: Mapping[str, Any]) -> list[str]:
    """Description, tags and the estimate of the Project's open Tasks, when the totals are read."""

    lines = _record_detail_lines(record)
    totals = record.get("estimate_totals")
    if totals is not None:
        open_tasks = count_phrase(totals["task_count"], "open task", "open tasks")
        lines.append(
            f"Estimate: {totals['estimated_minutes_total']} min over {open_tasks}, "
            f"{totals['unestimated_count']} unestimated."
        )
    return lines


def record_card_text(sentence: str, ref: str, details: Sequence[str]) -> str:
    """Return one Task or Project card's text: the voice sentence, the id line, the details.

    The details are short lines (description, tags, estimate, steps). The note last tells the model
    the card shows this record, so it does not repeat the record as text.
    """

    return spoken_line(sentence, "\n".join([ref, *details, RECORD_CARD_NOTE]))


def task_parent(record: Mapping[str, Any]) -> tuple[str, Any]:
    """Return the project, or else the process, that a Task belongs to, for `record_ref`."""

    if record.get("project_id") is not None:
        return ("project", record["project_id"])
    return ("process", record.get("process_id"))

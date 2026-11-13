"""Model-facing text of the Contact tools: summary lines, the meeting brief, hints."""

# En dashes are intentional human-facing tool copy preserved by contract snapshots.

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import Any

from sidekick.mcp.text import CONTACT_CARD_NOTE, count_phrase, flat

# Last line after a near match of a misheard name: confirm, then alias instead of a duplicate.
CLOSEST_HINT = (
    "Not an exact match; confirm the name with the user. If they confirm, add the heard "
    "spelling with add_contact_alias instead of creating a new Contact."
)
# Last line of list_contacts when a search has no hits: points Claude at the fuzzy search first.
NO_MATCH_HINT = "No match by name or alias; try search (kinds contacts) before creating."


def _profile_suffix(contact: dict[str, Any]) -> str:
    parts = [
        flat(contact[key], limit=200)
        for key in ("relationship", "role", "organization")
        if contact.get(key)
    ]
    return f" | {', '.join(parts)}" if parts else ""


# Model-facing summary lines (block 1) carry the ids the model needs for the next call.
def contact_row(contact: dict[str, Any]) -> str:
    return (
        f"- {contact['id']} | {flat(contact['display_name'])} | v{contact['version']}"
        f"{_profile_suffix(contact)}"
    )


# The spoken sentence (name, no id) comes first; line 2 keeps the id and version for the next call.
def contact_summary(sentence: str, contact: dict[str, Any]) -> str:
    return f"{sentence}\nContact {contact['id']} v{contact['version']}."


_TASK_PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


def _brief_identity(contact: dict[str, Any]) -> str:
    """`Name (role, organization).`; the relationship stands in when neither is set."""
    details = [
        flat(contact[key], limit=200) for key in ("role", "organization") if contact.get(key)
    ]
    if not details and contact.get("relationship"):
        details = [flat(contact["relationship"], limit=200)]
    name = flat(contact["display_name"])
    return f"{name} ({', '.join(details)})." if details else f"{name}."


def _urgency(task: dict[str, Any]) -> tuple[bool, bool, float, int]:
    """Sort key, smallest first: a due follow-up, then the earliest due date, then priority."""
    due = task["due_at"]
    due_ts = datetime.fromisoformat(due).timestamp() if due else 0.0
    return (
        not task["follow_up_due"],
        due is None,
        due_ts,
        _TASK_PRIORITY_RANK.get(task["priority"], len(_TASK_PRIORITY_RANK)),
    )


def _brief_tasks(tasks: list[dict[str, Any]], *, more: bool, other: bool = False) -> str:
    """The open Task count and the most urgent one. `more` means the page is not the whole list.

    `other` says the count leaves out the Tasks that wait on this Contact, which are named apart.
    """
    noun = "other open" if other else "open"
    open_tasks = [task for task in tasks if task["status"] != "completed"]
    scope = f" in the first {len(tasks)}" if more else ""
    if not open_tasks:
        return f"No {noun} tasks{scope}."
    urgent = min(open_tasks, key=_urgency)
    if urgent["follow_up_due"]:
        detail = " (follow-up overdue)"
    elif urgent["due_at"]:
        due = datetime.fromisoformat(urgent["due_at"]).date().isoformat()
        detail = f" (due {due})"
    else:
        detail = ""
    count = count_phrase(len(open_tasks), f"{noun} task", f"{noun} tasks")
    if more:
        count = f"At least {count}"
    return f"{count}, most urgent: {flat(urgent['title'], limit=120)}{detail}."


def _is_waited_on(task: dict[str, Any]) -> bool:
    """An open Task that waits on this Contact and has a start date, so its wait can be counted."""
    return (
        task["status"] != "completed"
        and bool(task.get("waiting_on_contact"))
        and task.get("waiting_since") is not None
    )


def _brief_waiting(
    contact: dict[str, Any], waiting: list[dict[str, Any]], *, now: datetime, zone: tzinfo
) -> str:
    """`You are waiting on <name> for 9 days: <title>.`, for the longest wait; more are counted."""
    longest = min(waiting, key=lambda task: datetime.fromisoformat(task["waiting_since"]))
    since = datetime.fromisoformat(longest["waiting_since"]).astimezone(zone).date()
    days = max(0, (now.astimezone(zone).date() - since).days)
    duration = "since today" if days == 0 else f"for {count_phrase(days, 'day', 'days')}"
    suffix = " (follow-up overdue)" if longest["follow_up_due"] else ""
    sentence = (
        f"You are waiting on {flat(contact['display_name'])} {duration}: "
        f"{flat(longest['title'], limit=120)}{suffix}"
    )
    if len(waiting) > 1:
        sentence += f", and {len(waiting) - 1} more"
    return sentence + "."


def _meeting_brief(
    structured: dict[str, Any], *, now: datetime | None = None, zone: tzinfo | None = None
) -> str:
    """Line 1 of the context text: a few plain sentences with no id, safe to read aloud.

    It uses only the data `get_contact_context` already returns. A Task that waits on this Contact
    comes first, as "You are waiting on <name> for 9 days: <title>.", and is left out of the open
    count after it, so "No open tasks" is never said while one waits. The newest linked Journal
    entry is named by its date only; its title stays in the JSON block as before.
    """
    contact = structured["contact"]
    tasks = structured["tasks"]
    waiting = [task for task in tasks["items"] if _is_waited_on(task)]
    others = [task for task in tasks["items"] if not _is_waited_on(task)]
    more = tasks["next_cursor"] is not None
    sentences = [_brief_identity(contact)]
    if waiting:
        sentences.append(
            _brief_waiting(contact, waiting, now=now or datetime.now(UTC), zone=zone or UTC)
        )
        if any(task["status"] != "completed" for task in others) or more:
            sentences.append(_brief_tasks(others, more=more, other=True))
    else:
        sentences.append(_brief_tasks(others, more=more))
    journal = structured["journal_entries"]
    if journal["readable"] and journal["items"]:
        sentences.append(f"Latest linked journal entry: {journal['items'][0]['journal_date']}.")
    return " ".join(sentences)


def contact_context_text(
    structured: dict[str, Any], *, now: datetime | None = None, zone: tzinfo | None = None
) -> str:
    contact = structured["contact"]
    projects = structured["projects"]["items"]
    tasks = structured["tasks"]["items"]
    lines = [
        _meeting_brief(structured, now=now, zone=zone),
        f"Contact {contact['id']} v{contact['version']}",
    ]
    for label, key in (
        ("Relationship", "relationship"),
        ("Organization", "organization"),
        ("Role", "role"),
    ):
        if contact.get(key):
            lines.append(f"{label}: {flat(contact[key], limit=200)}")
    if contact["context_note"]:
        lines.append(f"Context: {flat(contact['context_note'], limit=500)}")
    lines.extend(f"- alias {alias['id']} | {flat(alias['value'])}" for alias in contact["aliases"])
    lines.append(f"Projects: {len(projects)}")
    lines.extend(
        f"- project {p['id']} | {flat(p['title'])} | {p['status']} | v{p['version']}"
        for p in projects
    )
    lines.append(f"Tasks: {len(tasks)}")
    lines.extend(
        f"- task {t['id']} | {flat(t['title'])} | {t['status']} | v{t['version']}"
        + (" | waiting on contact" if t["waiting_on_contact"] else "")
        for t in tasks
    )
    journal = structured["journal_entries"]
    entries = journal["items"]
    if not journal["readable"]:
        lines.append("Journal entries: not readable with this session's scopes")
    elif not entries:
        lines.append("Journal entries: no linked journal entries")
    else:
        more = " (older links not shown)" if journal["has_more"] else ""
        lines.append(f"Journal entries: {len(entries)} newest{more}")
        lines.extend(
            # Ids and dates here; the titles are in block 2, which the model may read (D-060:
            # Claude reads the owner's own text within its scope).
            f"- journal entry {e['id']} | {e['journal_date']}"
            for e in entries
        )
    lines.append(CONTACT_CARD_NOTE)
    return "\n".join(lines)

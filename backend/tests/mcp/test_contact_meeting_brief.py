"""The meeting brief on line 1 of get_contact_context, built from already-fetched data only.

Pure tests: the text builder takes the structured result dict, so no database is needed. The
brief must read aloud without an id, name the open-task count and the most urgent Task, name the
newest linked journal date, and leave every later line of the existing text unchanged.
"""

import re
from typing import Any

from sidekick.mcp.contact_text import contact_context_text
from sidekick.mcp.text import CONTACT_CARD_NOTE
from tests.support.mcp_contact_brief import (
    CONTACT_ID,
    _structured,
    _task,
)

UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _brief_line(structured: dict[str, Any]) -> str:
    return contact_context_text(structured).split("\n", 1)[0]


def test_brief_names_role_and_organization_and_counts_open_tasks() -> None:
    structured = _structured(
        role="VD",
        organization="Acme AB",
        tasks=[
            _task("Skicka offert", "2026-10-30T09:00:00+01:00"),
            _task("Gammal sak", None, status="completed"),
        ],
    )

    assert _brief_line(structured) == (
        "Sara Lind (VD, Acme AB). 1 open task, most urgent: Skicka offert (due 2026-10-30)."
    )


def test_brief_falls_back_to_relationship_and_says_when_nothing_is_open() -> None:
    structured = _structured(relationship="syster")

    assert _brief_line(structured) == "Sara Lind (syster). No open tasks."


def test_a_due_follow_up_is_the_most_urgent_task_before_any_due_date() -> None:
    structured = _structured(
        tasks=[
            _task("Tidig deadline", "2026-10-20T09:00:00+02:00"),
            _task(
                "Följ upp Sara",
                "2026-11-30T09:00:00+01:00",
                waiting_on_contact=True,
                follow_up_due=True,
            ),
        ],
    )

    brief = _brief_line(structured)
    assert "2 open tasks, most urgent: Följ upp Sara (follow-up overdue)." in brief


def test_earliest_due_date_wins_and_undated_tasks_come_last() -> None:
    structured = _structured(
        tasks=[
            _task("Utan datum", None, priority="urgent"),
            _task("Senare", "2026-11-05T09:00:00+01:00"),
            _task("Först", "2026-10-31T09:00:00+01:00"),
        ],
    )

    assert "most urgent: Först (due 2026-10-31)." in _brief_line(structured)


def test_brief_says_at_least_when_the_task_page_is_not_the_whole_list() -> None:
    structured = _structured(
        tasks=[_task(f"Uppgift {index}", None) for index in range(3)],
        tasks_more=True,
    )

    assert _brief_line(structured) == ("Sara Lind. At least 3 open tasks, most urgent: Uppgift 0.")


def test_brief_names_the_newest_linked_journal_date_only() -> None:
    structured = _structured(
        journal_items=[
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "journal_date": "2026-10-20",
                "title": "Hemlig rubrik",
            },
        ],
    )

    brief = _brief_line(structured)
    assert brief.endswith("Latest linked journal entry: 2026-10-20.")
    assert "Hemlig rubrik" not in brief


def test_brief_leaves_the_journal_out_when_unreadable_or_empty() -> None:
    assert "journal" not in _brief_line(_structured(journal_readable=False))
    assert "journal" not in _brief_line(_structured(journal_items=[]))


def test_brief_is_one_line_with_no_id_and_the_rest_of_the_text_is_unchanged() -> None:
    structured = _structured(
        role="VD",
        organization="Acme AB",
        tasks=[_task("Skicka offert", "2026-10-30T09:00:00+01:00")],
        journal_items=[
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "journal_date": "2026-10-20",
                "title": "T",
            },
        ],
    )

    text = contact_context_text(structured)
    first, rest = text.split("\n", 1)

    assert not UUID_PATTERN.search(first)
    assert " v3" not in first
    assert rest.splitlines()[0] == f"Contact {CONTACT_ID} v3"
    assert "Projects: 0" in rest
    assert "Tasks: 1" in rest
    assert "- task 11111111-1111-4111-8111-111111111111 | Skicka offert | todo | v1" in rest
    assert rest.endswith(CONTACT_CARD_NOTE)

"""Line 1 of `search` reads as a sentence: hits are named, journal text never appears (D-058)."""

from datetime import date
from typing import Literal
from uuid import uuid4

from sidekick.mcp.search import _summary
from sidekick.search.domain import Kind
from sidekick.search.schemas import (
    ContactHitRecord,
    ContactSearchPage,
    JournalHitRecord,
    JournalSearchPage,
    SearchResult,
    TaskHitRecord,
    TaskSearchPage,
)


def _journal(title: str | None, id_type: Literal["entry", "source"] = "entry") -> JournalHitRecord:
    return JournalHitRecord(
        id=uuid4(),
        id_type=id_type,
        journal_date=date(2026, 10, 30),
        matched_in="entry",
        title=title,
    )


def _task(title: str) -> TaskHitRecord:
    return TaskHitRecord(id=uuid4(), title=title, status="todo", version=1)


def test_one_journal_entry_hit_is_named_by_its_title() -> None:
    found = SearchResult(
        searched=[Kind.JOURNAL], journal=JournalSearchPage(hits=[_journal("Flytten")])
    )

    assert _summary(found) == 'Found the journal entry "Flytten".'


def test_one_task_hit_is_named_without_quotes() -> None:
    found = SearchResult(searched=[Kind.TASK], tasks=TaskSearchPage(hits=[_task("Boka tvättid")]))

    assert _summary(found) == "Found the task Boka tvättid."


def test_a_source_without_an_entry_is_a_note_and_has_no_name() -> None:
    found = SearchResult(
        searched=[Kind.JOURNAL],
        journal=JournalSearchPage(hits=[_journal(None, id_type="source")]),
    )

    assert _summary(found) == "Found 1 journal note."


def test_several_kinds_give_counts_and_up_to_three_names_without_ids() -> None:
    found = SearchResult(
        searched=[Kind.TASK, Kind.CONTACT, Kind.JOURNAL],
        tasks=TaskSearchPage(hits=[_task("Ring Elias"), _task("Skicka offert")]),
        contacts=ContactSearchPage(
            hits=[ContactHitRecord(id=uuid4(), display_name="Elias Svensson", version=1)]
        ),
        journal=JournalSearchPage(hits=[_journal("Möte med Elias")]),
    )

    assert _summary(found) == (
        "Found 2 tasks, 1 contact and 1 journal entry: "
        "Ring Elias, Skicka offert, Elias Svensson and 1 more."
    )


def test_no_hits_say_so() -> None:
    assert _summary(SearchResult(searched=[Kind.TASK], tasks=TaskSearchPage(hits=[]))) == (
        "No matches."
    )

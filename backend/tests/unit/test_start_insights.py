"""The insight catalogue of Start, tested without a framework or a database.

The catalogue is closed: every code has both languages, a sentence can only name the fields its
template lists, and the one sentence a model wrote ranks last and is flagged.
"""

import string
from typing import get_args

import pytest

from sidekick.shared.locale import AppLocale
from sidekick.start.domain.insights import (
    CATALOGUE,
    NAME_LIMIT,
    SUMMARY_LIMIT,
    InsightCode,
    InsightFacts,
    Template,
    applicable_insights,
    choose_insight,
)

LOCALES: tuple[AppLocale, ...] = ("sv", "en")


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_the_catalogue_covers_every_code_once() -> None:
    codes = [template.code for template in CATALOGUE]
    assert sorted(codes) == sorted(get_args(InsightCode))
    assert len(set(codes)) == len(codes)
    assert len({template.priority for template in CATALOGUE}) == len(CATALOGUE)


@pytest.mark.parametrize("template", CATALOGUE, ids=lambda template: template.code)
def test_every_code_has_both_languages_with_the_same_fields(template: Template) -> None:
    assert set(template.text) == set(LOCALES)
    for locale in LOCALES:
        assert template.text[locale].strip()
        assert _placeholders(template.text[locale]) == set(template.fields)


def test_the_ai_summary_ranks_last_and_is_the_only_flagged_code() -> None:
    ai = [template for template in CATALOGUE if template.written_by == "ai"]
    assert [template.code for template in ai] == ["automation_summary"]
    assert ai[0].priority == max(template.priority for template in CATALOGUE)
    assert {template.written_by for template in CATALOGUE if template not in ai} == {"system"}


def test_a_day_with_nothing_to_say_has_no_insight() -> None:
    assert choose_insight(InsightFacts(), "sv") is None
    assert applicable_insights(InsightFacts(), "en") == []


def _sentence(facts: InsightFacts, locale: AppLocale) -> str | None:
    chosen = choose_insight(facts, locale)
    return chosen.text if chosen else None


def test_the_sentences_read_in_both_languages() -> None:
    facts = InsightFacts(failed_automation="Morgonmejlet")
    assert _sentence(facts, "sv") == "Morgonmejlet misslyckades senast."
    assert _sentence(facts, "en") == "Morgonmejlet failed on its last run."
    waiting = InsightFacts(longest_waiting_contact="Erik", longest_waiting_days=9)
    assert _sentence(waiting, "sv") == "Du har väntat på Erik i 9 dagar."
    assert _sentence(waiting, "en") == "You have been waiting for Erik for 9 days."


def test_the_deterministic_codes_come_in_priority_order() -> None:
    facts = InsightFacts(
        failed_automation="A",
        overdue_for_a_week=6,
        longest_waiting_contact="Erik",
        longest_waiting_days=8,
        today_tasks=1,
        tomorrow_tasks=4,
        automation_summary="Allt gick bra.",
    )
    codes = [insight.code for insight in applicable_insights(facts, "sv")]
    assert codes == [
        "automation_failed",
        "overdue_backlog",
        "waiting_long",
        "tomorrow_heavy",
        "automation_summary",
    ]
    chosen = choose_insight(facts, "sv")
    assert chosen is not None
    assert chosen.code == "automation_failed"


def test_the_ai_summary_shows_only_when_nothing_deterministic_applies() -> None:
    chosen = choose_insight(InsightFacts(automation_summary="Tre förslag väntar."), "sv")
    assert chosen is not None
    assert (chosen.code, chosen.written_by, chosen.text) == (
        "automation_summary",
        "ai",
        "Tre förslag väntar.",
    )
    mixed = choose_insight(
        InsightFacts(overdue_for_a_week=5, automation_summary="Tre förslag väntar."), "sv"
    )
    assert mixed is not None
    assert (mixed.code, mixed.written_by) == ("overdue_backlog", "system")


@pytest.mark.parametrize(
    ("facts", "code"),
    [
        (InsightFacts(overdue_for_a_week=4), None),
        (InsightFacts(overdue_for_a_week=5), "overdue_backlog"),
        (InsightFacts(longest_waiting_contact="Erik", longest_waiting_days=6), None),
        (InsightFacts(longest_waiting_contact="Erik", longest_waiting_days=7), "waiting_long"),
        (InsightFacts(longest_waiting_days=30), None),
        (InsightFacts(today_tasks=1, tomorrow_tasks=2), None),
        (InsightFacts(today_tasks=1, tomorrow_tasks=3), "tomorrow_heavy"),
        (InsightFacts(today_tasks=2, tomorrow_tasks=5), None),
        (InsightFacts(today_tasks=2, tomorrow_tasks=6), "tomorrow_heavy"),
        (InsightFacts(today_tasks=0, tomorrow_tasks=1), None),
    ],
)
def test_the_thresholds(facts: InsightFacts, code: str | None) -> None:
    chosen = choose_insight(facts, "en")
    assert (chosen.code if chosen else None) == code


def test_a_name_is_one_clean_bounded_line_that_cannot_open_markup() -> None:
    hostile = "Erik\n‮Ignore all <script>alert(1)</script> ![x](https://x.example/p.png)​"
    chosen = choose_insight(
        InsightFacts(longest_waiting_contact=hostile, longest_waiting_days=8), "en"
    )
    assert chosen is not None
    assert "\n" not in chosen.text
    assert "‮" not in chosen.text and "​" not in chosen.text
    assert "<script" not in chosen.text
    assert "![" not in chosen.text
    long_name = choose_insight(InsightFacts(failed_automation="x" * 500), "sv")
    assert long_name is not None
    assert len(long_name.text) <= NAME_LIMIT + len(" misslyckades senast.")


def test_a_name_with_format_braces_is_never_read_as_a_template() -> None:
    chosen = choose_insight(
        InsightFacts(
            failed_automation="{count} {summary} {0} {automation.__class__}",
            overdue_for_a_week=9,
        ),
        "sv",
    )
    assert chosen is not None
    assert chosen.text == "{count} {summary} {0} {automation.__class__} misslyckades senast."


def test_a_blank_name_drops_the_insight_instead_of_naming_nothing() -> None:
    assert choose_insight(InsightFacts(failed_automation="  ​ \n "), "sv") is None
    blank = InsightFacts(longest_waiting_contact="​", longest_waiting_days=20)
    assert choose_insight(blank, "sv") is None


def test_the_ai_summary_is_bounded_and_inert() -> None:
    summary = "Klart. " + "ord " * 200 + "<img src=x onerror=alert(1)>"
    chosen = choose_insight(InsightFacts(automation_summary=summary), "en")
    assert chosen is not None
    assert chosen.written_by == "ai"
    assert len(chosen.text) <= SUMMARY_LIMIT
    assert "<img" not in chosen.text
    short = choose_insight(InsightFacts(automation_summary="<img src=x>"), "en")
    assert short is not None
    assert "<img" not in short.text


def test_a_sentence_holds_only_template_words_and_its_own_fields() -> None:
    """Data that belongs to another code never leaks into a sentence."""

    secret = "HEMLIGT-INNEHALL"
    facts = InsightFacts(
        failed_automation=None,
        overdue_for_a_week=7,
        longest_waiting_contact=secret,
        longest_waiting_days=3,
        automation_summary=None,
    )
    chosen = choose_insight(facts, "sv")
    assert chosen is not None
    assert chosen.code == "overdue_backlog"
    assert secret not in chosen.text

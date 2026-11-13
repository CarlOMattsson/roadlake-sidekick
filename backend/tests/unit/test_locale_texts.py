"""Backend texts that follow the app language, tested without a framework or a database.

Swedish is the default and must read exactly as before; English is the reviewed translation with
its own plural forms.
"""

from uuid import UUID, uuid4

import pytest

from sidekick.mcp.brief import (
    BriefDiary,
    BriefShopping,
    BriefShoppingList,
    BriefTasks,
    _summary_text,  # pyright: ignore[reportPrivateUsage]
)
from sidekick.mcp.work_text import TextRow, list_text
from sidekick.shared.locale import AppLocale, localized


def tasks(overdue: int, today: int, upcoming: int) -> BriefTasks:
    return BriefTasks(
        overdue_count=overdue,
        today_count=today,
        upcoming_7d_count=upcoming,
        items=[],
        truncated=False,
        capped=False,
    )


def shopping(lists: int, items: int) -> BriefShopping:
    records = [
        BriefShoppingList(id=uuid4(), name=f"Lista {index}", version=1, open_item_count=0)
        for index in range(lists)
    ]
    return BriefShopping(open_list_count=lists, open_item_count=items, lists=records)


def test_the_localized_text_is_picked_by_language() -> None:
    pair = {"sv": "Hej", "en": "Hello"}
    assert (localized(pair, "sv"), localized(pair, "en")) == ("Hej", "Hello")


def test_an_empty_day_reads_in_both_languages() -> None:
    parts = {
        "tasks": tasks(0, 0, 0),
        "diary": BriefDiary(entry_count=0, has_summary=False, truncated=False),
        "shopping": shopping(0, 0),
    }

    assert _summary_text(parts) == (
        "Du har inga försenade uppgifter och inga uppgifter idag, och inga uppgifter inom 7 dagar. "
        "Dagboken är tom idag. Inga öppna inköpslistor."
    )
    assert _summary_text(parts, "en") == (
        "You have no overdue tasks, no tasks due today, and no tasks due in the next 7 days. "
        "Your journal is empty today. No open shopping lists."
    )


def test_english_uses_the_singular_for_one_and_the_plural_otherwise() -> None:
    one = {
        "tasks": tasks(1, 1, 1),
        "diary": BriefDiary(entry_count=1, has_summary=True, truncated=False),
        "shopping": shopping(1, 1),
    }
    many = {
        "tasks": tasks(2, 3, 4),
        "diary": BriefDiary(entry_count=2, has_summary=False, truncated=False),
        "shopping": shopping(2, 5),
    }

    assert _summary_text(one, "en") == (
        "You have 1 overdue task, 1 task due today, and 1 task due in the next 7 days. "
        "Your journal has 1 entry today, with a daily summary. "
        "You have 1 open shopping list with 1 item left to buy."
    )
    assert _summary_text(many, "en") == (
        "You have 2 overdue tasks, 3 tasks due today, and 4 tasks due in the next 7 days. "
        "Your journal has 2 entries today, without a daily summary. "
        "You have 2 open shopping lists with 5 items left to buy."
    )
    assert _summary_text(one) == (
        "Du har 1 försenad uppgift och 1 uppgift idag, och 1 uppgift inom 7 dagar. "
        "Dagboken har 1 post idag, med dagssammanfattning. "
        "Du har 1 öppen inköpslista med 1 ej köpt vara."
    )


def test_a_brief_without_any_part_says_so_in_both_languages() -> None:
    assert _summary_text({}) == "Inga delar av dagens läge är tillgängliga med dina behörigheter."
    assert _summary_text({}, "en") == (
        "No part of today\u2019s brief is available with your permissions."
    )


@pytest.mark.parametrize(
    ("locale", "last_line"),
    [("sv", "… 3 till (använd cursor)"), ("en", "… 3 more (use cursor)")],
)
def test_the_left_out_rows_line_follows_the_language(locale: AppLocale, last_line: str) -> None:
    items = [TextRow(UUID(int=index), f"Rad {index}") for index in range(53)]

    lines = list_text("Found 53 things.", items, locale=locale)

    assert lines.splitlines()[-1] == last_line

"""`validate_limit` and `paginate`: the shared page-size check and the page cut."""

import pytest

from sidekick.shared.errors import InvalidInputError, ValidationError
from sidekick.shared.types import paginate, validate_limit


@pytest.mark.parametrize("limit", [1, 50, 100])
def test_a_limit_within_bounds_is_returned_unchanged(limit: int) -> None:
    assert validate_limit(limit, maximum=100) == limit


@pytest.mark.parametrize("limit", [-1, 0, 101])
def test_a_limit_out_of_bounds_is_rejected_as_invalid_input(limit: int) -> None:
    with pytest.raises(InvalidInputError, match=r"^limit must be between 1 and 100$"):
        validate_limit(limit, maximum=100)


def test_the_minimum_the_message_and_the_error_class_can_be_chosen() -> None:
    assert validate_limit(2, minimum=2, maximum=5) == 2
    with pytest.raises(ValidationError, match=r"^page too big$"):
        validate_limit(6, maximum=5, message="page too big", error=ValidationError)
    with pytest.raises(InvalidInputError, match=r"^limit must be between 2 and 5$"):
        validate_limit(1, minimum=2, maximum=5)


def test_a_full_page_with_an_extra_row_yields_the_cursor_of_its_last_row() -> None:
    served: list[int] = []

    def cursor_for(row: int) -> str:
        served.append(row)
        return f"after-{row}"

    assert paginate([1, 2, 3, 4], 3, cursor_for) == ([1, 2, 3], "after-3")
    assert served == [3]


@pytest.mark.parametrize("rows", [[], [1], [1, 2, 3]])
def test_a_page_without_an_extra_row_has_no_cursor_and_builds_none(rows: list[int]) -> None:
    def cursor_for(row: int) -> str:
        raise AssertionError("the cursor is only built when more rows exist")

    assert paginate(rows, 3, cursor_for) == (rows, None)


def test_the_cursor_may_be_any_type_and_does_not_alias_the_input() -> None:
    rows = [10, 20, 30]
    page, next_offset = paginate(rows, 2, lambda _: 7)

    assert (page, next_offset) == ([10, 20], 7)
    page.append(99)
    assert rows == [10, 20, 30]

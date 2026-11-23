"""Building a source body from the line ranges that Claude chose to keep of a raw capture."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sidekick.library.domain.capture import (
    MAX_BODY_CHARS,
    MAX_CAPTURE_CHARS,
    MAX_RANGES,
    LineRange,
    build_body,
    check_capture_text,
    split_lines,
)
from sidekick.library.domain.errors import LibraryRefusedError

TEXT = "one\ntwo\nthree\nfour\nfive\nsix\n"


def refusal_of(text: str, *ranges: tuple[int, int]) -> str:
    with pytest.raises(LibraryRefusedError) as refused:
        build_body(text, [LineRange(first, last) for first, last in ranges])
    return refused.value.refusal


class TestSplitLines:
    def test_lines_are_numbered_from_the_text_without_the_final_break(self) -> None:
        assert split_lines("a\nb\n") == ("a", "b")
        assert split_lines("a\nb") == ("a", "b")
        assert split_lines("a\n\n") == ("a", "")
        assert split_lines("") == ()

    def test_every_kind_of_line_break_counts_once(self) -> None:
        assert split_lines("a\r\nb\rc\nd") == ("a", "b", "c", "d")

    @given(text=st.text(max_size=200))
    def test_the_count_matches_the_number_of_breaks(self, text: str) -> None:
        lines = split_lines(text)
        unified = text.replace("\r\n", "\n").replace("\r", "\n")
        assert len(lines) == unified.count("\n") + (
            1 if unified and not unified.endswith("\n") else 0
        )


class TestBuildBody:
    def test_one_range_keeps_its_lines_both_ends_included(self) -> None:
        assert build_body(TEXT, [LineRange(2, 4)]) == "two\nthree\nfour"
        assert build_body(TEXT, [LineRange(1, 1)]) == "one"
        assert build_body(TEXT, [LineRange(1, 6)]) == TEXT.rstrip("\n")

    def test_a_gap_between_ranges_becomes_a_blank_line_and_touching_ranges_join(self) -> None:
        assert build_body(TEXT, [LineRange(1, 2), LineRange(4, 4), LineRange(5, 6)]) == (
            "one\ntwo\n\nfour\nfive\nsix"
        )

    def test_ranges_may_come_in_any_order_and_are_kept_in_text_order(self) -> None:
        assert build_body(TEXT, [LineRange(5, 5), LineRange(1, 1)]) == "one\n\nfive"

    @pytest.mark.parametrize("last", [7, 8, 1000])
    def test_a_range_past_the_end_of_the_text_is_refused(self, last: int) -> None:
        assert refusal_of(TEXT, (1, last)) == "range_out_of_text"

    def test_the_last_line_is_inside_the_text_and_the_next_one_is_not(self) -> None:
        assert build_body(TEXT, [LineRange(6, 6)]) == "six"
        assert refusal_of(TEXT, (7, 7)) == "range_out_of_text"

    def test_ranges_that_share_a_line_are_refused(self) -> None:
        assert refusal_of(TEXT, (1, 3), (3, 4)) == "range_overlap"
        assert refusal_of(TEXT, (2, 2), (2, 2)) == "range_overlap"
        assert refusal_of(TEXT, (1, 6), (2, 3)) == "range_overlap"

    @pytest.mark.parametrize("bad", [(0, 1), (-1, 2), (3, 2)])
    def test_a_range_that_is_not_a_range_cannot_be_built(self, bad: tuple[int, int]) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            LineRange(*bad)
        assert refused.value.refusal == "range_invalid"

    def test_a_boolean_or_a_float_is_not_a_line_number(self) -> None:
        for first, last in ((True, 2), (1, 2.0)):
            with pytest.raises(LibraryRefusedError):
                LineRange(first, last)  # type: ignore[arg-type]

    def test_no_ranges_and_too_many_are_refused(self) -> None:
        assert refusal_of(TEXT) == "range_missing"
        many = [LineRange(number, number) for number in range(1, MAX_RANGES + 2)]
        with pytest.raises(LibraryRefusedError) as refused:
            build_body("\n".join(["x"] * (MAX_RANGES + 2)), many)
        assert refused.value.refusal == "range_count_invalid"

    def test_a_body_of_blank_lines_is_refused(self) -> None:
        assert refusal_of("a\n\n \nb", (2, 3)) == "body_empty"

    def test_a_body_over_the_cap_is_refused_not_cut(self) -> None:
        text = "\n".join(["x" * 1000] * 61)

        assert refusal_of(text, (1, 61)) == "body_too_long"
        assert len(build_body(text, [LineRange(1, 59)])) <= MAX_BODY_CHARS

    def test_a_refusal_never_quotes_the_text(self) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            build_body("secret passage\n", [LineRange(2, 2)])
        assert "secret" not in str(refused.value)

    @given(
        data=st.data(),
        lines=st.lists(
            st.text(alphabet="abc xyz", min_size=1, max_size=20), min_size=1, max_size=30
        ),
    )
    def test_the_body_is_exactly_the_chosen_lines_of_the_text(
        self, data: st.DataObject, lines: list[str]
    ) -> None:
        text = "\n".join(lines)
        total = len(lines)
        first = data.draw(st.integers(min_value=1, max_value=total))
        last = data.draw(st.integers(min_value=first, max_value=total))
        if not any(line.strip() for line in lines[first - 1 : last]):
            return

        assert build_body(text, [LineRange(first, last)]) == "\n".join(lines[first - 1 : last])


class TestCaptureText:
    def test_text_up_to_the_cap_is_accepted(self) -> None:
        assert check_capture_text("a" * MAX_CAPTURE_CHARS) == "a" * MAX_CAPTURE_CHARS

    @pytest.mark.parametrize(
        ("text", "refusal"),
        [
            ("", "capture_empty"),
            (" \n\t", "capture_empty"),
            ("a" * (MAX_CAPTURE_CHARS + 1), "capture_too_long"),
        ],
    )
    def test_an_empty_or_oversized_capture_is_refused(self, text: str, refusal: str) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            check_capture_text(text)
        assert refused.value.refusal == refusal

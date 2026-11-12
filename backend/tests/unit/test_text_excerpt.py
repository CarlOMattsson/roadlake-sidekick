"""The description excerpt used by list reads: word boundary, code points, exact limit."""

import pytest

from sidekick.shared.text_excerpt import EXCERPT_LIMIT, excerpt


def test_blank_or_missing_text_has_no_excerpt() -> None:
    assert excerpt(None) == (None, False)
    assert excerpt("") == (None, False)
    assert excerpt(" \n\t ") == (None, False)


def test_short_text_is_returned_whole_on_one_line() -> None:
    assert excerpt("Buy  milk\nand eggs") == ("Buy milk and eggs", False)


def test_text_of_exactly_the_limit_is_not_truncated() -> None:
    text = "a" * EXCERPT_LIMIT
    assert excerpt(text) == (text, False)


def test_text_one_over_the_limit_is_truncated_within_the_limit() -> None:
    text = "a" * (EXCERPT_LIMIT + 1)
    shortened, truncated = excerpt(text)
    assert truncated is True
    assert shortened == "a" * (EXCERPT_LIMIT - 1) + "…"
    assert len(shortened or "") == EXCERPT_LIMIT


def test_long_text_is_cut_on_a_word_boundary() -> None:
    text = " ".join(["word"] * 100)
    shortened, truncated = excerpt(text)
    assert truncated is True
    assert shortened is not None
    assert len(shortened) <= EXCERPT_LIMIT
    assert shortened.endswith("word…")
    assert set(shortened[:-1].split(" ")) == {"word"}


def test_cut_falling_exactly_before_a_space_keeps_the_whole_word() -> None:
    text = "a" * (EXCERPT_LIMIT - 1) + " bbbb"
    assert excerpt(text) == ("a" * (EXCERPT_LIMIT - 1) + "…", True)


def test_a_word_longer_than_the_limit_is_cut_mid_word() -> None:
    shortened, truncated = excerpt("x" * 500)
    assert truncated is True
    assert shortened == "x" * (EXCERPT_LIMIT - 1) + "…"


def test_multibyte_text_is_counted_in_characters_and_never_split() -> None:
    text = " ".join(["åäö€😀"] * 60)
    shortened, truncated = excerpt(text)
    assert truncated is True
    assert shortened is not None
    assert len(shortened) <= EXCERPT_LIMIT
    assert shortened.endswith("åäö€😀…")
    shortened.encode("utf-8")  # every character is whole
    exact = "😀" * EXCERPT_LIMIT
    assert excerpt(exact) == (exact, False)
    assert excerpt(exact + "😀")[1] is True


def test_limit_too_small_for_an_ellipsis_is_refused() -> None:
    with pytest.raises(ValueError):
        excerpt("text", limit=1)

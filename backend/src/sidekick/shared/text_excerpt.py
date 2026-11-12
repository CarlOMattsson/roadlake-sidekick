"""A short, one-line excerpt of a longer text, for list reads that must stay small."""

from __future__ import annotations

EXCERPT_LIMIT = 160
_ELLIPSIS = "…"


def excerpt(text: str | None, limit: int = EXCERPT_LIMIT) -> tuple[str | None, bool]:
    """Return `(excerpt, truncated)` for a text.

    Whitespace runs (including line breaks) collapse to one space, so the excerpt is one line.
    A text that fits in `limit` characters is returned whole and `truncated` is false; blank or
    missing text gives `(None, False)`. A longer text is cut on a word boundary and ends with
    an ellipsis, and the whole result is at most `limit` characters. A single word longer than
    the limit is cut mid-word, since there is no boundary to cut at. Length counts Unicode
    code points, never bytes, so multibyte text is never split inside a character.
    """

    if limit < 2:
        raise ValueError("limit must leave room for at least one character and the ellipsis")
    if text is None:
        return None, False
    words = " ".join(text.split())
    if not words:
        return None, False
    if len(words) <= limit:
        return words, False
    head = words[: limit - 1]
    if words[limit - 1] != " ":
        boundary = head.rfind(" ")
        if boundary > 0:
            head = head[:boundary]
    return head.rstrip() + _ELLIPSIS, True

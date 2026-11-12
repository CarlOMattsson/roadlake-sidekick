"""The byte budget of one `/companion/v1/` answer, shared with the Android app.

The paired app refuses a response above its own cap (`MAX_RESPONSE_BYTES` in
`frontend/android/.../companion/HttpTransport.kt`) with `response_too_large`, so a page the server
sent but the app could not read would be a dead screen. The server therefore never sends more than
[`MAX_RESPONSE_BYTES`], and the app's cap is at least twice as large (headroom for the content
that is not counted here). `tests/unit/test_companion_response_budget.py` reads both numbers and
fails when the app's cap falls below the server's.

How an answer is kept within the budget:

- A journal page (`journal/days/...`, `journal/entries`) is fetched again with half the `limit`
  until it fits; `next_cursor` then continues where the shorter page ended. The answer carries
  `Sidekick-Response-Trimmed: page`.
- A single entry that is still too large is answered without its content (summary, key points,
  link labels), the same shape as `include_content=false`. The answer carries
  `Sidekick-Response-Trimmed: content` (both words, comma separated, when both happened).
- Any other answer above the budget is a server error (`internal_error`), never an oversize body:
  `CompanionRoute` checks every response (`ensure_within_budget`).

Nothing here reads a title, a text or an id: only sizes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sidekick.shared.errors.core import InternalFaultError

# 1 MiB of rendered JSON. The app's cap is 2 MiB.
MAX_RESPONSE_BYTES = 1_048_576
TRIMMED_HEADER = "Sidekick-Response-Trimmed"


class ResponseTooLarge(InternalFaultError):
    """A companion answer above [`MAX_RESPONSE_BYTES`]; an unexpected error, not a client error."""


def rendered_size(content: Any) -> int:
    """The bytes `JSONResponse(content)` puts on the wire (compact, UTF-8, no ASCII escaping)."""

    return len(
        json.dumps(
            content, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
        ).encode("utf-8")
    )


def ensure_within_budget(body: bytes) -> None:
    if len(body) > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge


def fit_to_budget(
    fetch: Callable[[int, bool], dict[str, Any]], *, limit: int, include_content: bool
) -> tuple[dict[str, Any], str | None]:
    """The page `fetch(limit, include_content)` within the budget, and what was trimmed.

    The trimmed value is `None`, `"page"`, `"content"` or `"page,content"`. A page that cannot be
    brought under the budget even without content is returned as is for the final check to refuse.
    """

    trimmed: list[str] = []
    page_limit = limit
    content = include_content
    while True:
        result = fetch(page_limit, content)
        if rendered_size(result) <= MAX_RESPONSE_BYTES:
            if page_limit < limit and "page" not in trimmed:
                trimmed.insert(0, "page")
            return result, ",".join(trimmed) or None
        if page_limit > 1:
            page_limit = max(1, page_limit // 2)
        elif content:
            content = False
            page_limit = limit
            trimmed.append("content")
        else:
            return result, ",".join(trimmed) or None

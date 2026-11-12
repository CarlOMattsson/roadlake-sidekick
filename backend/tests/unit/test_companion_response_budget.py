"""The companion response budget: the server's number and the Android app's cap agree, and an
answer is kept within the server's number (no database)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.responses import JSONResponse

from sidekick.companion import response_budget
from sidekick.companion.response_budget import (
    MAX_RESPONSE_BYTES,
    ResponseTooLarge,
    ensure_within_budget,
    fit_to_budget,
    rendered_size,
)

REPO = Path(__file__).resolve().parents[3]
TRANSPORT = (
    REPO / "frontend/android/app/src/main/kotlin/com/roadlake/sidekick/companion/HttpTransport.kt"
)
CONSTANT = re.compile(r"^const val MAX_RESPONSE_BYTES\s*=\s*([0-9_]+)\s*$", re.MULTILINE)


def android_cap() -> int:
    match = CONSTANT.search(TRANSPORT.read_text(encoding="utf-8"))
    assert match, "HttpTransport.kt must declare `const val MAX_RESPONSE_BYTES = <number>`"
    return int(match.group(1).replace("_", ""))


def test_the_apps_cap_is_at_least_twice_the_servers_budget() -> None:
    assert android_cap() >= 2 * MAX_RESPONSE_BYTES, (
        "The app refuses answers above its cap, so the server's budget must stay well below it"
    )


def test_the_default_transport_uses_that_constant() -> None:
    source = TRANSPORT.read_text(encoding="utf-8")
    assert "private val maxResponseBytes: Int = MAX_RESPONSE_BYTES," in source


def test_rendered_size_is_the_size_of_the_json_response_body() -> None:
    content = {"text": 'åäö 😀 "quoted"', "list": [1, 2.5, None, True], "empty": {}}
    assert rendered_size(content) == len(JSONResponse(content).body)


def page(limit: int, content: bool, chars: int) -> dict[str, Any]:
    return {"entries": [{"text": "x" * chars if content else None} for _ in range(limit)]}


def test_a_page_within_the_budget_is_returned_untouched() -> None:
    result, trimmed = fit_to_budget(lambda n, c: page(n, c, 10), limit=10, include_content=True)
    assert (len(result["entries"]), trimmed) == (10, None)


def test_a_page_over_the_budget_is_halved_until_it_fits_and_marked() -> None:
    chars = MAX_RESPONSE_BYTES // 3
    calls: list[int] = []

    def fetch(n: int, c: bool) -> dict[str, Any]:
        calls.append(n)
        return page(n, c, chars)

    result, trimmed = fit_to_budget(fetch, limit=50, include_content=True)
    assert calls == [50, 25, 12, 6, 3, 1]
    assert (len(result["entries"]), trimmed) == (1, "page")


def test_one_entry_that_is_too_large_loses_its_content_and_is_marked() -> None:
    result, trimmed = fit_to_budget(
        lambda n, c: page(n, c, MAX_RESPONSE_BYTES + 1), limit=1, include_content=True
    )
    assert trimmed == "content"
    assert result == {"entries": [{"text": None}]}


def test_content_dropped_after_halving_restores_the_page_size() -> None:
    result, trimmed = fit_to_budget(
        lambda n, c: page(n, c, MAX_RESPONSE_BYTES + 1), limit=8, include_content=True
    )
    assert trimmed == "content"
    assert len(result["entries"]) == 8


def test_without_content_to_drop_the_answer_is_returned_for_the_final_check() -> None:
    huge = {"x": "y" * (MAX_RESPONSE_BYTES + 1)}
    result, trimmed = fit_to_budget(lambda n, c: huge, limit=1, include_content=False)
    assert (result, trimmed) == (huge, None)


def test_the_final_check_refuses_an_oversize_body_only() -> None:
    ensure_within_budget(b"x" * MAX_RESPONSE_BYTES)
    with pytest.raises(ResponseTooLarge):
        ensure_within_budget(b"x" * (MAX_RESPONSE_BYTES + 1))


def test_the_module_documents_the_header_it_sets() -> None:
    assert response_budget.TRIMMED_HEADER in (response_budget.__doc__ or "")

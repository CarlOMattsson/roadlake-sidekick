"""Hindsight adapter bank operations, against httpx.MockTransport (no network).

Pins the paths and shapes the lost-volume check and the orphan-bank sweep depend on, and that no
failure carries a provider body.
"""

from __future__ import annotations

import httpx
import pytest

from sidekick.memory.ports import MemoryProviderError
from tests.support.memory_hindsight import (
    OTHER_OWNER,
    OWNER,
    TOKEN,
    Script,
    _bank,  # pyright: ignore[reportPrivateUsage]
    _provider,  # pyright: ignore[reportPrivateUsage]
    _response,  # pyright: ignore[reportPrivateUsage]
)


def test_bank_id_for_is_the_bank_the_adapter_uses() -> None:
    provider = _provider(Script(_response(200, {})))

    assert provider.bank_id_for(OWNER) == _bank(OWNER)
    assert provider.bank_id_for(OWNER) != provider.bank_id_for(OTHER_OWNER)


def test_list_banks_reads_only_bank_ids() -> None:
    script = Script(
        _response(
            200,
            {
                "banks": [
                    {"bank_id": _bank(OWNER), "name": "private", "mission": "secret text"},
                    {"bank_id": "not a safe id/../x"},
                    {"name": "no id"},
                    {"bank_id": "legacy-bank"},
                ],
                "total": 4,
                "limit": 200,
                "offset": 0,
            },
        )
    )

    banks = _provider(script).list_banks()

    assert banks == (_bank(OWNER), "legacy-bank")
    request = script.requests[0]
    assert (request.method, request.url.path) == ("GET", "/v1/default/banks")
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


def test_list_banks_reads_every_page_until_the_total() -> None:
    first = [{"bank_id": f"bank-{i}"} for i in range(3)]
    second = [{"bank_id": "bank-3"}, {"bank_id": "bank-1"}]
    script = Script(
        _response(200, {"banks": first, "total": 5}),
        _response(200, {"banks": second, "total": 5}),
    )

    banks = _provider(script).list_banks()

    assert banks == ("bank-0", "bank-1", "bank-2", "bank-3")
    queries = [request.url.params for request in script.requests]
    assert [(q["limit"], q["offset"]) for q in queries] == [("200", "0"), ("200", "3")]


def test_list_banks_never_returns_a_partial_list() -> None:
    """A server that stops short of its own total must not be read as a complete list."""
    script = Script(
        _response(200, {"banks": [{"bank_id": "bank-0"}], "total": 3}),
        _response(200, {"banks": [], "total": 3}),
    )

    with pytest.raises(MemoryProviderError) as raised:
        _provider(script).list_banks()

    assert raised.value.category == "invalid_response"


@pytest.mark.parametrize(
    "body",
    [{}, {"banks": "x", "total": 1}, {"banks": ["x"], "total": 1}, {"banks": []}, []],
)
def test_list_banks_rejects_a_malformed_response(body: object) -> None:
    with pytest.raises(MemoryProviderError) as raised:
        _provider(Script(_response(200, body))).list_banks()

    assert raised.value.category == "invalid_response"


def test_list_banks_failures_carry_only_a_category() -> None:
    with pytest.raises(MemoryProviderError) as raised:
        _provider(Script(_response(401, text="SECRET provider body")), max_retries=0).list_banks()

    assert raised.value.category == "unauthorized"
    assert "SECRET" not in str(raised.value)


@pytest.mark.parametrize("status", [200, 204, 404])
def test_delete_bank_accepts_success_and_an_already_missing_bank(status: int) -> None:
    script = Script(_response(status))

    _provider(script).delete_bank(bank_id=_bank(OWNER))

    request = script.requests[0]
    assert (request.method, request.url.path) == ("DELETE", f"/v1/default/banks/{_bank(OWNER)}")


@pytest.mark.parametrize(
    "bad", ["legacy-bank", "v1_short", "v1_" + "A" * 64, "../" + _bank(OWNER), ""]
)
def test_delete_bank_rejects_any_id_outside_sidekicks_format_before_any_request(bad: str) -> None:
    script = Script(_response(200))

    with pytest.raises(ValueError):
        _provider(script).delete_bank(bank_id=bad)

    assert script.requests == []


def test_delete_bank_maps_failures_to_categories() -> None:
    with pytest.raises(MemoryProviderError) as raised:
        _provider(Script(_response(500, text="SECRET")), max_retries=0).delete_bank(
            bank_id=_bank(OWNER)
        )

    assert raised.value.category == "unavailable"
    assert "SECRET" not in str(raised.value)


def test_document_count_reads_the_total_from_the_derived_bank() -> None:
    script = Script(_response(200, {"items": [{"id": "x"}], "total": 7, "limit": 1}))

    assert _provider(script).document_count(owner_id=OWNER) == 7

    request = script.requests[0]
    assert request.method == "GET"
    assert request.url.path == f"/v1/default/banks/{_bank(OWNER)}/documents"
    assert request.url.query == b"limit=1"
    assert str(OWNER) not in str(request.url)


def test_document_count_404_is_an_error_never_a_zero() -> None:
    """A 404 may be a wrong base path or proxy route, not an empty bank: it must not read as 0."""
    with pytest.raises(MemoryProviderError) as raised:
        _provider(Script(_response(404)), max_retries=0).document_count(owner_id=OWNER)

    assert raised.value.category == "unavailable"


@pytest.mark.parametrize("body", [{}, {"total": "3"}, {"total": -1}, {"total": True}])
def test_document_count_rejects_a_malformed_total(body: dict[str, object]) -> None:
    with pytest.raises(MemoryProviderError) as raised:
        _provider(Script(_response(200, body))).document_count(owner_id=OWNER)

    assert raised.value.category == "invalid_response"


def test_document_count_network_failure_is_an_error_not_zero() -> None:
    with pytest.raises(MemoryProviderError) as raised:
        _provider(Script(httpx.ConnectError("down")), max_retries=0).document_count(owner_id=OWNER)

    assert raised.value.category == "unavailable"

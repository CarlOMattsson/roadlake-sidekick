"""Hindsight adapter for the memory port, against httpx.MockTransport (no network).

These tests pin exact request bodies and paths and assert that failures carry only a category.
"""

from __future__ import annotations

import gzip
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator

import httpx
import pytest

from sidekick.memory.adapters.hindsight import HindsightMemoryProvider
from sidekick.memory.ports import (
    MemoryFact,
    MemoryFailureCategory,
    MemoryProvider,
    MemoryProviderError,
    OperationResult,
    RetainItem,
)
from tests.support.memory_hindsight import (
    BASE_URL,
    KEY,
    OTHER_OWNER,
    OWNER,
    TOKEN,
    Script,
    _bank,
    _provider,
    _response,
)
from tests.support.polling import poll_until

DOC = "v1_" + "a" * 64
OTHER_DOC = "v1_" + "b" * 64
ITEM = RetainItem(
    document_id=DOC,
    content="Dagbok 2026-10-27\nJag sprang en mil i parken.",
    timestamp="2026-10-27T08:00:00+00:00",
    entities=("Anna",),
    tags=("k:journal_entry",),
)


def _as_port(provider: MemoryProvider) -> MemoryProvider:
    return provider


def test_hindsight_adapter_satisfies_the_memory_port() -> None:
    assert _as_port(_provider(Script(_response(200, {})))) is not None


def test_the_default_client_ignores_proxy_environment_and_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bearer token must not travel through an environment proxy or a redirect."""

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    provider = HindsightMemoryProvider(base_url=BASE_URL, api_token=TOKEN, id_derivation_key=KEY)
    try:
        assert provider._client.trust_env is False
        assert provider._client.follow_redirects is False
    finally:
        provider._client.close()


def test_retain_sends_exact_replace_body_to_the_derived_bank() -> None:
    handler = Script(_response(202, {"operation_id": "op-1"}))

    operation_id = _provider(handler).retain_batch(owner_id=OWNER, items=[ITEM])

    assert operation_id == "op-1"
    assert len(handler.requests) == 1
    request = handler.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{BASE_URL}/v1/default/banks/{_bank()}/memories"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "async": True,
        "items": [
            {
                "content": "Dagbok 2026-10-27\nJag sprang en mil i parken.",
                "document_id": DOC,
                "update_mode": "replace",
                "context": "sidekick_memory",
                "metadata": {"source": "sidekick_memory"},
                "timestamp": "2026-10-27T08:00:00+00:00",
                "entities": [{"text": "Anna"}],
                "tags": ["k:journal_entry"],
            }
        ],
    }


def test_retain_never_sends_the_raw_owner_id() -> None:
    handler = Script(_response(202, {"operation_id": "op-1"}))

    _provider(handler).retain_batch(owner_id=OWNER, items=[ITEM])

    request = handler.requests[0]
    assert str(OWNER) not in str(request.url)
    assert str(OWNER).encode("utf-8") not in request.content


def test_bank_is_derived_per_owner() -> None:
    handler = Script(_response(202, {"operation_id": "op-1"}))
    provider = _provider(handler)

    provider.retain_batch(owner_id=OWNER, items=[ITEM])
    provider.retain_batch(owner_id=OTHER_OWNER, items=[ITEM])

    first, second = (str(request.url) for request in handler.requests)
    assert _bank(OWNER) in first
    assert _bank(OTHER_OWNER) in second
    assert _bank(OWNER) != _bank(OTHER_OWNER)


def test_retain_with_unset_timestamp_and_no_entities_sends_the_literal_values() -> None:
    handler = Script(_response(202, {"operation_id": "op-2"}))
    contact = RetainItem(
        document_id=OTHER_DOC,
        content="Kontakt: Anna",
        timestamp="unset",
        entities=(),
        tags=("k:contact",),
    )

    _provider(handler).retain_batch(owner_id=OWNER, items=[contact])

    item = json.loads(handler.requests[0].content)["items"][0]
    assert item["timestamp"] == "unset"
    assert item["entities"] == []
    assert item["tags"] == ["k:contact"]


@pytest.mark.parametrize("count", [0, 21])
def test_retain_batch_bounds_are_checked_before_any_request(count: int) -> None:
    handler = Script(_response(202, {"operation_id": "op-1"}))
    items = [
        RetainItem(
            document_id=f"v1_{index:064x}",
            content="rad",
            timestamp="unset",
            entities=(),
            tags=(),
        )
        for index in range(count)
    ]

    with pytest.raises(ValueError, match="batch size"):
        _provider(handler).retain_batch(owner_id=OWNER, items=items)
    assert handler.requests == []


def test_retain_batch_rejects_a_repeated_document_before_any_request() -> None:
    handler = Script(_response(202, {"operation_id": "op-1"}))

    with pytest.raises(ValueError, match="repeats"):
        _provider(handler).retain_batch(owner_id=OWNER, items=[ITEM, ITEM])
    assert handler.requests == []


@pytest.mark.parametrize("body", [{}, {"operation_id": "../escape"}, {"operation_id": 7}])
def test_retain_rejects_a_response_without_a_safe_operation_id(body: dict[str, object]) -> None:
    handler = Script(_response(202, body))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler).retain_batch(owner_id=OWNER, items=[ITEM])

    assert error.value.category == "invalid_response"


def test_recall_sends_exact_body_and_returns_only_facts_with_a_source() -> None:
    handler = Script(
        _response(
            200,
            {
                "results": [
                    {
                        "id": "fact-1",
                        "text": "Jag sprang en mil.",
                        "document_id": DOC,
                        "occurred_start": "2026-10-27T00:00:00Z",
                        "occurred_end": None,
                    },
                    {"id": "fact-2", "text": "Utan giltig källa", "document_id": "bad doc!"},
                    {"id": "fact-3", "text": "Saknar källa helt"},
                ]
            },
        )
    )

    facts = _provider(handler).recall(owner_id=OWNER, query="sprang", max_tokens=512)

    request = handler.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{BASE_URL}/v1/default/banks/{_bank()}/memories/recall"
    assert json.loads(request.content) == {
        "query": "sprang",
        "budget": "low",
        "max_tokens": 512,
        "include": {"chunks": None, "source_facts": None},
    }
    assert facts == (
        MemoryFact(
            id="fact-1",
            text="Jag sprang en mil.",
            document_id=DOC,
            occurred_start="2026-10-27T00:00:00Z",
            occurred_end=None,
        ),
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"results": "inte en lista"},
        {"results": ["inte ett objekt"]},
        {"results": [{"id": "f", "text": "   ", "document_id": DOC}]},
        {"results": [{"id": "f", "text": 3, "document_id": DOC}]},
    ],
)
def test_recall_rejects_a_malformed_response(body: dict[str, object]) -> None:
    handler = Script(_response(200, body))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler).recall(owner_id=OWNER, query="sprang", max_tokens=64)

    assert error.value.category == "invalid_response"


@pytest.mark.parametrize(
    ("query", "max_tokens"),
    [("", 64), ("x" * 301, 64), ("sprang", 0), ("sprang", 2049)],
)
def test_recall_bounds_are_checked_before_any_request(query: str, max_tokens: int) -> None:
    handler = Script(_response(200, {"results": []}))

    with pytest.raises(ValueError):
        _provider(handler).recall(owner_id=OWNER, query=query, max_tokens=max_tokens)
    assert handler.requests == []


@pytest.mark.parametrize("status", [200, 204, 404])
def test_delete_accepts_success_and_an_already_missing_document(status: int) -> None:
    handler = Script(_response(status))

    _provider(handler).delete_document(owner_id=OWNER, document_id=DOC)

    request = handler.requests[0]
    assert request.method == "DELETE"
    assert str(request.url) == f"{BASE_URL}/v1/default/banks/{_bank()}/documents/{DOC}"
    assert request.content == b""


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "unauthorized"),
        (403, "unauthorized"),
        (400, "rejected"),
        (422, "rejected"),
        (500, "unavailable"),
    ],
)
def test_delete_maps_failures_to_categories_without_retrying_them(
    status: int, category: MemoryFailureCategory
) -> None:
    handler = Script(_response(status, text="SECRET-DOCUMENT-TEXT"))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler).delete_document(owner_id=OWNER, document_id=DOC)

    assert error.value.category == category
    assert len(handler.requests) == 1


def test_delete_rejects_an_unsafe_document_id_before_any_request() -> None:
    handler = Script(_response(200))

    with pytest.raises(ValueError):
        _provider(handler).delete_document(owner_id=OWNER, document_id="../documents")
    assert handler.requests == []


@pytest.mark.parametrize(
    ("body", "state", "category"),
    [
        ({"status": "completed"}, "retained", None),
        ({"status": "Succeeded"}, "retained", None),
        ({"state": "done"}, "retained", None),
        ({"status": "failed"}, "failed", "operation_failed"),
        ({"status": "cancelled"}, "failed", "operation_failed"),
        ({"status": "processing"}, "pending", None),
        ({"status": "queued"}, "pending", None),
    ],
)
def test_operation_status_maps_provider_states(
    body: dict[str, object], state: str, category: str | None
) -> None:
    handler = Script(_response(200, body))

    result = _provider(handler).operation_status(owner_id=OWNER, operation_id="op-1")

    assert result == OperationResult(state=state, failure_category=category)  # type: ignore[arg-type]
    request = handler.requests[0]
    assert request.method == "GET"
    assert str(request.url) == f"{BASE_URL}/v1/default/banks/{_bank()}/operations/op-1"


@pytest.mark.parametrize("response", [_response(404), _response(200, {"status": "not_found"})])
def test_operation_status_for_an_unknown_operation_is_lost(response: httpx.Response) -> None:
    handler = Script(response)

    result = _provider(handler).operation_status(owner_id=OWNER, operation_id="op-1")

    assert result == OperationResult(state="failed", failure_category="operation_lost")


def test_operation_status_rejects_a_body_without_a_status() -> None:
    handler = Script(_response(200, {"unexpected": "shape"}))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler).operation_status(owner_id=OWNER, operation_id="op-1")

    assert error.value.category == "invalid_response"


def test_operation_status_rejects_an_unsafe_operation_id_before_any_request() -> None:
    handler = Script(_response(200, {"status": "completed"}))

    with pytest.raises(ValueError):
        _provider(handler).operation_status(owner_id=OWNER, operation_id="../op")
    assert handler.requests == []


def test_a_retryable_status_is_retried_once_then_succeeds() -> None:
    handler = Script(_response(503), _response(202, {"operation_id": "op-9"}))

    operation_id = _provider(handler).retain_batch(owner_id=OWNER, items=[ITEM])

    assert operation_id == "op-9"
    assert len(handler.requests) == 2


def test_a_retryable_status_gives_up_after_one_retry() -> None:
    handler = Script(_response(429), _response(429))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler).retain_batch(owner_id=OWNER, items=[ITEM])

    assert error.value.category == "rate_limited"
    assert len(handler.requests) == 2


def test_no_retry_when_max_retries_is_zero() -> None:
    handler = Script(_response(503), _response(202, {"operation_id": "op-1"}))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler, max_retries=0).retain_batch(owner_id=OWNER, items=[ITEM])

    assert error.value.category == "unavailable"
    assert len(handler.requests) == 1


def test_connection_failure_is_unavailable_after_one_retry() -> None:
    handler = Script(httpx.ConnectError("refused"))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler).recall(owner_id=OWNER, query="sprang", max_tokens=64)

    assert error.value.category == "unavailable"
    assert len(handler.requests) == 2


def test_timeout_is_reported_as_timeout_not_as_unavailable() -> None:
    handler = Script(httpx.ReadTimeout("slow"))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler).recall(owner_id=OWNER, query="sprang", max_tokens=64)

    assert error.value.category == "timeout"


def test_errors_carry_only_a_category_never_a_provider_body() -> None:
    handler = Script(_response(500, text="SECRET-DOCUMENT-TEXT"))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler).delete_document(owner_id=OWNER, document_id=DOC)

    assert str(error.value) == "unavailable"
    assert "SECRET" not in repr(error.value)
    assert error.value.__cause__ is None


def test_non_json_success_body_is_invalid_and_does_not_echo_the_body() -> None:
    handler = Script(_response(200, text="SECRET-DOCUMENT-TEXT not json"))

    with pytest.raises(MemoryProviderError) as error:
        _provider(handler).operation_status(owner_id=OWNER, operation_id="op-1")

    assert error.value.category == "invalid_response"
    assert "SECRET" not in repr(error.value)
    assert error.value.__cause__ is None


def test_health_is_true_only_for_a_healthy_body() -> None:
    handler = Script(_response(200, {"status": "healthy", "database": "connected"}))

    assert _provider(handler).health() is True
    request = handler.requests[0]
    assert request.method == "GET"
    assert str(request.url) == f"{BASE_URL}/health"


@pytest.mark.parametrize(
    "step",
    [
        _response(200, {"status": "degraded"}),
        _response(503),
        _response(200, text="not json"),
        httpx.ConnectError("refused"),
    ],
)
def test_health_is_false_when_anything_is_not_healthy(step: httpx.Response | Exception) -> None:
    handler = Script(step)

    assert _provider(handler, max_retries=0).health() is False


@pytest.mark.parametrize(
    "base_url",
    [
        "https://memory.example.com",
        "http://hindsight:8888/v1",
        "http://user:pass@hindsight:8888",
        "ftp://hindsight:8888",
    ],
)
def test_constructor_rejects_public_pathed_or_credentialed_base_urls(base_url: str) -> None:
    with pytest.raises(ValueError):
        HindsightMemoryProvider(base_url=base_url, api_token=TOKEN, id_derivation_key=KEY)


def test_loopback_needs_the_explicit_exemption_from_the_composition_root() -> None:
    with pytest.raises(ValueError):
        HindsightMemoryProvider(
            base_url="http://127.0.0.1:18891", api_token=TOKEN, id_derivation_key=KEY
        )

    HindsightMemoryProvider(
        base_url="http://127.0.0.1:18891",
        api_token=TOKEN,
        id_derivation_key=KEY,
        allow_loopback=True,
    )


@pytest.mark.parametrize("timeout", [0, -1, 10.5])
def test_constructor_rejects_timeouts_outside_the_bounds(timeout: float) -> None:
    with pytest.raises(ValueError):
        HindsightMemoryProvider(
            base_url=BASE_URL,
            api_token=TOKEN,
            id_derivation_key=KEY,
            recall_timeout_seconds=timeout,
        )


def test_constructor_rejects_missing_secrets_and_unknown_retry_bounds() -> None:
    with pytest.raises(ValueError):
        HindsightMemoryProvider(base_url=BASE_URL, api_token=" ", id_derivation_key=KEY)
    with pytest.raises(ValueError):
        HindsightMemoryProvider(base_url=BASE_URL, api_token=TOKEN, id_derivation_key=" ")
    with pytest.raises(ValueError):
        HindsightMemoryProvider(
            base_url=BASE_URL, api_token=TOKEN, id_derivation_key=KEY, max_retries=2
        )


def test_recall_drops_observations_and_unknown_fact_types() -> None:
    def result(fact_id: str, fact_type: object) -> dict[str, object]:
        return {"id": fact_id, "text": f"fakta {fact_id}", "document_id": DOC, "type": fact_type}

    handler = Script(
        _response(
            200,
            {
                "results": [
                    result("a", "world"),
                    result("b", "experience"),
                    result("c", "observation"),
                    result("d", "something_new"),
                    result("e", 7),
                    {"id": "f", "text": "utan typ", "document_id": DOC},
                ]
            },
        )
    )

    facts = _provider(handler).recall(owner_id=OWNER, query="fakta", max_tokens=64)

    assert [(fact.id, fact.fact_type) for fact in facts] == [
        ("a", "world"),
        ("b", "experience"),
        ("f", None),
    ]


class _DripStream(httpx.SyncByteStream):
    """A body that yields one byte at a time and sleeps between bytes."""

    def __init__(self, total: int, pause: float) -> None:
        self._total = total
        self._pause = pause
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for _ in range(self._total):
            time.sleep(self._pause)  # Kept: a body that drips is what the read budget cuts off
            yield b" "

    def close(self) -> None:
        self.closed = True


class _EndlessStream(httpx.SyncByteStream):
    def __init__(self) -> None:
        self.sent = 0

    def __iter__(self) -> Iterator[bytes]:
        while self.sent < 10_000_000:
            self.sent += 512
            yield b"x" * 512


def test_a_body_dripped_slowly_hits_the_total_deadline_as_a_timeout() -> None:
    stream = _DripStream(total=200, pause=0.05)
    handler = Script(httpx.Response(200, stream=stream))
    provider = _provider(handler, max_retries=0, recall_timeout_seconds=0.3)

    started = time.monotonic()
    with pytest.raises(MemoryProviderError) as error:
        provider.recall(owner_id=OWNER, query="sprang", max_tokens=64)

    assert error.value.category == "timeout"
    assert time.monotonic() - started < 1.5
    assert stream.closed


def test_the_deadline_covers_the_retry_and_the_body_together() -> None:
    handler = Script(httpx.Response(200, stream=_DripStream(total=200, pause=0.05)))
    provider = _provider(handler, max_retries=1, recall_timeout_seconds=0.3)

    started = time.monotonic()
    with pytest.raises(MemoryProviderError) as error:
        provider.recall(owner_id=OWNER, query="sprang", max_tokens=64)

    assert error.value.category == "timeout"
    assert time.monotonic() - started < 1.5


def test_a_body_over_the_size_cap_is_invalid_without_echoing_content() -> None:
    big = b'{"results": [], "pad": "SECRET-DOCUMENT-TEXT' + b"x" * 5_000 + b'"}'
    handler = Script(httpx.Response(200, content=big))
    provider = _provider(handler, max_response_bytes=1_024)

    with pytest.raises(MemoryProviderError) as error:
        provider.recall(owner_id=OWNER, query="sprang", max_tokens=64)

    assert error.value.category == "invalid_response"
    assert "SECRET" not in repr(error.value)
    assert error.value.__cause__ is None
    assert len(handler.requests) == 1


def test_a_streamed_body_without_content_length_is_capped_while_reading() -> None:
    stream = _EndlessStream()
    handler = Script(httpx.Response(200, stream=stream))
    provider = _provider(handler, max_response_bytes=2_048)

    with pytest.raises(MemoryProviderError) as error:
        provider.operation_status(owner_id=OWNER, operation_id="op-1")

    assert error.value.category == "invalid_response"
    assert stream.sent <= 2_048 + 512


def test_a_declared_content_length_over_the_cap_is_refused_before_reading() -> None:
    stream = _EndlessStream()
    handler = Script(httpx.Response(200, headers={"content-length": "999999"}, stream=stream))
    provider = _provider(handler, max_response_bytes=1_024)

    with pytest.raises(MemoryProviderError) as error:
        provider.operation_status(owner_id=OWNER, operation_id="op-1")

    assert error.value.category == "invalid_response"
    assert stream.sent == 0


def test_a_decompressed_body_over_the_cap_is_refused() -> None:
    packed = gzip.compress(b'{"status": "' + b"a" * 100_000 + b'"}')
    assert len(packed) < 1_024
    handler = Script(httpx.Response(200, headers={"content-encoding": "gzip"}, content=packed))
    provider = _provider(handler, max_response_bytes=2_048)

    with pytest.raises(MemoryProviderError) as error:
        provider.operation_status(owner_id=OWNER, operation_id="op-1")

    assert error.value.category == "invalid_response"


def test_a_body_at_the_cap_still_parses() -> None:
    body = json.dumps({"results": []}).encode("utf-8")
    handler = Script(httpx.Response(200, content=body))
    provider = _provider(handler, max_response_bytes=len(body))

    assert provider.recall(owner_id=OWNER, query="sprang", max_tokens=64) == ()


def test_the_size_cap_must_be_positive() -> None:
    with pytest.raises(ValueError):
        HindsightMemoryProvider(
            base_url=BASE_URL, api_token=TOKEN, id_derivation_key=KEY, max_response_bytes=0
        )


def test_a_server_that_stalls_after_the_headers_is_cut_off_at_the_deadline() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    release = threading.Event()

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            connection.recv(65_536)
            connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 50\r\n\r\n{")
            release.wait(5)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    provider = HindsightMemoryProvider(
        base_url=f"http://127.0.0.1:{port}",
        api_token=TOKEN,
        id_derivation_key=KEY,
        allow_loopback=True,
        max_retries=0,
        recall_timeout_seconds=0.5,
    )
    started = time.monotonic()
    try:
        with pytest.raises(MemoryProviderError) as error:
            provider.recall(owner_id=OWNER, query="sprang", max_tokens=64)
    finally:
        release.set()
        server.close()
        thread.join(2)

    assert error.value.category == "timeout"
    assert time.monotonic() - started < 2


def test_a_server_that_drips_the_headers_is_cut_off_at_the_total_deadline() -> None:
    """Every header byte beats the per-read timeout, so only a total deadline stops the wait."""

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    release = threading.Event()

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            connection.recv(65_536)
            try:
                for byte in b"HTTP/1.1 200 OK\r\nX-Pad: " + b"a" * 400:
                    connection.sendall(bytes([byte]))
                    if release.wait(0.05):
                        return
            except OSError:
                return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    provider = HindsightMemoryProvider(
        base_url=f"http://127.0.0.1:{port}",
        api_token=TOKEN,
        id_derivation_key=KEY,
        allow_loopback=True,
        max_retries=1,
        recall_timeout_seconds=0.4,
    )
    started = time.monotonic()
    try:
        with pytest.raises(MemoryProviderError) as error:
            provider.recall(owner_id=OWNER, query="sprang", max_tokens=64)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        server.close()
        thread.join(2)

    assert error.value.category == "timeout"
    assert elapsed < 1.5


class _DrippingServer:
    """Loopback server: while `dripping` is set every connection drips its headers forever,
    afterwards every connection gets an empty recall answer at once."""

    def __init__(self) -> None:
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(64)
        self._socket.settimeout(0.1)
        self.port: int = self._socket.getsockname()[1]
        self.dripping = threading.Event()
        self.dripping.set()
        self._stop = threading.Event()
        self._accepter = threading.Thread(target=self._accept, daemon=True)
        self._accepter.start()

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except OSError:
                continue
            threading.Thread(target=self._serve, args=(connection,), daemon=True).start()

    def _serve(self, connection: socket.socket) -> None:
        with connection:
            try:
                connection.recv(65_536)
                if self.dripping.is_set():
                    connection.sendall(b"HTTP/1.1 200 OK\r\nX-Pad: ")
                    while self.dripping.is_set() and not self._stop.is_set():
                        connection.sendall(b"a")
                        time.sleep(0.02)  # Kept: the server drips on purpose (stalled response)
                    return  # closing mid-header ends the client's wait with an error
                body = b'{"results": []}'
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
            except OSError:
                return

    def close(self) -> None:
        self._stop.set()
        self.dripping.clear()
        self._accepter.join(2)
        self._socket.close()


def _send_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "memory-hindsight-send" and t.is_alive()]


def _wait_for(condition: Callable[[], bool], timeout: float = 3) -> bool:
    return poll_until(condition, timeout=timeout)


def test_expired_calls_against_a_dripping_server_leave_at_most_the_bounded_threads() -> None:
    server = _DrippingServer()
    before = len(_send_threads())
    provider = HindsightMemoryProvider(
        base_url=f"http://127.0.0.1:{server.port}",
        api_token=TOKEN,
        id_derivation_key=KEY,
        allow_loopback=True,
        max_retries=0,
        recall_timeout_seconds=0.2,
        max_pending_sends=2,
    )
    categories: list[str] = []
    try:
        for _ in range(8):
            started = time.monotonic()
            with pytest.raises(MemoryProviderError) as error:
                provider.recall(owner_id=OWNER, query="sprang", max_tokens=64)
            categories.append(error.value.category)
            assert time.monotonic() - started < 1
            # The abandoned threads keep dripping, but never more than the bound.
            assert len(_send_threads()) - before <= 2
    finally:
        server.close()
        assert _wait_for(lambda: len(_send_threads()) == before)

    assert categories[:2] == ["timeout", "timeout"]
    # With every slot held by an abandoned wait, further calls degrade at once, without a thread.
    assert categories[2:] == ["unavailable"] * 6


def test_the_capacity_is_released_when_the_abandoned_threads_end() -> None:
    server = _DrippingServer()
    before = len(_send_threads())
    provider = HindsightMemoryProvider(
        base_url=f"http://127.0.0.1:{server.port}",
        api_token=TOKEN,
        id_derivation_key=KEY,
        allow_loopback=True,
        max_retries=0,
        recall_timeout_seconds=0.2,
        max_pending_sends=2,
    )
    try:
        for _ in range(3):
            with pytest.raises(MemoryProviderError):
                provider.recall(owner_id=OWNER, query="sprang", max_tokens=64)
        assert len(_send_threads()) - before == 2

        server.dripping.clear()  # the server ends the dripped responses
        assert _wait_for(lambda: len(_send_threads()) == before)

        assert provider.recall(owner_id=OWNER, query="sprang", max_tokens=64) == ()
        assert provider.recall(owner_id=OWNER, query="sprang", max_tokens=64) == ()
        assert provider.recall(owner_id=OWNER, query="sprang", max_tokens=64) == ()
    finally:
        server.close()
        assert _wait_for(lambda: len(_send_threads()) == before)


@pytest.mark.parametrize("bound", [0, 65])
def test_the_concurrency_bound_must_be_within_limits(bound: int) -> None:
    with pytest.raises(ValueError):
        HindsightMemoryProvider(
            base_url=BASE_URL, api_token=TOKEN, id_derivation_key=KEY, max_pending_sends=bound
        )

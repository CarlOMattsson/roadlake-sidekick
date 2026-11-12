"""Authenticated Hindsight HTTP adapter for the memory port (contracts/reviewed/hindsight-memory).

Bank and operation identifiers are derived or validated here, so the URL never carries an owner
id, a document text or a provider-supplied string that has not matched the opaque-id alphabet.
Every failure leaves as `MemoryProviderError` with a category, never with a response body.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
from collections.abc import Mapping, Sequence
from time import monotonic
from typing import Any, Literal, cast
from uuid import UUID

import httpx

from sidekick.memory.ports import (
    ALLOWED_FACT_TYPES,
    OPAQUE_ID_PATTERN,
    MemoryFact,
    MemoryFailureCategory,
    MemoryProviderError,
    OperationResult,
    RetainItem,
    validate_bank_id,
    validate_opaque_id,
    validate_retain_items,
)
from sidekick.shared.errors.core import InternalFaultError
from sidekick.shared.observability import silence_http_client_loggers
from sidekick.shared.private_endpoint import validate_private_base_url

KEY_VERSION = "v1"
BANK_LABEL = "memory-bank"
RETAIN_CONTEXT = "sidekick_memory"
RETAIN_SOURCE = "sidekick_memory"
MAX_RECALL_TOKENS = 2_048
MAX_QUERY_CHARS = 300
MAX_TIMEOUT_SECONDS = 10
# Largest response body read from Hindsight, after decompression. Recall asks for at most 2 048
# tokens and no chunks, so a body beyond this is a fault or an attack, never a bigger answer.
DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
CONNECT_TIMEOUT_SECONDS = 2
# Most header waits that may run at once. A wait abandoned at its deadline keeps its slot until
# its thread really ends, so a server that drips headers cannot pile up threads and sockets.
DEFAULT_MAX_PENDING_SENDS = 8
MAX_PENDING_SENDS = 64
RETRYABLE_STATUS_CODES = frozenset({408, 429, 502, 503, 504})
RETAINED_STATUSES = frozenset({"completed", "succeeded", "success", "done"})
FAILED_STATUSES = frozenset({"failed", "error", "cancelled"})


class HindsightMemoryProvider:
    """Narrow synchronous Hindsight client for the memory bank of one owner per call."""

    name = "hindsight"

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        id_derivation_key: str,
        allow_loopback: bool = False,
        max_retries: int = 1,
        health_timeout_seconds: float = 2,
        recall_timeout_seconds: float = 3,
        operation_timeout_seconds: float = 5,
        retain_timeout_seconds: float = 10,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_pending_sends: int = DEFAULT_MAX_PENDING_SENDS,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_token.strip() or not id_derivation_key.strip():
            raise ValueError("Memory provider configuration is incomplete")
        if max_retries not in {0, 1}:
            raise ValueError("Memory provider retry bound is invalid")
        timeouts = (
            health_timeout_seconds,
            recall_timeout_seconds,
            operation_timeout_seconds,
            retain_timeout_seconds,
        )
        if any(not 0 < timeout <= MAX_TIMEOUT_SECONDS for timeout in timeouts):
            raise ValueError("Memory provider timeout bound is invalid")
        if max_response_bytes < 1:
            raise ValueError("Memory provider response size bound is invalid")
        if not 1 <= max_pending_sends <= MAX_PENDING_SENDS:
            raise ValueError("Memory provider concurrency bound is invalid")
        # Loopback is granted only by the mode that packages the service itself (see config).
        self._base_url = validate_private_base_url(
            base_url, label="Memory", allow_loopback=allow_loopback
        )
        self._api_token = api_token
        self._key = id_derivation_key.encode("utf-8")
        self._max_retries = max_retries
        self._health_timeout = health_timeout_seconds
        self._recall_timeout = recall_timeout_seconds
        self._operation_timeout = operation_timeout_seconds
        self._retain_timeout = retain_timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._send_slots = threading.BoundedSemaphore(max_pending_sends)
        silence_http_client_loggers()
        # trust_env=False keeps the bearer token away from any proxy named in the environment.
        self._client = client or httpx.Client(trust_env=False, follow_redirects=False)

    @property
    def provider_name(self) -> Literal["hindsight"]:
        return "hindsight"

    def retain_batch(self, *, owner_id: UUID, items: Sequence[RetainItem]) -> str:
        validate_retain_items(items)
        bank_id = self._bank_id(owner_id)
        payload: dict[str, Any] = {
            "async": True,
            "items": [_retain_item_body(item) for item in items],
        }
        data = self._json(
            "POST",
            f"/v1/default/banks/{bank_id}/memories",
            payload=payload,
            timeout=self._retain_timeout,
        )
        operation_id = data.get("operation_id")
        if not isinstance(operation_id, str) or not OPAQUE_ID_PATTERN.fullmatch(operation_id):
            raise MemoryProviderError("invalid_response")
        return operation_id

    def operation_status(self, *, owner_id: UUID, operation_id: str) -> OperationResult:
        validate_opaque_id(operation_id)
        bank_id = self._bank_id(owner_id)
        response = self._send(
            "GET",
            f"/v1/default/banks/{bank_id}/operations/{operation_id}",
            payload=None,
            timeout=self._operation_timeout,
        )
        if response.status_code == 404:
            # The operation is unknown to Hindsight, for example after a volume was lost.
            return OperationResult(state="failed", failure_category="operation_lost")
        _require_success(response)
        data = _json_object(response)
        status = data.get("status", data.get("state"))
        if not isinstance(status, str):
            raise MemoryProviderError("invalid_response")
        normalized = status.strip().casefold()
        if normalized in RETAINED_STATUSES:
            return OperationResult(state="retained")
        if normalized in FAILED_STATUSES:
            return OperationResult(state="failed", failure_category="operation_failed")
        return OperationResult(state="pending")

    def delete_document(self, *, owner_id: UUID, document_id: str) -> None:
        validate_opaque_id(document_id)
        bank_id = self._bank_id(owner_id)
        response = self._send(
            "DELETE",
            f"/v1/default/banks/{bank_id}/documents/{document_id}",
            payload=None,
            timeout=self._retain_timeout,
        )
        if response.status_code == 404:
            return
        _require_success(response)

    def recall(self, *, owner_id: UUID, query: str, max_tokens: int) -> tuple[MemoryFact, ...]:
        if not 1 <= max_tokens <= MAX_RECALL_TOKENS:
            raise ValueError("memory recall token budget is out of bounds")
        if not query.strip() or len(query) > MAX_QUERY_CHARS:
            raise ValueError("memory query is out of bounds")
        bank_id = self._bank_id(owner_id)
        # A fact-type filter is not sent: the reviewed source list in
        # contracts/reviewed/hindsight-memory/hindsight-memory-sources.yaml does not list a recall
        # types field and it cannot be checked offline. Observations are
        # off by design (ENABLE_OBSERVATIONS=false) and, as a second guard, a fact whose `type` is
        # present and not in `ALLOWED_FACT_TYPES` is dropped below.
        payload = {
            "query": query,
            "budget": "low",
            "max_tokens": max_tokens,
            "include": {"chunks": None, "source_facts": None},
        }
        data = self._json(
            "POST",
            f"/v1/default/banks/{bank_id}/memories/recall",
            payload=payload,
            timeout=self._recall_timeout,
        )
        results = data.get("results")
        if not isinstance(results, list):
            raise MemoryProviderError("invalid_response")
        facts: list[MemoryFact] = []
        for raw_result in cast(list[object], results):
            if not isinstance(raw_result, Mapping):
                raise MemoryProviderError("invalid_response")
            result = cast(Mapping[str, object], raw_result)
            text = result.get("text")
            if not isinstance(text, str) or not text.strip():
                raise MemoryProviderError("invalid_response")
            document_id = result.get("document_id")
            if not isinstance(document_id, str) or not OPAQUE_ID_PATTERN.fullmatch(document_id):
                # A fact whose source cannot be named is never returned to the caller.
                continue
            raw_type = result.get("type")
            if raw_type is not None and (
                not isinstance(raw_type, str) or raw_type not in ALLOWED_FACT_TYPES
            ):
                # An observation or an unknown type has no single source version.
                continue
            fact_id = result.get("id")
            facts.append(
                MemoryFact(
                    id=fact_id if isinstance(fact_id, str) else "",
                    text=text,
                    document_id=document_id,
                    occurred_start=_optional_text(result.get("occurred_start")),
                    occurred_end=_optional_text(result.get("occurred_end")),
                    fact_type=raw_type,
                )
            )
        return tuple(facts)

    def bank_id_for(self, owner_id: UUID) -> str:
        return self._bank_id(owner_id)

    def list_banks(self) -> tuple[str, ...]:
        """`GET /v1/default/banks` -> `{"banks": [{"bank_id": ...}, ...]}`. Only ids are read;
        names, missions and every other field are ignored."""

        data = self._json("GET", "/v1/default/banks", payload=None, timeout=self._operation_timeout)
        banks = data.get("banks")
        if not isinstance(banks, list):
            raise MemoryProviderError("invalid_response")
        ids: list[str] = []
        for raw_bank in cast(list[object], banks):
            if not isinstance(raw_bank, Mapping):
                raise MemoryProviderError("invalid_response")
            bank_id = cast(Mapping[str, object], raw_bank).get("bank_id")
            if isinstance(bank_id, str) and OPAQUE_ID_PATTERN.fullmatch(bank_id):
                ids.append(bank_id)
        return tuple(ids)

    def delete_bank(self, *, bank_id: str) -> None:
        validate_bank_id(bank_id)
        response = self._send(
            "DELETE",
            f"/v1/default/banks/{bank_id}",
            payload=None,
            timeout=self._retain_timeout,
        )
        if response.status_code == 404:
            return
        _require_success(response)

    def document_count(self, *, owner_id: UUID) -> int:
        """`GET .../documents?limit=1` -> `{"total": N, ...}`. Only `total` is read.

        A 404 is not a count: it can mean a bank that is gone or a wrong base path or proxy route.
        It raises `unavailable`, so a caller never takes it for an empty bank. Callers check
        `list_banks` first and only ask about banks that are listed."""

        bank_id = self._bank_id(owner_id)
        response = self._send(
            "GET",
            f"/v1/default/banks/{bank_id}/documents?limit=1",
            payload=None,
            timeout=self._operation_timeout,
        )
        if response.status_code == 404:
            raise MemoryProviderError("unavailable")
        _require_success(response)
        total = _json_object(response).get("total")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise MemoryProviderError("invalid_response")
        return total

    def health(self) -> bool:
        try:
            response = self._send("GET", "/health", payload=None, timeout=self._health_timeout)
            _require_success(response)
            data = _json_object(response)
        except MemoryProviderError:
            return False
        return data.get("status") == "healthy"

    def _json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        response = self._send(method, path, payload=payload, timeout=timeout)
        _require_success(response)
        return _json_object(response)

    def _send(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> httpx.Response:
        """Send with one overall deadline that covers connect, headers, every retry and the body.

        httpx timeouts apply per socket operation, so a server that drips bytes, in the headers
        or in the body, would never trip them. The wait for the response headers is therefore
        bounded by `_send_within_deadline`, the body by a watchdog that closes the response, and
        a 2xx body is read in a stream that stops at `max_response_bytes`. A body of a non-2xx
        response is never read: no caller uses it."""

        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        deadline = monotonic() + timeout
        category: MemoryFailureCategory = "unavailable"
        for attempt in range(self._max_retries + 1):
            remaining = deadline - monotonic()
            if remaining <= 0:
                category = "timeout"
                break
            try:
                request = self._client.build_request(
                    method,
                    url,
                    headers=headers,
                    json=payload,
                    timeout=httpx.Timeout(
                        remaining, connect=min(CONNECT_TIMEOUT_SECONDS, remaining)
                    ),
                )
                streamed = self._send_within_deadline(request, deadline)
            except httpx.TimeoutException:
                category = "timeout"
                continue
            except httpx.RequestError:
                category = "unavailable"
                continue
            try:
                if _is_retryable(streamed) and attempt < self._max_retries:
                    continue
                return self._read_body(streamed, deadline)
            except _BodyFailure as failure:
                category = failure.category
            finally:
                streamed.close()
        raise MemoryProviderError(category)

    def _send_within_deadline(self, request: httpx.Request, deadline: float) -> httpx.Response:
        """Send the request and return when the headers have arrived, or raise a timeout at the
        deadline however the server paces its bytes.

        The (synchronous) client call runs in a daemon thread so the caller can stop waiting at
        the deadline. The caller cannot interrupt that call: a server that drips its headers keeps
        the thread alive past the deadline, and when it finishes the thread closes the response
        itself. Each thread therefore holds one of `max_pending_sends` slots until it really
        ends, and with no slot free the request fails at once as unavailable, which callers treat
        as any other degraded memory call, instead of starting one more thread."""

        if not self._send_slots.acquire(blocking=False):
            raise httpx.ConnectError("too many memory requests still in flight")
        lock = threading.Lock()
        finished = threading.Event()
        abandoned = False
        outcome: list[httpx.Response | Exception] = []

        def run() -> None:
            try:
                try:
                    result: httpx.Response | Exception = self._client.send(request, stream=True)
                except Exception as error:  # handed to the caller, re-raised there
                    result = error
                with lock:
                    if abandoned:
                        if isinstance(result, httpx.Response):
                            result.close()
                    else:
                        outcome.append(result)
            finally:
                self._send_slots.release()
                finished.set()

        try:
            threading.Thread(target=run, name="memory-hindsight-send", daemon=True).start()
        except RuntimeError:
            self._send_slots.release()
            raise httpx.ConnectError("no thread for the memory request") from None
        finished.wait(max(deadline - monotonic(), 0))
        with lock:
            if not outcome:
                abandoned = True
        if not outcome:
            raise httpx.ReadTimeout("deadline reached before the response headers")
        result = outcome[0]
        if isinstance(result, Exception):
            raise result
        return result

    def _read_body(self, response: httpx.Response, deadline: float) -> httpx.Response:
        """Return a response whose body is fully read within the deadline and the size cap."""

        if not 200 <= response.status_code < 300:
            return httpx.Response(response.status_code)
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_response_bytes:
            raise MemoryProviderError("invalid_response")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise _BodyFailure("timeout")
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            response.close()

        watchdog = threading.Timer(remaining, expire)
        watchdog.daemon = True
        watchdog.start()
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self._max_response_bytes:
                    raise MemoryProviderError("invalid_response")
                chunks.append(chunk)
                if monotonic() >= deadline:
                    raise _BodyFailure("timeout")
        except httpx.TimeoutException:
            raise _BodyFailure("timeout") from None
        except (httpx.RequestError, httpx.StreamError, OSError):
            raise _BodyFailure("timeout" if expired.is_set() else "unavailable") from None
        finally:
            watchdog.cancel()
        if expired.is_set():
            raise _BodyFailure("timeout")
        return httpx.Response(response.status_code, content=b"".join(chunks))

    def _bank_id(self, owner_id: UUID) -> str:
        return _opaque_id(self._key, BANK_LABEL, str(owner_id))


class _BodyFailure(InternalFaultError):
    """Internal: reading a response body failed in a way that may be retried."""

    def __init__(self, category: MemoryFailureCategory) -> None:
        super().__init__(category)
        self.category: MemoryFailureCategory = category


def _is_retryable(response: httpx.Response) -> bool:
    return response.status_code in RETRYABLE_STATUS_CODES


def _retain_item_body(item: RetainItem) -> dict[str, Any]:
    return {
        "content": item.content,
        "document_id": item.document_id,
        "update_mode": "replace",
        "context": RETAIN_CONTEXT,
        "metadata": {"source": RETAIN_SOURCE},
        "timestamp": item.timestamp,
        "entities": [{"text": name} for name in item.entities],
        "tags": list(item.tags),
    }


def _require_success(response: httpx.Response) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if status in {401, 403}:
        raise MemoryProviderError("unauthorized")
    if status == 408:
        raise MemoryProviderError("timeout")
    if status == 429:
        raise MemoryProviderError("rate_limited")
    if 400 <= status < 500:
        raise MemoryProviderError("rejected")
    raise MemoryProviderError("unavailable")


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        raw: object = response.json()
    except ValueError:
        raise MemoryProviderError("invalid_response") from None
    if not isinstance(raw, dict):
        raise MemoryProviderError("invalid_response")
    return cast(dict[str, Any], raw)


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _opaque_id(key: bytes, *parts: str) -> str:
    material = "\x1f".join(parts).encode("utf-8")
    digest = hmac.new(key, material, hashlib.sha256).hexdigest()
    return f"{KEY_VERSION}_{digest}"

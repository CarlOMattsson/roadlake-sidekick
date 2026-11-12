"""HTTP side of push delivery: one POST to a UnifiedPush endpoint, with a hard deadline.

`HttpPushSender` implements `PushSender`. The response is never read beyond its status line and a
`Retry-After` header. Nothing here logs an endpoint, a topic or a response, and the HTTP client
loggers (which print request URLs) are silenced.
"""

from __future__ import annotations

import threading

import httpx

from sidekick.companion.push_delivery import SendFailed, SendsBusy
from sidekick.shared.observability import silence_http_client_loggers

SEND_TIMEOUT_SECONDS = 10.0
# One overall deadline for a send, from the start of the request to the response headers. httpx
# timeouts apply per socket operation, so a server that drips its headers a byte at a time would
# never trip them; the wait is cut off here whatever the pace. Shorter than the delivery lease.
SEND_DEADLINE_SECONDS = 15.0
# Most sends that may still be running past their deadline. An abandoned send keeps its slot until
# its thread really ends, so a slow-dripping host cannot pile up threads and sockets.
MAX_PENDING_SENDS = 4


def create_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """The delivery HTTP client: no redirects, the send timeout, and quiet loggers."""

    silence_http_client_loggers()
    return httpx.Client(
        follow_redirects=False, timeout=SEND_TIMEOUT_SECONDS, transport=transport, trust_env=False
    )


class HttpPushSender:
    def __init__(
        self, client: httpx.Client, *, deadline_seconds: float = SEND_DEADLINE_SECONDS
    ) -> None:
        silence_http_client_loggers()
        self._client = client
        self._deadline = deadline_seconds
        self._slots = threading.BoundedSemaphore(MAX_PENDING_SENDS)

    def send(
        self, endpoint: str, content: bytes, headers: dict[str, str]
    ) -> tuple[int, str | None]:
        try:
            return self._send_within_deadline(endpoint, content, headers)
        except httpx.TimeoutException:
            raise SendFailed("timeout") from None
        except (httpx.HTTPError, httpx.InvalidURL):
            raise SendFailed("network") from None

    def _send_within_deadline(
        self, endpoint: str, content: bytes, headers: dict[str, str]
    ) -> tuple[int, str | None]:
        """POST once and return (status, Retry-After header), or raise a timeout at the deadline.

        The synchronous client call runs in a daemon thread so this method can stop waiting at the
        deadline however slowly the server paces its bytes. The call itself cannot be interrupted:
        an abandoned thread ends on its own (the per-operation timeouts still apply) and closes its
        response, and holds one of `MAX_PENDING_SENDS` slots until then. With no slot free the send
        raises `SendsBusy` at once instead of starting one more thread. The response body is
        never read."""

        if not self._slots.acquire(blocking=False):
            raise SendsBusy
        finished = threading.Event()
        outcome: list[tuple[int, str | None] | Exception] = []

        def run() -> None:
            try:
                try:
                    # Streamed and closed unread: the response body is never read.
                    with self._client.stream(
                        "POST",
                        endpoint,
                        content=content,
                        headers=headers,
                        timeout=SEND_TIMEOUT_SECONDS,
                        follow_redirects=False,
                    ) as response:
                        outcome.append((response.status_code, response.headers.get("retry-after")))
                except Exception as error:  # handed to the caller, re-raised there
                    outcome.append(error)
            finally:
                self._slots.release()
                finished.set()

        try:
            threading.Thread(target=run, name="push-send", daemon=True).start()
        except RuntimeError:
            self._slots.release()
            raise httpx.ConnectError("no thread for the send") from None
        if not finished.wait(self._deadline):
            raise httpx.ReadTimeout("deadline reached before the response headers")
        result = outcome[0]
        if isinstance(result, Exception):
            raise result
        return result

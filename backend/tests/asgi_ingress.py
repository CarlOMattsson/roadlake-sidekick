"""Raw ASGI helpers for testing an ingress middleware without any framework app."""

import json
from typing import Any

from starlette.types import Message


class Recorder:
    """A terminal ASGI app that answers 204 and remembers what it was handed."""

    def __init__(self) -> None:
        self.reached = False
        self.sent: list[Message] = []

    async def app(self, scope: Any, receive: Any, send: Any) -> None:
        self.reached = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    def reset(self) -> None:
        self.reached = False
        self.sent = []

    async def send(self, message: Message) -> None:
        self.sent.append(message)

    @property
    def status(self) -> int:
        return int(self.sent[0]["status"])

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(b"".join(m.get("body", b"") for m in self.sent))


async def receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


def chunked(*parts: bytes) -> Any:
    """A `receive` that delivers the body in chunks, as a request without Content-Length does."""

    messages = [
        {"type": "http.request", "body": part, "more_body": index < len(parts) - 1}
        for index, part in enumerate(parts)
    ]

    async def deliver() -> dict[str, Any]:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    return deliver


def http_scope(
    path: str, method: str, headers: list[tuple[bytes, bytes]] | None = None
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "headers": headers or [],
        "query_string": b"",
        "sidekick.correlation_id": "corr-unit",
    }


async def call(
    middleware: Any,
    recorder: Recorder,
    path: str,
    *,
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    deliver: Any = receive,
) -> None:
    await middleware(http_scope(path, method, headers), deliver, recorder.send)

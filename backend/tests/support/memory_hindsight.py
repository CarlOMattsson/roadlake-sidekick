"""Shared test helpers moved out of `tests/memory/test_hindsight_adapter.py`."""

from __future__ import annotations

import hashlib
import hmac
from uuid import UUID

import httpx

from sidekick.memory.adapters.hindsight import HindsightMemoryProvider

BASE_URL = "http://hindsight:8888"


TOKEN = "memory-test-token"


KEY = "memory-derivation-test-key"


OWNER = UUID("018af000-0000-7000-8000-0000000000a1")


OTHER_OWNER = UUID("018af000-0000-7000-8000-0000000000a2")


class Script:
    """Replays scripted responses or exceptions in order; the last step repeats."""

    def __init__(self, *steps: httpx.Response | Exception) -> None:
        self._steps = list(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self._steps.pop(0) if len(self._steps) > 1 else self._steps[0]
        if isinstance(step, Exception):
            raise step
        return step


def _response(
    status: int, body: object | None = None, *, text: str | None = None
) -> httpx.Response:
    if text is not None:
        return httpx.Response(status, content=text.encode("utf-8"))
    if body is None:
        return httpx.Response(status)
    return httpx.Response(status, json=body)


def _provider(handler: Script, **kwargs: object) -> HindsightMemoryProvider:
    return HindsightMemoryProvider(
        base_url=BASE_URL,
        api_token=TOKEN,
        id_derivation_key=KEY,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,  # type: ignore[arg-type]
    )


def _bank(owner: UUID = OWNER) -> str:
    material = "\x1f".join(["memory-bank", str(owner)]).encode("utf-8")
    return "v1_" + hmac.new(KEY.encode("utf-8"), material, hashlib.sha256).hexdigest()

"""Asking the model server which models it offers: ``GET <base>/models`` with the API key as a bearer token.

The key arrives as an argument of the function (the command reads it from stdin) and only travels in the request
header: it is never printed and never on a command line. Redirects are not followed, so the key cannot be passed
on to another host."""

from __future__ import annotations

import http.client
import json
import urllib.request
from email.message import Message
from typing import IO

TIMEOUT_SECONDS = 15
MAX_BODY_BYTES = 1 << 20


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: Message, newurl: str
    ) -> None:
        return None


def parse_model_ids(body: str) -> list[str]:
    """The ids of an OpenAI-compatible ``/models`` answer; ``ValueError`` when it is not one."""
    try:
        data = json.loads(body).get("data", [])
        return [model["id"] for model in data if isinstance(model, dict) and "id" in model]
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError("not a model list") from error


def fetch_model_ids(base_url: str, key: str) -> list[str]:
    """The model ids the server lists; ``ValueError`` when it cannot be asked or does not answer with a list."""
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("not an http(s) address")
    request = urllib.request.Request(f"{base_url}/models")  # noqa: S310 - http(s) checked above
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body: bytes = response.read(MAX_BODY_BYTES)
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise ValueError("the model server did not answer") from error
    return parse_model_ids(body.decode("utf-8", errors="replace"))

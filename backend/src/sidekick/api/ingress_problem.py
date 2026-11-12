"""The one closed problem+json envelope every Sidekick HTTP surface answers an error with."""

from collections.abc import Mapping
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

DEFAULT_TYPE_PREFIX = "urn:sidekick:error"


def problem_response(
    scope: Scope,
    *,
    status: int,
    code: str,
    title: str,
    headers: Mapping[str, str] | None = None,
    type_prefix: str = DEFAULT_TYPE_PREFIX,
    extra: Mapping[str, Any] | None = None,
) -> JSONResponse:
    """Build the fixed envelope: no request content, only the correlation id.

    `extra` adds closed, caller-chosen fields after the correlation id; callers never pass
    request content or exception text.
    """

    content: dict[str, Any] = {
        "type": f"{type_prefix}:{code}",
        "title": title,
        "status": status,
        "code": code,
        "correlation_id": scope.get("sidekick.correlation_id", "unknown"),
    }
    if extra:
        content.update(extra)
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        headers=dict(headers) if headers is not None else None,
        content=content,
    )


async def refuse_request(
    scope: Scope,
    receive: Receive,
    send: Send,
    status: int,
    code: str,
    title: str,
    headers: dict[str, str] | None = None,
) -> None:
    """Answer an ingress refusal with the fixed envelope."""

    response = problem_response(scope, status=status, code=code, title=title, headers=headers)
    await response(scope, receive, send)

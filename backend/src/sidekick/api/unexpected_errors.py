"""A safe, structured answer for any exception no handler claimed.

Starlette's `ServerErrorMiddleware` sits outside the correlation middleware, so its 500 would
carry neither the correlation header nor Sidekick's problem envelope, and it re-raises the error
to the server, which logs the message. This middleware sits inside `CorrelationMiddleware`
instead: an unexpected exception from any route (FastAPI, companion or a mounted app) becomes the
same `application/problem+json` envelope the other handlers use, with the request's correlation id
and the closed code `internal_error`. The exception's text, its traceback and any SQL are never
sent, and the log line carries the exception class and the correlation id only (the message may
echo personal data).
"""

import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sidekick.api.ingress_problem import problem_response
from sidekick.shared.observability import safe_http_method, safe_log_fields

LOGGER = logging.getLogger("sidekick.api.errors")

INTERNAL_ERROR_CODE = "internal_error"


class UnexpectedErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def track(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track)
        except Exception as error:
            correlation = scope.get("sidekick.correlation_id")
            correlation_id = correlation if isinstance(correlation, str) else "unknown"
            LOGGER.error(
                "unexpected_error",
                extra=safe_log_fields(
                    {
                        "correlation_id": correlation_id,
                        "http_method": safe_http_method(scope),
                        "http_status": 500,
                        "error_type": type(error).__name__,
                    }
                ),
            )
            if started:
                # The status line is already out; the connection cannot carry an envelope.
                raise
            response = problem_response(
                scope,
                status=500,
                code=INTERNAL_ERROR_CODE,
                title="Internal server error",
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)

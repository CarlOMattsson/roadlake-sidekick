"""The Anthropic adapter of the model port: the only module that imports `anthropic`.

One structured call per run, no tools, no thinking, no caching. The adapter turns every failure
into one of the port's three errors and never carries the SDK's text, which may quote the
request, the key or the model's answer. Nothing here logs.
"""

from typing import cast

import anthropic
import httpx2

from sidekick.work.domain.ai_model_port import (
    CallUsage,
    ModelError,
    ModelRejected,
    ModelRequest,
    ModelResponse,
    ModelTransient,
    ModelUncertain,
    RejectionKind,
    StopReason,
)

API_BASE_URL = "https://api.anthropic.com"
MAX_RETRY_AFTER_SECONDS = 60.0
# Rate limit, unavailable and overloaded: the provider refused before doing any work. A 500, 502
# or 504 can come after work began, so it is not known to be unbilled.
_TRANSIENT_STATUSES = frozenset({429, 503, 529})
_AUTH_STATUSES = frozenset({401, 403})
_REQUEST_STATUSES = frozenset({400, 404, 413, 422})
_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.REFUSAL,
}


class AnthropicModel:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float,
        *,
        http_client: httpx2.Client | None = None,
    ) -> None:
        self._model = model
        # `base_url` and `api_key` are always explicit so ANTHROPIC_BASE_URL and ANTHROPIC_API_KEY
        # in the environment never decide where the key is sent. The SDK's OpenTelemetry spans
        # (and the trace headers they add to the request) are switched off.
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=API_BASE_URL,
            max_retries=0,
            timeout=timeout_seconds,
            open_telemetry=False,
            http_client=http_client,
        )

    def complete(self, request: ModelRequest) -> ModelResponse:
        failure: ModelError
        try:
            reply = self._client.messages.create(
                model=self._model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=cast("list[anthropic.types.MessageParam]", list(request.messages)),
                output_config={
                    "format": {"type": "json_schema", "schema": dict(request.output_schema)}
                },
            )
            return _response(reply)
        except Exception as error:
            failure = _failure(error)
        # Raised outside the handler so the SDK's exception is neither the cause nor the context.
        raise failure from None


def _response(reply: anthropic.types.Message) -> ModelResponse:
    texts = [block.text for block in reply.content if block.type == "text"]
    usage = reply.usage
    return ModelResponse(
        stop_reason=_STOP_REASONS.get(str(reply.stop_reason), StopReason.OTHER),
        output_json="".join(texts) if texts else None,
        usage=CallUsage(
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
        ),
        model=str(reply.model),
    )


def _failure(error: Exception) -> ModelError:
    if isinstance(error, anthropic.APIStatusError):
        status = error.status_code
        if status in _AUTH_STATUSES:
            return ModelRejected(RejectionKind.AUTH)
        if status in _REQUEST_STATUSES:
            return ModelRejected(RejectionKind.REQUEST)
        if status in _TRANSIENT_STATUSES:
            return ModelTransient(_retry_after(error.response))
    return ModelUncertain()


def _retry_after(response: httpx2.Response) -> float:
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return 0.0
    if not seconds > 0.0:  # also rejects NaN
        return 0.0
    return min(seconds, MAX_RETRY_AFTER_SECONDS)

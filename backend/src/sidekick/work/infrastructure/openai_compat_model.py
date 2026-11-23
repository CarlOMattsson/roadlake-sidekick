"""The OpenAI-compatible adapter of the model port: OpenRouter with the owner's key, or a local
server such as Ollama or LM Studio.

One structured call, no tools, no streaming. The adapter speaks plain HTTP through `httpx` and
imports no vendor SDK, so there is no SDK telemetry to switch off. It never follows a redirect and
ignores proxy variables in the environment, so the key goes only where the validated base URL
says. The response body is read in a stream that stops at a size limit and at one deadline for
the whole call. Every failure becomes one of the port's three errors and carries nothing of the
request, the key or the provider's text. Nothing here logs.
"""

import json
import threading
from time import monotonic
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from sidekick.shared.private_endpoint import is_hosted_model_url, validate_model_base_url
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

DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
CONNECT_TIMEOUT_SECONDS = 10.0
MAX_RETRY_AFTER_SECONDS = 60.0
MAX_MODEL_NAME_CHARS = 120
# Rate limit and unavailable: the provider refused before doing any work. A 500, 502 or 504 can
# come after work began, so it is not known to be unbilled.
_TRANSIENT_STATUSES = frozenset({429, 503})
# 402 is OpenRouter's "out of credits": like a refused key, no call succeeds until the owner acts.
_AUTH_STATUSES = frozenset({401, 402, 403})
_REQUEST_STATUSES = frozenset({400, 404, 413, 422})
_FINISH_REASONS = {
    "stop": StopReason.END_TURN,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.REFUSAL,
}
_COMPLETIONS_PATH: Final = "/v1/chat/completions"
_HOSTED_COMPLETIONS_PATH: Final = "/api/v1/chat/completions"
# Only for the hosted route: send the call to providers that honour the schema, and never to one
# that may train on the owner's data.
_HOSTED_ROUTING: Final = {"require_parameters": True, "data_collection": "deny"}


class _Details(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cached_tokens: int | None = None


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    prompt_tokens_details: _Details | None = None


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str | None = None
    refusal: str | None = None


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: _Message
    finish_reason: str | None = None


class _Completion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    choices: list[_Choice]
    usage: _Usage | None = None
    model: str | None = None


class OpenAiCompatModel:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str,
        timeout_seconds: float,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        allow_loopback: bool = False,
        http_client: httpx.Client | None = None,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("the response size limit must be positive")
        # The same rule as the settings: the hosted origin, or an approved private server.
        origin = validate_model_base_url(base_url, label="AI model", allow_loopback=allow_loopback)
        hosted = is_hosted_model_url(origin)
        self._url = origin + (_HOSTED_COMPLETIONS_PATH if hosted else _COMPLETIONS_PATH)
        self._hosted = hosted
        self._model = model
        self._max_response_bytes = max_response_bytes
        self._timeout_seconds = timeout_seconds
        self._headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        # `trust_env=False` keeps the key away from any proxy named in the environment, and no
        # redirect is followed, so a server cannot send the key on to another host.
        self._client = http_client or httpx.Client(trust_env=False, follow_redirects=False)

    def complete(self, request: ModelRequest) -> ModelResponse:
        failure: ModelError
        try:
            return self._call(request)
        except ModelError as error:
            failure = error
        except Exception:
            failure = ModelUncertain()
        # Raised outside the handler: the library's exception is neither the cause nor the context.
        raise failure from None

    def _call(self, request: ModelRequest) -> ModelResponse:
        deadline = monotonic() + self._timeout_seconds
        built = self._client.build_request(
            "POST",
            self._url,
            headers=self._headers,
            content=json.dumps(self._body(request)),
            timeout=httpx.Timeout(
                self._timeout_seconds, connect=min(CONNECT_TIMEOUT_SECONDS, self._timeout_seconds)
            ),
        )
        response = self._client.send(built, stream=True)
        try:
            status = response.status_code
            if not 200 <= status < 300:
                raise status_failure(status, response.headers)
            return _response(read_json(response, deadline, self._max_response_bytes), self._model)
        finally:
            response.close()

    def _body(self, request: ModelRequest) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "stream": False,
            "messages": [{"role": "system", "content": request.system}, *request.messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "result",
                    "strict": True,
                    "schema": dict(request.output_schema),
                },
            },
        }
        if self._hosted:
            body["provider"] = dict(_HOSTED_ROUTING)
        return body


def read_json(response: httpx.Response, deadline: float, limit: int) -> object:
    """The body as JSON, read within the size limit and the call's one deadline.

    httpx timeouts apply to each socket operation, so a server that drips bytes would never trip
    them: a timer closes the response at the deadline instead. The wait for the headers is bounded
    by those per-operation timeouts only."""

    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise ModelUncertain()
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ModelUncertain()
    watchdog = threading.Timer(remaining, response.close)
    watchdog.daemon = True
    watchdog.start()
    chunks: list[bytes] = []
    size = 0
    try:
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > limit or monotonic() >= deadline:
                raise ModelUncertain()
            chunks.append(chunk)
    finally:
        watchdog.cancel()
    return json.loads(b"".join(chunks))


def _response(payload: object, configured_model: str) -> ModelResponse:
    completion: _Completion | None
    try:
        completion = _Completion.model_validate(payload)
    except ValidationError:
        completion = None
    # Raised outside the handler: pydantic's error quotes the input, so it must not be the context.
    if completion is None or not completion.choices:
        raise ModelUncertain()
    choice = completion.choices[0]
    refused = bool(choice.message.refusal)
    stop_reason = (
        StopReason.REFUSAL
        if refused
        else _FINISH_REASONS.get(choice.finish_reason or "", StopReason.OTHER)
    )
    usage = completion.usage or _Usage()
    # OpenAI counts cached tokens inside `prompt_tokens`; the port counts them apart.
    cached = max((usage.prompt_tokens_details or _Details()).cached_tokens or 0, 0)
    prompt = max(usage.prompt_tokens or 0, 0)
    cached = min(cached, prompt)
    return ModelResponse(
        stop_reason=stop_reason,
        output_json=None if refused else choice.message.content or None,
        usage=CallUsage(
            input_tokens=prompt - cached,
            output_tokens=max(usage.completion_tokens or 0, 0),
            cache_read_tokens=cached,
        ),
        model=(completion.model or configured_model)[:MAX_MODEL_NAME_CHARS],
    )


def status_failure(status: int, headers: httpx.Headers) -> ModelError:
    if status in _AUTH_STATUSES:
        return ModelRejected(RejectionKind.AUTH)
    # A redirect is refused unread: the server did no work, and the base URL is wrong.
    if status in _REQUEST_STATUSES or 300 <= status < 400:
        return ModelRejected(RejectionKind.REQUEST)
    if status in _TRANSIENT_STATUSES:
        return ModelTransient(_retry_after(headers))
    return ModelUncertain()


def _retry_after(headers: httpx.Headers) -> float:
    try:
        seconds = float(headers.get("retry-after", ""))
    except ValueError:
        return 0.0
    if not seconds > 0.0:  # also rejects NaN
        return 0.0
    return min(seconds, MAX_RETRY_AFTER_SECONDS)

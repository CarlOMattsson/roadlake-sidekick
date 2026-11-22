"""The OpenAI-compatible model adapter against a mock transport; no network, no real key."""

import json
import logging
import time
from collections.abc import Callable, Iterator

import httpx
import pytest

from sidekick.work.domain.ai_model_port import (
    CallUsage,
    ModelRejected,
    ModelRequest,
    ModelTransient,
    ModelUncertain,
    RejectionKind,
    StopReason,
)
from sidekick.work.infrastructure import openai_compat_model
from sidekick.work.infrastructure.openai_compat_model import OpenAiCompatModel

SENTINEL = "SENTINEL-4f9a1c"
KEY = f"sk-test-{SENTINEL}"
PROMPT = f"PROMPT-{SENTINEL}"
LOCAL = "http://ollama.internal:11434"
HOSTED = "https://openrouter.ai"
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}}
REQUEST = ModelRequest(
    system=f"rules {PROMPT}",
    messages=({"role": "user", "content": "brief"},),
    max_tokens=500,
    output_schema=SCHEMA,
)
ANSWER = '{"text": "done"}'


def _completion(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "gen-1",
        "object": "chat.completion",
        "model": "check-model-1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": ANSWER},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 7,
            "total_tokens": 27,
            "prompt_tokens_details": {"cached_tokens": 5},
        },
    }
    body.update(overrides)
    return body


def _choice(finish_reason: str | None = "stop", **message: object) -> dict[str, object]:
    return _completion(
        choices=[
            {"message": {"role": "assistant", "content": ANSWER, **message}}
            | {"finish_reason": finish_reason}
        ]
    )


class Recorder:
    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)

    def model(
        self,
        *,
        key: str | None = KEY,
        base_url: str = LOCAL,
        timeout: float = 30.0,
        limit: int = 1_048_576,
    ) -> OpenAiCompatModel:
        client = httpx.Client(transport=httpx.MockTransport(self), follow_redirects=False)
        return OpenAiCompatModel(
            key, "check-model-1", base_url, timeout, max_response_bytes=limit, http_client=client
        )


def _ok(body: dict[str, object] | None = None) -> Recorder:
    return Recorder(lambda _request: httpx.Response(200, json=body or _completion()))


def _status(status: int, headers: dict[str, str] | None = None) -> Recorder:
    error = {"error": {"message": f"quoted {SENTINEL}", "code": status}}
    return Recorder(lambda _request: httpx.Response(status, json=error, headers=headers))


# The destination


def test_a_private_server_is_called_at_the_openai_path_with_the_key() -> None:
    recorder = _ok()

    recorder.model().complete(REQUEST)

    (sent,) = recorder.requests
    assert str(sent.url) == f"{LOCAL}/v1/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {KEY}"


def test_the_hosted_origin_is_called_at_its_own_path() -> None:
    recorder = _ok()

    recorder.model(base_url=HOSTED + "/").complete(REQUEST)

    assert str(recorder.requests[0].url) == f"{HOSTED}/api/v1/chat/completions"


def test_a_local_server_without_a_key_gets_no_authorization_header() -> None:
    recorder = _ok()

    recorder.model(key=None).complete(REQUEST)

    assert "authorization" not in recorder.requests[0].headers


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.com",
        "http://8.8.8.8:11434",
        "https://openrouter.ai.evil.example",
        "https://openrouter.ai/api/v1",
        "http://openrouter.ai",
        "http://169.254.169.254",
        "http://user:pass@ollama.internal",
        "ollama.internal",
        "http://127.0.0.1:11434",
    ],
)
def test_a_destination_that_is_neither_hosted_nor_private_is_refused(base_url: str) -> None:
    with pytest.raises(ValueError, match="base URL"):
        OpenAiCompatModel(KEY, "m", base_url, 30.0)


def test_loopback_is_allowed_only_when_asked_for() -> None:
    OpenAiCompatModel(None, "m", "http://127.0.0.1:11434", 30.0, allow_loopback=True)


def test_the_default_client_ignores_the_environment_and_follows_no_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class SpyClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(openai_compat_model.httpx, "Client", SpyClient)

    OpenAiCompatModel(KEY, "m", LOCAL, 30.0)

    assert captured == {"trust_env": False, "follow_redirects": False}


def test_a_redirect_is_not_followed_and_is_a_refused_request() -> None:
    recorder = Recorder(
        lambda _request: httpx.Response(307, headers={"location": "https://elsewhere.invalid/x"})
    )

    with pytest.raises(ModelRejected) as caught:
        recorder.model().complete(REQUEST)

    assert caught.value.kind is RejectionKind.REQUEST
    assert len(recorder.requests) == 1


# The request


def test_the_body_is_one_structured_call_without_tools_or_streaming() -> None:
    recorder = _ok()

    recorder.model().complete(REQUEST)

    body = json.loads(recorder.requests[0].content)
    assert body["model"] == "check-model-1"
    assert body["max_tokens"] == 500
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": REQUEST.system},
        {"role": "user", "content": "brief"},
    ]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "result", "strict": True, "schema": SCHEMA},
    }
    for absent in ("tools", "tool_choice", "functions", "provider", "plugins", "transforms"):
        assert absent not in body


def test_only_the_hosted_route_asks_for_schema_support_and_no_data_collection() -> None:
    recorder = _ok()

    recorder.model(base_url=HOSTED).complete(REQUEST)

    body = json.loads(recorder.requests[0].content)
    assert body["provider"] == {"require_parameters": True, "data_collection": "deny"}


# The reply


def test_a_reply_is_mapped_with_its_usage_and_cached_tokens_counted_apart() -> None:
    reply = _ok().model().complete(REQUEST)

    assert reply.stop_reason is StopReason.END_TURN
    assert reply.output_json == ANSWER
    assert reply.model == "check-model-1"
    assert reply.usage == CallUsage(input_tokens=15, output_tokens=7, cache_read_tokens=5)


def test_a_reply_without_usage_counts_zero_and_names_the_configured_model() -> None:
    reply = _ok(_completion(usage=None, model=None)).model().complete(REQUEST)

    assert reply.usage == CallUsage()
    assert reply.model == "check-model-1"


def test_cached_tokens_never_exceed_the_prompt() -> None:
    usage = {
        "prompt_tokens": 4,
        "completion_tokens": 1,
        "prompt_tokens_details": {"cached_tokens": 9},
    }

    reply = _ok(_completion(usage=usage)).model().complete(REQUEST)

    assert reply.usage == CallUsage(input_tokens=0, output_tokens=1, cache_read_tokens=4)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("length", StopReason.MAX_TOKENS),
        ("content_filter", StopReason.REFUSAL),
        ("tool_calls", StopReason.OTHER),
        (None, StopReason.OTHER),
    ],
)
def test_a_finish_reason_is_mapped(reason: str | None, expected: StopReason) -> None:
    assert _ok(_choice(reason)).model().complete(REQUEST).stop_reason is expected


def test_a_refusal_has_no_output() -> None:
    reply = _ok(_choice(content=None, refusal="no")).model().complete(REQUEST)

    assert reply.stop_reason is StopReason.REFUSAL
    assert reply.output_json is None


@pytest.mark.parametrize("content", [None, ""])
def test_a_reply_without_text_has_no_output(content: str | None) -> None:
    assert _ok(_choice(content=content)).model().complete(REQUEST).output_json is None


# Failures


def test_rate_limit_carries_retry_after() -> None:
    with pytest.raises(ModelTransient) as caught:
        _status(429, {"retry-after": "12"}).model().complete(REQUEST)

    assert caught.value.retry_after == 12.0


@pytest.mark.parametrize(
    ("header", "expected"),
    [(None, 0.0), ("soon", 0.0), ("-3", 0.0), ("nan", 0.0), ("600", 60.0)],
)
def test_retry_after_is_zero_when_unusable_and_capped_at_a_minute(
    header: str | None, expected: float
) -> None:
    with pytest.raises(ModelTransient) as caught:
        _status(429, {"retry-after": header} if header is not None else None).model().complete(
            REQUEST
        )

    assert caught.value.retry_after == expected


@pytest.mark.parametrize("status", [429, 503])
def test_a_refusal_before_any_work_may_be_tried_again(status: int) -> None:
    with pytest.raises(ModelTransient):
        _status(status).model().complete(REQUEST)


@pytest.mark.parametrize("status", [408, 409, 500, 502, 504, 529])
def test_a_status_that_may_have_done_work_is_uncertain(status: int) -> None:
    with pytest.raises(ModelUncertain):
        _status(status).model().complete(REQUEST)


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, RejectionKind.AUTH),
        (402, RejectionKind.AUTH),
        (403, RejectionKind.AUTH),
        (400, RejectionKind.REQUEST),
        (404, RejectionKind.REQUEST),
        (413, RejectionKind.REQUEST),
        (422, RejectionKind.REQUEST),
    ],
)
def test_a_refused_call_is_rejected_with_its_kind(status: int, kind: RejectionKind) -> None:
    with pytest.raises(ModelRejected) as caught:
        _status(status).model().complete(REQUEST)

    assert caught.value.kind is kind


def test_a_timeout_and_a_broken_connection_are_uncertain() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    for respond in (timeout, broken):
        with pytest.raises(ModelUncertain):
            Recorder(respond).model().complete(REQUEST)


def test_an_unexpected_failure_is_uncertain() -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"unexpected {SENTINEL}")

    with pytest.raises(ModelUncertain):
        Recorder(boom).model().complete(REQUEST)


@pytest.mark.parametrize(
    "body",
    [
        f"<html>{SENTINEL}</html>",
        json.dumps(["not", "an", "object"]),
        json.dumps({"choices": []}),
        json.dumps({"error": {"message": f"credits {SENTINEL}", "code": 402}}),
        json.dumps({"choices": [{"message": {"content": 5}}]}),
        json.dumps({"choices": [{"message": {"content": "x"}}], "usage": "many"}),
    ],
)
def test_a_reply_that_is_not_a_completion_is_uncertain(body: str) -> None:
    with pytest.raises(ModelUncertain):
        Recorder(lambda _request: httpx.Response(200, text=body)).model().complete(REQUEST)


# The size and time limits


def test_a_body_that_declares_more_than_the_limit_is_refused() -> None:
    with pytest.raises(ModelUncertain):
        _ok().model(limit=10).complete(REQUEST)


def test_a_body_without_a_declared_size_is_cut_off_at_the_limit() -> None:
    class Endless(httpx.SyncByteStream):
        def __init__(self) -> None:
            self.served = 0

        def __iter__(self) -> Iterator[bytes]:
            while True:
                self.served += 1
                yield b"x" * 1_000

    stream = Endless()
    recorder = Recorder(lambda _request: httpx.Response(200, stream=stream))

    with pytest.raises(ModelUncertain):
        recorder.model(limit=5_000).complete(REQUEST)

    assert stream.served <= 7


def test_a_body_that_drips_past_the_deadline_is_uncertain() -> None:
    class Slow(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            for _ in range(20):
                time.sleep(0.05)
                yield b" "

    recorder = Recorder(lambda _request: httpx.Response(200, stream=Slow()))

    started = time.monotonic()
    with pytest.raises(ModelUncertain):
        recorder.model(timeout=0.2).complete(REQUEST)

    assert time.monotonic() - started < 0.8


# Nothing leaks


@pytest.mark.parametrize("status", [None, 400, 401, 402, 429, 500])
def test_no_error_carries_the_provider_text_the_prompt_or_the_key(
    caplog: pytest.LogCaptureFixture, status: int | None
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if status is None:
            raise httpx.ConnectError(f"refused {SENTINEL}", request=request)
        return httpx.Response(status, json={"error": {"message": f"quoted {SENTINEL}"}})

    with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as caught:
        Recorder(respond).model().complete(REQUEST)

    error: BaseException | None = caught.value
    while error is not None:
        for text in (str(error), repr(error), repr(error.args)):
            assert SENTINEL not in text
        error = error.__cause__ or error.__context__
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SENTINEL not in caplog.text


def test_a_malformed_reply_leaves_no_validation_error_behind(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = json.dumps({"choices": [{"message": {"content": SENTINEL}}], "usage": SENTINEL})
    recorder = Recorder(lambda _request: httpx.Response(200, text=body))

    with caplog.at_level(logging.DEBUG), pytest.raises(ModelUncertain) as caught:
        recorder.model().complete(REQUEST)

    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert SENTINEL not in caplog.text


def test_a_successful_call_logs_nothing_of_the_key_the_prompt_or_the_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        _ok().model(base_url=HOSTED).complete(REQUEST)

    assert KEY not in caplog.text
    assert PROMPT not in caplog.text
    assert ANSWER not in caplog.text

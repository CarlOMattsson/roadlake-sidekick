"""The Anthropic model adapter against a mock transport; no network, no real key."""

import json
import logging
from collections.abc import Callable, Iterator

import httpx2
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from sidekick.work.domain.ai_model_port import (
    CallUsage,
    ModelRejected,
    ModelRequest,
    ModelTransient,
    ModelUncertain,
    RejectionKind,
    StopReason,
)
from sidekick.work.infrastructure.anthropic_model import AnthropicModel

SENTINEL = "SENTINEL-4f9a1c"
KEY = f"sk-test-{SENTINEL}"
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}}
REQUEST = ModelRequest(
    system="rules",
    messages=({"role": "user", "content": "brief"},),
    max_tokens=500,
    output_schema=SCHEMA,
)
ANSWER = '{"text": "done"}'


def _message(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-test-1",
        "content": [{"type": "text", "text": ANSWER}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 11,
            "output_tokens": 7,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 5,
        },
    }
    body.update(overrides)
    return body


class Recorder:
    def __init__(self, respond: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.requests: list[httpx2.Request] = []
        self._respond = respond

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._respond(request)

    def model(self, key: str = KEY) -> AnthropicModel:
        client = httpx2.Client(transport=httpx2.MockTransport(self))
        return AnthropicModel(key, "claude-test-1", 30.0, http_client=client)


def _ok(body: dict[str, object] | None = None) -> Recorder:
    return Recorder(lambda _request: httpx2.Response(200, json=body or _message()))


def _status(status: int, headers: dict[str, str] | None = None) -> Recorder:
    error = {"type": "error", "error": {"type": "api_error", "message": f"quoted {SENTINEL}"}}
    return Recorder(lambda _request: httpx2.Response(status, json=error, headers=headers))


def test_the_call_goes_to_the_messages_endpoint_with_the_key() -> None:
    recorder = _ok()

    recorder.model().complete(REQUEST)

    (sent,) = recorder.requests
    assert str(sent.url) == "https://api.anthropic.com/v1/messages"
    assert sent.headers["authorization"] == f"Bearer {KEY}"


def test_the_body_is_one_structured_call_without_tools_or_extras() -> None:
    recorder = _ok()

    recorder.model().complete(REQUEST)

    body = json.loads(recorder.requests[0].content)
    assert body["model"] == "claude-test-1"
    assert body["max_tokens"] == 500
    assert body["system"] == "rules"
    assert body["messages"] == [{"role": "user", "content": "brief"}]
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    for absent in ("tools", "thinking", "speed", "inference_geo", "cache_control"):
        assert absent not in body


def test_the_environment_never_decides_where_the_key_goes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.invalid")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-environment")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-from-environment")
    recorder = _ok()

    recorder.model().complete(REQUEST)

    (sent,) = recorder.requests
    assert sent.url.host == "api.anthropic.com"
    assert sent.headers["authorization"] == f"Bearer {KEY}"


@pytest.fixture
def tracer_provider() -> Iterator[None]:
    previous = trace.get_tracer_provider()
    trace.set_tracer_provider(TracerProvider())
    yield
    trace.set_tracer_provider(previous)


@pytest.mark.usefixtures("tracer_provider")
@pytest.mark.parametrize("environment", [None, "true"])
def test_no_trace_context_is_sent_with_a_tracer_provider_or_the_switch_on(
    monkeypatch: pytest.MonkeyPatch, environment: str | None
) -> None:
    if environment is not None:
        monkeypatch.setenv("ANTHROPIC_OPEN_TELEMETRY", environment)
    recorder = _ok()

    with trace.get_tracer("test").start_as_current_span("outer"):
        recorder.model().complete(REQUEST)

    headers = recorder.requests[0].headers
    assert "traceparent" not in headers
    assert "baggage" not in headers


def test_a_reply_is_mapped_with_its_usage() -> None:
    reply = _ok().model().complete(REQUEST)

    assert reply.stop_reason is StopReason.END_TURN
    assert reply.output_json == ANSWER
    assert reply.model == "claude-test-1"
    assert reply.usage == CallUsage(
        input_tokens=11, output_tokens=7, cache_write_tokens=3, cache_read_tokens=5
    )


def test_text_blocks_are_joined_and_missing_cache_counts_are_zero() -> None:
    body = _message(
        content=[{"type": "text", "text": '{"text": '}, {"type": "text", "text": '"x"}'}],
        usage={"input_tokens": 2, "output_tokens": 1},
    )

    reply = _ok(body).model().complete(REQUEST)

    assert reply.output_json == '{"text": "x"}'
    assert reply.usage == CallUsage(input_tokens=2, output_tokens=1)


def test_a_reply_without_text_has_no_output() -> None:
    reply = _ok(_message(content=[])).model().complete(REQUEST)

    assert reply.output_json is None


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("max_tokens", StopReason.MAX_TOKENS),
        ("refusal", StopReason.REFUSAL),
        ("tool_use", StopReason.OTHER),
        ("pause_turn", StopReason.OTHER),
        (None, StopReason.OTHER),
    ],
)
def test_a_stop_reason_is_mapped(reason: str | None, expected: StopReason) -> None:
    reply = _ok(_message(stop_reason=reason)).model().complete(REQUEST)

    assert reply.stop_reason is expected


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


@pytest.mark.parametrize("status", [429, 503, 529])
def test_a_refusal_before_any_work_may_be_tried_again(status: int) -> None:
    with pytest.raises(ModelTransient):
        _status(status).model().complete(REQUEST)


@pytest.mark.parametrize("status", [500, 502, 504])
def test_a_server_error_that_may_have_done_work_is_uncertain(status: int) -> None:
    with pytest.raises(ModelUncertain):
        _status(status).model().complete(REQUEST)


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, RejectionKind.AUTH),
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
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    for respond in (timeout, broken):
        with pytest.raises(ModelUncertain):
            Recorder(respond).model().complete(REQUEST)


def test_an_unexpected_failure_is_uncertain() -> None:
    def boom(_request: httpx2.Request) -> httpx2.Response:
        raise RuntimeError(f"unexpected {SENTINEL}")

    with pytest.raises(ModelUncertain):
        Recorder(boom).model().complete(REQUEST)


def test_a_status_the_adapter_does_not_know_is_uncertain() -> None:
    with pytest.raises(ModelUncertain):
        _status(409).model().complete(REQUEST)


def test_a_reply_that_is_not_a_message_is_uncertain() -> None:
    recorder = Recorder(lambda _request: httpx2.Response(200, text=f"<html>{SENTINEL}</html>"))

    with pytest.raises(ModelUncertain):
        recorder.model().complete(REQUEST)


@pytest.mark.parametrize("status", [None, 400, 401, 429, 529])
def test_no_error_carries_the_provider_text_or_the_key(
    caplog: pytest.LogCaptureFixture, status: int | None
) -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        if status is None:
            raise httpx2.ConnectError(f"refused {SENTINEL}", request=request)
        error = {"type": "error", "error": {"type": "x", "message": f"quoted {SENTINEL}"}}
        return httpx2.Response(status, json=error)

    with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as caught:
        Recorder(respond).model().complete(REQUEST)

    error: BaseException | None = caught.value
    while error is not None:
        assert SENTINEL not in str(error)
        assert SENTINEL not in repr(error)
        assert SENTINEL not in repr(error.args)
        error = error.__cause__ or error.__context__
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SENTINEL not in caplog.text
    assert KEY not in caplog.text

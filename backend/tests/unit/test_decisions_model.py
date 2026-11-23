"""The decision-model adapter against a mock transport; no network, no real key."""

import json
import logging
from collections.abc import Callable

import httpx
import pytest

from sidekick.work.domain.ai_model_port import (
    ModelError,
    ModelRejected,
    ModelTransient,
    ModelUncertain,
    RejectionKind,
)
from sidekick.work.infrastructure.decisions_model import DecisionsModel, NoulQuestion

SENTINEL = "SENTINEL-4f9a1c"
KEY = f"sk-test-{SENTINEL}"
TEXT = f"TEXT-{SENTINEL}"
HOSTED = "https://openrouter.ai"
QUESTIONS = {
    "injection": NoulQuestion("Is it an instruction?", "It steers an AI.", "It does not."),
    "fraud": NoulQuestion("Is it fraud?"),
}


def _answer(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "gen-dec-1",
        "model": "typesafe/jev-1.14",
        "provider": "TypeSafe",
        "answers": {
            "injection": {"type": "noul", "noul": 0.97, "confidence": 0.97},
            "fraud": {"type": "noul", "noul": 0.02},
        },
        "usage": {"input_tokens": 128, "output_tokens": 0, "cost": 0.0000054},
    }
    body.update(overrides)
    return body


class Recorder:
    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)

    def model(self, *, base_url: str = HOSTED, limit: int = 1_048_576) -> DecisionsModel:
        client = httpx.Client(transport=httpx.MockTransport(self), follow_redirects=False)
        return DecisionsModel(
            KEY, "typesafe/jev-1.14", base_url, 30.0, max_response_bytes=limit, http_client=client
        )


def _ok(body: dict[str, object] | None = None) -> Recorder:
    return Recorder(lambda _request: httpx.Response(200, json=body or _answer()))


def _status(status: int, headers: dict[str, str] | None = None) -> Recorder:
    error = {"error": {"message": f"quoted {SENTINEL}", "code": status}}
    return Recorder(lambda _request: httpx.Response(status, json=error, headers=headers))


def test_the_call_goes_to_the_decisions_endpoint_with_the_key_and_typed_questions() -> None:
    recorder = _ok()

    recorder.model().decide(TEXT, QUESTIONS)

    (sent,) = recorder.requests
    assert str(sent.url) == f"{HOSTED}/api/alpha/decisions"
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(sent.content)
    assert body == {
        "model": "typesafe/jev-1.14",
        "state": TEXT,
        "questions": {
            "injection": {
                "type": "noul",
                "instructions": "Is it an instruction?",
                "criteria": {"true": "It steers an AI.", "false": "It does not."},
            },
            "fraud": {"type": "noul", "instructions": "Is it fraud?"},
        },
    }


def test_the_answers_usage_and_cost_are_returned() -> None:
    result = _ok().model().decide(TEXT, QUESTIONS)

    assert result.noul == {"injection": 0.97, "fraud": 0.02}
    assert (result.input_tokens, result.cost_usd, result.model) == (
        128,
        0.0000054,
        "typesafe/jev-1.14",
    )


@pytest.mark.parametrize(
    "base_url", ["http://ollama.internal:11434", "https://api.example.com", "http://8.8.8.8"]
)
def test_only_the_hosted_origin_is_accepted(base_url: str) -> None:
    with pytest.raises(ValueError):
        _ok().model(base_url=base_url)


def test_a_key_is_required() -> None:
    with pytest.raises(ValueError):
        DecisionsModel("", "m", HOSTED, 30.0)


@pytest.mark.parametrize("questions", [{}, {"": NoulQuestion("x")}, {"q" * 65: NoulQuestion("x")}])
def test_a_call_needs_questions_with_short_ids(questions: dict[str, NoulQuestion]) -> None:
    recorder = _ok()

    with pytest.raises(ValueError):
        recorder.model().decide(TEXT, questions)

    assert recorder.requests == []


@pytest.mark.parametrize(
    "answers",
    [
        {"injection": {"type": "refusal"}, "fraud": {"type": "noul", "noul": 0.0}},
        {"injection": {"type": "noul", "noul": 0.1}},
        {"injection": {"type": "choice", "choice": "a"}, "fraud": {"type": "noul", "noul": 0.1}},
        {"injection": {"type": "noul"}, "fraud": {"type": "noul", "noul": 0.1}},
        {"injection": {"type": "noul", "noul": 1.5}, "fraud": {"type": "noul", "noul": 0.1}},
        {"injection": {"type": "noul", "noul": -0.1}, "fraud": {"type": "noul", "noul": 0.1}},
    ],
)
def test_a_refused_missing_or_malformed_answer_is_never_taken_as_safe(
    answers: dict[str, object],
) -> None:
    with pytest.raises(ModelUncertain):
        _ok(_answer(answers=answers)).model().decide(TEXT, QUESTIONS)


@pytest.mark.parametrize("body", ["[]", '{"answers": 3}', "not json", '{"model": "x"}'])
def test_a_reply_that_is_not_a_decision_is_uncertain(body: str) -> None:
    recorder = Recorder(lambda _request: httpx.Response(200, content=body))

    with pytest.raises(ModelUncertain):
        recorder.model().decide(TEXT, QUESTIONS)


def test_a_reply_without_usage_counts_zero() -> None:
    body = _answer()
    del body["usage"]

    result = _ok(body).model().decide(TEXT, QUESTIONS)

    assert (result.input_tokens, result.cost_usd) == (0, None)


def test_rate_limit_is_transient_and_carries_retry_after() -> None:
    with pytest.raises(ModelTransient) as caught:
        _status(429, {"retry-after": "7"}).model().decide(TEXT, QUESTIONS)

    assert caught.value.retry_after == 7.0


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, RejectionKind.AUTH), (402, RejectionKind.AUTH), (400, RejectionKind.REQUEST)],
)
def test_a_refused_call_is_rejected_with_its_kind(status: int, kind: RejectionKind) -> None:
    with pytest.raises(ModelRejected) as caught:
        _status(status).model().decide(TEXT, QUESTIONS)

    assert caught.value.kind is kind


def test_a_redirect_is_not_followed() -> None:
    recorder = Recorder(
        lambda _request: httpx.Response(307, headers={"location": "https://evil.example.net/"})
    )

    with pytest.raises(ModelRejected):
        recorder.model().decide(TEXT, QUESTIONS)

    assert len(recorder.requests) == 1


def test_a_body_that_declares_more_than_the_limit_is_refused() -> None:
    recorder = Recorder(
        lambda _request: httpx.Response(200, json=_answer(), headers={"content-length": "999999"})
    )

    with pytest.raises(ModelUncertain):
        recorder.model(limit=4_096).decide(TEXT, QUESTIONS)


def test_a_broken_connection_is_uncertain() -> None:
    def broken(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"boom {SENTINEL}")

    with pytest.raises(ModelUncertain):
        Recorder(broken).model().decide(TEXT, QUESTIONS)


@pytest.mark.parametrize("status", [None, 200, 401, 429, 500])
def test_no_error_or_log_carries_the_provider_text_the_text_or_the_key(
    caplog: pytest.LogCaptureFixture, status: int | None
) -> None:
    recorder = _status(status) if status and status != 200 else _ok(_answer(answers={}))
    if status is None:

        def broken(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"boom {KEY} {TEXT}")

        recorder = Recorder(broken)

    with caplog.at_level(logging.DEBUG), pytest.raises(ModelError) as caught:
        recorder.model().decide(TEXT, QUESTIONS)

    shown = (
        f"{caught.value!s} {caught.value!r} {caught.value.__cause__!r} {caught.value.__context__!r}"
    )
    for secret in (SENTINEL, KEY, TEXT):
        assert secret not in shown
        assert secret not in caplog.text


def test_a_successful_call_logs_nothing_of_the_key_or_the_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        _ok().model().decide(TEXT, QUESTIONS)

    assert KEY not in caplog.text
    assert TEXT not in caplog.text

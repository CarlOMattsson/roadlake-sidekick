"""The two checkers and the factory that builds one, against stand-ins for the provider: no network,
no key. What reaches the model is captured and searched for what must never reach it."""

import json
import os
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from sidekick.automations.domain.checking import (
    CheckContext,
    CheckItem,
    CheckThresholds,
    ReasonCode,
    check_item,
)
from sidekick.automations.domain.datapoints import Datapoint, DatapointKind, SourceKind
from sidekick.automations.domain.suggestion import Verdict
from sidekick.automations.infrastructure.checkers import (
    ChatChecker,
    DecisionsChecker,
    build_suggestion_checker,
)
from sidekick.shared.config import Settings
from sidekick.shared.errors import RefusedError
from sidekick.shared.types import new_uuid7
from sidekick.work.domain.ai_cost import ModelPrice
from sidekick.work.domain.ai_model_port import (
    CallUsage,
    ModelRejected,
    ModelRequest,
    ModelResponse,
    ModelTransient,
    ModelUncertain,
    RejectionKind,
    StopReason,
)
from sidekick.work.domain.ai_runs import CostSource
from sidekick.work.infrastructure.decisions_model import DecisionsModel
from tests.support.automations import DATAPOINT_ID, NOW, parsed_task, suggestion

CANARY = "CANARY-7b30"
KEY = "sk-or-" + "k" * 30
HOSTED = "https://openrouter.ai"
JEV = "typesafe/jev-1.14"
CONTEXT = CheckContext("Morning mail", "Collect requests", ("mail",), ("create_task",))
THRESHOLDS = CheckThresholds(uncertain=0.10, suspicious=0.30)
PRICE = ModelPrice(Decimal("0.042"), Decimal(0), Decimal(0), Decimal(0))
CHAT_PRICE = ModelPrice(Decimal(2), Decimal(10), Decimal(0), Decimal(0))


@pytest.fixture(autouse=True)
def no_ai_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in [name for name in os.environ if name.startswith("SIDEKICK_AI_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def _item(title: str = "Call the dentist") -> CheckItem:
    point = Datapoint(
        id=DATAPOINT_ID,
        owner_id=new_uuid7(),
        run_id=new_uuid7(),
        automation_id=new_uuid7(),
        kind=DatapointKind.PERSON,
        fields={"name": f"Field {CANARY}"},
        source_kind=SourceKind.MAIL,
        source_fingerprint="f" * 64,
        source_label="Mail from Anna",
        source_received_at=NOW,
        created_at=NOW,
        purge_after=NOW,
    )
    card = suggestion(
        verdict=None, rationale=f"Rationale {CANARY}", parsed=parsed_task(title=title)
    )
    return check_item(card, {DATAPOINT_ID: point})


# The decision model


def _jev(
    injection: float = 0.01,
    fraud: float = 0.02,
    *,
    usage: dict[str, Any] | None = None,
    status: int = 200,
    seen: list[httpx.Request] | None = None,
) -> DecisionsChecker:
    body = {
        "model": JEV,
        "answers": {
            "injection": {"type": "noul", "noul": injection},
            "fraud": {"type": "noul", "noul": fraud},
        },
        "usage": usage if usage is not None else {"input_tokens": 200, "cost": 0.0000084},
    }

    def respond(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if status == 200 else {})

    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    model = DecisionsModel(KEY, JEV, HOSTED, 30.0, http_client=client)
    return DecisionsChecker(model, JEV, PRICE, THRESHOLDS)


def test_a_decision_model_checks_one_proposal_and_its_probabilities_become_the_verdict() -> None:
    item = _item()

    call = _jev(0.01, 0.02).check(CONTEXT, [item])

    assert call.answers is not None
    answer = call.answers[item.suggestion_id]
    assert (answer.verdict, answer.confidence, answer.reason_codes) == (Verdict.OK, 98, ())


def test_a_risky_probability_is_suspicious_with_its_reason_code() -> None:
    item = _item()

    call = _jev(0.92, 0.01).check(CONTEXT, [item])

    assert call.answers is not None
    answer = call.answers[item.suggestion_id]
    assert answer.verdict is Verdict.SUSPICIOUS
    assert answer.reason_codes == (ReasonCode.INSTRUCTION_LIKE_TEXT,)


def test_the_provider_reported_cost_is_booked_rounded_up() -> None:
    call = _jev(usage={"input_tokens": 200, "cost": 0.0000084}).check(CONTEXT, [_item()])

    assert call.usage.input_tokens == 200
    assert call.usage.cost_microusd == 9  # 8.4 micro-dollars, rounded up
    assert call.usage.cost_source is CostSource.PROVIDER


def test_without_a_reported_cost_the_price_table_prices_the_input() -> None:
    call = _jev(usage={"input_tokens": 1_000_000}).check(CONTEXT, [_item()])

    assert call.usage.cost_microusd == 42_000
    assert call.usage.cost_source is CostSource.PRICE_TABLE


def test_the_reservation_covers_the_cost_of_the_call() -> None:
    item = _item()
    checker = _jev(usage={"input_tokens": 400})

    reserve = checker.reserve_microusd(CONTEXT, [item])
    call = checker.check(CONTEXT, [item])

    assert reserve >= call.usage.cost_microusd > 0


def test_the_model_is_asked_about_the_proposal_and_never_the_rationale_or_the_fields() -> None:
    seen: list[httpx.Request] = []

    _jev(seen=seen).check(CONTEXT, [_item("Pay the invoice")])

    (request,) = seen
    body = json.loads(request.content)
    assert body["model"] == JEV
    assert set(body["questions"]) == {"injection", "fraud"}
    assert "Pay the invoice" in body["state"]
    assert "Morning mail" in body["state"]
    assert CANARY not in request.content.decode()
    assert KEY not in request.content.decode()
    assert request.headers["authorization"] == f"Bearer {KEY}"


def test_a_decision_checker_takes_one_proposal_per_call() -> None:
    assert _jev().max_batch == 1


@pytest.mark.parametrize(
    ("status", "error"),
    [(429, ModelTransient), (401, ModelRejected), (400, ModelRejected), (500, ModelUncertain)],
)
def test_a_failed_call_raises_the_ports_error(status: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        _jev(status=status).check(CONTEXT, [_item()])


# The chat model


class FakePort:
    def __init__(self, respond: Callable[[ModelRequest], ModelResponse]) -> None:
        self.requests: list[ModelRequest] = []
        self._respond = respond

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self._respond(request)


def _chat(
    answer: Callable[[list[str]], str | None],
    *,
    stop: StopReason = StopReason.END_TURN,
    cost_source: CostSource = CostSource.PRICE_TABLE,
) -> tuple[ChatChecker, FakePort]:
    def respond(request: ModelRequest) -> ModelResponse:
        listed = json.loads(request.messages[0]["content"].splitlines()[-1])
        ids = [entry["id"] for entry in listed]
        return ModelResponse(
            stop, answer(ids), CallUsage(input_tokens=1_000, output_tokens=100), "m"
        )

    port = FakePort(respond)
    return ChatChecker(port, "anthropic", "claude-sonnet-5-5", CHAT_PRICE, cost_source), port


def _all_ok(ids: list[str]) -> str:
    return json.dumps(
        {
            "checks": [
                {"id": item, "verdict": "ok", "confidence": 96, "reason_codes": []} for item in ids
            ]
        }
    )


def test_a_chat_model_checks_a_batch_in_one_call() -> None:
    items = [_item(f"Task {number}") for number in range(5)]
    checker, port = _chat(_all_ok)

    call = checker.check(CONTEXT, items)

    assert len(port.requests) == 1
    assert call.answers is not None
    assert set(call.answers) == {item.suggestion_id for item in items}
    assert call.usage.input_tokens == 1_000
    assert call.usage.cost_microusd == 3_000  # 1000 * 2 + 100 * 10
    assert checker.max_batch == 25


def test_the_chat_request_carries_the_schema_and_nothing_the_checker_may_not_see() -> None:
    checker, port = _chat(_all_ok)

    checker.check(CONTEXT, [_item()])

    (request,) = port.requests
    sent = request.system + request.messages[0]["content"]
    assert CANARY not in sent
    assert "Rationale" not in sent
    assert request.output_schema["required"] == ["checks"]
    assert request.max_tokens >= 256


def test_the_chat_reservation_covers_the_most_the_call_can_cost() -> None:
    items = [_item()]
    checker, _ = _chat(_all_ok)

    reserve = checker.reserve_microusd(CONTEXT, items)
    request_max = (len(items) * 96 + 256) * 10  # the answer filling its limit, at the output price

    assert reserve > request_max


@pytest.mark.parametrize(
    "answer",
    [
        lambda ids: None,
        lambda ids: "not json",
        lambda ids: json.dumps({"checks": []}),
        lambda ids: _all_ok([*ids, str(new_uuid7())]),
    ],
)
def test_an_unusable_answer_has_no_answers_but_its_cost_is_kept(
    answer: Callable[[list[str]], str | None],
) -> None:
    checker, _ = _chat(answer)

    call = checker.check(CONTEXT, [_item()])

    assert call.answers is None
    assert call.usage.cost_microusd == 3_000


@pytest.mark.parametrize("stop", [StopReason.MAX_TOKENS, StopReason.REFUSAL, StopReason.OTHER])
def test_a_cut_off_or_refused_answer_is_not_used(stop: StopReason) -> None:
    checker, _ = _chat(_all_ok, stop=stop)

    assert checker.check(CONTEXT, [_item()]).answers is None


def test_a_local_model_is_booked_as_costing_nothing() -> None:
    checker, _ = _chat(_all_ok, cost_source=CostSource.NONE)

    call = checker.check(CONTEXT, [_item()])

    assert call.usage.cost_source is CostSource.NONE


# The factory


def settings(**fields: Any) -> Settings:
    return Settings(_env_file=None, **fields)


def test_no_checker_is_built_while_the_check_is_off() -> None:
    assert build_suggestion_checker(settings()) is None


def test_a_decision_model_is_built_with_its_price_and_thresholds() -> None:
    checker = build_suggestion_checker(
        settings(
            ai_check_provider="openai_compat",
            ai_check_mode="decisions",
            ai_check_model=JEV,
            ai_check_base_url=HOSTED,
            ai_check_api_key=KEY,
            ai_check_uncertain_threshold=0.2,
            ai_check_suspicious_threshold=0.5,
        )
    )

    assert isinstance(checker, DecisionsChecker)
    assert checker.model == JEV
    assert checker.kind == "openai_compat"
    assert checker.thresholds == CheckThresholds(0.2, 0.5)
    assert checker.price == PRICE  # the built-in price of the model


def test_a_decision_model_without_a_key_refuses_to_start() -> None:
    with pytest.raises(RefusedError, match="no key"):
        build_suggestion_checker(
            settings(
                ai_check_provider="openai_compat",
                ai_check_mode="decisions",
                ai_check_model=JEV,
                ai_check_base_url=HOSTED,
            )
        )


def test_a_decision_model_without_a_price_refuses_to_start() -> None:
    with pytest.raises(RefusedError, match="no built-in price"):
        build_suggestion_checker(
            settings(
                ai_check_provider="openai_compat",
                ai_check_mode="decisions",
                ai_check_model="vendor/unpriced",
                ai_check_base_url=HOSTED,
                ai_check_api_key=KEY,
            )
        )


def test_a_chat_model_is_built_from_the_check_model_settings() -> None:
    checker = build_suggestion_checker(
        settings(
            ai_check_provider="openai_compat",
            ai_check_model="llama3.3",
            ai_check_base_url="http://ollama.internal:11434",
        )
    )

    assert isinstance(checker, ChatChecker)
    assert checker.kind == "openai_compat"
    assert checker.cost_source is CostSource.NONE


def test_the_rejection_kinds_are_the_ones_the_check_service_handles() -> None:
    assert {kind.value for kind in RejectionKind} == {"auth", "request"}

"""The checkers: a decision model that answers yes/no questions, and a chat model that answers
with JSON. Both behind the one interface the check use case calls, and both built from the
settings in one place.

Only the AI worker builds one, because only it may hold a key. A call that fails raises one of
the model port's errors, which carry nothing of the request, the key or the provider's text. A
call that was made but gave no usable answer returns no answers and its cost. Nothing here logs.
"""

from collections.abc import Sequence
from decimal import ROUND_CEILING, Decimal
from typing import Final, Protocol

from sidekick.automations.domain.checking import (
    CHECK_SYSTEM_PROMPT,
    MAX_CHECK_BATCH,
    RISK_QUESTIONS,
    CheckAnswerError,
    CheckContext,
    CheckerCall,
    CheckItem,
    CheckThresholds,
    answer_from_probabilities,
    check_schema,
    parse_chat_answers,
    render_batch,
    render_state,
)
from sidekick.shared.config import Settings
from sidekick.shared.errors.core import RefusedError
from sidekick.work.domain.ai_cost import ModelPrice, call_cost, call_reserve, price_for
from sidekick.work.domain.ai_model_port import CallUsage, ModelPort, ModelRequest, StopReason
from sidekick.work.domain.ai_runs import AiUsage, CostSource
from sidekick.work.infrastructure.check_model import build_check_model
from sidekick.work.infrastructure.decisions_model import DecisionsModel, NoulQuestion

MICROUSD_PER_USD: Final = 1_000_000
ANSWER_TOKENS_BASE: Final = 256
ANSWER_TOKENS_PER_ITEM: Final = 96


class SuggestionChecker(Protocol):
    """A model that checks proposals, as the check use case sees it."""

    kind: str
    """`anthropic` or `openai_compat`: what a check row records as the checker."""
    model: str
    max_batch: int
    cost_source: CostSource

    def reserve_microusd(self, context: CheckContext, items: Sequence[CheckItem]) -> int:
        """The most a call that checks `items` can cost."""
        ...

    def check(self, context: CheckContext, items: Sequence[CheckItem]) -> CheckerCall:
        """One call over at most `max_batch` items. Raises one of the model port's errors."""
        ...


class DecisionsChecker:
    """Asks a decision model the risk questions about one proposal at a time, as the model is
    calibrated on one text at a time, and reads the probabilities against the thresholds."""

    kind = "openai_compat"
    max_batch = 1
    cost_source = CostSource.PRICE_TABLE

    def __init__(
        self,
        model: DecisionsModel,
        name: str,
        price: ModelPrice,
        thresholds: CheckThresholds,
    ) -> None:
        self._model = model
        self.model = name
        self.price = price
        self.thresholds = thresholds
        self._questions = {
            question.id: NoulQuestion(question.instructions, question.yes, question.no)
            for question in RISK_QUESTIONS
        }
        self._question_bytes = sum(
            len(question.instructions.encode())
            + len((question.yes or "").encode())
            + len((question.no or "").encode())
            for question in self._questions.values()
        )

    def reserve_microusd(self, context: CheckContext, items: Sequence[CheckItem]) -> int:
        state_bytes = sum(len(render_state(context, item).encode()) for item in items)
        return call_reserve(state_bytes + self._question_bytes, 0, self.price)

    def check(self, context: CheckContext, items: Sequence[CheckItem]) -> CheckerCall:
        (item,) = items
        result = self._model.decide(render_state(context, item), self._questions)
        if result.cost_usd is not None:
            cost = _micro(result.cost_usd)
            source = CostSource.PROVIDER
        else:
            cost = call_cost(CallUsage(input_tokens=result.input_tokens), self.price)
            source = CostSource.PRICE_TABLE
        usage = AiUsage(
            input_tokens=result.input_tokens, cost_microusd=cost, cost_source=source, model=None
        )
        try:
            answer = answer_from_probabilities(result.noul, self.thresholds)
        except CheckAnswerError:
            return CheckerCall(None, usage)
        return CheckerCall({item.suggestion_id: answer}, usage)


class ChatChecker:
    """Asks a chat model for a JSON answer about up to 25 proposals in one call."""

    max_batch = MAX_CHECK_BATCH

    def __init__(
        self, port: ModelPort, kind: str, name: str, price: ModelPrice, cost_source: CostSource
    ) -> None:
        self._port = port
        self.kind = kind
        self.model = name
        self.price = price
        self.cost_source = cost_source

    def _request(self, context: CheckContext, items: Sequence[CheckItem]) -> ModelRequest:
        return ModelRequest(
            system=CHECK_SYSTEM_PROMPT,
            messages=({"role": "user", "content": render_batch(context, items)},),
            max_tokens=ANSWER_TOKENS_BASE + ANSWER_TOKENS_PER_ITEM * len(items),
            output_schema=check_schema(),
        )

    def reserve_microusd(self, context: CheckContext, items: Sequence[CheckItem]) -> int:
        request = self._request(context, items)
        return call_reserve(request.size_bytes(), request.max_tokens, self.price)

    def check(self, context: CheckContext, items: Sequence[CheckItem]) -> CheckerCall:
        response = self._port.complete(self._request(context, items))
        usage = AiUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_tokens,
            cache_write_tokens=response.usage.cache_write_tokens,
            cost_microusd=call_cost(response.usage, self.price),
            cost_source=self.cost_source,
            model=None,
        )
        if response.stop_reason is not StopReason.END_TURN or response.output_json is None:
            return CheckerCall(None, usage)
        try:
            answers = parse_chat_answers(
                response.output_json, [item.suggestion_id for item in items]
            )
        except CheckAnswerError:
            return CheckerCall(None, usage)
        return CheckerCall(answers, usage)


def build_suggestion_checker(settings: Settings) -> SuggestionChecker | None:
    """The configured checker, None while the check is off, or the refusal to start."""

    if settings.ai_check_provider == "off":
        return None
    if settings.ai_check_mode == "decisions":
        return _decisions_checker(settings)
    built = build_check_model(settings)
    if built is None:  # not reachable while the provider is not off; narrows the type
        return None
    return ChatChecker(built.port, built.provider, built.name, built.price, built.cost_source)


def _decisions_checker(settings: Settings) -> DecisionsChecker:
    key = settings.ai_check_api_key
    if key is None:
        raise RefusedError(
            "the AI check uses a decision model but SIDEKICK_AI_CHECK_API_KEY_FILE gives no key"
        )
    name = settings.ai_check_model
    price = price_for(
        name,
        input=settings.ai_check_price_input_usd_per_mtok,
        output=settings.ai_check_price_output_usd_per_mtok,
        cache_write=settings.ai_check_price_cache_write_usd_per_mtok,
        cache_read=settings.ai_check_price_cache_read_usd_per_mtok,
    )
    if price is None:
        raise RefusedError(
            "the check model has no built-in price; "
            "set all four SIDEKICK_AI_CHECK_PRICE_* variables"
        )
    model = DecisionsModel(
        key.get_secret_value(),
        name,
        settings.ai_check_base_url,
        settings.ai_request_timeout_seconds,
        max_response_bytes=settings.ai_check_max_response_bytes,
    )
    thresholds = CheckThresholds(
        settings.ai_check_uncertain_threshold, settings.ai_check_suspicious_threshold
    )
    return DecisionsChecker(model, name, price, thresholds)


def _micro(usd: float) -> int:
    """A provider's cost in dollars as whole micro-dollars, rounded up like every other cost."""

    return int((Decimal(str(usd)) * MICROUSD_PER_USD).to_integral_value(rounding=ROUND_CEILING))

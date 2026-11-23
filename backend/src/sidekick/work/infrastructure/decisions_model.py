"""The decision-model adapter: typed yes/no questions about a text, answered with probabilities.

A decision model (TypeSafe's Jev on OpenRouter) does not write text. It takes a state and a set of
typed questions and returns, per question, a probability. This adapter asks yes/no (`noul`)
questions only, through OpenRouter's Decisions endpoint, and holds the same guarantees as the chat
adapter it shares its reading code with: the hosted origin only, no redirect, no proxy from the
environment, a bounded body read against one deadline, and failures that become the port's errors
and carry nothing of the request, the key or the provider's text. A refused, missing or malformed
answer is a failure, never "safe". Nothing here logs.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from sidekick.shared.private_endpoint import is_hosted_model_url, validate_model_base_url
from sidekick.work.domain.ai_model_port import ModelError, ModelUncertain
from sidekick.work.infrastructure.openai_compat_model import (
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MAX_RESPONSE_BYTES,
    MAX_MODEL_NAME_CHARS,
    read_json,
    status_failure,
)

_DECISIONS_PATH: Final = "/api/alpha/decisions"
MAX_QUESTION_ID_CHARS = 64


@dataclass(frozen=True, slots=True)
class NoulQuestion:
    """One yes/no question; `yes` and `no` optionally say what each answer means."""

    instructions: str
    yes: str | None = None
    no: str | None = None

    def body(self) -> dict[str, object]:
        question: dict[str, object] = {"type": "noul", "instructions": self.instructions}
        if self.yes is not None and self.no is not None:
            question["criteria"] = {"true": self.yes, "false": self.no}
        return question


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """The probability of yes per question id, and what the call used."""

    noul: Mapping[str, float]
    input_tokens: int
    cost_usd: float | None
    model: str


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    noul: float | None = None


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    input_tokens: int | None = None
    cost: float | None = None


class _Decision(BaseModel):
    model_config = ConfigDict(extra="ignore")
    answers: dict[str, _Answer]
    usage: _Usage | None = None
    model: str | None = None


class DecisionsModel:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        http_client: httpx.Client | None = None,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("the response size limit must be positive")
        if not api_key:
            raise ValueError("a decision model needs a key")
        # The Decisions endpoint exists on the hosted origin only; a private server is refused.
        origin = validate_model_base_url(base_url, label="AI decision model")
        if not is_hosted_model_url(origin):
            raise ValueError("the decision model must be reached through the hosted origin")
        self._url = origin + _DECISIONS_PATH
        self._model = model
        self._max_response_bytes = max_response_bytes
        self._timeout_seconds = timeout_seconds
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        # No proxy from the environment and no redirect: the key goes only to the validated origin.
        self._client = http_client or httpx.Client(trust_env=False, follow_redirects=False)

    def decide(self, state: str, questions: Mapping[str, NoulQuestion]) -> DecisionResult:
        """One call. Raises one of the port's errors; never returns a partial answer."""

        if not questions or any(
            not 0 < len(question_id) <= MAX_QUESTION_ID_CHARS for question_id in questions
        ):
            raise ValueError("a decision call needs questions with short ids")
        failure: ModelError
        try:
            return self._call(state, questions)
        except ModelError as error:
            failure = error
        except Exception:
            failure = ModelUncertain()
        # Raised outside the handler: the library's exception is neither the cause nor the context.
        raise failure from None

    def _call(self, state: str, questions: Mapping[str, NoulQuestion]) -> DecisionResult:
        deadline = monotonic() + self._timeout_seconds
        body = {
            "model": self._model,
            "state": state,
            "questions": {name: question.body() for name, question in questions.items()},
        }
        built = self._client.build_request(
            "POST",
            self._url,
            headers=self._headers,
            content=json.dumps(body),
            timeout=httpx.Timeout(
                self._timeout_seconds, connect=min(CONNECT_TIMEOUT_SECONDS, self._timeout_seconds)
            ),
        )
        response = self._client.send(built, stream=True)
        try:
            status = response.status_code
            if not 200 <= status < 300:
                raise status_failure(status, response.headers)
            payload = read_json(response, deadline, self._max_response_bytes)
        finally:
            response.close()
        return _result(payload, tuple(questions), self._model)


def _result(payload: object, asked: tuple[str, ...], configured_model: str) -> DecisionResult:
    decision: _Decision | None
    try:
        decision = _Decision.model_validate(payload)
    except ValidationError:
        decision = None
    # Raised outside the handler: pydantic's error quotes the input, so it must not be the context.
    if decision is None:
        raise ModelUncertain()
    noul: dict[str, float] = {}
    for question_id in asked:
        answer = decision.answers.get(question_id)
        # A refusal, a missing answer or an unexpected type is not evidence that a text is safe.
        if answer is None or answer.type != "noul" or answer.noul is None:
            raise ModelUncertain()
        if not 0.0 <= answer.noul <= 1.0:  # also rejects NaN
            raise ModelUncertain()
        noul[question_id] = answer.noul
    usage = decision.usage or _Usage()
    return DecisionResult(
        noul=noul,
        input_tokens=max(usage.input_tokens or 0, 0),
        cost_usd=usage.cost if usage.cost is not None and usage.cost >= 0 else None,
        model=(decision.model or configured_model)[:MAX_MODEL_NAME_CHARS],
    )

"""Helpers for the AI runner tests: a scripted model, a container with the runner on, a runner."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sidekick.activity.application.service import ActivityLedger
from sidekick.activity.persistence import ActivityStore
from sidekick.api.app import Container
from sidekick.shared.types import SystemClock
from sidekick.work.application.ai_runner import AiRunnerService
from sidekick.work.application.ai_store import AiLimits, ServerRunnerConfig
from sidekick.work.domain.ai_model_port import (
    CallUsage,
    ModelError,
    ModelRequest,
    ModelResponse,
    StopReason,
)
from sidekick.work.persistence.store import SqlWorkStore
from tests.support.ai_steps import container_with

MODEL = "claude-opus-5-5"
DEFAULT_USAGE = CallUsage(input_tokens=1_000, output_tokens=200)

Step = ModelResponse | ModelError | Callable[[ModelRequest], ModelResponse | ModelError]


def answer(
    outcome: str = "result",
    *,
    text: str = "The pharmacy opens at nine.",
    summary: str = "Opens at nine",
    question: str = "",
    failure: str = "none",
    checklist: Sequence[dict[str, object]] = (),
    usage: CallUsage = DEFAULT_USAGE,
    stop_reason: StopReason = StopReason.END_TURN,
) -> ModelResponse:
    """A model answer in the schema the runner asks for."""

    body = {
        "outcome": outcome,
        "text": text,
        "summary": summary,
        "question": question,
        "failure": failure,
        "checklist": list(checklist),
    }
    return ModelResponse(stop_reason, json.dumps(body), usage, MODEL)


@dataclass
class FakeModel:
    """A `ModelPort` that plays a script: one entry per call, an error entry is raised.

    An entry may be a function of the request, which can also change the world (edit the plan,
    cancel the run) before it answers. The last entry repeats when the script runs out.
    """

    script: list[Step] = field(default_factory=lambda: [answer()])
    requests: list[ModelRequest] = field(default_factory=list[ModelRequest])

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        step = self.script[min(len(self.requests), len(self.script)) - 1]
        outcome = step(request) if callable(step) else step
        if isinstance(outcome, ModelError):
            raise outcome
        return outcome

    @property
    def calls(self) -> int:
        return len(self.requests)


def runner_container(**settings: object) -> Container:
    """A container whose settings turn the server runner on."""

    return container_with(ai_runner_enabled=True, **settings)


def make_runner(
    container: Container,
    model: FakeModel,
    *,
    sleeps: list[float] | None = None,
    stopping: Callable[[], bool] = lambda: False,
) -> AiRunnerService:
    """The runner the worker builds, over the container's database and a fake model."""

    settings = container.settings
    factory = container.session_factory
    waited = sleeps if sleeps is not None else []
    return AiRunnerService(
        SqlWorkStore(factory, container.telemetry),
        SystemClock(),
        AiLimits.from_settings(settings),
        ServerRunnerConfig.from_settings(settings),
        model,
        owner_timezone=settings.owner_zone,
        telemetry=container.telemetry,
        activity=ActivityLedger(ActivityStore(factory, container.telemetry)),
        sleep=waited.append,
        stopping=stopping,
    )

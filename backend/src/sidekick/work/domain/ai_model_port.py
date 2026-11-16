"""The port between an AI Step run and the model that answers it.

A run makes one structured call: the fixed rules, the step's brief and a JSON schema go in, a JSON
answer and the call's token counts come out. The model has no tools. An adapter (one per provider)
turns its provider's failures into the three errors below, so the runner decides what a failure
costs and whether to try again without knowing the provider.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sidekick.shared.errors.core import SidekickError


class StopReason(StrEnum):
    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"
    OTHER = "other"
    """Any other reason the provider gave; the answer is not used."""


class RejectionKind(StrEnum):
    AUTH = "auth"
    """The key was refused (401, 403): no further run can succeed until it is replaced."""
    REQUEST = "request"
    """The request was refused as malformed or too large, or the model is unknown."""


@dataclass(frozen=True, slots=True)
class CallUsage:
    """What one call used, as the provider counted it."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ModelRequest:
    system: str
    messages: tuple[Mapping[str, str], ...]
    max_tokens: int
    output_schema: Mapping[str, object]

    def size_bytes(self) -> int:
        """The UTF-8 size of everything sent as text, an upper bound of its token count."""

        return (
            len(self.system.encode())
            + sum(len(part.encode()) for message in self.messages for part in message.values())
            + len(json.dumps(self.output_schema).encode())
        )


@dataclass(frozen=True, slots=True)
class ModelResponse:
    stop_reason: StopReason
    output_json: str | None
    usage: CallUsage
    model: str


class ModelPort(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        """One call. Raises one of the errors below; never returns a partial answer."""
        ...


class ModelError(SidekickError):
    """A failed call. The message never carries the provider's text, which may quote the request."""

    code = "model_error"


class ModelTransient(ModelError):
    """The provider refused or failed before doing any work (rate limit, overload): nothing was
    billed and the same call may be tried again after `retry_after` seconds."""

    def __init__(self, retry_after: float = 0.0) -> None:
        super().__init__("the model call may be tried again")
        self.retry_after = retry_after


class ModelUncertain(ModelError):
    """The call may have been billed but gave no answer (timeout, a broken connection)."""

    def __init__(self) -> None:
        super().__init__("the model call ended without an answer")


class ModelRejected(ModelError):
    def __init__(self, kind: RejectionKind) -> None:
        super().__init__(f"the model call was rejected ({kind.value})")
        self.kind = kind

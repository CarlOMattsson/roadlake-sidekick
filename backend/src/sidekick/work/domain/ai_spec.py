"""The validated instruction of an AI Step: who performs it and what it may do (`AiStepSpecV1`).

A Step is performed by the owner or by AI. An AI Step carries a spec that the server validates
and enforces, so tool lists, budgets and effects are rules and not advice. A spec can only name
effects that stay inside Sidekick (`none` or `draft`): sending, buying, deleting and publishing
are never representable, they are Steps the owner performs.
"""

import unicodedata
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)

from sidekick.shared.errors import ValidationError

MAX_PLAN_STEPS = 12
"""The most Steps one plan holds."""
MAX_SPEC_TURNS = 12
MAX_RESULT_CHARS = 32_000
MAX_SPEC_BUDGET_USD = 1_000.0

FIXED_STOP_CONDITIONS: tuple[str, ...] = (
    "a sign-in, a password or a captcha is needed",
    "a payment or a purchase is needed",
    "personal data would have to be entered into a form",
    "anything would have to be sent, bought, deleted or published",
    "the goal is unclear or the instruction contradicts itself",
    "the budget or the number of turns is not enough to finish",
)
"""Added to every brief; a spec cannot remove them."""

_KEPT_CONTROL_CHARACTERS = frozenset("\n\t")
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


class Performer(StrEnum):
    OWNER = "owner"
    AI = "ai"


class ResultFormat(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"
    CHECKLIST = "checklist"
    TABLE = "table"
    EMAIL_DRAFT = "email_draft"


class Capability(StrEnum):
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    READ_TASK_CONTEXT = "read_task_context"
    CODE = "code"


class Effects(StrEnum):
    """What a step may do outside its own result. Nothing leaves Sidekick."""

    NONE = "none"
    DRAFT = "draft"


class RunnerPreference(StrEnum):
    ANY = "any"
    CLAUDE_CODE = "claude_code"
    SERVER = "server"


class Privacy(StrEnum):
    NORMAL = "normal"
    LOCAL_ONLY = "local_only"


def clean_text(value: str, *, multiline: bool = False) -> str:
    """`value` in Unicode form NFC without invisible control characters.

    Zero-width, bidirectional and other format or control characters are the way to hide
    instructions from the person reading a text, so they are removed. Line breaks and tabs stay
    when `multiline`, otherwise they become spaces.
    """

    normalised = unicodedata.normalize("NFC", value)
    kept: list[str] = []
    for character in normalised:
        if character in _KEPT_CONTROL_CHARACTERS:
            kept.append(character if multiline else " ")
        elif unicodedata.category(character) not in _DROPPED_CATEGORIES:
            kept.append(character)
    return "".join(kept)


def _one_line(value: str) -> str:
    return " ".join(clean_text(value).split())


Line = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class AiOutputSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    format: ResultFormat = ResultFormat.TEXT
    max_chars: int = Field(default=8_000, ge=1, le=MAX_RESULT_CHARS)


class AiBudgetSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_usd: float = Field(default=1.0, gt=0, le=MAX_SPEC_BUDGET_USD)
    max_turns: int = Field(default=8, ge=1, le=MAX_SPEC_TURNS)


class AiContextSpec(BaseModel):
    """Which linked records the brief may name; titles and names only, never contact details."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    include_contacts: bool = False
    include_references: bool = False


class AiStepSpecV1(BaseModel):
    """The instruction of one AI Step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec_version: Literal[1] = 1
    goal: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    done_when: Annotated[list[Line], Field(max_length=5)] = Field(default_factory=list)
    output: AiOutputSpec = Field(default_factory=AiOutputSpec)
    capabilities: Annotated[list[Capability], Field(max_length=4)] = Field(
        default_factory=list[Capability]
    )
    effects: Effects = Effects.NONE
    stop_and_ask: Annotated[list[Line], Field(max_length=5)] = Field(default_factory=list)
    runner: RunnerPreference = RunnerPreference.ANY
    privacy: Privacy = Privacy.NORMAL
    budget: AiBudgetSpec = Field(default_factory=AiBudgetSpec)
    context: AiContextSpec = Field(default_factory=AiContextSpec)

    @field_validator("goal", mode="after")
    @classmethod
    def _clean_goal(cls, value: str) -> str:
        cleaned = _one_line(value)
        if not cleaned:
            raise ValueError("the goal cannot be empty")
        return cleaned

    @field_validator("done_when", "stop_and_ask", mode="after")
    @classmethod
    def _clean_conditions(cls, value: list[str]) -> list[str]:
        cleaned = [_one_line(item) for item in value]
        if not all(cleaned):
            raise ValueError("a listed condition cannot be empty")
        return cleaned

    @field_validator("capabilities", mode="after")
    @classmethod
    def _unique_capabilities(cls, value: list[Capability]) -> list[Capability]:
        return sorted(set(value))

    @model_validator(mode="after")
    def _check_combinations(self) -> Self:
        if Capability.CODE in self.capabilities and self.runner is not RunnerPreference.CLAUDE_CODE:
            raise ValueError("code needs runner claude_code")
        if self.privacy is Privacy.LOCAL_ONLY and self.runner is not RunnerPreference.SERVER:
            raise ValueError("local_only needs runner server")
        return self

    def allows_claude_code(self) -> bool:
        """Whether the owner's own Claude Code may run the step."""

        return self.runner in (RunnerPreference.ANY, RunnerPreference.CLAUDE_CODE) and (
            self.privacy is Privacy.NORMAL
        )

    def budget_microusd(self) -> int:
        return round(self.budget.max_usd * 1_000_000)


def parse_spec(raw: object) -> AiStepSpecV1:
    """The spec a stored or sent value describes, or the domain's validation error."""

    try:
        return AiStepSpecV1.model_validate(raw)
    except ValueError as error:
        raise ValidationError(f"invalid AI step spec: {_first_message(error)}") from error


def _first_message(error: ValueError) -> str:
    if isinstance(error, PydanticValidationError):
        details = error.errors(include_input=False, include_url=False)
        if details:
            first = details[0]
            location = ".".join(str(part) for part in first["loc"])
            return f"{location}: {first['msg']}".strip(": ")
    return "invalid"

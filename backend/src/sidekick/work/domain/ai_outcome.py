"""The one structured answer a model gives for an AI Step, and how the server checks it.

The model answers with a JSON object of a fixed schema: a result, a question or a failure. The
server never trusts it: the result's format is the step's own, its length and checklist are checked
against the step, and anything that does not hold is an invalid answer, not a partial one.
"""

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Final, Literal, cast
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.work.domain.ai_runs import (
    AiRunResult,
    ChecklistItem,
    FailureCategory,
    dialog_text,
)
from sidekick.work.domain.ai_spec import AiStepSpecV1

_OUTCOMES: Final = ("result", "question", "failed")
_FAILURES: Final = ("blocked", "unclear_goal", "budget", "other", "none")

OUTCOME_SCHEMA: Final[Mapping[str, object]] = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": list(_OUTCOMES)},
        "text": {"type": "string"},
        "summary": {"type": "string"},
        "question": {"type": "string"},
        "failure": {"type": "string", "enum": list(_FAILURES)},
        "checklist": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"action_id": {"type": "string"}, "done": {"type": "boolean"}},
                "required": ["action_id", "done"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["outcome", "text", "summary", "question", "failure", "checklist"],
    "additionalProperties": False,
}
"""Every field is required and the unused ones are empty, `none` or an empty list: the provider's
structured output has no optional unions."""


@dataclass(frozen=True, slots=True)
class ParsedOutcome:
    kind: Literal["result", "question", "failed"]
    result: AiRunResult | None = None
    question: str | None = None
    failure: FailureCategory | None = None


def _text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValidationError(f"the answer's {key} is not text")
    return value


def _checklist(
    data: Mapping[str, object], action_ids: Collection[UUID]
) -> tuple[ChecklistItem, ...]:
    raw = data.get("checklist")
    if not isinstance(raw, list):
        raise ValidationError("the answer's checklist is not a list")
    items: list[ChecklistItem] = []
    for entry in cast("list[object]", raw):
        if not isinstance(entry, dict):
            raise ValidationError("a checklist entry is malformed")
        fields = cast("Mapping[str, object]", entry)
        done = fields.get("done")
        if not isinstance(done, bool):
            raise ValidationError("a checklist entry is malformed")
        try:
            action_id = UUID(str(fields.get("action_id")))
        except ValueError:
            raise ValidationError("a checklist entry names no action") from None
        if action_id not in action_ids:
            raise ValidationError("the checklist names an action that is not in the step")
        items.append(ChecklistItem(action_id, done))
    return tuple(items)


def parse_outcome(raw: str, spec: AiStepSpecV1, action_ids: Collection[UUID]) -> ParsedOutcome:
    """The outcome the answer holds, or a `ValidationError` when it does not hold the schema or
    the step's limits. The words `outcome` and `failure` are read without regard to case."""

    try:
        data = json.loads(raw)
    except ValueError:
        raise ValidationError("the answer is not JSON") from None
    if not isinstance(data, dict):
        raise ValidationError("the answer is not an object")
    data = cast("Mapping[str, object]", data)
    outcome = _text(data, "outcome").strip().lower()
    if outcome == "result":
        text = _text(data, "text")
        if len(text) > spec.output.max_chars:
            raise ValidationError("the result is longer than the step allows")
        result = AiRunResult(
            format=spec.output.format,
            text=text,
            summary=_text(data, "summary"),
            checklist=_checklist(data, action_ids),
        )
        return ParsedOutcome("result", result=result)
    if outcome == "question":
        return ParsedOutcome(
            "question", question=dialog_text(_text(data, "question"), "a question")
        )
    if outcome == "failed":
        failure = _text(data, "failure").strip().lower()
        if failure not in _FAILURES:
            raise ValidationError("the answer names an unknown failure")
        category = FailureCategory.OTHER if failure == "none" else FailureCategory(failure)
        return ParsedOutcome("failed", failure=category)
    raise ValidationError("the answer names an unknown outcome")

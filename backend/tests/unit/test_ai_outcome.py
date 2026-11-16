"""Database-free unit tests for reading a model's answer: its schema, the step's limits and the
closed set of outcomes."""

import json
from collections.abc import Mapping
from typing import Any, cast

import pytest

from sidekick.shared.errors import ValidationError
from sidekick.shared.types import new_uuid7
from sidekick.work.domain.ai_outcome import OUTCOME_SCHEMA, ParsedOutcome, parse_outcome
from sidekick.work.domain.ai_runs import ChecklistItem, FailureCategory
from sidekick.work.domain.ai_spec import AiStepSpecV1, ResultFormat, parse_spec

ACTION_ID = new_uuid7()
OTHER_ACTION_ID = new_uuid7()
SPEC: AiStepSpecV1 = parse_spec(
    {"goal": "Summarise the notes", "output": {"format": "markdown", "max_chars": 200}}
)
FIELDS = {"outcome", "text", "summary", "question", "failure", "checklist"}


def answer(**fields: Any) -> str:
    """A model answer in the schema: every field empty, `none` or an empty list unless given."""

    base: dict[str, Any] = {
        "outcome": "result",
        "text": "",
        "summary": "",
        "question": "",
        "failure": "none",
        "checklist": [],
    }
    return json.dumps({**base, **fields})


def result_answer(**fields: Any) -> str:
    """A result answer; `fields` replace the default text and summary."""

    return answer(**{"text": "The pharmacy opens at nine.", "summary": "Opens at nine", **fields})


def parse(raw: str) -> ParsedOutcome:
    return parse_outcome(raw, SPEC, (ACTION_ID,))


def _section(schema: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = schema[key]
    assert isinstance(value, dict)
    return cast("Mapping[str, object]", value)


# result


def test_a_result_takes_its_format_from_the_step_not_from_the_answer() -> None:
    parsed = parse(result_answer(format="table"))

    assert parsed.kind == "result"
    assert parsed.result is not None
    assert parsed.result.format is ResultFormat.MARKDOWN
    assert parsed.result.text == "The pharmacy opens at nine."
    assert parsed.result.summary == "Opens at nine"
    assert parsed.result.checklist == ()
    assert parsed.question is None
    assert parsed.failure is None


def test_a_result_of_exactly_the_step_limit_is_kept() -> None:
    parsed = parse(result_answer(text="x" * 200))

    assert parsed.result is not None
    assert len(parsed.result.text) == 200


def test_a_result_longer_than_the_step_allows_is_refused() -> None:
    with pytest.raises(ValidationError):
        parse(result_answer(text="x" * 201))


@pytest.mark.parametrize("summary", ["", "   ", "​"])
def test_a_result_without_a_summary_is_refused(summary: str) -> None:
    with pytest.raises(ValidationError):
        parse(result_answer(summary=summary))


def test_a_result_without_text_is_refused() -> None:
    with pytest.raises(ValidationError):
        parse(result_answer(text=""))


def test_a_checklist_names_the_actions_it_reports_on() -> None:
    parsed = parse(result_answer(checklist=[{"action_id": str(ACTION_ID), "done": True}]))

    assert parsed.result is not None
    assert parsed.result.checklist == (ChecklistItem(ACTION_ID, True),)


def test_a_checklist_naming_an_action_outside_the_step_is_refused() -> None:
    checklist = [{"action_id": str(OTHER_ACTION_ID), "done": True}]

    with pytest.raises(ValidationError):
        parse(result_answer(checklist=checklist))


@pytest.mark.parametrize("action_id", ["not-a-uuid", "", None])
def test_a_checklist_entry_without_a_valid_action_is_refused(action_id: object) -> None:
    with pytest.raises(ValidationError):
        parse(result_answer(checklist=[{"action_id": action_id, "done": True}]))


@pytest.mark.parametrize("done", ["yes", 1, None])
def test_a_checklist_entry_whose_done_is_not_a_boolean_is_refused(done: object) -> None:
    with pytest.raises(ValidationError):
        parse(result_answer(checklist=[{"action_id": str(ACTION_ID), "done": done}]))


def test_a_checklist_that_is_not_a_list_is_refused() -> None:
    with pytest.raises(ValidationError):
        parse(result_answer(checklist={"action_id": str(ACTION_ID), "done": True}))


# question


def test_a_question_carries_its_text_and_no_result() -> None:
    parsed = parse(answer(outcome="question", question="Which city?"))

    assert parsed.kind == "question"
    assert parsed.question == "Which city?"
    assert parsed.result is None
    assert parsed.failure is None


def test_a_question_of_the_maximum_length_is_kept() -> None:
    parsed = parse(answer(outcome="question", question="q" * 1_000))

    assert parsed.question == "q" * 1_000


@pytest.mark.parametrize("question", ["", "   ", "q" * 1_001])
def test_a_question_must_have_one_to_a_thousand_characters(question: str) -> None:
    with pytest.raises(ValidationError):
        parse(answer(outcome="question", question=question))


# failed


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        ("blocked", FailureCategory.BLOCKED),
        ("unclear_goal", FailureCategory.UNCLEAR_GOAL),
        ("budget", FailureCategory.BUDGET),
        ("other", FailureCategory.OTHER),
        ("none", FailureCategory.OTHER),
    ],
)
def test_a_failure_names_its_category_and_none_means_other(
    failure: str, category: FailureCategory
) -> None:
    parsed = parse(answer(outcome="failed", failure=failure))

    assert parsed.kind == "failed"
    assert parsed.failure is category
    assert parsed.result is None
    assert parsed.question is None


@pytest.mark.parametrize("failure", ["tool_error", "provider", "exploded", ""])
def test_a_failure_outside_the_model_vocabulary_is_refused(failure: str) -> None:
    with pytest.raises(ValidationError):
        parse(answer(outcome="failed", failure=failure))


# Reading the words


def test_outcome_and_failure_are_read_without_regard_to_case() -> None:
    assert parse(result_answer(outcome="RESULT")).kind == "result"
    assert parse(answer(outcome="Question", question="Which day?")).kind == "question"

    parsed = parse(answer(outcome=" Failed ", failure="BLOCKED"))

    assert parsed.kind == "failed"
    assert parsed.failure is FailureCategory.BLOCKED


def test_an_unknown_outcome_is_refused() -> None:
    with pytest.raises(ValidationError):
        parse(answer(outcome="maybe"))


def test_an_answer_without_an_outcome_is_refused() -> None:
    with pytest.raises(ValidationError):
        parse(json.dumps({"text": "hello"}))


# Malformed answers


@pytest.mark.parametrize("raw", ["", "{not json", "result"])
def test_an_answer_that_is_not_json_is_refused(raw: str) -> None:
    with pytest.raises(ValidationError):
        parse(raw)


@pytest.mark.parametrize("raw", ["[]", '"result"', "42", "null"])
def test_an_answer_that_is_not_a_json_object_is_refused(raw: str) -> None:
    with pytest.raises(ValidationError):
        parse(raw)


# The schema


def test_the_schema_refuses_extra_fields_at_the_top_and_in_each_checklist_entry() -> None:
    checklist = _section(_section(OUTCOME_SCHEMA, "properties"), "checklist")

    assert OUTCOME_SCHEMA["additionalProperties"] is False
    assert _section(checklist, "items")["additionalProperties"] is False


def test_every_field_is_declared_and_required() -> None:
    required = OUTCOME_SCHEMA["required"]
    assert isinstance(required, list)

    assert set(_section(OUTCOME_SCHEMA, "properties")) == FIELDS
    assert set(cast("list[str]", required)) == FIELDS
    assert len(cast("list[str]", required)) == len(FIELDS)


def test_the_schema_lists_exactly_the_three_outcomes() -> None:
    outcome = _section(_section(OUTCOME_SCHEMA, "properties"), "outcome")

    assert outcome["enum"] == ["result", "question", "failed"]


def test_the_checklist_entries_need_both_an_action_and_a_done_flag() -> None:
    entry = _section(_section(_section(OUTCOME_SCHEMA, "properties"), "checklist"), "items")

    assert set(cast("list[str]", entry["required"])) == {"action_id", "done"}

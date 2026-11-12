"""Closed daily-summary schema and evaluation fixtures."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from sidekick.journal.domain.analysis import ContradictionStatus, Perspective
from sidekick.journal.domain.summary import SummaryContent, validate_content_references

ENTRY_ONE = UUID("01910000-0000-7000-8000-000000000003")
ENTRY_TWO = UUID("01910000-0000-7000-8000-000000000004")


def full_summary_content() -> SummaryContent:
    return SummaryContent(
        overview="Dagen innehöll ett beslut och en plan för uppföljning.",
        overview_entry_ids=[ENTRY_ONE, ENTRY_TWO],
        themes=[
            {
                "title": "Planering",
                "summary": "Nästa steg konkretiserades.",
                "perspective": Perspective.INTERPRETATION,
                "entry_ids": [ENTRY_ONE],
            }
        ],
        important_events=[
            {
                "text": "Ett syntetiskt beslut dokumenterades.",
                "perspective": Perspective.FACT,
                "entry_ids": [ENTRY_ONE],
            }
        ],
        decisions=[
            {
                "text": "Uppföljning sker på fredag.",
                "perspective": Perspective.PLAN,
                "entry_ids": [ENTRY_TWO],
            }
        ],
        commitments=[
            {
                "text": "Underlaget ska förberedas.",
                "perspective": Perspective.PLAN,
                "entry_ids": [ENTRY_TWO],
            }
        ],
        open_questions=[
            {
                "text": "Vilken tid passar uppföljningen?",
                "perspective": Perspective.INTERPRETATION,
                "entry_ids": [ENTRY_ONE, ENTRY_TWO],
            }
        ],
        unresolved_items=[
            {
                "text": "Tidpunkten är ännu inte bekräftad.",
                "perspective": Perspective.FACT,
                "entry_ids": [ENTRY_TWO],
            }
        ],
        contradictions=[
            {
                "description": "Två anteckningar anger olika uppföljningsdagar.",
                "status": ContradictionStatus.UNRESOLVED,
                "resolution": None,
                "entry_ids": [ENTRY_ONE, ENTRY_TWO],
            },
            {
                "description": "En äldre formulering ersattes av ett senare beslut.",
                "status": ContradictionStatus.RESOLVED,
                "resolution": "Det senare beslutet gäller.",
                "entry_ids": [ENTRY_ONE, ENTRY_TWO],
            },
            {
                "description": "En möjlig skillnad behöver mer underlag.",
                "status": ContradictionStatus.POSSIBLY_SUPERSEDED,
                "resolution": None,
                "entry_ids": [ENTRY_ONE, ENTRY_TWO],
            },
        ],
    )


def test_summary_schema_accepts_all_structured_sections_and_entry_only_evidence() -> None:
    content = full_summary_content()
    assert set(content.model_dump()) == {
        "overview",
        "overview_entry_ids",
        "themes",
        "important_events",
        "decisions",
        "commitments",
        "open_questions",
        "unresolved_items",
        "contradictions",
    }
    assert {item.perspective for item in content.themes} == {"interpretation"}
    assert {item.perspective for item in content.important_events} == {"fact"}
    assert {item.perspective for item in content.decisions} == {"plan"}
    assert {item.status for item in content.contradictions} == {
        "unresolved",
        "resolved",
        "possibly_superseded",
    }
    validate_content_references(content, {ENTRY_ONE, ENTRY_TWO})


def test_summary_schema_is_closed_and_rejects_external_or_unknown_content() -> None:
    payload = full_summary_content().model_dump()
    with pytest.raises(ValidationError):
        SummaryContent.model_validate({**payload, "external_facts": ["weather"]})

    invalid_reference = full_summary_content().model_dump()
    invalid_reference["overview_entry_ids"] = [UUID("01910000-0000-7000-8000-000000000099")]
    parsed = SummaryContent.model_validate(invalid_reference)
    with pytest.raises(ValueError, match="outside the active day"):
        validate_content_references(parsed, {ENTRY_ONE, ENTRY_TWO})


def test_summary_json_schema_has_closed_nested_models() -> None:
    schema = SummaryContent.model_json_schema()
    assert schema["additionalProperties"] is False
    definitions = schema["$defs"]
    assert definitions["SummaryTheme"]["additionalProperties"] is False
    assert definitions["SummaryStatement"]["additionalProperties"] is False
    assert definitions["SummaryContradiction"]["additionalProperties"] is False

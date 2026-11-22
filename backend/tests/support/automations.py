"""Builders and the injection corpus for the automation domain tests."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sidekick.automations.domain.effects import (
    EffectKind,
    ParsedPayload,
    PayloadProblem,
    parse_payload,
)
from sidekick.automations.domain.screening import (
    Proposal,
    Screened,
    ScreeningContext,
    ScreeningFlag,
    SourceInfo,
    screen_proposals,
)
from sidekick.automations.domain.spec import ApplyMode, AutomationSpecV1, parse_spec
from sidekick.automations.domain.suggestion import (
    CheckState,
    Suggestion,
    SuggestionState,
    Verdict,
)
from sidekick.shared.types import new_uuid7

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "injection"
OWNER_ID = UUID("00000000-0000-7000-8000-000000000001")
AUTOMATION_ID = UUID("00000000-0000-7000-8000-000000000002")
RUN_ID = UUID("00000000-0000-7000-8000-000000000003")
DATAPOINT_ID = UUID("00000000-0000-7000-8000-000000000004")
SOURCE = SourceInfo(kind="mail", fingerprint="f" * 64, sender_domain="example.se")


def spec(**overrides: Any) -> AutomationSpecV1:
    values: dict[str, Any] = {
        "purpose": "Collect what the morning mail asks of me",
        "instruction": "Read yesterday's mail and propose tasks for requests.",
        "sources": ["mail"],
        "allowed_effects": ["create_task", "create_contact"],
    }
    return parse_spec({**values, **overrides})


def auto_spec(**overrides: Any) -> AutomationSpecV1:
    values: dict[str, Any] = {
        "apply_mode": ApplyMode.AUTO_LOW_RISK,
        "auto_effects": ["create_task"],
        **overrides,
    }
    return spec(**values)


def parsed_task(**overrides: Any) -> ParsedPayload:
    parsed = parse_payload(EffectKind.CREATE_TASK, {"title": "Call the dentist", **overrides})
    assert not isinstance(parsed, PayloadProblem)
    return parsed


def parsed_contact(**overrides: Any) -> ParsedPayload:
    values = {"display_name": "Anna Svensson", "email": "anna@example.se", **overrides}
    parsed = parse_payload(EffectKind.CREATE_CONTACT, values)
    assert not isinstance(parsed, PayloadProblem)
    return parsed


def context(**overrides: Any) -> ScreeningContext:
    values: dict[str, Any] = {
        "allowed_effects": frozenset(EffectKind),
        "run_open": True,
        "max_suggestions": 15,
        "already_recorded": 0,
        "datapoint_sources": {DATAPOINT_ID: SOURCE},
    }
    return ScreeningContext(**{**values, **overrides})


def proposal(effect: str = "create_task", payload: object = None, **overrides: Any) -> Proposal:
    values: dict[str, Any] = {
        "effect": effect,
        "payload": {"title": "Call the dentist"} if payload is None else payload,
        "rationale": "Anna asked for it in the mail",
        "datapoint_refs": (DATAPOINT_ID,),
    }
    return Proposal(**{**values, **overrides})


def screened_one(**proposal_overrides: Any) -> Screened:
    result = screen_proposals([proposal(**proposal_overrides)], context())
    assert result.accepted, result.rejected
    return result.accepted[0]


def suggestion(
    *,
    state: SuggestionState = SuggestionState.PENDING,
    verdict: Verdict | None = Verdict.OK,
    confidence: int | None = 97,
    flags: tuple[ScreeningFlag, ...] = (),
    edited: bool = False,
    effect: EffectKind = EffectKind.CREATE_TASK,
    bulk_eligible: bool = False,
    expires_in: timedelta = timedelta(days=14),
    rationale: str = "why",
    parsed: ParsedPayload | None = None,
) -> Suggestion:
    """A suggestion built directly in a state, the way a stored row is loaded."""

    parsed = parsed or (parsed_task() if effect is EffectKind.CREATE_TASK else parsed_contact())
    checked = verdict is not None
    payload = dict(parsed.data)
    if edited:
        payload["title" if effect is EffectKind.CREATE_TASK else "display_name"] = "Edited"
    return Suggestion(
        id=new_uuid7(),
        owner_id=OWNER_ID,
        automation_id=AUTOMATION_ID,
        run_id=RUN_ID,
        effect=effect,
        effect_version=1,
        payload=payload,
        proposed_payload=parsed.data,
        rationale=rationale,
        datapoint_ids=(DATAPOINT_ID,),
        dedupe_fingerprint="a" * 64,
        state=state,
        expires_at=NOW + expires_in,
        screening_flags=flags,
        check_state=CheckState.CHECKED if checked else CheckState.OFF,
        verdict=verdict,
        confidence=confidence if checked else None,
        bulk_eligible=bulk_eligible,
    )


@dataclass(frozen=True, slots=True)
class CorpusCase:
    name: str
    text: str
    target: str
    flags: frozenset[ScreeningFlag]
    email: str | None
    sender_domain: str | None
    inert: tuple[str, ...]


_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})")


def corpus() -> list[CorpusCase]:
    """The injection corpus. `\\uXXXX` in a text file stands for that character, so the files
    hold no invisible or bidirectional characters; `\\UXXXXXXXX` is a character outside the
    basic plane."""

    expected = json.loads((CORPUS / "expected.json").read_text(encoding="utf-8"))
    cases: list[CorpusCase] = []
    for name, meta in sorted(expected.items()):
        raw = (CORPUS / f"{name}.txt").read_text(encoding="utf-8").rstrip("\n")
        cases.append(
            CorpusCase(
                name=name,
                text=_ESCAPE.sub(lambda match: chr(int(match.group(1) or match.group(2), 16)), raw),
                target=meta["target"],
                flags=frozenset(ScreeningFlag(flag) for flag in meta["flags"]),
                email=meta.get("email"),
                sender_domain=meta.get("sender_domain"),
                inert=tuple(meta.get("inert", ())),
            )
        )
    return cases

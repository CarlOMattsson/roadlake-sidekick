"""The effect catalogue is closed: nothing outside it can be proposed (invariant I1)."""

import pytest

from sidekick.automations.domain import effects
from sidekick.automations.domain.effects import (
    AUTO_APPLY_EFFECTS,
    CATALOGUE,
    EffectKind,
    PayloadProblem,
    effect_schema,
    parse_payload,
    resolve_effect,
    target_key,
)
from sidekick.automations.domain.screening import RejectionCode
from sidekick.shared.auth.service import MCP_SCOPES
from tests.support.automations import parsed_contact, parsed_task


def test_the_catalogue_holds_exactly_the_two_creating_effects() -> None:
    assert {kind.value for kind in EffectKind} == {"create_task", "create_contact"}
    assert set(CATALOGUE) == set(EffectKind)
    assert set(EffectKind) == AUTO_APPLY_EFFECTS
    assert [entry.label for entry in CATALOGUE.values()] == ["create_task.v1", "create_contact.v1"]
    assert all(entry.low_risk for entry in CATALOGUE.values())


def test_every_effect_names_a_write_scope_that_exists() -> None:
    assert all(entry.write_scope in MCP_SCOPES for entry in CATALOGUE.values())


@pytest.mark.parametrize(
    "name",
    [
        "send_email",
        "reply",
        "forward",
        "delete_contact",
        "move_to_trash",
        "complete_task",
        "archive_task",
        "buy",
        "pay_invoice",
        "publish",
        "create_task.v2",
        "create_task.v0",
        "create_task.v1.1",
        "Create_Task",
        "create_task ",
        "create_task\u200b",
        "",
    ],
)
def test_a_name_outside_the_catalogue_does_not_resolve(name: str) -> None:
    assert resolve_effect(name) is None


@pytest.mark.parametrize("name", ["create_task", "create_task.v1"])
def test_a_catalogue_name_resolves_with_or_without_its_current_version(name: str) -> None:
    assert resolve_effect(name) is EffectKind.CREATE_TASK


@pytest.mark.parametrize(
    "extra",
    [
        {"send_to": "boss@example.se"},
        {"recipients": ["a@example.se"]},
        {"confidence": 99},
        {"tags": ["x"]},
        {"contact_ids": ["00000000-0000-7000-8000-000000000009"]},
        {"effect": "send_email"},
    ],
)
def test_a_payload_cannot_carry_more_than_its_schema(extra: dict[str, object]) -> None:
    for kind, base in (
        (EffectKind.CREATE_TASK, {"title": "t"}),
        (EffectKind.CREATE_CONTACT, {"display_name": "Anna"}),
    ):
        assert parse_payload(kind, {**base, **extra}) is PayloadProblem.SCHEMA_INVALID


def test_the_schemas_forbid_extra_properties() -> None:
    for kind in EffectKind:
        assert effect_schema(kind)["additionalProperties"] is False


def test_the_payload_problems_are_rejection_codes() -> None:
    assert {problem.value for problem in PayloadProblem} <= {code.value for code in RejectionCode}


def test_a_task_is_bounded_and_normalised() -> None:
    parsed = parsed_task(
        title="  Call \u200bthe\n dentist\u202e ",
        description="Line one  \nLine <b>two</b>",
        priority="high",
        due_on="2026-12-01",
    )
    assert parsed.data["title"] == "Call the dentist"
    assert parsed.data["description"] == "Line one\nLine \u2039b>two\u2039/b>"
    assert parsed.data["due_on"] == "2026-12-01"
    assert (
        parse_payload(EffectKind.CREATE_TASK, {"title": "x" * 200}) is not PayloadProblem.TOO_LONG
    )
    assert parse_payload(EffectKind.CREATE_TASK, {"title": "x" * 201}) is PayloadProblem.TOO_LONG
    assert (
        parse_payload(EffectKind.CREATE_TASK, {"title": "t", "description": "x" * 2001})
        is PayloadProblem.TOO_LONG
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "\u200b\u202e"},
        {"title": 5},
        {"title": "t", "priority": "urgent"},
        {"title": "t", "due_on": "tomorrow"},
        {"title": "t", "project_id": "not-a-uuid"},
        {},
        "title",
        None,
    ],
)
def test_a_malformed_task_payload_is_refused(payload: object) -> None:
    assert parse_payload(EffectKind.CREATE_TASK, payload) is PayloadProblem.SCHEMA_INVALID


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "no-at-sign"},
        {"email": "a@b@c"},
        {"phone": "call me"},
        {"display_name": ""},
    ],
)
def test_a_malformed_contact_payload_is_refused(overrides: dict[str, object]) -> None:
    payload = {"display_name": "Anna", **overrides}
    assert parse_payload(EffectKind.CREATE_CONTACT, payload) is PayloadProblem.SCHEMA_INVALID


def test_a_contact_is_bounded() -> None:
    parsed = parsed_contact(organization="  Firma\tAB ", role="", phone="+46 70 123 45 67")
    assert parsed.data["organization"] == "Firma AB"
    assert parsed.data["role"] is None
    too_long = parse_payload(
        EffectKind.CREATE_CONTACT, {"display_name": "Anna", "organization": "x" * 201}
    )
    assert too_long is PayloadProblem.TOO_LONG


def test_the_payload_cap_is_stricter_than_the_database_limit() -> None:
    assert effects.MAX_PAYLOAD_BYTES < 8192


def test_a_stored_payload_is_capped_in_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(effects, "MAX_PAYLOAD_BYTES", 40)
    assert parse_payload(EffectKind.CREATE_TASK, {"title": "x" * 100}) is PayloadProblem.TOO_LONG


def test_the_target_survives_case_spacing_and_hidden_characters() -> None:
    assert target_key(parsed_task(title="Call the dentist")) == target_key(
        parsed_task(title="  CALL\u200b the   Dentist ")
    )
    assert target_key(parsed_task(title="Call the dentist")) != target_key(
        parsed_task(title="Call the dentist", project_id="00000000-0000-7000-8000-000000000009")
    )
    assert target_key(parsed_contact(email="Anna@Example.SE")) == target_key(
        parsed_contact(email="anna@example.se", display_name="Another Name")
    )
    assert target_key(parsed_contact(email=None)).startswith("name:")

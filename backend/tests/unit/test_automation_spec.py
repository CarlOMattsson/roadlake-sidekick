"""The spec, its digest and the rule that a changed spec does not run (invariant I4)."""

from typing import Any

import pytest

from sidekick.automations.domain.effects import EffectKind
from sidekick.automations.domain.spec import (
    DEFAULT_RUN_BUDGET_MICROUSD,
    ApprovalDigestMismatchError,
    ApprovalState,
    AutomationSpecV1,
    AutomationState,
    ModelTier,
    NotRunnableCause,
    NotRunnableError,
    approval_state,
    approve,
    auto_confirmed_digest,
    is_auto_apply_confirmed,
    is_runnable,
    missing_write_scopes,
    normalise_title,
    parse_spec,
    require_runnable,
    spec_digest,
)
from sidekick.shared.errors import ValidationError
from tests.support.automations import auto_spec, spec

CADENCE = {"frequency": "daily", "local_time": "07:30"}


def test_the_defaults_are_the_owner_decisions() -> None:
    base = spec()
    assert base.run_budget_microusd == DEFAULT_RUN_BUDGET_MICROUSD == 1_000_000
    assert base.model_tier is ModelTier.STANDARD
    assert (base.bulk_threshold, base.auto_threshold, base.max_suggestions_per_run) == (90, 95, 15)
    assert base.apply_mode.value == "suggest"
    assert base.auto_effects == []


def test_the_digest_is_a_stable_sha256() -> None:
    assert spec_digest(spec()) == spec_digest(spec())
    assert len(spec_digest(spec())) == 64


def test_the_digest_ignores_the_order_the_owner_listed_things_in() -> None:
    first = spec(sources=["mail", "chat"], allowed_effects=["create_task", "create_contact"])
    second = spec(
        sources=["chat", "mail", "chat"], allowed_effects=["create_contact", "create_task"]
    )
    assert spec_digest(first) == spec_digest(second)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "Something else"),
        ("instruction", "Read the mail and also forward it to everyone."),
        ("sources", ["mail", "web"]),
        ("runner", "server"),
        ("cadence", CADENCE),
        ("allowed_effects", ["create_task"]),
        ("bulk_threshold", 85),
        ("auto_threshold", 97),
        ("max_suggestions_per_run", 5),
        ("run_budget_microusd", 2_000_000),
        ("model_tier", "strong"),
    ],
)
def test_every_field_that_steers_a_run_changes_the_digest(field: str, value: Any) -> None:
    assert spec_digest(spec(**{field: value})) != spec_digest(spec())


def test_the_apply_mode_and_the_auto_effects_change_the_digest() -> None:
    assert spec_digest(auto_spec()) != spec_digest(spec())
    assert spec_digest(auto_spec()) != spec_digest(auto_spec(auto_effects=["create_contact"]))


def test_a_cadence_is_part_of_the_digest_and_is_normalised() -> None:
    weekly = {"frequency": "weekly", "weekdays": [4, 0], "local_time": "07:30"}
    same = {"frequency": "weekly", "weekdays": [0, 4], "local_time": "07:30"}
    assert spec_digest(spec(cadence=weekly)) == spec_digest(spec(cadence=same))
    assert spec_digest(spec(cadence=weekly)) != spec_digest(
        spec(cadence={**weekly, "local_time": "08:00"})
    )


def test_title_state_and_pause_are_not_in_the_spec_so_they_cannot_change_the_digest() -> None:
    assert not {"title", "state", "paused", "archived"} & set(AutomationSpecV1.model_fields)
    for field in ("title", "state", "paused"):
        with pytest.raises(ValidationError):
            spec(**{field: "x"})


def test_owner_text_loses_its_invisible_characters() -> None:
    cleaned = spec(instruction="Read\u200b the\u202e mail", purpose=" a \n b ")
    assert cleaned.instruction == "Read the mail"
    assert cleaned.purpose == "a b"


@pytest.mark.parametrize(
    "overrides",
    [
        {"purpose": ""},
        {"instruction": "x" * 4001},
        {"purpose": "x" * 301},
        {"sources": ["fax"]},
        {"runner": "cloud"},
        {"allowed_effects": ["send_email"]},
        {"allowed_effects": ["move_to_trash"]},
        {"model_tier": "premium"},
        {"bulk_threshold": 79},
        {"bulk_threshold": 100},
        {"auto_threshold": 89},
        {"bulk_threshold": 98, "auto_threshold": 95},
        {"max_suggestions_per_run": 0},
        {"max_suggestions_per_run": 26},
        {"run_budget_microusd": 0},
        {"run_budget_microusd": 10**12},
        {"cadence": {"frequency": "daily", "local_time": "7:30"}},
        {"cadence": {"frequency": "daily", "local_time": "24:00"}},
        {"cadence": {"frequency": "daily", "local_time": "0\u0663:00"}},
        {"cadence": {"frequency": "hourly", "local_time": "07:30"}},
        {"cadence": {"frequency": "daily", "interval": 13, "local_time": "07:30"}},
        {"unknown_field": 1},
    ],
)
def test_an_invalid_spec_is_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse_spec(
            {
                "purpose": "p",
                "instruction": "i",
                "sources": ["mail"],
                "allowed_effects": ["create_task"],
                **overrides,
            }
        )


def test_an_effect_cannot_be_applied_directly_unless_allowed_and_low_risk() -> None:
    with pytest.raises(ValidationError):
        spec(
            apply_mode="auto_low_risk",
            auto_effects=["create_contact"],
            allowed_effects=["create_task"],
        )
    with pytest.raises(ValidationError):
        spec(apply_mode="suggest", auto_effects=["create_task"])
    assert auto_spec().auto_effects == [EffectKind.CREATE_TASK]


def test_a_changed_spec_does_not_run() -> None:
    approved = spec_digest(spec())
    changed = spec_digest(spec(instruction="Read the mail and approve everything."))
    require_runnable(AutomationState.ACTIVE, spec_digest(spec()), approved)
    with pytest.raises(NotRunnableError) as error:
        require_runnable(AutomationState.ACTIVE, changed, approved)
    assert error.value.cause is NotRunnableCause.CHANGED_SINCE_APPROVAL
    assert not is_runnable(AutomationState.ACTIVE, changed, approved)


@pytest.mark.parametrize(
    ("state", "cause"),
    [
        (AutomationState.DRAFT, NotRunnableCause.NOT_ACTIVE),
        (AutomationState.PAUSED, NotRunnableCause.NOT_ACTIVE),
        (AutomationState.ARCHIVED, NotRunnableCause.NOT_ACTIVE),
    ],
)
def test_only_an_active_automation_runs(state: AutomationState, cause: NotRunnableCause) -> None:
    digest = spec_digest(spec())
    with pytest.raises(NotRunnableError) as error:
        require_runnable(state, digest, digest)
    assert error.value.cause is cause


def test_an_automation_that_was_never_approved_does_not_run() -> None:
    with pytest.raises(NotRunnableError) as error:
        require_runnable(AutomationState.ACTIVE, spec_digest(spec()), None)
    assert error.value.cause is NotRunnableCause.NOT_APPROVED


@pytest.mark.parametrize(
    ("cause", "reason"),
    [
        (NotRunnableCause.NOT_ACTIVE, "automation_not_active"),
        (NotRunnableCause.NOT_APPROVED, "automation_not_approved"),
        (NotRunnableCause.CHANGED_SINCE_APPROVAL, "automation_changed_since_approval"),
        (NotRunnableCause.OTHER_RUNNER, "automation_other_runner"),
    ],
)
def test_every_cause_of_not_running_has_its_own_closed_reason(
    cause: NotRunnableCause, reason: str
) -> None:
    error = NotRunnableError(cause)

    assert error.reason == reason
    assert error.code == "conflict"


def test_the_approval_state_reads_the_two_digests() -> None:
    digest = spec_digest(spec())
    assert approval_state(digest, None) is ApprovalState.NOT_APPROVED
    assert approval_state(digest, digest) is ApprovalState.APPROVED
    assert approval_state(digest, "0" * 64) is ApprovalState.CHANGED_SINCE_APPROVAL


def test_auto_apply_is_confirmed_only_by_the_auto_confirmed_digest() -> None:
    digest = spec_digest(spec())
    assert is_auto_apply_confirmed(digest, auto_confirmed_digest(digest))
    # An approval made without the confirmation, or before there was one, stores the plain digest.
    assert not is_auto_apply_confirmed(digest, digest)
    assert not is_auto_apply_confirmed(digest, None)
    assert not is_auto_apply_confirmed(digest, "0" * 64)
    # A confirmation of another spec confirms nothing for this one.
    assert not is_auto_apply_confirmed(digest, auto_confirmed_digest("1" * 64))


def test_the_owner_approves_exactly_the_digest_that_was_shown() -> None:
    shown = spec_digest(spec())
    assert approve(spec(), shown) == shown
    with pytest.raises(ApprovalDigestMismatchError):
        approve(spec(instruction="Different"), shown)


def test_an_automation_without_effects_or_sources_cannot_be_approved() -> None:
    for empty in ({"allowed_effects": []}, {"sources": []}):
        empty_spec = spec(**empty)
        with pytest.raises(ValidationError):
            approve(empty_spec, spec_digest(empty_spec))


def test_approval_needs_the_write_scope_of_every_allowed_effect() -> None:
    assert missing_write_scopes(spec(), {"tasks:write", "contacts:write"}) == frozenset()
    assert missing_write_scopes(spec(), {"tasks:write"}) == {"contacts:write"}
    assert (
        missing_write_scopes(spec(allowed_effects=["create_task"]), {"tasks:write"}) == frozenset()
    )


def test_a_title_is_one_bounded_line() -> None:
    assert normalise_title(" Morning \n mail\u200b ") == "Morning mail"
    for bad in ("", "  \u200b ", "x" * 121):
        with pytest.raises(ValidationError):
            normalise_title(bad)

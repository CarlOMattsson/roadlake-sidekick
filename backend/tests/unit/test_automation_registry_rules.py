"""The registry's rules without storage: a new automation is a draft, a changed spec withdraws the
approval, and the approval holds only for the exact digest, model tier included."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from sidekick.automations.domain.automation import Automation
from sidekick.automations.domain.registry import (
    RegistryChange,
    RegistryEvent,
    approve_current,
    change,
    create,
)
from sidekick.automations.domain.spec import (
    ApprovalDigestMismatchError,
    ApprovalState,
    AutomationState,
    approval_state,
    is_runnable,
)
from sidekick.shared.config import Settings
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import new_uuid7
from tests.support.settings import make_settings

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
OWNER = UUID("00000000-0000-7000-8000-000000000001")
CAP = 15_000_000
FIELDS: dict[str, Any] = {
    "purpose": "Collect what the morning mail asks of me",
    "instruction": "Read yesterday's mail and propose tasks for requests.",
    "sources": ["mail"],
    "allowed_effects": ["create_task"],
}


def _draft(**fields: Any) -> Automation:
    created = create(
        automation_id=new_uuid7(),
        owner_id=OWNER,
        title="Morning mail",
        spec_fields={**FIELDS, **fields},
        run_budget_cap_microusd=CAP,
        now=NOW,
    )
    assert created.events == (RegistryEvent.CREATED,)
    return created.automation


def _approved(**fields: Any) -> Automation:
    draft = _draft(**fields)
    return approve_current(
        draft, draft.spec_digest, run_budget_cap_microusd=CAP, now=NOW
    ).automation


def _change(current: Automation, **requested: Any) -> Any:
    spec_fields = requested.pop("spec_fields", {})
    return change(
        current,
        RegistryChange(spec_fields=spec_fields, **requested),
        run_budget_cap_microusd=CAP,
        now=LATER,
    )


def test_a_new_automation_is_a_draft_that_cannot_run() -> None:
    draft = _draft()

    assert draft.state is AutomationState.DRAFT
    assert draft.approved_digest is None
    assert draft.version == 1
    assert approval_state(draft.spec_digest, draft.approved_digest) is ApprovalState.NOT_APPROVED
    assert not is_runnable(draft.state, draft.spec_digest, draft.approved_digest)


@pytest.mark.parametrize("missing", ["purpose", "instruction"])
def test_a_new_automation_needs_a_purpose_and_an_instruction(missing: str) -> None:
    fields = {key: value for key, value in FIELDS.items() if key != missing}

    with pytest.raises(ValidationError, match=missing):
        create(
            automation_id=new_uuid7(),
            owner_id=OWNER,
            title="Morning mail",
            spec_fields=fields,
            run_budget_cap_microusd=CAP,
            now=NOW,
        )


def test_a_new_automation_needs_a_title() -> None:
    with pytest.raises(ValidationError, match="title"):
        create(
            automation_id=new_uuid7(),
            owner_id=OWNER,
            title=None,
            spec_fields=FIELDS,
            run_budget_cap_microusd=CAP,
            now=NOW,
        )


def test_approving_the_current_digest_makes_a_draft_active_and_runnable() -> None:
    approved = _approved()

    assert approved.state is AutomationState.ACTIVE
    assert approved.approved_digest == approved.spec_digest
    assert approved.approved_at == NOW
    assert approved.version == 2
    assert is_runnable(approved.state, approved.spec_digest, approved.approved_digest)


def test_approving_another_digest_is_refused_and_changes_nothing() -> None:
    draft = _draft()

    with pytest.raises(ApprovalDigestMismatchError):
        approve_current(draft, "0" * 64, run_budget_cap_microusd=CAP, now=NOW)


def test_approving_what_is_approved_changes_nothing() -> None:
    approved = _approved()

    again = approve_current(approved, approved.spec_digest, run_budget_cap_microusd=CAP, now=LATER)

    assert again.events == ()
    assert again.automation is approved


@pytest.mark.parametrize(
    "fields",
    [
        {"instruction": "Read the mail and propose tasks, and add contacts too."},
        {"allowed_effects": ["create_task", "create_contact"]},
        {"sources": ["mail", "web"]},
        {"apply_mode": "auto_low_risk", "auto_effects": ["create_task"]},
        {"run_budget_microusd": 500_000},
        {"model_tier": "strong"},
        {"cadence": {"frequency": "daily", "local_time": "07:30"}},
    ],
)
def test_every_change_to_the_spec_withdraws_the_approval(fields: dict[str, Any]) -> None:
    approved = _approved()

    result = _change(approved, spec_fields=fields)
    changed = result.automation

    assert result.events[0] is RegistryEvent.UPDATED
    assert RegistryEvent.APPROVAL_WITHDRAWN in result.events
    assert changed.approved_digest is None
    assert changed.approved_at is None
    assert changed.state is AutomationState.DRAFT
    assert changed.version == approved.version + 1
    assert not is_runnable(changed.state, changed.spec_digest, changed.approved_digest)


def test_the_approval_is_bound_to_the_tier_as_well_as_the_text() -> None:
    standard = _approved()
    strong = _change(standard, spec_fields={"model_tier": "strong"}).automation

    assert strong.spec_digest != standard.spec_digest
    with pytest.raises(ApprovalDigestMismatchError):
        approve_current(strong, standard.spec_digest, run_budget_cap_microusd=CAP, now=LATER)


def test_a_title_or_a_pause_keeps_the_approval() -> None:
    approved = _approved()

    renamed = _change(approved, title="Evening mail").automation
    paused = _change(approved, paused=True).automation

    assert renamed.approved_digest == approved.approved_digest
    assert renamed.state is AutomationState.ACTIVE
    assert paused.state is AutomationState.PAUSED
    assert paused.approved_digest == approved.approved_digest
    assert paused.spec_digest == approved.spec_digest


def test_resuming_runs_again_only_when_the_spec_is_still_approved() -> None:
    paused = _change(_approved(), paused=True).automation
    resumed = _change(paused, paused=False).automation
    edited = _change(paused, spec_fields={"model_tier": "strong"}).automation
    still_paused_after_edit = _change(edited, paused=False).automation

    assert resumed.state is AutomationState.ACTIVE
    assert edited.state is AutomationState.PAUSED
    assert still_paused_after_edit.state is AutomationState.DRAFT


def test_a_paused_automation_stays_paused_when_it_is_approved() -> None:
    paused = _change(_draft(), paused=True).automation

    approved = approve_current(
        paused, paused.spec_digest, run_budget_cap_microusd=CAP, now=LATER
    ).automation

    assert approved.state is AutomationState.PAUSED
    assert approved.approved_digest == approved.spec_digest


def test_an_archived_automation_can_only_be_restored_and_never_approved() -> None:
    archived = _change(_approved(), archived=True).automation

    assert archived.state is AutomationState.ARCHIVED
    with pytest.raises(ValidationError, match="restored"):
        _change(archived, title="Renamed")
    with pytest.raises(ValidationError, match="restored"):
        approve_current(archived, archived.spec_digest, run_budget_cap_microusd=CAP, now=LATER)
    restored = _change(archived, archived=False).automation
    assert restored.state is AutomationState.PAUSED


def test_a_change_that_changes_nothing_has_no_events() -> None:
    approved = _approved()

    same = _change(approved, title="Morning mail", spec_fields={"model_tier": "standard"})

    assert same.events == ()
    assert same.automation is approved


def test_the_cadence_is_the_only_field_that_can_be_emptied() -> None:
    scheduled = _draft(cadence={"frequency": "daily", "local_time": "07:30"})

    emptied = _change(scheduled, spec_fields={"cadence": None}).automation

    assert emptied.spec.cadence is None
    with pytest.raises(ValidationError, match="cannot be emptied"):
        _change(scheduled, spec_fields={"instruction": None})


def test_an_unknown_spec_field_is_refused() -> None:
    with pytest.raises(ValidationError, match="not_a_field"):
        _change(_draft(), spec_fields={"not_a_field": 1})


def test_the_run_budget_cannot_be_above_the_cap_for_automations() -> None:
    with pytest.raises(ValidationError, match="monthly cap"):
        _draft(run_budget_microusd=CAP + 1)
    assert _draft(run_budget_microusd=CAP).spec.run_budget_microusd == CAP
    with pytest.raises(ValidationError, match="monthly cap"):
        _change(_draft(), spec_fields={"run_budget_microusd": CAP + 1})


def test_a_budget_above_a_lowered_cap_is_refused_at_approval() -> None:
    draft = _draft(run_budget_microusd=CAP)

    with pytest.raises(ValidationError, match="monthly cap"):
        approve_current(draft, draft.spec_digest, run_budget_cap_microusd=CAP - 1, now=NOW)


def test_an_automation_needs_an_effect_and_a_source_before_it_is_approved() -> None:
    draft = _draft(allowed_effects=[])

    with pytest.raises(ValidationError, match="effect"):
        approve_current(draft, draft.spec_digest, run_budget_cap_microusd=CAP, now=NOW)


def test_the_automation_cap_cannot_be_above_the_monthly_cap() -> None:
    assert make_settings().ai_automation_monthly_cap_usd == 15.0
    base = make_settings().model_dump()
    with pytest.raises(ValueError, match="AUTOMATION_MONTHLY_CAP"):
        Settings.model_validate(
            {**base, "ai_monthly_cap_usd": 10.0, "ai_automation_monthly_cap_usd": 11.0}
        )


def test_a_monthly_cap_below_the_automation_default_lowers_the_default_with_it() -> None:
    settings = Settings(
        environment="test",
        database_url=make_settings().database_url,
        cursor_signing_secret="session-secret-for-tests-only-123456",
        token_pepper="token-pepper-for-tests-only-12345678",
        ai_monthly_cap_usd=10.0,
    )

    assert settings.ai_monthly_cap_usd == 10.0
    assert settings.ai_automation_monthly_cap_usd == 10.0

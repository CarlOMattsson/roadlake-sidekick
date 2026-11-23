"""Who is in the high-confidence group, who may be applied by the policy (invariant I3)."""

import dataclasses
from datetime import timedelta
from typing import Any

import pytest

from sidekick.automations.domain.effects import EffectKind
from sidekick.automations.domain.grouping import (
    MAX_AUTO_PER_DAY,
    MAX_AUTO_PER_RUN,
    MAX_GROUP_SIZE,
    AutoApplyRefusal,
    BulkBlocker,
    auto_apply_refusal,
    bulk_blockers,
    check_group,
    group_digest,
    is_bulk_eligible,
    with_bulk_eligibility,
)
from sidekick.automations.domain.screening import ScreeningFlag
from sidekick.automations.domain.spec import AutomationSpecV1, auto_confirmed_digest, spec_digest
from sidekick.automations.domain.suggestion import (
    DecisionChannel,
    DecisionContext,
    DecisionRefusal,
    Suggestion,
    SuggestionRefusedError,
    Verdict,
)
from tests.support.automations import NOW, auto_spec, spec, suggestion


def blockers(**kwargs: Any) -> tuple[BulkBlocker, ...]:
    return bulk_blockers(suggestion(**kwargs), spec(), run_done=True)


def test_a_checked_clean_card_above_the_threshold_is_eligible() -> None:
    assert bulk_blockers(suggestion(), spec(), run_done=True) == ()
    assert is_bulk_eligible(suggestion(), spec(), run_done=True)


@pytest.mark.parametrize(
    ("kwargs", "blocker"),
    [
        ({"verdict": None}, BulkBlocker.NOT_CHECKED),
        ({"verdict": Verdict.UNCERTAIN}, BulkBlocker.VERDICT_NOT_OK),
        ({"verdict": Verdict.SUSPICIOUS, "confidence": 99}, BulkBlocker.VERDICT_NOT_OK),
        ({"confidence": 89}, BulkBlocker.BELOW_THRESHOLD),
        ({"edited": True}, BulkBlocker.EDITED),
    ],
)
def test_each_reason_keeps_a_card_out_of_the_group(
    kwargs: dict[str, Any], blocker: BulkBlocker
) -> None:
    assert blocker in blockers(**kwargs)


def test_a_card_that_is_not_pending_is_not_eligible() -> None:
    dismissed = suggestion().dismiss(
        DecisionContext(DecisionChannel.APP), now=NOW, expected_version=1
    )
    assert BulkBlocker.NOT_PENDING in bulk_blockers(dismissed, spec(), run_done=True)


def test_the_threshold_is_inclusive() -> None:
    assert not blockers(confidence=90)
    assert BulkBlocker.BELOW_THRESHOLD in blockers(confidence=89)
    stricter = spec(bulk_threshold=99, auto_threshold=99)
    assert BulkBlocker.BELOW_THRESHOLD in bulk_blockers(
        suggestion(confidence=98), stricter, run_done=True
    )
    assert not bulk_blockers(suggestion(confidence=99), stricter, run_done=True)


def test_a_run_that_is_not_done_has_no_group() -> None:
    assert bulk_blockers(suggestion(), spec(), run_done=False) == (BulkBlocker.RUN_NOT_DONE,)


def test_without_a_checker_nothing_is_eligible() -> None:
    assert bulk_blockers(suggestion(verdict=None), spec(), run_done=True) == (
        BulkBlocker.NOT_CHECKED,
    )


@pytest.mark.parametrize("flag", list(ScreeningFlag))
def test_a_flagged_card_is_never_eligible_whatever_the_checker_said(flag: ScreeningFlag) -> None:
    card = suggestion(flags=(flag,), confidence=100)
    assert bulk_blockers(card, spec(), run_done=True) == (BulkBlocker.FLAGGED,)
    assert not with_bulk_eligibility(card, spec(), run_done=True).bulk_eligible


def test_recomputing_eligibility_does_not_change_the_version() -> None:
    card = suggestion()
    marked = with_bulk_eligibility(card, spec(), run_done=True)
    assert marked.bulk_eligible
    assert marked.version == card.version
    assert not with_bulk_eligibility(marked, spec(), run_done=False).bulk_eligible


# --- the group ---------------------------------------------------------------------------------


def group(size: int = 3) -> list[Suggestion]:
    return [with_bulk_eligibility(suggestion(), spec(), run_done=True) for _ in range(size)]


def test_the_group_digest_ignores_order_and_follows_versions() -> None:
    items = group()
    assert group_digest(items) == group_digest(list(reversed(items)))
    bumped = [dataclasses.replace(items[0], version=2), *items[1:]]
    assert group_digest(bumped) != group_digest(items)
    assert len(group_digest(items)) == 64


def test_a_group_as_the_owner_saw_it_is_accepted() -> None:
    items = group()
    check_group(group_digest(items), items, spec(), run_done=True)


def assert_group_refused(
    refusal: DecisionRefusal, digest: str, items: list[Suggestion], *, run_done: bool = True
) -> None:
    with pytest.raises(SuggestionRefusedError) as error:
        check_group(digest, items, spec(), run_done=run_done)
    assert error.value.refusal is refusal


def test_one_changed_card_refuses_the_whole_group() -> None:
    items = group()
    digest = group_digest(items)
    changed = [dataclasses.replace(items[0], version=items[0].version + 1), *items[1:]]
    assert_group_refused(DecisionRefusal.GROUP_CHANGED, digest, changed)
    assert_group_refused(DecisionRefusal.GROUP_CHANGED, digest, items[:2])


def test_a_card_that_lost_its_eligibility_refuses_the_whole_group() -> None:
    items = group()
    digest = group_digest(items)
    lower = dataclasses.replace(items[0], confidence=50, bulk_eligible=False)
    assert_group_refused(
        DecisionRefusal.GROUP_NOT_ELIGIBLE, group_digest([lower, *items[1:]]), [lower, *items[1:]]
    )
    assert_group_refused(DecisionRefusal.GROUP_NOT_ELIGIBLE, digest, items, run_done=False)


def test_a_group_is_between_one_and_twenty_five() -> None:
    assert_group_refused(DecisionRefusal.GROUP_TOO_LARGE, group_digest([]), [])
    big = group(MAX_GROUP_SIZE + 1)
    assert_group_refused(DecisionRefusal.GROUP_TOO_LARGE, group_digest(big), big)
    full = group(MAX_GROUP_SIZE)
    check_group(group_digest(full), full, spec(), run_done=True)


def test_a_group_holds_one_owner() -> None:
    items = group(2)
    other = dataclasses.replace(items[1], owner_id=items[1].run_id)
    assert_group_refused(
        DecisionRefusal.GROUP_CHANGED, group_digest([items[0], other]), [items[0], other]
    )


def test_a_group_holds_one_automation_and_each_card_once() -> None:
    items = group(2)
    other = dataclasses.replace(items[1], automation_id=items[1].run_id)
    assert_group_refused(
        DecisionRefusal.GROUP_CHANGED, group_digest([items[0], other]), [items[0], other]
    )
    assert_group_refused(
        DecisionRefusal.GROUP_CHANGED, group_digest([items[0], items[0]]), [items[0], items[0]]
    )


# --- applying without the owner ----------------------------------------------------------------


def eligible(**kwargs: Any) -> Suggestion:
    """A card the group holds, the one the policy may look at."""

    return suggestion(**{"bulk_eligible": True, "confidence": 96, **kwargs})


def auto(
    card: Suggestion | None = None,
    spec_: AutomationSpecV1 | None = None,
    *,
    checker_configured: bool = True,
    contact_domain_matches_sender: bool | None = None,
    auto_applied_in_run: int = 0,
    auto_applied_today: int = 0,
    approved_digest: str | None = "",
    automation_active: bool = True,
) -> AutoApplyRefusal | None:
    used = spec_ or auto_spec()
    return auto_apply_refusal(
        card or eligible(),
        used,
        now=NOW,
        approved_digest=auto_confirmed_digest(spec_digest(used))
        if approved_digest == ""
        else approved_digest,
        automation_active=automation_active,
        checker_configured=checker_configured,
        contact_domain_matches_sender=contact_domain_matches_sender,
        auto_applied_in_run=auto_applied_in_run,
        auto_applied_today=auto_applied_today,
    )


def test_a_clean_checked_card_is_applied_by_an_automation_that_opted_in() -> None:
    assert auto() is None


@pytest.mark.parametrize(
    ("overrides", "refusal"),
    [
        ({"checker_configured": False}, AutoApplyRefusal.NO_CHECKER),
        ({"auto_applied_in_run": MAX_AUTO_PER_RUN}, AutoApplyRefusal.RUN_CAP),
        ({"auto_applied_today": MAX_AUTO_PER_DAY}, AutoApplyRefusal.DAY_CAP),
    ],
)
def test_the_checker_and_the_counts_gate_the_policy(
    overrides: dict[str, Any], refusal: AutoApplyRefusal
) -> None:
    assert auto(**overrides) is refusal
    assert (
        auto(auto_applied_in_run=MAX_AUTO_PER_RUN - 1, auto_applied_today=MAX_AUTO_PER_DAY - 1)
        is None
    )


def test_a_spec_that_is_not_the_approved_one_applies_nothing() -> None:
    changed = auto_spec(auto_threshold=90)
    assert auto(card=eligible(confidence=92), spec_=changed, approved_digest=None) is (
        AutoApplyRefusal.SPEC_NOT_APPROVED
    )
    assert auto(
        card=eligible(confidence=92),
        spec_=changed,
        approved_digest=auto_confirmed_digest(spec_digest(auto_spec())),
    ) is (AutoApplyRefusal.SPEC_NOT_APPROVED)
    assert (
        auto(
            card=eligible(confidence=96),
            approved_digest=auto_confirmed_digest(spec_digest(auto_spec())),
        )
        is None
    )


def test_the_policy_needs_the_opt_in_and_the_effect() -> None:
    assert auto(spec_=spec()) is AutoApplyRefusal.MODE_OFF
    assert auto(card=eligible(effect=EffectKind.CREATE_CONTACT)) is (
        AutoApplyRefusal.EFFECT_NOT_AUTO
    )


def test_the_policy_has_its_own_stricter_threshold() -> None:
    assert auto(card=eligible(confidence=94)) is AutoApplyRefusal.BELOW_THRESHOLD
    assert auto(card=eligible(confidence=95)) is None
    assert auto(card=eligible(confidence=100), spec_=auto_spec(auto_threshold=99)) is None
    assert auto(card=eligible(confidence=98), spec_=auto_spec(auto_threshold=99)) is (
        AutoApplyRefusal.BELOW_THRESHOLD
    )


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"verdict": None}, AutoApplyRefusal.NOT_CHECKED),
        ({"verdict": Verdict.UNCERTAIN, "confidence": 99}, AutoApplyRefusal.VERDICT_NOT_OK),
        ({"verdict": Verdict.SUSPICIOUS, "confidence": 99}, AutoApplyRefusal.VERDICT_NOT_OK),
        ({"edited": True, "confidence": 99}, AutoApplyRefusal.EDITED),
    ],
)
def test_an_unchecked_doubtful_or_edited_card_stays_pending(
    kwargs: dict[str, Any], refusal: AutoApplyRefusal
) -> None:
    assert auto(card=suggestion(**kwargs)) is refusal


@pytest.mark.parametrize("flag", list(ScreeningFlag))
def test_a_flagged_card_is_never_applied_by_the_policy(flag: ScreeningFlag) -> None:
    assert auto(card=suggestion(flags=(flag,), confidence=100)) is AutoApplyRefusal.FLAGGED


def test_a_contact_with_an_address_needs_the_sender_domain_to_match() -> None:
    contact_spec = auto_spec(auto_effects=["create_contact"])
    card = eligible(effect=EffectKind.CREATE_CONTACT, confidence=99)
    assert auto(card=card, spec_=contact_spec) is AutoApplyRefusal.SENDER_DOMAIN_MISMATCH
    assert auto(card=card, spec_=contact_spec, contact_domain_matches_sender=False) is (
        AutoApplyRefusal.SENDER_DOMAIN_MISMATCH
    )
    assert auto(card=card, spec_=contact_spec, contact_domain_matches_sender=True) is None


def test_a_card_the_group_does_not_hold_is_not_applied_by_the_policy() -> None:
    assert auto(card=suggestion(confidence=99)) is AutoApplyRefusal.NOT_BULK_ELIGIBLE
    assert auto(card=eligible(confidence=99)) is None


def test_an_automation_that_is_paused_or_archived_applies_nothing() -> None:
    assert auto(automation_active=False) is AutoApplyRefusal.NOT_ACTIVE


def test_a_card_past_its_time_to_live_is_not_applied() -> None:
    expired = eligible(expires_in=timedelta(seconds=0))
    assert auto(card=expired) is AutoApplyRefusal.EXPIRED
    assert auto(card=eligible(expires_in=timedelta(seconds=1))) is None


def test_an_approval_made_without_the_confirmation_never_applies_by_policy() -> None:
    used = auto_spec()

    assert auto(spec_=used, approved_digest=spec_digest(used)) is (
        AutoApplyRefusal.AUTO_NOT_CONFIRMED
    )
    assert auto(spec_=used) is None

"""Which suggestions may be approved together or applied without the owner, and on what grounds.

Confidence is the independent checker's number and nothing else; a proposer's own rating is never
stored. A suggestion is *bulk eligible* only when the checker called it `ok` with at least the
automation's threshold, screening raised no flag, the effect is low risk, the owner has not
edited it and the run is done. Without a checker nothing is eligible and every card is decided
alone. The same flag-free rule gates automatic apply, which has its own, stricter threshold and
counts. Both rules are pure functions of the suggestion and the approved spec.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from enum import StrEnum

from sidekick.automations.domain.effects import AUTO_APPLY_EFFECTS, CATALOGUE, EffectKind
from sidekick.automations.domain.spec import (
    ApplyMode,
    ApprovalState,
    AutomationSpecV1,
    approval_state,
    is_auto_apply_confirmed,
    spec_digest,
)
from sidekick.automations.domain.suggestion import (
    CheckState,
    DecisionRefusal,
    Suggestion,
    SuggestionRefusedError,
    SuggestionState,
    Verdict,
)

MAX_GROUP_SIZE = 25
MAX_AUTO_PER_RUN = 10
MAX_AUTO_PER_DAY = 25


class BulkBlocker(StrEnum):
    """Why a card is not in the high-confidence group. The card shows it in plain words."""

    NOT_PENDING = "not_pending"
    NOT_CHECKED = "not_checked"
    VERDICT_NOT_OK = "verdict_not_ok"
    BELOW_THRESHOLD = "below_threshold"
    FLAGGED = "flagged"
    EDITED = "edited"
    NOT_LOW_RISK = "not_low_risk"
    RUN_NOT_DONE = "run_not_done"


def bulk_blockers(
    suggestion: Suggestion, spec: AutomationSpecV1, *, run_done: bool
) -> tuple[BulkBlocker, ...]:
    """Every reason the suggestion is not bulk eligible; empty when it is."""

    checked = suggestion.check_state is CheckState.CHECKED
    blockers = (
        (BulkBlocker.NOT_PENDING, suggestion.state is not SuggestionState.PENDING),
        (BulkBlocker.NOT_CHECKED, not checked),
        (BulkBlocker.VERDICT_NOT_OK, checked and suggestion.verdict is not Verdict.OK),
        (
            BulkBlocker.BELOW_THRESHOLD,
            checked
            and (suggestion.confidence is None or suggestion.confidence < spec.bulk_threshold),
        ),
        (BulkBlocker.FLAGGED, bool(suggestion.screening_flags)),
        (BulkBlocker.EDITED, suggestion.edited),
        (BulkBlocker.NOT_LOW_RISK, not CATALOGUE[suggestion.effect].low_risk),
        (BulkBlocker.RUN_NOT_DONE, not run_done),
    )
    return tuple(blocker for blocker, applies in blockers if applies)


def is_bulk_eligible(suggestion: Suggestion, spec: AutomationSpecV1, *, run_done: bool) -> bool:
    return not bulk_blockers(suggestion, spec, run_done=run_done)


def with_bulk_eligibility(
    suggestion: Suggestion, spec: AutomationSpecV1, *, run_done: bool
) -> Suggestion:
    """The suggestion with `bulk_eligible` recomputed. A derived value: the version is kept."""

    return replace(suggestion, bulk_eligible=is_bulk_eligible(suggestion, spec, run_done=run_done))


def group_digest(suggestions: Sequence[Suggestion]) -> str:
    """SHA-256 over the sorted (id, version) pairs the owner saw in a group."""

    pairs = sorted((str(item.id), item.version) for item in suggestions)
    lines = "\n".join(f"{item_id}:{version}" for item_id, version in pairs)
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def check_group(
    presented_digest: str,
    current: Sequence[Suggestion],
    spec: AutomationSpecV1,
    *,
    run_done: bool,
) -> None:
    """Raise unless the group the owner saw is still exactly the group, and all of it eligible.

    `current` is the cards as they are now, loaded under the decision's lock. One changed card,
    one card that lost its eligibility or a larger group refuses the whole call.
    """

    if not current or len(current) > MAX_GROUP_SIZE:
        raise SuggestionRefusedError(DecisionRefusal.GROUP_TOO_LARGE)
    ids = {item.id for item in current}
    if (
        len(ids) != len(current)
        or len({item.automation_id for item in current}) != 1
        or len({item.owner_id for item in current}) != 1
    ):
        raise SuggestionRefusedError(DecisionRefusal.GROUP_CHANGED)
    if group_digest(current) != presented_digest:
        raise SuggestionRefusedError(DecisionRefusal.GROUP_CHANGED)
    if not all(is_bulk_eligible(item, spec, run_done=run_done) for item in current):
        raise SuggestionRefusedError(DecisionRefusal.GROUP_NOT_ELIGIBLE)


class AutoApplyRefusal(StrEnum):
    """Why a suggestion stays a pending card instead of being applied by the policy."""

    NOT_PENDING = "not_pending"
    EXPIRED = "expired"
    SPEC_NOT_APPROVED = "spec_not_approved"
    NOT_ACTIVE = "not_active"
    MODE_OFF = "mode_off"
    AUTO_NOT_CONFIRMED = "auto_not_confirmed"
    EFFECT_NOT_AUTO = "effect_not_auto"
    NO_CHECKER = "no_checker"
    NOT_CHECKED = "not_checked"
    VERDICT_NOT_OK = "verdict_not_ok"
    BELOW_THRESHOLD = "below_threshold"
    FLAGGED = "flagged"
    EDITED = "edited"
    NOT_BULK_ELIGIBLE = "not_bulk_eligible"
    SENDER_DOMAIN_MISMATCH = "sender_domain_mismatch"
    RUN_CAP = "run_cap"
    DAY_CAP = "day_cap"


def _contact_domain_unverified(suggestion: Suggestion, matches_sender: bool | None) -> bool:
    return (
        suggestion.effect is EffectKind.CREATE_CONTACT
        and bool(suggestion.payload.get("email"))
        and matches_sender is not True
    )


def auto_apply_refusal(
    suggestion: Suggestion,
    spec: AutomationSpecV1,
    *,
    now: datetime,
    approved_digest: str | None,
    automation_active: bool,
    checker_configured: bool,
    contact_domain_matches_sender: bool | None,
    auto_applied_in_run: int,
    auto_applied_today: int,
) -> AutoApplyRefusal | None:
    """The first reason the policy may not apply the suggestion, or None when it may.

    `approved_digest` is the digest the owner approved for the automation. A spec that differs
    from it (or none approved) never applies anything: only what the owner approved decides, and
    only while the automation is active (a pause or an archive stops the policy too).
    `contact_domain_matches_sender` is `screening.email_matches_sender` for a contact that has an
    e-mail address; anything but True refuses.
    """

    refusals = (
        (AutoApplyRefusal.NOT_PENDING, suggestion.state is not SuggestionState.PENDING),
        (
            AutoApplyRefusal.SPEC_NOT_APPROVED,
            approval_state(spec_digest(spec), approved_digest) is not ApprovalState.APPROVED,
        ),
        (AutoApplyRefusal.EXPIRED, now >= suggestion.expires_at),
        (AutoApplyRefusal.NOT_ACTIVE, not automation_active),
        (AutoApplyRefusal.MODE_OFF, spec.apply_mode is not ApplyMode.AUTO_LOW_RISK),
        # An approval made without the owner's confirmation of this mode (or before it existed)
        # never applies anything: the confirmation is part of the stored digest.
        (
            AutoApplyRefusal.AUTO_NOT_CONFIRMED,
            not is_auto_apply_confirmed(spec_digest(spec), approved_digest),
        ),
        (
            AutoApplyRefusal.EFFECT_NOT_AUTO,
            suggestion.effect not in spec.auto_effects
            or suggestion.effect not in AUTO_APPLY_EFFECTS,
        ),
        (AutoApplyRefusal.NO_CHECKER, not checker_configured),
        (AutoApplyRefusal.NOT_CHECKED, suggestion.check_state is not CheckState.CHECKED),
        (AutoApplyRefusal.VERDICT_NOT_OK, suggestion.verdict is not Verdict.OK),
        (
            AutoApplyRefusal.BELOW_THRESHOLD,
            suggestion.confidence is None or suggestion.confidence < spec.auto_threshold,
        ),
        (AutoApplyRefusal.FLAGGED, bool(suggestion.screening_flags)),
        (AutoApplyRefusal.EDITED, suggestion.edited),
        # The group's own test, as stored when the run's check ended: the policy never applies a
        # card the high-confidence group would not hold.
        (AutoApplyRefusal.NOT_BULK_ELIGIBLE, not suggestion.bulk_eligible),
        (
            AutoApplyRefusal.SENDER_DOMAIN_MISMATCH,
            _contact_domain_unverified(suggestion, contact_domain_matches_sender),
        ),
        (AutoApplyRefusal.RUN_CAP, auto_applied_in_run >= MAX_AUTO_PER_RUN),
        (AutoApplyRefusal.DAY_CAP, auto_applied_today >= MAX_AUTO_PER_DAY),
    )
    return next((reason for reason, applies in refusals if applies), None)

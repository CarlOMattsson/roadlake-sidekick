"""Creating, changing and approving an automation: the rules of the registry.

A new automation is a draft. Anything that steers a run (the spec) is covered by the digest the
owner approves, so a change to the spec withdraws the approval and an active automation goes back
to draft; the title, a pause and an archive are not part of it. Only the owner's approval of the
exact digest makes an automation active. Nothing here knows storage or transport.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from sidekick.automations.domain.automation import Automation
from sidekick.automations.domain.spec import (
    ApprovalState,
    AutomationSpecV1,
    AutomationState,
    approval_state,
    approve,
    normalise_title,
    parse_spec,
    require_budget_within,
    spec_digest,
)
from sidekick.shared.errors import ValidationError

CLEARABLE_SPEC_FIELDS: Final = frozenset({"cadence"})
"""The spec fields that may be emptied; every other one has a value of its own to keep."""


class RegistryEvent(StrEnum):
    """What a registry write did, one word per audit event."""

    CREATED = "created"
    UPDATED = "updated"
    APPROVAL_WITHDRAWN = "approval_withdrawn"
    APPROVED = "approved"
    PAUSED = "paused"
    RESUMED = "resumed"
    ARCHIVED = "archived"
    RESTORED = "restored"


@dataclass(frozen=True, slots=True)
class RegistryChange:
    """What the caller sent. A spec field present with `None` is emptied (`cadence` only)."""

    title: str | None = None
    spec_fields: Mapping[str, object] = field(default_factory=dict[str, object])
    paused: bool | None = None
    archived: bool | None = None


@dataclass(frozen=True, slots=True)
class RegistryResult:
    """The automation after a write and the events to audit; no events means nothing changed."""

    automation: Automation
    events: tuple[RegistryEvent, ...]


def _spec_with(base: AutomationSpecV1, fields: Mapping[str, object]) -> AutomationSpecV1:
    if emptied := {name for name, value in fields.items() if value is None} - CLEARABLE_SPEC_FIELDS:
        raise ValidationError(f"invalid automation spec: {sorted(emptied)[0]} cannot be emptied")
    return parse_spec({**base.model_dump(mode="json"), **fields})


def create(
    *,
    automation_id: UUID,
    owner_id: UUID,
    title: str | None,
    spec_fields: Mapping[str, object],
    run_budget_cap_microusd: int,
    now: datetime,
) -> RegistryResult:
    """A new draft. It needs a title, a purpose and an instruction; the rest has defaults."""

    if title is None:
        raise ValidationError("a new automation needs a title")
    spec = parse_spec({name: value for name, value in spec_fields.items() if value is not None})
    require_budget_within(spec, run_budget_cap_microusd)
    automation = Automation(
        id=automation_id,
        owner_id=owner_id,
        title=normalise_title(title),
        spec=spec,
        state=AutomationState.DRAFT,
        spec_digest=spec_digest(spec),
        approved_digest=None,
        approved_at=None,
        last_run_at=None,
        version=1,
        created_at=now,
        updated_at=now,
    )
    return RegistryResult(automation, (RegistryEvent.CREATED,))


def _requested_state(
    state: AutomationState, change: RegistryChange, *, approved: bool
) -> tuple[AutomationState, tuple[RegistryEvent, ...]]:
    if change.archived is True:
        if state is AutomationState.ARCHIVED:
            return state, ()
        return AutomationState.ARCHIVED, (RegistryEvent.ARCHIVED,)
    events: list[RegistryEvent] = []
    if state is AutomationState.ARCHIVED:
        state = AutomationState.PAUSED
        events.append(RegistryEvent.RESTORED)
    if change.paused is True and state is not AutomationState.PAUSED:
        state = AutomationState.PAUSED
        events.append(RegistryEvent.PAUSED)
    elif change.paused is False and state is AutomationState.PAUSED:
        state = AutomationState.ACTIVE if approved else AutomationState.DRAFT
        events.append(RegistryEvent.RESUMED)
    return state, tuple(events)


def change(
    current: Automation, requested: RegistryChange, *, run_budget_cap_microusd: int, now: datetime
) -> RegistryResult:
    """The automation with the change applied, or unchanged (and no events) when it changes nothing.

    A changed spec withdraws the approval; an active automation then returns to draft. An archived
    automation can only be restored.
    """

    if current.state is AutomationState.ARCHIVED and requested.archived is not False:
        raise ValidationError("an archived automation must be restored before it is changed")
    title = current.title if requested.title is None else normalise_title(requested.title)
    spec = (
        _spec_with(current.spec, requested.spec_fields) if requested.spec_fields else current.spec
    )
    digest = spec_digest(spec)
    spec_changed = digest != current.spec_digest
    events: list[RegistryEvent] = []
    state = current.state
    approved_digest, approved_at = current.approved_digest, current.approved_at
    if spec_changed:
        require_budget_within(spec, run_budget_cap_microusd)
        if approved_digest is not None:
            approved_digest = approved_at = None
            events.append(RegistryEvent.APPROVAL_WITHDRAWN)
        if state is AutomationState.ACTIVE:
            state = AutomationState.DRAFT
    if spec_changed or title != current.title:
        events.insert(0, RegistryEvent.UPDATED)
    state, state_events = _requested_state(
        state,
        requested,
        approved=approval_state(digest, approved_digest) is ApprovalState.APPROVED,
    )
    events.extend(state_events)
    if not events:
        return RegistryResult(current, ())
    changed = replace(
        current,
        title=title,
        spec=spec,
        state=state,
        spec_digest=digest,
        approved_digest=approved_digest,
        approved_at=approved_at,
        updated_at=now,
        version=current.version + 1,
    )
    return RegistryResult(changed, tuple(events))


def approve_current(
    current: Automation,
    presented_digest: str,
    *,
    run_budget_cap_microusd: int,
    now: datetime,
    auto_apply_confirmed: bool = False,
) -> RegistryResult:
    """The automation approved at `presented_digest`, which must be its current digest.

    Approving what is already approved changes nothing. A draft becomes active; a paused one stays
    paused until the owner resumes it. A spec that applies changes without the owner's click
    (`apply_mode` `auto_low_risk`) is approved only when the owner confirmed that in the same call,
    so a draft that a model prepared never turns it on by an approval of the digest alone.
    """

    if current.state is AutomationState.ARCHIVED:
        raise ValidationError("an archived automation must be restored before it is approved")
    approved = approve(current.spec, presented_digest, auto_apply_confirmed=auto_apply_confirmed)
    require_budget_within(current.spec, run_budget_cap_microusd)
    if current.approved_digest == approved:
        return RegistryResult(current, ())
    state = AutomationState.ACTIVE if current.state is AutomationState.DRAFT else current.state
    changed = replace(
        current,
        state=state,
        spec_digest=presented_digest,
        approved_digest=approved,
        approved_at=now,
        updated_at=now,
        version=current.version + 1,
    )
    return RegistryResult(changed, (RegistryEvent.APPROVED,))

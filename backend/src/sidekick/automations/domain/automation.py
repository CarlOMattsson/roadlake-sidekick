"""An automation as the owner's registry holds it, and one check of a suggestion.

These are plain values. What an automation may do is decided by the spec and the functions in
`spec.py` (`approval_state`, `is_runnable`); what a check means is decided by the suggestion's
transitions. Neither is repeated here.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sidekick.automations.domain.spec import AutomationSpecV1, AutomationState


@dataclass(frozen=True, slots=True)
class Automation:
    """One entry of the registry.

    `spec_digest` and `approved_digest` are as `spec.py` defines them; the title and the state
    are not part of the digest.
    """

    id: UUID
    owner_id: UUID
    title: str
    spec: AutomationSpecV1
    state: AutomationState
    spec_digest: str
    approved_digest: str | None
    approved_at: datetime | None
    last_run_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SuggestionCheck:
    """One attempt of the independent check of a suggestion.

    The checker answers with a verdict (`ok`, `uncertain`, `suspicious` or `error`), a confidence
    and codes from a closed set, never free text.
    """

    id: UUID
    owner_id: UUID
    suggestion_id: UUID
    run_id: UUID
    attempt: int
    checker: str
    model: str
    verdict: str
    confidence: int | None
    reason_codes: tuple[str, ...]
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class ReportCursor:
    """The instant up to which the owner has seen the automation report."""

    owner_id: UUID
    seen_until: datetime
    version: int
    updated_at: datetime

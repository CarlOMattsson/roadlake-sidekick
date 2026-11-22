"""A suggestion: one proposed change, and the states it passes through until the owner decides.

```
received --screened--> checking --check done or failed--> pending
received --screened (checker off)--> pending
pending --approve--> applied --undo--> undone
pending --dismiss--> dismissed        pending --TTL--> expired
pending --approve fails--> pending (shows a closed error code)
```

Every transition checks the version the caller saw and returns a new value with the version
raised. What the checker said, what the owner decided and what was created are written by the
transition that owns them and by nothing else: confidence exists only after `record_check`, and
a decision only through `approve`, `dismiss` or `auto_apply`. A card that carries a flag, or a
suspicious verdict, can never be eligible for a group and can never be decided from a model tool.
"""

import hashlib
import hmac
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sidekick.automations.domain.effects import (
    AUTO_APPLY_EFFECTS,
    MAX_DATAPOINT_REFS,
    EffectKind,
    ParsedPayload,
    canonical_json,
    target_key,
)
from sidekick.automations.domain.screening import Screened, ScreeningFlag, flags_after_edit
from sidekick.shared.errors import ConflictError, ValidationError

MIN_FINGERPRINT_KEY_BYTES = 16


class SuggestionState(StrEnum):
    RECEIVED = "received"
    CHECKING = "checking"
    PENDING = "pending"
    APPLIED = "applied"
    UNDONE = "undone"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class CheckState(StrEnum):
    OFF = "off"
    QUEUED = "queued"
    CHECKED = "checked"
    FAILED = "failed"


class Verdict(StrEnum):
    OK = "ok"
    UNCERTAIN = "uncertain"
    SUSPICIOUS = "suspicious"


class Decision(StrEnum):
    APPROVE = "approve"
    DISMISS = "dismiss"


class DecisionChannel(StrEnum):
    APP = "app"
    MODEL = "model"
    COMPANION = "companion"
    POLICY = "policy"


class DecidedBy(StrEnum):
    YOU = "you"
    CLAUDE = "claude"
    POLICY = "policy"


class ApplyError(StrEnum):
    """Why applying failed. The card stays pending and shows the code."""

    PROJECT_GONE = "project_gone"
    CONFLICT = "conflict"
    INVALID_PAYLOAD = "invalid_payload"
    NOT_PERMITTED = "not_permitted"


class DecisionRefusal(StrEnum):
    """The closed reasons a decision, an undo or a group approval is refused."""

    NEEDS_APP = "needs_app"
    NEEDS_CONFIRMATION = "needs_confirmation"
    SAME_SESSION = "same_session"
    STALE = "stale"
    NOT_PENDING = "not_pending"
    NOT_EXPIRED = "not_expired"
    EXPIRED = "expired"
    NOT_ALLOWED = "not_allowed"
    NOT_APPLIED = "not_applied"
    CHANGED_SINCE_APPLY = "changed_since_apply"
    GROUP_CHANGED = "group_changed"
    GROUP_TOO_LARGE = "group_too_large"
    GROUP_NOT_ELIGIBLE = "group_not_eligible"
    AUTO_NOT_ALLOWED = "auto_not_allowed"


class SuggestionRefusedError(ConflictError):
    """A decision was refused. `refusal` is a fixed code; the message holds no owner text."""

    code = "suggestion_refused"
    safe_title = "Suggestion cannot be decided"

    def __init__(self, refusal: DecisionRefusal) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Who decides and through what, as the transport established it."""

    channel: DecisionChannel
    session_matches_run: bool | None = None
    """The deciding MCP session is the one that ran the automation. A model decision must say
    which: there is no default that lets one through."""
    confirmed: bool = False
    """The owner's second explicit tap, for a card the checker called suspicious."""

    def __post_init__(self) -> None:
        if self.channel is DecisionChannel.MODEL and self.session_matches_run is None:
            raise ValidationError("a model decision states whether it is the running session")

    @property
    def decided_by(self) -> DecidedBy:
        match self.channel:
            case DecisionChannel.APP | DecisionChannel.COMPANION:
                return DecidedBy.YOU
            case DecisionChannel.MODEL:
                return DecidedBy.CLAUDE
            case DecisionChannel.POLICY:
                return DecidedBy.POLICY


@dataclass(frozen=True, slots=True)
class AppliedRecord:
    """The record an approved suggestion created, and its version right after the create."""

    kind: str
    id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class Suggestion:
    id: UUID
    owner_id: UUID
    automation_id: UUID
    run_id: UUID
    effect: EffectKind
    effect_version: int
    payload: Mapping[str, object]
    """What will be applied: the proposal, or the owner's edit of it."""
    proposed_payload: Mapping[str, object]
    rationale: str
    """Written by the AI and untrusted. Shown escaped and labelled."""
    datapoint_ids: tuple[UUID, ...]
    dedupe_fingerprint: str
    state: SuggestionState
    expires_at: datetime
    screening_flags: tuple[ScreeningFlag, ...] = ()
    check_state: CheckState = CheckState.OFF
    verdict: Verdict | None = None
    confidence: int | None = None
    """0 to 100, and only ever from the independent checker."""
    bulk_eligible: bool = False
    decided_at: datetime | None = None
    decided_by: DecidedBy | None = None
    decision_channel: DecisionChannel | None = None
    applied_kind: str | None = None
    applied_id: UUID | None = None
    applied_version: int | None = None
    undone_at: datetime | None = None
    apply_error: ApplyError | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValidationError("version must be greater than or equal to 1")
        if len(self.datapoint_ids) > MAX_DATAPOINT_REFS:
            raise ValidationError("too many datapoint references")
        self._check_check_fields()
        self._check_decision_fields()
        if self.bulk_eligible and not (
            self.state is SuggestionState.PENDING
            and self.check_state is CheckState.CHECKED
            and self.verdict is Verdict.OK
            and not self.screening_flags
        ):
            raise ValidationError("only a checked, flag-free, pending suggestion is bulk eligible")

    def _check_check_fields(self) -> None:
        checked = self.check_state is CheckState.CHECKED
        if (self.verdict is not None or self.confidence is not None) and not checked:
            raise ValidationError("a verdict and a confidence come only from a check")
        if checked and (self.verdict is None or self.confidence is None):
            raise ValidationError("a checked suggestion has a verdict and a confidence")
        if self.confidence is not None and not 0 <= self.confidence <= 100:
            raise ValidationError("confidence must be between 0 and 100")

    def _check_decision_fields(self) -> None:
        decided = self.state in (
            SuggestionState.APPLIED,
            SuggestionState.UNDONE,
            SuggestionState.DISMISSED,
        )
        decision_values = (self.decided_at, self.decided_by, self.decision_channel)
        if decided != all(value is not None for value in decision_values) or (
            not decided and any(value is not None for value in decision_values)
        ):
            raise ValidationError("a decision is recorded exactly when one was made")
        applied = self.state in (SuggestionState.APPLIED, SuggestionState.UNDONE)
        applied_values = (self.applied_kind, self.applied_id, self.applied_version)
        if applied != all(value is not None for value in applied_values):
            raise ValidationError("the applied record is set exactly when it was applied")

    @property
    def edited(self) -> bool:
        return self.payload != self.proposed_payload

    @property
    def flagged(self) -> bool:
        return bool(self.screening_flags) or self.verdict is Verdict.SUSPICIOUS

    # --- creation -----------------------------------------------------------------------------

    @classmethod
    def received(
        cls,
        screened: Screened,
        *,
        id: UUID,
        owner_id: UUID,
        automation_id: UUID,
        run_id: UUID,
        dedupe_fingerprint: str,
        expires_at: datetime,
    ) -> "Suggestion":
        """A suggestion as screening left it, before it is queued for a check or shown."""

        return cls(
            id=id,
            owner_id=owner_id,
            automation_id=automation_id,
            run_id=run_id,
            effect=screened.parsed.kind,
            effect_version=screened.parsed.version,
            payload=screened.parsed.data,
            proposed_payload=screened.parsed.data,
            rationale=screened.rationale,
            datapoint_ids=screened.datapoint_ids,
            dedupe_fingerprint=dedupe_fingerprint,
            state=SuggestionState.RECEIVED,
            expires_at=expires_at,
            screening_flags=screened.flags,
        )

    # --- transitions --------------------------------------------------------------------------

    def _expect(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise SuggestionRefusedError(DecisionRefusal.STALE)

    def _next(self, **changes: Any) -> "Suggestion":
        """The suggestion after a transition: version raised, never bulk eligible unless set."""

        changes.setdefault("bulk_eligible", False)
        return replace(self, version=self.version + 1, **changes)

    def _require_state(self, state: SuggestionState) -> None:
        if self.state is not state:
            raise SuggestionRefusedError(DecisionRefusal.NOT_PENDING)

    def screened(self, *, checker_enabled: bool, expected_version: int) -> "Suggestion":
        """Screening is done: queue the check, or show the card unchecked when no checker is on."""

        self._expect(expected_version)
        self._require_state(SuggestionState.RECEIVED)
        if checker_enabled:
            return self._next(state=SuggestionState.CHECKING, check_state=CheckState.QUEUED)
        return self._next(state=SuggestionState.PENDING, check_state=CheckState.OFF)

    def record_check(
        self, verdict: Verdict, confidence: int, *, expected_version: int
    ) -> "Suggestion":
        """The independent checker's verdict. The only way a confidence comes to exist."""

        self._expect(expected_version)
        self._require_state(SuggestionState.CHECKING)
        if not 0 <= confidence <= 100:
            raise ValidationError("confidence must be between 0 and 100")
        return self._next(
            state=SuggestionState.PENDING,
            check_state=CheckState.CHECKED,
            verdict=verdict,
            confidence=confidence,
        )

    def fail_check(self, *, expected_version: int) -> "Suggestion":
        """The check did not produce a usable answer: the card is shown as not checked."""

        self._expect(expected_version)
        self._require_state(SuggestionState.CHECKING)
        return self._next(state=SuggestionState.PENDING, check_state=CheckState.FAILED)

    def edit(
        self,
        parsed: ParsedPayload,
        edited_flags: Sequence[ScreeningFlag],
        *,
        expected_version: int,
    ) -> "Suggestion":
        """The owner's edit. The payload is validated and screened again (`edited_flags` is
        `screening.flags_for_edit`'s answer); the card leaves any group, and keeps its earlier
        verdict, which was about the proposal.

        A flag is dropped only when the payload text that raised it was changed: a flag from the
        rationale or the source stays, whatever `edited_flags` holds."""

        self._expect(expected_version)
        self._require_state(SuggestionState.PENDING)
        if parsed.kind is not self.effect:
            raise ValidationError("an edit cannot change the effect")
        flags = flags_after_edit(self.screening_flags, self.payload, self.rationale, edited_flags)
        return self._next(payload=parsed.data, screening_flags=flags, apply_error=None)

    def _authorize(self, context: DecisionContext, decision: Decision, now: datetime) -> None:
        self._require_state(SuggestionState.PENDING)
        if now >= self.expires_at:
            raise SuggestionRefusedError(DecisionRefusal.EXPIRED)
        if context.channel is DecisionChannel.POLICY:
            raise SuggestionRefusedError(DecisionRefusal.NOT_ALLOWED)
        if context.channel is DecisionChannel.MODEL:
            if self.flagged:
                raise SuggestionRefusedError(DecisionRefusal.NEEDS_APP)
            if context.session_matches_run:
                raise SuggestionRefusedError(DecisionRefusal.SAME_SESSION)
        elif (
            decision is Decision.APPROVE
            and self.verdict is Verdict.SUSPICIOUS
            and not context.confirmed
        ):
            raise SuggestionRefusedError(DecisionRefusal.NEEDS_CONFIRMATION)

    def approve(
        self,
        context: DecisionContext,
        applied: AppliedRecord,
        *,
        now: datetime,
        expected_version: int,
    ) -> "Suggestion":
        """The owner, or a model on the owner's word, approved and the record was created."""

        self._expect(expected_version)
        self._authorize(context, Decision.APPROVE, now)
        return self._next(
            state=SuggestionState.APPLIED,
            decided_at=now,
            decided_by=context.decided_by,
            decision_channel=context.channel,
            applied_kind=applied.kind,
            applied_id=applied.id,
            applied_version=applied.version,
            apply_error=None,
        )

    def dismiss(
        self, context: DecisionContext, *, now: datetime, expected_version: int
    ) -> "Suggestion":
        """Dismissed. The fingerprint stays, so the same proposal is never made again."""

        self._expect(expected_version)
        self._authorize(context, Decision.DISMISS, now)
        return self._next(
            state=SuggestionState.DISMISSED,
            decided_at=now,
            decided_by=context.decided_by,
            decision_channel=context.channel,
        )

    def apply_failed(self, error: ApplyError, *, expected_version: int) -> "Suggestion":
        """Applying failed. The card stays pending and shows why."""

        self._expect(expected_version)
        self._require_state(SuggestionState.PENDING)
        return self._next(apply_error=error)

    def auto_apply(
        self, applied: AppliedRecord, *, now: datetime, expected_version: int
    ) -> "Suggestion":
        """Applied by the opt-in policy. The card must be one no policy may refuse: a direct
        effect, checked, `ok`, without a flag and unedited. The thresholds and counts are
        `grouping.auto_apply_refusal`'s."""

        self._expect(expected_version)
        self._require_state(SuggestionState.PENDING)
        if (
            self.effect not in AUTO_APPLY_EFFECTS
            or self.check_state is not CheckState.CHECKED
            or self.verdict is not Verdict.OK
            or self.screening_flags
            or self.edited
            or now >= self.expires_at
        ):
            raise SuggestionRefusedError(DecisionRefusal.AUTO_NOT_ALLOWED)
        return self._next(
            state=SuggestionState.APPLIED,
            decided_at=now,
            decided_by=DecidedBy.POLICY,
            decision_channel=DecisionChannel.POLICY,
            applied_kind=applied.kind,
            applied_id=applied.id,
            applied_version=applied.version,
        )

    def expire(self, *, now: datetime) -> "Suggestion":
        """A pending card past its time to live. Nothing is decided."""

        self._require_state(SuggestionState.PENDING)
        if now < self.expires_at:
            raise SuggestionRefusedError(DecisionRefusal.NOT_EXPIRED)
        return self._next(state=SuggestionState.EXPIRED)

    def undo(
        self,
        *,
        record_version: int,
        record_trashed: bool,
        now: datetime,
        expected_version: int,
    ) -> "Suggestion":
        """Undo an applied suggestion while the record it created is as it was created.

        The caller moves the record to the trash. When the record changed since, or is already
        in the trash, the undo is refused and the owner uses the trash directly.
        """

        self._expect(expected_version)
        if self.state is not SuggestionState.APPLIED:
            raise SuggestionRefusedError(DecisionRefusal.NOT_APPLIED)
        if record_trashed or record_version != self.applied_version:
            raise SuggestionRefusedError(DecisionRefusal.CHANGED_SINCE_APPLY)
        return self._next(state=SuggestionState.UNDONE, undone_at=now)


# --- dedupe -------------------------------------------------------------------------------------


def dedupe_fingerprint(
    key: bytes,
    automation_id: UUID,
    parsed: ParsedPayload,
    source_fingerprints: Collection[str],
) -> str:
    """HMAC-SHA256 over what a suggestion is about: automation, effect, target and sources.

    The target is normalised (case, spacing, hidden characters), so a cosmetic change in the
    proposal gives the same fingerprint. The fingerprint is unique per automation across every
    state, which is how a dismissed suggestion stays dismissed.
    """

    if len(key) < MIN_FINGERPRINT_KEY_BYTES:
        raise ValueError("the fingerprint key is too short")
    canonical = canonical_json(
        {
            "automation": str(automation_id),
            "effect": parsed.kind.value,
            "target": target_key(parsed),
            "sources": sorted(set(source_fingerprints)),
        }
    )
    return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def fresh_indexes(fingerprints: Sequence[str], known: Collection[str]) -> list[int]:
    """The positions of fingerprints that are new: not known in any state, not repeated here."""

    seen = set(known)
    fresh: list[int] = []
    for index, fingerprint in enumerate(fingerprints):
        if fingerprint not in seen:
            seen.add(fingerprint)
            fresh.append(index)
    return fresh

"""The spec of an automation and the digest the owner approves.

An automation runs only while the digest of its current spec equals the digest the owner
approved. The digest covers everything that steers a run (instruction, sources, runner, cadence,
effects, apply mode, thresholds, budget and model tier) and nothing else: not the title, the
state or a pause. A model that edits the instruction therefore makes the automation unrunnable
until the owner approves again in the app.
"""

import hashlib
import json
import re
from collections.abc import Collection, Mapping
from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)

from sidekick.automations.domain.effects import AUTO_APPLY_EFFECTS, CATALOGUE, EffectKind
from sidekick.automations.domain.text import normalise_block, normalise_line
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.errors.core import SidekickErrorReason
from sidekick.tasks.domain.recurrence import RecurrenceRule
from sidekick.work.domain.ai_spec import MAX_SPEC_BUDGET_USD

DIGEST_VERSION = 1
MAX_TITLE_CHARS = 120
MAX_PURPOSE_CHARS = 300
MAX_INSTRUCTION_CHARS = 4_000
MICROUSD_PER_USD = 1_000_000
DEFAULT_RUN_BUDGET_MICROUSD = MICROUSD_PER_USD
"""One US dollar per run, set by the owner on 2026-11-22."""
MAX_RUN_BUDGET_MICROUSD = round(MAX_SPEC_BUDGET_USD * MICROUSD_PER_USD)
MAX_SUGGESTIONS_PER_RUN = 25
BULK_THRESHOLD_RANGE = (80, 99)
AUTO_THRESHOLD_RANGE = (90, 99)

_LOCAL_TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d", re.ASCII)


class Source(StrEnum):
    MAIL = "mail"
    CALENDAR = "calendar"
    CHAT = "chat"
    WEB = "web"
    SIDEKICK = "sidekick"
    MANUAL = "manual"


class Runner(StrEnum):
    CLAUDE = "claude"
    CLAUDE_CODE = "claude_code"
    SERVER = "server"
    ANY = "any"


class ApplyMode(StrEnum):
    SUGGEST = "suggest"
    AUTO_LOW_RISK = "auto_low_risk"


class ModelTier(StrEnum):
    """Which model a server run uses: a very cheap one, or the configured Anthropic model."""

    STANDARD = "standard"
    STRONG = "strong"


class AutomationState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ApprovalState(StrEnum):
    NOT_APPROVED = "not_approved"
    APPROVED = "approved"
    CHANGED_SINCE_APPROVAL = "changed_since_approval"


class NotRunnableCause(StrEnum):
    NOT_ACTIVE = "not_active"
    NOT_APPROVED = "not_approved"
    CHANGED_SINCE_APPROVAL = "changed_since_approval"
    OTHER_RUNNER = "other_runner"


_NOT_RUNNABLE_REASONS: Mapping[NotRunnableCause, SidekickErrorReason] = {
    NotRunnableCause.NOT_ACTIVE: "automation_not_active",
    NotRunnableCause.NOT_APPROVED: "automation_not_approved",
    NotRunnableCause.CHANGED_SINCE_APPROVAL: "automation_changed_since_approval",
    NotRunnableCause.OTHER_RUNNER: "automation_other_runner",
}


class NotRunnableError(ConflictError):
    """The automation may not run now. The cause is a fixed code and holds no owner text; the
    error's closed reason is what an MCP client is told."""

    safe_title = "Automation cannot run"

    def __init__(self, cause: NotRunnableCause) -> None:
        super().__init__(cause.value, reason=_NOT_RUNNABLE_REASONS[cause])
        self.cause = cause


class ApprovalDigestMismatchError(ConflictError):
    """The owner approved a digest that is no longer the spec's current digest."""

    safe_title = "Automation changed before approval"

    def __init__(self, message: str) -> None:
        super().__init__(message, reason="automation_changed")


class Cadence(BaseModel):
    """When a scheduled run is due: a recurrence rule plus the local time of day."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    frequency: str
    interval: int = 1
    weekdays: tuple[int, ...] = ()
    day_of_month: int | None = None
    last_weekday: bool = False
    until: date | None = None
    local_time: str

    @field_validator("weekdays", mode="after")
    @classmethod
    def _sorted_weekdays(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(sorted(value))

    @field_validator("local_time", mode="after")
    @classmethod
    def _check_time(cls, value: str) -> str:
        if not _LOCAL_TIME.fullmatch(value):
            raise ValueError("local_time must be HH:MM")
        return value

    @model_validator(mode="after")
    def _check_rule(self) -> Self:
        try:
            self.rule()
        except ValidationError as error:
            raise ValueError("invalid recurrence") from error
        return self

    def rule(self) -> RecurrenceRule:
        return RecurrenceRule(
            frequency=self.frequency,
            interval=self.interval,
            weekdays=tuple(sorted(self.weekdays)),
            day_of_month=self.day_of_month,
            last_weekday=self.last_weekday,
            until=self.until,
        )


def _unique_sorted[T: StrEnum](values: list[T]) -> list[T]:
    return sorted(set(values), key=lambda item: item.value)


class AutomationSpecV1(BaseModel):
    """What steers a run. Owner text, so trusted; still cleaned of invisible characters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec_version: int = Field(default=1, ge=1, le=1)
    purpose: Annotated[str, StringConstraints(min_length=1, max_length=MAX_PURPOSE_CHARS)]
    instruction: Annotated[str, StringConstraints(min_length=1, max_length=MAX_INSTRUCTION_CHARS)]
    sources: Annotated[list[Source], Field(max_length=len(Source))] = Field(
        default_factory=list[Source]
    )
    runner: Runner = Runner.ANY
    cadence: Cadence | None = None
    """No cadence means the automation runs only when the owner starts it."""
    allowed_effects: Annotated[list[EffectKind], Field(max_length=len(EffectKind))] = Field(
        default_factory=list[EffectKind]
    )
    apply_mode: ApplyMode = ApplyMode.SUGGEST
    auto_effects: Annotated[list[EffectKind], Field(max_length=len(EffectKind))] = Field(
        default_factory=list[EffectKind]
    )
    bulk_threshold: int = Field(default=90, ge=BULK_THRESHOLD_RANGE[0], le=BULK_THRESHOLD_RANGE[1])
    auto_threshold: int = Field(default=95, ge=AUTO_THRESHOLD_RANGE[0], le=AUTO_THRESHOLD_RANGE[1])
    max_suggestions_per_run: int = Field(default=15, ge=1, le=MAX_SUGGESTIONS_PER_RUN)
    run_budget_microusd: int = Field(
        default=DEFAULT_RUN_BUDGET_MICROUSD, gt=0, le=MAX_RUN_BUDGET_MICROUSD
    )
    model_tier: ModelTier = ModelTier.STANDARD

    @field_validator("purpose", mode="before")
    @classmethod
    def _clean_purpose(cls, value: object) -> object:
        return normalise_line(value) if isinstance(value, str) else value

    @field_validator("instruction", mode="before")
    @classmethod
    def _clean_instruction(cls, value: object) -> object:
        return normalise_block(value) if isinstance(value, str) else value

    @field_validator("sources", "allowed_effects", "auto_effects", mode="after")
    @classmethod
    def _sorted_unique(cls, value: list[StrEnum]) -> list[StrEnum]:
        return _unique_sorted(value)

    @model_validator(mode="after")
    def _check_combinations(self) -> Self:
        if self.auto_threshold < self.bulk_threshold:
            raise ValueError("auto_threshold cannot be below bulk_threshold")
        if not set(self.auto_effects) <= set(self.allowed_effects) & AUTO_APPLY_EFFECTS:
            raise ValueError("auto_effects must be allowed effects that may be applied directly")
        if self.auto_effects and self.apply_mode is not ApplyMode.AUTO_LOW_RISK:
            raise ValueError("auto_effects need apply_mode auto_low_risk")
        return self


def parse_spec(raw: object) -> AutomationSpecV1:
    """The spec a stored or sent value describes, or the domain's validation error."""

    try:
        return AutomationSpecV1.model_validate(raw)
    except PydanticValidationError as error:
        details = error.errors(include_input=False, include_url=False)
        location = ".".join(str(part) for part in details[0]["loc"]) if details else ""
        raise ValidationError(f"invalid automation spec: {location}".strip(": ")) from error


def normalise_title(value: str) -> str:
    """The title as it is stored: one line, 1 to 120 characters."""

    title = normalise_line(value)
    if not 1 <= len(title) <= MAX_TITLE_CHARS:
        raise ValidationError(f"title must be 1-{MAX_TITLE_CHARS} characters long")
    return title


def spec_digest(spec: AutomationSpecV1) -> str:
    """SHA-256 over the canonical JSON of every field of the spec.

    The spec holds no title, state or pause, so none of them can change the digest. Sources and
    effects are sorted and unique, so the order the owner listed them in does not matter.
    """

    canonical = {"v": DIGEST_VERSION, "spec": spec.model_dump(mode="json")}
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


AUTO_CONFIRMED_VERSION = 1


def auto_confirmed_digest(current_digest: str) -> str:
    """The digest stored when the owner approved a spec that applies without a click and
    confirmed that in the same call. It covers the spec's digest and the marker, so an approval
    made without the confirmation (or before there was one) never equals it."""

    marker = f"auto_apply_confirmed:v{AUTO_CONFIRMED_VERSION}:{current_digest}"
    return hashlib.sha256(marker.encode("utf-8")).hexdigest()


def approval_state(current_digest: str, approved_digest: str | None) -> ApprovalState:
    if approved_digest is None:
        return ApprovalState.NOT_APPROVED
    if approved_digest in (current_digest, auto_confirmed_digest(current_digest)):
        return ApprovalState.APPROVED
    return ApprovalState.CHANGED_SINCE_APPROVAL


def is_auto_apply_confirmed(current_digest: str, approved_digest: str | None) -> bool:
    """Whether the owner approved exactly this spec and confirmed it applies without a click."""

    return approved_digest == auto_confirmed_digest(current_digest)


def require_runnable(
    state: AutomationState, current_digest: str, approved_digest: str | None
) -> None:
    """Raise unless the automation is active and its current spec is the approved one."""

    if state is not AutomationState.ACTIVE:
        raise NotRunnableError(NotRunnableCause.NOT_ACTIVE)
    match approval_state(current_digest, approved_digest):
        case ApprovalState.NOT_APPROVED:
            raise NotRunnableError(NotRunnableCause.NOT_APPROVED)
        case ApprovalState.CHANGED_SINCE_APPROVAL:
            raise NotRunnableError(NotRunnableCause.CHANGED_SINCE_APPROVAL)
        case ApprovalState.APPROVED:
            return


def is_runnable(state: AutomationState, current_digest: str, approved_digest: str | None) -> bool:
    try:
        require_runnable(state, current_digest, approved_digest)
    except NotRunnableError:
        return False
    return True


def approve(
    spec: AutomationSpecV1, presented_digest: str, *, auto_apply_confirmed: bool = False
) -> str:
    """The digest to store as approved, when the owner approved exactly the current spec.

    A spec that applies without a click is stored with the confirmation bound into the digest
    (`auto_confirmed_digest`) and is refused without it.

    The owner approves the digest the app showed. When the spec changed since then, the approval
    is refused and the owner looks again.
    """

    if not spec.allowed_effects:
        raise ValidationError("an automation needs at least one allowed effect")
    if not spec.sources:
        raise ValidationError("an automation needs at least one source")
    current = spec_digest(spec)
    if presented_digest != current:
        raise ApprovalDigestMismatchError("the automation changed since it was shown")
    if spec.apply_mode is ApplyMode.AUTO_LOW_RISK:
        if not auto_apply_confirmed:
            raise ValidationError("applying without a click needs the owner's confirmation")
        return auto_confirmed_digest(current)
    return current


def require_budget_within(spec: AutomationSpecV1, cap_microusd: int) -> None:
    """Refuse a run budget above the automations' monthly cap.

    The cap itself is validated against the monthly cap when the settings are read, so a run
    budget within it is also within the month.
    """

    if spec.run_budget_microusd > cap_microusd:
        raise ValidationError("the run budget is above the monthly cap for automations")


def required_write_scopes(spec: AutomationSpecV1) -> frozenset[str]:
    """The write scopes the approving actor needs: one per allowed effect."""

    return frozenset(CATALOGUE[effect].write_scope for effect in spec.allowed_effects)


def missing_write_scopes(spec: AutomationSpecV1, granted: Collection[str]) -> frozenset[str]:
    return required_write_scopes(spec) - set(granted)

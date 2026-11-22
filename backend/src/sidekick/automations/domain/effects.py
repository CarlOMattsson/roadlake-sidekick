"""The catalogue of effects a suggestion may propose, and the payload each one carries.

The catalogue is closed and versioned. A suggestion names one effect from it; what the effect may
carry is the payload model below and nothing else (`extra="forbid"`), so a payload cannot smuggle
a recipient, a link target or a confidence value. Sending, deleting, completing, buying, paying
and publishing are not effects and cannot be named. A change to a payload is a new version of the
effect, never a reshape of an old one: pending suggestions store the payload as it was proposed.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)

from sidekick.automations.domain.text import match_key, normalise_block, normalise_line
from sidekick.contacts.domain.normalization import (
    PROFILE_FIELD_LIMITS,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from sidekick.shared.errors import ValidationError

MAX_PAYLOAD_BYTES = 8_000
"""The most a stored payload takes as canonical JSON: below the database's 8192-byte limit on
`payload::text`, which spells the same JSON with a few more spaces."""
MAX_RATIONALE_CHARS = 300
MAX_DATAPOINT_REFS = 10
_MAX_TITLE_CHARS = 200
_MAX_TASK_DESCRIPTION_CHARS = 2_000
_MAX_CONTEXT_NOTE_CHARS = 2_000


class EffectKind(StrEnum):
    """What a suggestion may do. Every member is undoable and stays inside Sidekick."""

    CREATE_TASK = "create_task"
    CREATE_CONTACT = "create_contact"


AUTO_APPLY_EFFECTS = frozenset({EffectKind.CREATE_TASK, EffectKind.CREATE_CONTACT})
"""The ceiling for `auto_effects`: no automation may apply any other effect without the owner."""


class PayloadProblem(StrEnum):
    """Why a payload or an effect name was refused. The values are also rejection codes."""

    EFFECT_UNKNOWN = "effect_unknown"
    SCHEMA_INVALID = "schema_invalid"
    TOO_LONG = "too_long"


def _blank_to_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CreateTaskV1(_Payload):
    """`create_task.v1`: one Task. Tags, contacts and urgency stay with the owner."""

    title: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_TITLE_CHARS)]
    description: (
        Annotated[str, StringConstraints(max_length=_MAX_TASK_DESCRIPTION_CHARS)] | None
    ) = None
    project_id: UUID | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    due_on: date | None = None
    """A calendar day; the application turns it into the end of that day in the owner's zone."""

    @field_validator("title", mode="before")
    @classmethod
    def _clean_title(cls, value: object) -> object:
        return normalise_line(value) if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def _clean_description(cls, value: object) -> object:
        value = _blank_to_none(value)
        return normalise_block(value) if isinstance(value, str) else value


class CreateContactV1(_Payload):
    """`create_contact.v1`: one Contact with the fields a mail signature gives."""

    display_name: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_TITLE_CHARS)]
    email: str | None = None
    phone: str | None = None
    organization: (
        Annotated[str, StringConstraints(max_length=PROFILE_FIELD_LIMITS["organization"])] | None
    ) = None
    role: Annotated[str, StringConstraints(max_length=PROFILE_FIELD_LIMITS["role"])] | None = None
    context_note: Annotated[str, StringConstraints(max_length=_MAX_CONTEXT_NOTE_CHARS)] | None = (
        None
    )

    @field_validator("display_name", mode="before")
    @classmethod
    def _clean_name(cls, value: object) -> object:
        return normalise_line(value) if isinstance(value, str) else value

    @field_validator("display_name", mode="after")
    @classmethod
    def _check_name(cls, value: str) -> str:
        try:
            return normalize_name(value)[0]
        except ValidationError as error:
            raise ValueError("invalid display name") from error

    @field_validator("organization", "role", mode="before")
    @classmethod
    def _clean_line(cls, value: object) -> object:
        value = _blank_to_none(value)
        return normalise_line(value) if isinstance(value, str) else value

    @field_validator("context_note", mode="before")
    @classmethod
    def _clean_note(cls, value: object) -> object:
        value = _blank_to_none(value)
        return normalise_block(value) if isinstance(value, str) else value

    @field_validator("email", mode="after")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        try:
            return normalize_email(value)[0]
        except ValidationError as error:
            raise ValueError("invalid email") from error

    @field_validator("phone", mode="after")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        try:
            return normalize_phone(value)[0]
        except ValidationError as error:
            raise ValueError("invalid phone") from error


type PayloadValue = CreateTaskV1 | CreateContactV1


@dataclass(frozen=True, slots=True)
class EffectSpec:
    """One catalogue entry."""

    kind: EffectKind
    version: int
    model: type[CreateTaskV1] | type[CreateContactV1]
    write_scope: str
    """The scope an actor needs to write the record this effect creates."""
    low_risk: bool

    @property
    def label(self) -> str:
        return f"{self.kind.value}.v{self.version}"


CATALOGUE: Mapping[EffectKind, EffectSpec] = MappingProxyType(
    {
        EffectKind.CREATE_TASK: EffectSpec(
            EffectKind.CREATE_TASK, 1, CreateTaskV1, "tasks:write", low_risk=True
        ),
        EffectKind.CREATE_CONTACT: EffectSpec(
            EffectKind.CREATE_CONTACT, 1, CreateContactV1, "contacts:write", low_risk=True
        ),
    }
)


def resolve_effect(name: str) -> EffectKind | None:
    """The effect `name` stands for: `create_task` or `create_task.v1`; nothing else matches.

    A version other than the catalogue's current one does not resolve, so an old or invented
    version never reaches a payload model.
    """

    base, dot, version = name.partition(".")
    try:
        kind = EffectKind(base)
    except ValueError:
        return None
    if not dot:
        return kind
    return kind if version == f"v{CATALOGUE[kind].version}" else None


def effect_schema(kind: EffectKind) -> dict[str, Any]:
    """The JSON Schema of the effect's payload, for the brief a runner is given."""

    return CATALOGUE[kind].model.model_json_schema()


@dataclass(frozen=True, slots=True)
class ParsedPayload:
    """A payload that passed its schema: the effect, its validated value and the stored form."""

    kind: EffectKind
    version: int
    value: PayloadValue
    data: Mapping[str, object]
    """The normalised payload as JSON values, as it is stored and hashed."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_payload(kind: EffectKind, raw: object) -> ParsedPayload | PayloadProblem:
    """The validated, normalised payload of `kind`, or why it was refused."""

    entry = CATALOGUE[kind]
    try:
        value = entry.model.model_validate(raw)
    except PydanticValidationError as error:
        too_long = any(
            detail["type"] in {"string_too_long", "too_long"}
            for detail in error.errors(include_input=False, include_url=False)
        )
        return PayloadProblem.TOO_LONG if too_long else PayloadProblem.SCHEMA_INVALID
    data: dict[str, object] = value.model_dump(mode="json")
    if len(canonical_json(data).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        return PayloadProblem.TOO_LONG
    return ParsedPayload(kind, entry.version, value, data)


def free_text(parsed: ParsedPayload) -> tuple[str, ...]:
    """The free-text fields of the payload, which screening reads for links and payment text.

    E-mail and phone are structured values and are screened separately.
    """

    value = parsed.value
    if isinstance(value, CreateTaskV1):
        return tuple(item for item in (value.title, value.description) if item)
    return tuple(
        item
        for item in (value.display_name, value.organization, value.role, value.context_note)
        if item
    )


def contact_email(parsed: ParsedPayload) -> str | None:
    value = parsed.value
    return value.email if isinstance(value, CreateContactV1) else None


def project_reference(parsed: ParsedPayload) -> UUID | None:
    value = parsed.value
    return value.project_id if isinstance(value, CreateTaskV1) else None


def target_key(parsed: ParsedPayload) -> str:
    """What the effect is about, in a form that survives case, spacing and hidden characters.

    A task is its title in its project; a contact is its e-mail address or, without one, its name.
    """

    value = parsed.value
    if isinstance(value, CreateTaskV1):
        return f"{match_key(value.title)}|{value.project_id or ''}"
    if value.email:
        return f"email:{match_key(value.email)}"
    return f"name:{match_key(value.display_name)}"

"""Datapoints: the facts a run read, never an action.

A runner reduces what it read (a mail, a calendar entry, a chat message) to a few closed facts
and records them with a reference to where it read them. The fields are closed per kind, so a
datapoint cannot carry an instruction as a field of its own, and the client's own reference to the
source (a Message-ID, say) is kept only as a keyed hash. A suggestion points at the datapoints it
comes from, which is how screening can tell whose mail a proposed contact came from.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from pydantic import ValidationError as PydanticValidationError

from sidekick.automations.domain.effects import canonical_json
from sidekick.automations.domain.fingerprints import keyed_hash
from sidekick.automations.domain.screening import RejectionCode, SourceInfo
from sidekick.automations.domain.text import normalise_block, normalise_line
from sidekick.contacts.domain.normalization import normalize_email, normalize_phone
from sidekick.shared.errors import ValidationError

MAX_DATAPOINTS_PER_CALL = 50
MAX_DATAPOINTS_PER_RUN = 200
MAX_FIELDS_BYTES = 3_800
"""The most the fields take as canonical JSON: below the database's 4096-byte limit on
`fields::text`, which spells the same JSON with a few more spaces."""
MAX_SOURCE_REF_CHARS = 300
MAX_SOURCE_LABEL_CHARS = 160
MAX_REF_KEY_CHARS = 40
DATAPOINT_RETENTION = timedelta(days=30)
"""How long the fields and the label of a datapoint are kept; a purge then empties both."""


class DatapointKind(StrEnum):
    PERSON = "person"
    ORGANISATION = "organisation"
    EVENT = "event"
    COMMITMENT = "commitment"
    REQUEST = "request"
    NOTE = "note"


class SourceKind(StrEnum):
    MAIL = "mail"
    CALENDAR = "calendar"
    CHAT = "chat"
    WEB = "web"
    API = "api"
    SHARE = "share"
    SIDEKICK = "sidekick"


_Line = Annotated[str, StringConstraints(max_length=200)]


class DatapointFields(BaseModel):
    """Every field any kind may carry; `FIELDS_BY_KIND` says which belong to which kind."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: _Line | None = None
    email: Annotated[str, StringConstraints(max_length=320)] | None = None
    phone: Annotated[str, StringConstraints(max_length=64)] | None = None
    organisation: _Line | None = None
    role: Annotated[str, StringConstraints(max_length=120)] | None = None
    title: _Line | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location: _Line | None = None
    what: Annotated[str, StringConstraints(max_length=500)] | None = None
    who: _Line | None = None
    due_on: date | None = None
    text: Annotated[str, StringConstraints(max_length=1_500)] | None = None
    is_sender: bool | None = None
    """For a person read from a mail: this is the one who sent it."""

    @field_validator(
        "name", "organisation", "role", "title", "location", "what", "who", mode="before"
    )
    @classmethod
    def _clean_line(cls, value: object) -> object:
        return _blank_to_none(normalise_line(value)) if isinstance(value, str) else value

    @field_validator("text", mode="before")
    @classmethod
    def _clean_block(cls, value: object) -> object:
        return _blank_to_none(normalise_block(value)) if isinstance(value, str) else value

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


def _blank_to_none(value: str) -> str | None:
    return value or None


FIELDS_BY_KIND: Mapping[DatapointKind, frozenset[str]] = {
    DatapointKind.PERSON: frozenset(
        {"name", "email", "phone", "organisation", "role", "is_sender"}
    ),
    DatapointKind.ORGANISATION: frozenset({"name", "email", "phone", "location"}),
    DatapointKind.EVENT: frozenset({"title", "starts_at", "ends_at", "location"}),
    DatapointKind.COMMITMENT: frozenset({"what", "who", "due_on"}),
    DatapointKind.REQUEST: frozenset({"what", "who", "due_on"}),
    DatapointKind.NOTE: frozenset({"text"}),
}
REQUIRED_FIELD: Mapping[DatapointKind, str] = {
    DatapointKind.PERSON: "name",
    DatapointKind.ORGANISATION: "name",
    DatapointKind.EVENT: "title",
    DatapointKind.COMMITMENT: "what",
    DatapointKind.REQUEST: "what",
    DatapointKind.NOTE: "text",
}


def parse_fields(kind: DatapointKind, raw: object) -> Mapping[str, object] | RejectionCode:
    """The validated, normalised fields of a datapoint of `kind`, or why they were refused."""

    try:
        parsed = DatapointFields.model_validate(raw)
    except PydanticValidationError as error:
        too_long = any(
            detail["type"] == "string_too_long"
            for detail in error.errors(include_input=False, include_url=False)
        )
        return RejectionCode.TOO_LONG if too_long else RejectionCode.SCHEMA_INVALID
    data: dict[str, object] = parsed.model_dump(mode="json", exclude_none=True)
    if not set(data) <= FIELDS_BY_KIND[kind] or REQUIRED_FIELD[kind] not in data:
        return RejectionCode.SCHEMA_INVALID
    if len(canonical_json(data).encode("utf-8")) > MAX_FIELDS_BYTES:
        return RejectionCode.TOO_LONG
    return data


@dataclass(frozen=True, slots=True)
class SubmittedDatapoint:
    """One datapoint as a runner sent it, before it is checked."""

    kind: DatapointKind
    fields: object
    source_kind: SourceKind
    source_ref: str
    key: str | None = None
    """A name the runner gives it, so a suggestion in the same call can point at it."""
    source_label: str | None = None
    source_received_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Datapoint:
    """A stored datapoint. After a purge `fields` and `source_label` are empty."""

    id: UUID
    owner_id: UUID
    run_id: UUID
    automation_id: UUID
    kind: DatapointKind
    fields: Mapping[str, object] | None
    source_kind: SourceKind
    source_fingerprint: str
    source_label: str | None
    source_received_at: datetime | None
    created_at: datetime
    purge_after: datetime
    purged_at: datetime | None = None


def clean_source_label(value: str | None) -> str | None:
    """The label as stored: one line, at most 160 characters, never empty."""

    if value is None:
        return None
    label = normalise_line(value)[:MAX_SOURCE_LABEL_CHARS].rstrip()
    return label or None


def source_fingerprint(key: bytes, source_kind: SourceKind, source_ref: str) -> str:
    """The keyed hash of the runner's own reference to a source; the reference is never stored."""

    return keyed_hash(key, source_kind.value, normalise_line(source_ref))


def sender_domain(fields: Mapping[str, object] | None) -> str | None:
    """The domain of the sender a person datapoint names, lower case."""

    if not fields or fields.get("is_sender") is not True:
        return None
    email = fields.get("email")
    if not isinstance(email, str) or "@" not in email:
        return None
    return email.rpartition("@")[2].casefold() or None


def source_infos(datapoints: Sequence[Datapoint]) -> dict[UUID, SourceInfo]:
    """What screening knows of each datapoint's source, never its text.

    A mail's sender is a person datapoint of the same mail: every datapoint of that mail (same
    fingerprint) carries the sender's domain.
    """

    senders: dict[str, str] = {}
    for item in datapoints:
        domain = sender_domain(item.fields)
        if domain is not None and item.source_kind is SourceKind.MAIL:
            senders[item.source_fingerprint] = domain
    return {
        item.id: SourceInfo(
            kind=item.source_kind.value,
            fingerprint=item.source_fingerprint,
            sender_domain=senders.get(item.source_fingerprint),
        )
        for item in datapoints
    }


def counts_by_source(
    suggestion_refs: Collection[Sequence[UUID]], datapoints: Sequence[Datapoint]
) -> dict[str, int]:
    """How many suggestions point at each source: one per suggestion and source."""

    fingerprints = {item.id: item.source_fingerprint for item in datapoints}
    counts: dict[str, int] = {}
    for refs in suggestion_refs:
        for fingerprint in {fingerprints[ref] for ref in refs if ref in fingerprints}:
            counts[fingerprint] = counts.get(fingerprint, 0) + 1
    return counts

"""Framework-independent immutable Journal source rules."""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

from sidekick.shared.errors import InvalidInputError

_ALLOWED_CONTROL_CHARACTERS = frozenset({"\t", "\n", "\r"})
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,4}$")


class SourceType(StrEnum):
    MANUAL_TEXT = "manual_text"
    TRANSCRIPT_TEXT = "transcript_text"


def require_aware(value: datetime | None, field_name: str) -> None:
    """Reject naive datetimes at the framework-independent boundary."""

    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise InvalidInputError(f"{field_name} must be timezone-aware")


def validate_raw_text(raw_text: str) -> str:
    """Validate retained source bytes without normalizing or trimming them."""

    if not isinstance(cast(object, raw_text), str):
        raise InvalidInputError("raw_text must be text")
    if not 1 <= len(raw_text) <= 100_000 or not raw_text.strip():
        raise InvalidInputError("raw_text must contain 1 to 100000 nonblank characters")
    if any(
        character not in _ALLOWED_CONTROL_CHARACTERS
        and unicodedata.category(character) in {"Cc", "Cs"}
        for character in raw_text
    ):
        raise InvalidInputError("raw_text contains an invalid control character")
    return raw_text


def _canonical_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    require_aware(value, "fingerprint datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def content_fingerprint(
    *,
    source_type: SourceType,
    journal_date: date,
    occurred_at: datetime | None,
    source_recorded_at: datetime | None,
    raw_text: str,
    language: str | None,
    replaces_source_id: UUID | None,
) -> str:
    """Return a stable SHA-256 over source content and provenance metadata."""

    if not isinstance(cast(object, source_type), SourceType):
        raise InvalidInputError("unsupported source type")
    validate_raw_text(raw_text)
    require_aware(occurred_at, "occurred_at")
    require_aware(source_recorded_at, "source_recorded_at")
    payload = {
        "journal_date": journal_date.isoformat(),
        "language": language,
        "occurred_at": _canonical_datetime(occurred_at),
        "raw_text": raw_text,
        "replaces_source_id": str(replaces_source_id) if replaces_source_id else None,
        "source_recorded_at": _canonical_datetime(source_recorded_at),
        "source_type": source_type.value,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class JournalSource:
    id: UUID
    owner_id: UUID
    source_type: SourceType
    journal_date: date
    occurred_at: datetime | None
    source_recorded_at: datetime | None
    raw_text: str
    language: str | None
    replaces_source_id: UUID | None
    created_at: datetime
    content_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.source_type), SourceType):
            raise InvalidInputError("unsupported source type")
        validate_raw_text(self.raw_text)
        require_aware(self.occurred_at, "occurred_at")
        require_aware(self.source_recorded_at, "source_recorded_at")
        require_aware(self.created_at, "created_at")
        if self.language is not None and (
            not 2 <= len(self.language) <= 35 or not _LANGUAGE_PATTERN.fullmatch(self.language)
        ):
            raise InvalidInputError(
                "language must be a BCP-47-like tag containing 2 to 35 characters"
            )
        if self.replaces_source_id == self.id:
            raise InvalidInputError("a source cannot replace itself")
        object.__setattr__(
            self,
            "content_fingerprint",
            content_fingerprint(
                source_type=self.source_type,
                journal_date=self.journal_date,
                occurred_at=self.occurred_at,
                source_recorded_at=self.source_recorded_at,
                raw_text=self.raw_text,
                language=self.language,
                replaces_source_id=self.replaces_source_id,
            ),
        )


def replacement_source(
    replaced: JournalSource,
    *,
    source_id: UUID,
    raw_text: str,
    created_at: datetime,
    owner_id: UUID | None = None,
) -> JournalSource:
    """Create a new source preserving the replaced row as direct provenance."""

    replacement_owner = replaced.owner_id if owner_id is None else owner_id
    if source_id == replaced.id:
        raise InvalidInputError("replacement source must have a distinct id")
    if replacement_owner != replaced.owner_id:
        raise InvalidInputError("replacement source must have the same owner")
    require_aware(created_at, "created_at")
    if created_at < replaced.created_at:
        raise InvalidInputError("replacement source cannot predate the source it replaces")
    return JournalSource(
        id=source_id,
        owner_id=replacement_owner,
        source_type=replaced.source_type,
        journal_date=replaced.journal_date,
        occurred_at=replaced.occurred_at,
        source_recorded_at=replaced.source_recorded_at,
        raw_text=raw_text,
        language=replaced.language,
        replaces_source_id=replaced.id,
        created_at=created_at,
    )

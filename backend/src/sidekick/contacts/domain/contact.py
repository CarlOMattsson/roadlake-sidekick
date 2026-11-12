"""Contact and ContactAlias domain entities, invariants, and aggregate rules."""

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from sidekick.contacts.domain.normalization import (
    PROFILE_FIELD_LIMITS,
    normalize_context_note,
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_profile_text,
)
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import UNSET, UnsetType


@dataclass(frozen=True, slots=True)
class ContactAlias:
    id: UUID
    value: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Contact:
    id: UUID
    owner_id: UUID
    display_name: str
    display_name_key: str
    context_note: str | None
    email: str | None
    email_key: str | None
    phone: str | None
    phone_key: str | None
    aliases: list[ContactAlias]
    archived: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int = 1
    relationship: str | None = None
    organization: str | None = None
    role: str | None = None
    address: str | None = None

    def __post_init__(self) -> None:
        # Invariants validation
        if not self.display_name:
            raise ValidationError("display name is required")
        if self.context_note is not None and len(self.context_note) > 10000:
            raise ValidationError("context note is too long")
        if (self.email is None) != (self.email_key is None):
            raise ValidationError("email and email_key must be set or cleared together")
        if (self.phone is None) != (self.phone_key is None):
            raise ValidationError("phone and phone_key must be set or cleared together")
        for field, limit in PROFILE_FIELD_LIMITS.items():
            value = getattr(self, field)
            if value is not None and len(value) > limit:
                raise ValidationError(f"{field} must be at most {limit} characters long")
        if self.version < 1:
            raise ValidationError("version must be greater than or equal to 1")
        if self.archived != (self.archived_at is not None):
            raise ValidationError("archived and archived_at must agree")

    def update(
        self,
        *,
        now: datetime,
        display_name: str | UnsetType = UNSET,
        context_note: str | None | UnsetType = UNSET,
        email: str | None | UnsetType = UNSET,
        phone: str | None | UnsetType = UNSET,
        relationship: str | None | UnsetType = UNSET,
        organization: str | None | UnsetType = UNSET,
        role: str | None | UnsetType = UNSET,
        address: str | None | UnsetType = UNSET,
    ) -> "Contact":
        """Update allowed contact fields and advance aggregate version."""
        if self.archived:
            raise ValidationError("archived contact cannot be updated")

        changes = {}
        if display_name is not UNSET:
            disp_val, key_val = normalize_name(display_name)
            changes["display_name"] = disp_val
            changes["display_name_key"] = key_val

        if context_note is not UNSET:
            changes["context_note"] = normalize_context_note(context_note)

        if email is not UNSET:
            disp_email, key_email = normalize_email(email)
            changes["email"] = disp_email
            changes["email_key"] = key_email

        if phone is not UNSET:
            disp_phone, key_phone = normalize_phone(phone)
            changes["phone"] = disp_phone
            changes["phone_key"] = key_phone

        for field, value in (
            ("relationship", relationship),
            ("organization", organization),
            ("role", role),
            ("address", address),
        ):
            if value is not UNSET:
                changes[field] = normalize_profile_text(value, field)

        if not changes:
            raise ValidationError("at least one contact change is required")

        return replace(
            self,
            **changes,
            updated_at=now,
            version=self.version + 1,
        )

    def archive(self, *, now: datetime) -> "Contact":
        """Reversibly archive this Contact."""
        if self.archived:
            # Replay idempotent behavior: return self unchanged or updated
            return self
        return replace(
            self,
            archived=True,
            archived_at=now,
            updated_at=now,
            version=self.version + 1,
        )

    def restore(self, *, now: datetime) -> "Contact":
        """Restore this Contact from archived state."""
        if not self.archived:
            # Replay idempotent behavior
            return self
        return replace(
            self,
            archived=False,
            archived_at=None,
            updated_at=now,
            version=self.version + 1,
        )

    def add_alias(self, *, now: datetime, value: str, alias_id: UUID) -> "Contact":
        """Add a normalized alias to this Contact."""
        if self.archived:
            raise ValidationError("archived contact cannot receive aliases")
        norm_val, norm_key = normalize_name(value)
        if any(normalize_name(a.value)[1] == norm_key for a in self.aliases):
            raise ValidationError("alias already exists on this contact")
        if len(self.aliases) >= 20:
            raise ValidationError("maximum of 20 aliases is allowed")

        new_alias = ContactAlias(id=alias_id, value=norm_val, created_at=now)
        new_aliases = [*self.aliases, new_alias]
        return replace(self, aliases=new_aliases, updated_at=now, version=self.version + 1)

    def remove_alias(self, *, now: datetime, alias_id: UUID) -> "Contact":
        """Remove an alias from this Contact by ID."""
        if self.archived:
            raise ValidationError("archived contact cannot have aliases removed")
        new_aliases = [a for a in self.aliases if a.id != alias_id]
        if len(new_aliases) == len(self.aliases):
            return self
        return replace(self, aliases=new_aliases, updated_at=now, version=self.version + 1)

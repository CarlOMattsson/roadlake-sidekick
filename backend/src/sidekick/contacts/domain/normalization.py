"""Pure domain value normalization and validation rules for Contacts."""

import unicodedata

from sidekick.shared.errors import ValidationError


def normalize_name(name: str | None) -> tuple[str, str]:
    """Normalize a display name and return (display_value, normalized_key)."""
    if not name:
        raise ValidationError("display name is required")

    # Unicode NFKC normalization
    s = unicodedata.normalize("NFKC", name)

    # Reject Unicode control/format characters
    for char in s:
        cat = unicodedata.category(char)
        if cat in {"Cc", "Cf"}:
            raise ValidationError("unicode control or format characters are not allowed")

    # Trim and collapse internal whitespace
    collapsed = " ".join(s.split())
    if not collapsed or len(collapsed) > 200:
        raise ValidationError("display name must be 1-200 characters long")

    return collapsed, collapsed.casefold()


def normalize_email(email: str | None) -> tuple[str | None, str | None]:
    """Normalize an email and return (display_value, email_key)."""
    if email is None:
        return None, None

    s = email.strip()
    if not s:
        return None, None

    if len(s) > 320:
        raise ValidationError("email is too long")

    # Reject whitespace and Unicode control/format characters
    if any(char.isspace() for char in s):
        raise ValidationError("email cannot contain whitespace")
    for char in s:
        cat = unicodedata.category(char)
        if cat in {"Cc", "Cf"}:
            raise ValidationError("email cannot contain control characters")

    # Require exactly one '@' with nonempty parts
    parts = s.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValidationError(
            "email must contain exactly one '@' with nonempty local and domain parts"
        )

    return s, s.casefold()


def normalize_phone(phone: str | None) -> tuple[str | None, str | None]:
    """Normalize a phone number and return (display_value, phone_key)."""
    if phone is None:
        return None, None

    s = phone.strip()
    if not s:
        return None, None

    if len(s) > 64:
        raise ValidationError("phone number is too long")

    # Allow only ASCII digits, spaces, +, -, (, ), .
    allowed = set("0123456789 +-().")
    if not all(char in allowed for char in s):
        raise ValidationError("phone number contains invalid characters")

    # Require at most one '+' placed as the first non-space character
    plus_count = s.count("+")
    if plus_count > 1:
        raise ValidationError("phone number cannot contain more than one '+'")
    if plus_count == 1:
        if not s.startswith("+"):
            raise ValidationError("'+' must be the first character in the phone number")
        if len(s) > 1 and s[1].isspace():
            raise ValidationError("space cannot follow '+'")

    # Require at least one digit
    digits = "".join(char for char in s if char.isdigit())
    if not digits:
        raise ValidationError("phone number must contain at least one digit")

    # Exact-match key keeps that optional leading '+' plus ASCII digits
    key = "+" + digits if s.startswith("+") else digits
    return s, key


def normalize_context_note(note: str | None) -> str | None:
    """Normalize context note: preserve ordinary Unicode/newlines, reject NUL, enforce length."""
    if note is None:
        return None

    if "\u0000" in note:
        raise ValidationError("NUL character is not allowed in context note")

    if len(note) > 10000:
        raise ValidationError("context note is too long")

    return note


PROFILE_FIELD_LIMITS: dict[str, int] = {
    "relationship": 80,
    "organization": 200,
    "role": 120,
    "address": 500,
}


def normalize_profile_text(value: str | None, field: str) -> str | None:
    """Normalize a short free-text Contact profile field (relationship, organization, role,
    address): trimmed, blank clears to None, control and format characters rejected."""
    if value is None:
        return None
    limit = PROFILE_FIELD_LIMITS[field]
    s = unicodedata.normalize("NFKC", value)
    for char in s:
        if char in "\n\r\t":
            continue
        if unicodedata.category(char) in {"Cc", "Cf"}:
            raise ValidationError(f"{field} cannot contain control characters")
    s = s.strip()
    if not s:
        return None
    if len(s) > limit:
        raise ValidationError(f"{field} must be at most {limit} characters long")
    return s

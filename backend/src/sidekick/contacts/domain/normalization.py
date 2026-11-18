"""Pure domain value normalization and validation rules for Contacts."""

import re
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


# A Slack member ID: `U` (or `W` on Enterprise Grid) followed by upper-case letters and digits.
_SLACK_MEMBER_ID = re.compile(r"[UW][A-Z0-9]{2,19}")
# One or more DNS labels in front of `slack.com`: a workspace (`acme.slack.com`) or an Enterprise
# Grid organisation (`acme.enterprise.slack.com`). Bare `slack.com` and look-alike hosts such as
# `slack.com.example.org` or `notslack.com` do not match.
_SLACK_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+slack\.com")
SLACK_PROFILE_LIMIT = 160
# The longest pasted link accepted: room for a query string or tracking parameters that are dropped.
SLACK_PROFILE_INPUT_LIMIT = 300


def normalize_slack_profile(value: str | None) -> str | None:
    """Normalize a Slack profile link to `https://<workspace>.slack.com/team/<member id>`.

    The owner copies it from a Slack profile (the profile's menu, "Copy link to profile"). Only the
    two validated parts are kept and the link is built from them, so no other host, scheme, port,
    credentials, path or query can be stored: the link opens one member's profile in a Slack
    workspace and nothing else. The scheme may be left out; `http` and every other scheme are
    refused. A blank value clears the field.
    """
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    if len(s) > SLACK_PROFILE_INPUT_LIMIT:
        raise ValidationError("slack profile link is too long")
    if not s.isascii() or any(unicodedata.category(char) in {"Cc", "Cf", "Zs"} for char in s):
        raise ValidationError("slack profile link contains invalid characters")

    if "://" in s:
        scheme, _, rest = s.partition("://")
        if scheme.lower() != "https":
            raise ValidationError("slack profile link must use https")
    else:
        rest = s
    # A fragment or query (such as a tracking parameter) carries nothing that is kept.
    rest = rest.split("#", 1)[0].split("?", 1)[0]
    host, slash, path = rest.partition("/")
    host = host.lower()
    if not _SLACK_HOST.fullmatch(host):
        raise ValidationError("slack profile link must be on a slack.com workspace")
    segments = path.rstrip("/").split("/") if slash else []
    if len(segments) != 2 or segments[0] != "team" or not _SLACK_MEMBER_ID.fullmatch(segments[1]):
        raise ValidationError(
            "slack profile link must look like https://<workspace>.slack.com/team/<member id>"
        )
    return f"https://{host}/team/{segments[1]}"


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

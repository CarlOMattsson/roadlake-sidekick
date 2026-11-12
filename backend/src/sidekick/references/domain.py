"""External reference rules independent of transports, providers and persistence.

A reference is a pointer to an object in another service. Sidekick keeps identity, a
possibly stale title and an https link; it never stores content, participants or tokens.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from sidekick.shared.errors import ValidationError

KINDS: Final = ("mail", "calendar_event", "document")
SOURCES: Final = ("claude_connector", "manual")
OTHER_PROVIDER: Final = "other"
MAX_REFERENCES_PER_TASK: Final = 50

# The provider list is closed and extended in code, never by configuration.
PROVIDER_KINDS: Final[dict[str, frozenset[str]]] = {
    "google_gmail": frozenset({"mail"}),
    "google_calendar": frozenset({"calendar_event"}),
    "google_drive": frozenset({"document"}),
    OTHER_PROVIDER: frozenset(KINDS),
}
PROVIDER_HOSTS: Final[dict[str, frozenset[str]]] = {
    "google_gmail": frozenset({"mail.google.com"}),
    "google_calendar": frozenset({"calendar.google.com"}),
    "google_drive": frozenset({"docs.google.com", "drive.google.com"}),
}
# Best-effort guard against links that carry a credential. Not a complete defence.
# Query and fragment parameter names are matched case-insensitively: exact names, then prefixes
# and suffixes. Common Google parameters such as authuser, resourcekey and usp stay allowed.
_CREDENTIAL_PARAMETER_NAMES: Final = frozenset(
    {
        "token",
        "access_token",
        "id_token",
        "refresh_token",
        "api_key",
        "apikey",
        "key",
        "secret",
        "client_secret",
        "password",
        "passwd",
        "pwd",
        "auth",
        "authorization",
        "credential",
        "credentials",
        "session",
        "sessionid",
        "sid",
        "jwt",
        "code",
        "sig",
        "signature",
    }
)
_CREDENTIAL_PARAMETER_PREFIXES: Final = ("x-goog-", "x-amz-")
_CREDENTIAL_PARAMETER_SUFFIXES: Final = ("_token", "_secret", "_key", "_password", "_signature")


def _is_credential_parameter(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in _CREDENTIAL_PARAMETER_NAMES
        or lowered.startswith(_CREDENTIAL_PARAMETER_PREFIXES)
        or lowered.endswith(_CREDENTIAL_PARAMETER_SUFFIXES)
    )


def _clean(value: str, maximum: int, *, field: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValidationError(f"invalid external reference {field}")
    return cleaned


def validate_reference_url(provider: str, value: str) -> str:
    """Accept only an https link that fits the provider; return it with scheme and host lowercased.

    The returned link always matches the database CHECK ``^https://``.
    """

    if provider not in PROVIDER_KINDS:
        raise ValidationError("invalid external reference provider")
    url = value.strip()
    if not url or len(url) > 2000 or any(ord(c) <= 32 or ord(c) == 127 or c == "\\" for c in url):
        raise ValidationError("invalid external reference link")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValidationError("invalid external reference link") from error
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise ValidationError("invalid external reference link")
    allowed_hosts = PROVIDER_HOSTS.get(provider)
    if allowed_hosts is not None and host.lower() not in allowed_hosts:
        raise ValidationError("external reference link does not match its provider")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if "=" in parsed.fragment:
        pairs += parse_qsl(parsed.fragment, keep_blank_values=True)
    for name, _ in pairs:
        if _is_credential_parameter(name):
            raise ValidationError("external reference link must not carry credentials")
    return urlunsplit(parsed._replace(scheme="https", netloc=parsed.netloc.lower()))


@dataclass(frozen=True, slots=True)
class ExternalReferenceDetails:
    """Validated identity and snapshot of one external object."""

    kind: str
    provider: str
    account_ref: str
    external_id: str
    title: str
    instance_ref: str | None = None
    url: str | None = None
    occurs_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValidationError("invalid external reference kind")
        if self.provider not in PROVIDER_KINDS:
            raise ValidationError("invalid external reference provider")
        if self.kind not in PROVIDER_KINDS[self.provider]:
            raise ValidationError("external reference kind does not match its provider")
        object.__setattr__(
            self, "account_ref", _clean(self.account_ref, 200, field="account").lower()
        )
        object.__setattr__(self, "external_id", _clean(self.external_id, 500, field="identity"))
        object.__setattr__(self, "title", _clean(self.title, 300, field="title"))
        if self.instance_ref is not None:
            object.__setattr__(
                self, "instance_ref", _clean(self.instance_ref, 500, field="instance")
            )
        if self.url is not None:
            object.__setattr__(self, "url", validate_reference_url(self.provider, self.url))
        if self.occurs_at is not None and self.occurs_at.tzinfo is None:
            raise ValidationError("external reference time requires a timezone")

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        """The provider-side identity inside one owner: the same object, whoever links it."""

        return (
            self.kind,
            self.provider,
            self.account_ref,
            self.external_id,
            self.instance_ref or "",
        )

    def identity_fingerprint(self) -> str:
        """Opaque digest of the identity, safe for locks and idempotency payloads."""

        return hashlib.sha256("\x1f".join(self.identity).encode()).hexdigest()

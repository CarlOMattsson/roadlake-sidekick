"""GitHub OAuth sign-in for the public MCP server (`mcp_auth_mode=github_oauth`)."""

from pathlib import Path
from typing import Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from sidekick.shared.auth.service import MCP_SCOPES
from sidekick.shared.config.mcp import McpServerSettings
from sidekick.shared.config.validation import is_unusable_secret, secret_is_blank

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# The one callback Anthropic documents for every hosted Claude client (web, Desktop, mobile).
DEFAULT_MCP_OAUTH_REDIRECT_URIS = "https://claude.ai/api/mcp/auth_callback"


def validate_mcp_public_base_url(value: str) -> str:
    """Accept only a bare public origin: HTTPS, or plain HTTP towards loopback for local proof.

    The message never repeats the value, so a mistyped URL cannot put a credential-bearing
    string into a startup error.
    """

    parsed = urlsplit(value.strip())
    host = parsed.hostname
    if host is None:
        raise ValueError("SIDEKICK_MCP_PUBLIC_BASE_URL must be an absolute URL with a host")
    if "*" in host:
        raise ValueError("SIDEKICK_MCP_PUBLIC_BASE_URL must name one concrete host")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and host in _LOOPBACK_HOSTS):
        raise ValueError("SIDEKICK_MCP_PUBLIC_BASE_URL must use HTTPS (HTTP only for loopback)")
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "SIDEKICK_MCP_PUBLIC_BASE_URL must be a bare origin without credentials, path, "
            "query, or fragment"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_mcp_oauth_identities(value: str) -> dict[str, UUID]:
    """Parse `github:<numeric id>=<user uuid>,...` into an upstream-identity -> user map.

    The numeric GitHub id is the identity, never the login, which a person can rename and
    another person can later claim. Errors name the entry's position, never its content.
    """

    identities: dict[str, UUID] = {}
    entries = [entry.strip() for entry in value.split(",") if entry.strip()]
    for position, entry in enumerate(entries, start=1):
        upstream, separator, user = entry.partition("=")
        provider, colon, number = upstream.strip().partition(":")
        if (
            not separator
            or not colon
            or provider != "github"
            or not number.isascii()
            or not number.isdecimal()
            or not 0 < int(number) < 2**63
        ):
            raise ValueError(
                f"SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES entry {position} must look like "
                "github:<numeric id>=<user uuid>"
            )
        try:
            user_id = UUID(user.strip())
        except ValueError:
            raise ValueError(
                f"SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES entry {position} has an invalid user uuid"
            ) from None
        key = f"github:{int(number)}"
        if key in identities:
            raise ValueError(
                f"SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES entry {position} repeats an identity"
            )
        identities[key] = user_id
    return identities


def parse_mcp_oauth_scopes(value: str) -> frozenset[str]:
    """Parse the OAuth scope policy and refuse anything above the MCP scope ceiling.

    A name outside the ceiling is refused, so a typo or an `admin` never passes unnoticed.
    """

    requested = frozenset(scope.strip() for scope in value.split(",") if scope.strip())
    if not requested <= frozenset(MCP_SCOPES):
        raise ValueError("SIDEKICK_MCP_OAUTH_SCOPES names a scope outside the public MCP scopes")
    return requested


def parse_mcp_oauth_redirect_uris(value: str) -> tuple[str, ...]:
    uris = tuple(uri.strip() for uri in value.split(",") if uri.strip())
    for uri in uris:
        # A wildcard may stand for a loopback port or a path, never for a host: `https://*` or
        # `https://*.example` would accept a callback on a domain the operator never named.
        parsed = urlsplit(uri)
        if uri.strip() == "*" or "*" in (parsed.hostname or ""):
            raise ValueError(
                "SIDEKICK_MCP_OAUTH_ALLOWED_REDIRECT_URIS entries must name one concrete host"
            )
        parsed = urlsplit(uri.replace("*", "x"))
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS
        ):
            raise ValueError(
                "SIDEKICK_MCP_OAUTH_ALLOWED_REDIRECT_URIS entries must be HTTPS "
                "(HTTP only for loopback)"
            )
    return uris


class OAuthSettings(McpServerSettings):
    mcp_oauth_github_client_id: str = Field(
        default="", description="Client id of the GitHub OAuth app; required for github_oauth."
    )
    mcp_oauth_github_client_secret: SecretStr | None = Field(
        default=None,
        description="Client secret of the GitHub OAuth app; required for github_oauth.",
    )
    mcp_oauth_signing_key: SecretStr | None = Field(
        default=None,
        description="Key (32+ characters) that signs OAuth state; required for github_oauth.",
    )
    mcp_oauth_storage_dir: Path | None = Field(
        default=None,
        description="Absolute directory for persisted OAuth state; required for github_oauth.",
    )
    mcp_oauth_allowed_identities: str = Field(
        default="",
        description="Comma-separated `github:<numeric id>=<user uuid>`; anyone else is refused.",
    )
    mcp_oauth_scopes: str = Field(
        default="",
        description="Comma-separated Sidekick scopes an OAuth session holds (MCP scopes only).",
    )
    mcp_oauth_allowed_redirect_uris: str = Field(
        default=DEFAULT_MCP_OAUTH_REDIRECT_URIS,
        description="Comma-separated OAuth callback URIs accepted (HTTPS, or loopback HTTP).",
    )
    mcp_oauth_enable_cimd: bool = Field(
        default=False,
        description="Accepts Client ID Metadata Documents, which make the server fetch a URL.",
    )
    mcp_oauth_upstream_cache_seconds: int = Field(
        default=300,
        ge=0,
        le=3600,
        description="Seconds a successful GitHub token check is reused (0 = check every request).",
    )
    mcp_oauth_session_days: int = Field(
        default=30,
        ge=1,
        le=90,
        description="Days a newly issued OAuth session lasts before the client must sign in again.",
    )

    @model_validator(mode="after")
    def validate_mcp_oauth(self) -> Self:
        """Fail closed: a public OAuth surface starts only with a complete, valid policy."""

        if self.mcp_auth_mode != "github_oauth":
            return self
        if not self.mcp_public_base_url.strip():
            raise ValueError("SIDEKICK_MCP_PUBLIC_BASE_URL is required for github_oauth")
        self.mcp_public_base_url = validate_mcp_public_base_url(self.mcp_public_base_url)
        if not self.mcp_oauth_github_client_id.strip():
            raise ValueError("SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_ID is required for github_oauth")
        if secret_is_blank(self.mcp_oauth_github_client_secret):
            raise ValueError("SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_SECRET is required for github_oauth")
        key = self.mcp_oauth_signing_key
        if key is None or len(key.get_secret_value().strip()) < 32:
            raise ValueError("SIDEKICK_MCP_OAUTH_SIGNING_KEY is required (at least 32 characters)")
        if is_unusable_secret(key.get_secret_value()):
            raise ValueError("SIDEKICK_MCP_OAUTH_SIGNING_KEY must be configured, not a placeholder")
        if self.mcp_oauth_storage_dir is None or not self.mcp_oauth_storage_dir.is_absolute():
            raise ValueError("SIDEKICK_MCP_OAUTH_STORAGE_DIR must be an absolute path")
        if not parse_mcp_oauth_identities(self.mcp_oauth_allowed_identities):
            raise ValueError(
                "SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES must name at least one identity"
            )
        if not parse_mcp_oauth_scopes(self.mcp_oauth_scopes):
            raise ValueError("SIDEKICK_MCP_OAUTH_SCOPES must name at least one scope")
        if not parse_mcp_oauth_redirect_uris(self.mcp_oauth_allowed_redirect_uris):
            raise ValueError("SIDEKICK_MCP_OAUTH_ALLOWED_REDIRECT_URIS must name at least one URI")
        return self

    @property
    def mcp_oauth_identities(self) -> dict[str, UUID]:
        return parse_mcp_oauth_identities(self.mcp_oauth_allowed_identities)

    @property
    def mcp_oauth_scope_set(self) -> frozenset[str]:
        return parse_mcp_oauth_scopes(self.mcp_oauth_scopes)

    @property
    def mcp_oauth_redirect_uris(self) -> tuple[str, ...]:
        return parse_mcp_oauth_redirect_uris(self.mcp_oauth_allowed_redirect_uris)

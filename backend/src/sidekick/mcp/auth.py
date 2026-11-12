"""FastMCP bearer verification mapped to Sidekick User."""

import logging
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

import anyio.to_thread
import httpx2
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.providers.github import GitHubTokenVerifier
from fastmcp.server.dependencies import get_access_token

from sidekick.mcp.correlation import UNKNOWN_CORRELATION, request_correlation_id
from sidekick.shared.auth import MCP_SCOPES, AuthService
from sidekick.shared.auth.verification_signal import mark_verified
from sidekick.shared.errors import AuthenticationRequiredError
from sidekick.shared.observability import (
    TelemetryPort,
    safe_log_fields,
    silence_http_client_loggers,
)
from sidekick.shared.types import Actor

LOGGER = logging.getLogger("sidekick.mcp.auth")

OAUTH_CLIENT_ID = "sidekick-github-oauth"
SESSION_PLACEHOLDER = "sidekick-oauth-session"
# A successful GitHub answer is reused for `SIDEKICK_MCP_OAUTH_UPSTREAM_CACHE_SECONDS` (default
# five minutes, 0 turns the cache off). Only the upstream *token check* is cached; the
# active-user check runs on every request, so disabling a user takes effect at once. The
# allowlist itself is read from configuration at startup, so removing an identity needs a
# restart. A revoked GitHub grant lingers at most the configured time; a restart clears it.


class PersonalTokenVerifier(TokenVerifier):
    def __init__(self, auth: AuthService) -> None:
        super().__init__(required_scopes=[])
        self._auth = auth

    @property
    def scopes_supported(self) -> list[str]:
        return list(MCP_SCOPES)

    async def verify_token(self, token: str) -> AccessToken | None:
        # Synchronous database work: off the event loop so other requests keep moving.
        actor = await anyio.to_thread.run_sync(self._auth.verify_personal_token, token)
        if actor is None:
            return None
        return AccessToken(
            token=token,
            client_id="sidekick-personal-token",
            scopes=sorted(actor.scopes),
            subject=str(actor.user_id),
            claims={"user_id": str(actor.user_id)},
        )


class ActiveUserLookup(Protocol):
    """The one question the OAuth verifier asks Sidekick about a mapped user."""

    def is_user_active(self, user_id: UUID) -> bool: ...


class GitHubIdentityVerifier(GitHubTokenVerifier):
    """Map a valid GitHub token to a Sidekick user, or refuse it.

    FastMCP's `GitHubTokenVerifier` proves that the upstream token is live and says which
    GitHub account owns it. Sidekick then decides, by numeric GitHub id only, whether that
    account is one of the people it serves, and what it may do. The result is an ordinary
    `AccessToken` whose `subject` is the Sidekick user id, so `current_actor()` and every
    scope check downstream are exactly what a personal token already uses.

    Scopes are server policy, never the upstream grant and never the client's request, and
    are clipped to the public MCP scope ceiling here as well as in configuration.
    """

    def __init__(
        self,
        *,
        users: ActiveUserLookup,
        identities: Mapping[str, UUID],
        scopes: frozenset[str],
        telemetry: TelemetryPort,
        upstream_cache_seconds: int,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        silence_http_client_loggers()
        # No upstream scope requirement: the OAuth app asks GitHub for no scopes at all.
        super().__init__(
            required_scopes=None,
            cache_ttl_seconds=upstream_cache_seconds,
            http_client=http_client,
        )
        self._users = users
        self._identities = dict(identities)
        self._scopes = frozenset(scopes) & frozenset(MCP_SCOPES)
        self._telemetry = telemetry

    @property
    def scopes_supported(self) -> list[str]:
        return [scope for scope in MCP_SCOPES if scope in self._scopes]

    async def aclose(self) -> None:
        """Close the pooled GitHub client this verifier owns."""

        if self._http_client is not None:
            await self._http_client.aclose()

    async def verify_token(self, token: str) -> AccessToken | None:
        upstream = await super().verify_token(token)
        if upstream is None:
            return self._refuse("upstream_invalid")
        claims = upstream.claims or {}
        subject = claims.get("sub")
        user_id = self._identities.get(f"github:{subject}") if isinstance(subject, str) else None
        if user_id is None:
            return self._refuse("identity_not_allowlisted")
        if not await anyio.to_thread.run_sync(self._users.is_user_active, user_id):
            return self._refuse("user_inactive")
        scopes = self.scopes_supported
        if not scopes:
            return self._refuse("no_scopes_permitted")
        mark_verified()
        self._record("accepted", None)
        # A fresh token object: nothing from the GitHub profile (login, name, e-mail, avatar)
        # is carried forward into the request context.
        return AccessToken(
            # Never the upstream credential: nothing downstream needs it.
            token=SESSION_PLACEHOLDER,
            client_id=OAUTH_CLIENT_ID,
            scopes=scopes,
            subject=str(user_id),
            claims={"user_id": str(user_id)},
        )

    def _refuse(self, reason: str) -> None:
        """Record a closed-vocabulary reason and answer `None`, which FastMCP turns into 401."""

        self._record("denied", reason)
        return None

    def _record(self, outcome: str, reason: str | None) -> None:
        attributes = {"mcp.auth.mode": "github_oauth", "mcp.auth.outcome": outcome}
        fields: dict[str, object] = {
            "correlation_id": request_correlation_id() or UNKNOWN_CORRELATION,
            "mcp_auth_mode": "github_oauth",
            "mcp_auth_outcome": outcome,
        }
        if reason is not None:
            attributes["mcp.auth.reason"] = reason
            fields["mcp_auth_reason"] = reason
        self._telemetry.count("sidekick.mcp.auth", attributes)
        LOGGER.info(
            "mcp_auth_decision" if outcome == "accepted" else "mcp_auth_refused",
            extra=safe_log_fields(fields),
        )


def current_actor() -> Actor:
    access_token = get_access_token()
    if access_token is None or access_token.subject is None:
        raise AuthenticationRequiredError("MCP authentication required")
    return Actor(UUID(access_token.subject), frozenset(access_token.scopes))

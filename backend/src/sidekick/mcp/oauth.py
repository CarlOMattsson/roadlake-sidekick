"""Public MCP sign-in through FastMCP's OAuth proxy in front of GitHub.

Sidekick writes no authorization server. FastMCP's `OAuthProxy` answers Dynamic Client
Registration, enforces PKCE and the audience, runs the consent step, issues its own signed
tokens and keeps the upstream grant encrypted at rest. This module only configures it for one
deployment, plugs Sidekick's identity mapping in as the token verifier, and states where the
well-known documents live when the MCP application is mounted under a path prefix.

Pinned to the behaviour of fastmcp 4.1.6 (`backend/uv.lock`). The two overrides below touch
members the library documents as extension points or that its HTTP layer calls directly; the
transport tests assert the public result (resource, issuer, challenge) so an upgrade that moves
them fails loudly. `build_client_storage` also refuses to start when the file store's private
hook and root attribute that the owner-only subclass depends on are no longer as reviewed.
"""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, override

import httpx2
from cryptography.fernet import Fernet
from fastmcp.server.auth.auth import AuthProvider
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from pydantic import AnyHttpUrl
from starlette.routing import Route

from sidekick.mcp import MCP_MOUNT_PATH
from sidekick.mcp.auth import GitHubIdentityVerifier
from sidekick.shared.config import Settings
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.observability.library_logs import withhold_record_content

if TYPE_CHECKING:
    from sidekick.mcp.auth import ActiveUserLookup

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105  # endpoint URL
SECONDS_PER_DAY = 24 * 60 * 60
ROOT_AUTHORIZATION_SERVER_METADATA = "/.well-known/oauth-authorization-server"

# Library loggers that can interpolate an authorization code, a transaction id, an upstream
# error body, a token or a traceback into a message, whether through `%s` arguments or an
# f-string. Every record they emit is replaced by a constant template, DEBUG is dropped, and no
# traceback survives, so none of those values can reach a log sink. The prefixes also cover any
# sub-module logger that already exists when the provider is built.
_LIBRARY_LOGGERS: tuple[str, ...] = (
    "fastmcp.server.auth",
    "fastmcp.server.auth.auth",
    "fastmcp.server.auth.cimd",
    "fastmcp.server.auth.handlers.authorize",
    "fastmcp.server.auth.jwt_issuer",
    "fastmcp.server.auth.middleware",
    "fastmcp.server.auth.oauth_proxy.consent",
    "fastmcp.server.auth.oauth_proxy.proxy",
    "fastmcp.server.auth.providers.github",
    "fastmcp.server.auth.ssrf",
    "mcp.server.auth",
    "mcp.server.auth.handlers.authorize",
    "mcp.server.auth.handlers.register",
    "mcp.server.auth.handlers.token",
    "mcp.server.auth.middleware.bearer_auth",
)
_LIBRARY_LOGGER_PREFIXES = ("fastmcp.server.auth.", "mcp.server.auth.")


def _redact_library_logs() -> None:
    names = set(_LIBRARY_LOGGERS)
    names.update(
        name
        for name in list(logging.root.manager.loggerDict)
        if name.startswith(_LIBRARY_LOGGER_PREFIXES)
    )
    withhold_record_content(names, label="oauth library")


class _PrivateFileTreeStore(FileTreeStore):
    """`FileTreeStore` whose collection directories are created owner-only (0700)."""

    @override
    async def _setup_collection(self, *, collection: str) -> None:
        await super()._setup_collection(collection=collection)
        _tighten(Path(str(self._data_directory)))


def _require_file_tree_hooks() -> None:
    """Refuse to start unless `FileTreeStore` still has the members `_PrivateFileTreeStore` uses.

    `_setup_collection(self, *, collection)` creates each collection directory and
    `_data_directory` is the store root. If either changed, the override would no longer run or
    would tighten the wrong tree, and new directories would keep the process umask.
    """

    hook = getattr(FileTreeStore, "_setup_collection", None)
    reviewed = (
        inspect.iscoroutinefunction(hook)
        and tuple(inspect.signature(hook).parameters) == ("self", "collection")
        and inspect.signature(hook).parameters["collection"].kind is inspect.Parameter.KEYWORD_ONLY
        and "_data_directory" in getattr(FileTreeStore, "__annotations__", {})
    )
    if not reviewed:
        raise RuntimeError("the OAuth file store changed; owner-only storage cannot be guaranteed")


def _tighten(root: Path) -> None:
    """Owner-only mode for the storage root and every directory below it."""

    os.chmod(root, 0o700)
    for entry in root.rglob("*"):
        if entry.is_dir() and not entry.is_symlink():
            os.chmod(entry, 0o700)


def build_client_storage(directory: Path, signing_key: bytes) -> AsyncKeyValue:
    """Encrypted file storage for client registrations, grants and tokens.

    Built from the library's own store and Fernet wrapper, with the key derived from the
    configured signing key the same way FastMCP does when it builds its default store, but
    in a directory the operator chose instead of a per-user data directory. The directory is
    forced to 0700 even if it already existed with a looser mode, and startup is refused if it
    cannot be made owner-only.
    """

    _require_file_tree_hooks()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    _tighten(directory)
    if directory.stat().st_mode & 0o077:
        raise RuntimeError("SIDEKICK_MCP_OAUTH_STORAGE_DIR could not be made owner-only")
    encryption_key = derive_jwt_key(
        high_entropy_material=signing_key.decode(), salt="fastmcp-storage-encryption-key"
    )
    file_store = _PrivateFileTreeStore(
        data_directory=directory,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(directory),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(directory),
    )
    return FernetEncryptionWrapper(
        key_value=file_store,
        fernet=Fernet(key=encryption_key),
        raise_on_decryption_error=False,
    )


class SidekickGitHubOAuthProxy(OAuthProxy):
    """`OAuthProxy` for GitHub with Sidekick's resource URL and a scope-free upstream grant."""

    def __init__(
        self,
        *,
        settings: Settings,
        verifier: GitHubIdentityVerifier,
        client_storage: AsyncKeyValue,
        jwt_signing_key: bytes,
    ) -> None:
        if settings.mcp_oauth_github_client_secret is None:
            raise RuntimeError("github_oauth mode requires a GitHub client secret")
        public = settings.mcp_public_base_url
        # The one URL a client types, receives as `resource`, and is audience-bound to. It is
        # fixed here because the mounted application is addressed as `/mcp/` internally while
        # the published form has no trailing slash.
        self._published_resource = f"{public}{MCP_MOUNT_PATH}"
        self._sidekick_verifier = verifier
        session_seconds = settings.mcp_oauth_session_days * SECONDS_PER_DAY
        super().__init__(
            upstream_authorization_endpoint=GITHUB_AUTHORIZE_URL,
            upstream_token_endpoint=GITHUB_TOKEN_URL,
            upstream_client_id=settings.mcp_oauth_github_client_id,
            upstream_client_secret=settings.mcp_oauth_github_client_secret.get_secret_value(),
            token_verifier=verifier,
            # Operational routes and the issuer both sit under the mount prefix.
            base_url=f"{public}{MCP_MOUNT_PATH}",
            allowed_client_redirect_uris=list(settings.mcp_oauth_redirect_uris),
            valid_scopes=verifier.scopes_supported,
            # GitHub has no RFC 8707 support; the resource is still checked locally.
            forward_resource=False,
            # The OAuth app asks GitHub for no scopes: identity only.
            extra_authorize_params={"scope": ""},
            client_storage=client_storage,
            jwt_signing_key=jwt_signing_key,
            require_authorization_consent=True,
            enable_cimd=settings.mcp_oauth_enable_cimd,
            # Applies to sessions issued from now on (the library otherwise defaults to a year).
            # Tokens and refresh grants already issued carry their own expiry and are untouched.
            fallback_access_token_expiry_seconds=session_seconds,
            fallback_refresh_token_expiry_seconds=session_seconds,
        )

    async def aclose(self) -> None:
        """Release the pooled GitHub client at shutdown."""

        await self._sidekick_verifier.aclose()

    def _get_resource_url(self, path: str | None = None) -> AnyHttpUrl | None:
        return AnyHttpUrl(self._published_resource)

    def _prepare_scopes_for_token_exchange(self, scopes: list[str]) -> list[str]:
        # Sidekick scopes mean nothing to GitHub.
        return []


def build_github_oauth_provider(
    settings: Settings, users: ActiveUserLookup, telemetry: TelemetryPort
) -> AuthProvider:
    """Build the OAuth proxy for `mcp_auth_mode=github_oauth` from validated settings."""

    if settings.mcp_oauth_signing_key is None or settings.mcp_oauth_storage_dir is None:
        raise RuntimeError("github_oauth mode requires a signing key and a storage directory")
    _redact_library_logs()
    signing_key = derive_jwt_key(
        low_entropy_material=settings.mcp_oauth_signing_key.get_secret_value(),
        salt="sidekick-mcp-oauth-signing-key",
    )
    verifier = GitHubIdentityVerifier(
        users=users,
        identities=settings.mcp_oauth_identities,
        scopes=settings.mcp_oauth_scope_set,
        telemetry=telemetry,
        upstream_cache_seconds=settings.mcp_oauth_upstream_cache_seconds,
        http_client=_upstream_client(),
    )
    return SidekickGitHubOAuthProxy(
        settings=settings,
        verifier=verifier,
        client_storage=build_client_storage(settings.mcp_oauth_storage_dir, signing_key),
        jwt_signing_key=signing_key,
    )


def _upstream_client() -> httpx2.AsyncClient:
    """One pooled client for the GitHub identity check, bounded and never following redirects."""

    return httpx2.AsyncClient(timeout=10.0, follow_redirects=False)


def root_well_known_routes(provider: AuthProvider) -> list[Route]:
    """Discovery documents that must answer at the host root.

    A client looks for them at the origin, not under the `/mcp` prefix the application is
    mounted on, so FastMCP requires them to be added to the parent application by hand.
    Besides the path-aware routes it produces, the unprefixed authorization-server document
    is served too: the older MCP revisions that Claude still speaks derive it from the host.
    """

    routes = provider.get_well_known_routes(mcp_path="/")
    root_alias: list[Route] = []
    if not any(route.path == ROOT_AUTHORIZATION_SERVER_METADATA for route in routes):
        for route in routes:
            if route.path.startswith(f"{ROOT_AUTHORIZATION_SERVER_METADATA}/"):
                root_alias.append(
                    Route(
                        ROOT_AUTHORIZATION_SERVER_METADATA,
                        endpoint=route.endpoint,
                        methods=route.methods,
                    )
                )
                break
    return [*routes, *root_alias]

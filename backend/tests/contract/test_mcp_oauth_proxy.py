"""Public MCP sign-in through FastMCP's OAuth proxy in front of GitHub.

None of this needs a database or the network. The application is built with a lazy engine that
is never used, the identity check talks to a mocked GitHub, and the authorization service is a
two-line fake. The checks are the ones that matter on a publicly tunnelled process: discovery
documents are exactly right, nothing but the MCP and sign-in paths answers, only an
allowlisted active person is let in, scopes never exceed the policy, and no credential or
identity reaches a log.
"""

import base64
import hashlib
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import fastmcp
import httpx
import httpx2
import pytest
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastmcp.server.auth.jwt_issuer import JWTIssuer
from fastmcp.server.auth.oauth_proxy.models import JTIMapping, UpstreamTokenSet

from sidekick.api.app import create_app
from sidekick.mcp import oauth as oauth_module
from sidekick.mcp.auth import GitHubIdentityVerifier, current_actor
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.config import Settings
from sidekick.shared.errors import PermissionDeniedError
from sidekick.shared.observability import NoopTelemetryAdapter
from sidekick.shared.types import Actor

PUBLIC = "https://box.tail1234.ts.net"
OWNER = UUID("018af000-0000-7000-8000-000000000001")
OWNER_GITHUB_ID = 4_242_424
STRANGER_GITHUB_ID = 9_999_999
CORRELATION_ID = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
LOGIN_SENTINEL = "octocat-login-sentinel"
EMAIL_SENTINEL = "octocat-sentinel@example.invalid"
UPSTREAM_TOKEN_OWNER = "gho_owner_token_sentinel"
UPSTREAM_TOKEN_STRANGER = "gho_stranger_token_sentinel"
CLIENT_SECRET = "github-client-secret-sentinel-0123456789"
SIGNING_KEY = "mcp-oauth-signing-key-sentinel-0123456789-abc"
POLICY = frozenset({"projects:read", "tasks:read", "tasks:write"})
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture(autouse=True)
def fast_key_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fastmcp.settings, "test_mode", True)


class FakeUsers:
    def __init__(self, active: set[UUID]) -> None:
        self.active = active

    def is_user_active(self, user_id: UUID) -> bool:
        return user_id in self.active


class SpyTelemetry(NoopTelemetryAdapter):
    def __init__(self) -> None:
        self.counts: list[tuple[str, dict[str, Any]]] = []

    def count(self, name: str, attributes: dict[str, Any]) -> None:
        self.counts.append((name, attributes))


def github_transport() -> httpx2.MockTransport:
    """GitHub's identity endpoints, answering by bearer token and nothing else."""

    profiles = {
        UPSTREAM_TOKEN_OWNER: OWNER_GITHUB_ID,
        UPSTREAM_TOKEN_STRANGER: STRANGER_GITHUB_ID,
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.host == "api.github.com"
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in profiles:
            return httpx2.Response(401, json={"message": "Bad credentials"})
        if request.url.path == "/user":
            return httpx2.Response(
                200,
                json={
                    "id": profiles[token],
                    "login": LOGIN_SENTINEL,
                    "name": "Octo Cat",
                    "email": EMAIL_SENTINEL,
                },
            )
        return httpx2.Response(200, json=[], headers={"x-oauth-scopes": ""})

    return httpx2.MockTransport(handler)


def github_token_endpoint() -> httpx2.MockTransport:
    """GitHub's code-for-token exchange: any code yields the owner's upstream token.

    Authlib (>= 1.9) builds its OAuth client on httpx2, so the mock transport must be httpx2's.
    """

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == "https://github.com/login/oauth/access_token"
        return httpx2.Response(
            200, json={"access_token": UPSTREAM_TOKEN_OWNER, "token_type": "bearer", "scope": ""}
        )

    return httpx2.MockTransport(handler)


def make_verifier(
    *,
    active: set[UUID] | None = None,
    scopes: frozenset[str] = POLICY,
    telemetry: SpyTelemetry | None = None,
) -> GitHubIdentityVerifier:
    return GitHubIdentityVerifier(
        users=FakeUsers({OWNER} if active is None else active),
        identities={f"github:{OWNER_GITHUB_ID}": OWNER},
        scopes=scopes,
        telemetry=telemetry or SpyTelemetry(),
        upstream_cache_seconds=300,
        http_client=httpx2.AsyncClient(transport=github_transport()),
    )


class LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def text(self) -> str:
        parts: list[str] = []
        for record in self.records:
            parts.append(record.getMessage())
            parts.append(json.dumps(record.__dict__, default=str))
        return "\n".join(parts)


@pytest.fixture
def logs() -> Iterator[LogCapture]:
    capture = LogCapture()
    logger = logging.getLogger("sidekick")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    yield capture
    logger.removeHandler(capture)


def assert_no_credential_or_identity(text: str) -> None:
    for forbidden in (
        UPSTREAM_TOKEN_OWNER,
        UPSTREAM_TOKEN_STRANGER,
        LOGIN_SENTINEL,
        EMAIL_SENTINEL,
        CLIENT_SECRET,
        SIGNING_KEY,
        str(OWNER_GITHUB_ID),
        str(STRANGER_GITHUB_ID),
        str(OWNER),
    ):
        assert forbidden not in text, forbidden


# --- identity mapping -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_allowlisted_active_identity_becomes_the_sidekick_user_with_policy_scopes() -> (
    None
):
    access = await make_verifier().verify_token(UPSTREAM_TOKEN_OWNER)
    assert access is not None
    assert access.subject == str(OWNER)
    assert access.scopes == [scope for scope in MCP_SCOPES if scope in POLICY]
    # Nothing from the GitHub profile is carried into the request context.
    assert access.claims == {"user_id": str(OWNER)}
    assert LOGIN_SENTINEL not in repr(access.claims)


@pytest.mark.asyncio
async def test_current_actor_is_unchanged_for_an_oauth_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = await make_verifier().verify_token(UPSTREAM_TOKEN_OWNER)
    assert access is not None
    monkeypatch.setattr("sidekick.mcp.auth.get_access_token", lambda: access)
    actor = current_actor()
    assert actor == Actor(OWNER, frozenset(POLICY))
    actor.require("tasks:write")
    with pytest.raises(PermissionDeniedError):
        actor.require("contacts:read")


@pytest.mark.asyncio
async def test_scopes_are_clipped_to_the_public_mcp_ceiling_even_if_policy_overreaches() -> None:
    verifier = make_verifier(
        scopes=frozenset({"tasks:read", "preferences:write", "preferences:read"})
    )
    access = await verifier.verify_token(UPSTREAM_TOKEN_OWNER)
    assert access is not None
    assert access.scopes == ["tasks:read"]
    assert set(access.scopes) <= set(MCP_SCOPES)


@pytest.mark.asyncio
async def test_a_policy_with_no_permitted_scope_refuses_everyone() -> None:
    verifier = make_verifier(scopes=frozenset({"preferences:write"}))
    assert await verifier.verify_token(UPSTREAM_TOKEN_OWNER) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "active", "reason"),
    [
        (UPSTREAM_TOKEN_STRANGER, {OWNER}, "identity_not_allowlisted"),
        ("gho_not_a_github_token", {OWNER}, "upstream_invalid"),
        (UPSTREAM_TOKEN_OWNER, set(), "user_inactive"),
    ],
)
async def test_everything_else_is_refused_with_a_closed_reason_and_no_leak(
    token: str, active: set[UUID], reason: str, logs: LogCapture
) -> None:
    telemetry = SpyTelemetry()
    verifier = make_verifier(active=active, telemetry=telemetry)
    assert await verifier.verify_token(token) is None
    assert telemetry.counts == [
        (
            "sidekick.mcp.auth",
            {
                "mcp.auth.mode": "github_oauth",
                "mcp.auth.outcome": "denied",
                "mcp.auth.reason": reason,
            },
        )
    ]
    refusals = [record for record in logs.records if record.getMessage() == "mcp_auth_refused"]
    assert len(refusals) == 1
    assert refusals[0].__dict__["mcp_auth_reason"] == reason
    assert refusals[0].__dict__["correlation_id"] == "unknown"
    assert_no_credential_or_identity(logs.text())


@pytest.mark.asyncio
async def test_an_accepted_session_is_logged_without_identity_or_token(logs: LogCapture) -> None:
    telemetry = SpyTelemetry()
    assert await make_verifier(telemetry=telemetry).verify_token(UPSTREAM_TOKEN_OWNER)
    assert telemetry.counts[0][1]["mcp.auth.outcome"] == "accepted"
    assert [record.getMessage() for record in logs.records] == ["mcp_auth_decision"]
    assert_no_credential_or_identity(logs.text())


# --- the mounted application ------------------------------------------------------------


def oauth_settings(storage: Path) -> Settings:
    return Settings(
        environment="test",
        cursor_signing_secret="session-secret-for-tests-only-123456",
        token_pepper="token-pepper-for-tests-only-12345678",
        mcp_auth_mode="github_oauth",
        mcp_public_base_url=PUBLIC,
        mcp_oauth_github_client_id="Ov23liClientId",
        mcp_oauth_github_client_secret=CLIENT_SECRET,
        mcp_oauth_signing_key=SIGNING_KEY,
        mcp_oauth_storage_dir=storage,
        mcp_oauth_allowed_identities=f"github:{OWNER_GITHUB_ID}={OWNER}",
        mcp_oauth_scopes=",".join(sorted(POLICY)),
    )


@asynccontextmanager
async def running_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    monkeypatch.setattr(
        oauth_module,
        "_upstream_client",
        lambda: httpx2.AsyncClient(transport=github_transport()),
    )
    app = create_app(oauth_settings(tmp_path / "oauth-state"))
    monkeypatch.setattr(
        app.state.container.auth, "is_user_active", lambda user_id: user_id == OWNER
    )
    provider = fastmcp_provider(app)
    monkeypatch.setattr(
        provider,
        "_create_upstream_oauth_client",
        lambda: AsyncOAuth2Client(
            client_id="Ov23liClientId",
            client_secret=CLIENT_SECRET,
            transport=github_token_endpoint(),
        ),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC) as client,
    ):
        yield app, client


@pytest.fixture
def oauth_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]]:
    """The running application as an async context manager, entered inside each test.

    Entering it inside the test keeps the application's lifespan in the task that uses it.
    """

    return running_app(tmp_path, monkeypatch)


@pytest.mark.asyncio
async def test_protected_resource_metadata_names_the_exact_resource_and_issuer(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (_app, client):
        response = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert response.status_code == 200
        document = response.json()
        assert document["resource"] == f"{PUBLIC}/mcp"
        assert document["authorization_servers"] == [f"{PUBLIC}/mcp"]
        assert set(document["scopes_supported"]) == POLICY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-authorization-server/mcp",
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration/mcp",
        "/.well-known/openid-configuration",
    ],
)
async def test_authorization_server_metadata_is_published_at_the_host_root(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]], path: str
) -> None:
    async with oauth_app as (_app, client):
        response = await client.get(path)
        assert response.status_code == 200
        document = response.json()
        assert document["issuer"] == f"{PUBLIC}/mcp"
        assert document["authorization_endpoint"] == f"{PUBLIC}/mcp/authorize"
        assert document["token_endpoint"] == f"{PUBLIC}/mcp/token"
        assert document["registration_endpoint"] == f"{PUBLIC}/mcp/register"
        assert document["code_challenge_methods_supported"] == ["S256"]
        assert set(document["scopes_supported"]) == POLICY
        assert response.headers["x-correlation-id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
async def test_an_unauthenticated_call_gets_a_challenge_pointing_at_the_resource_metadata(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]], path: str
) -> None:
    async with oauth_app as (_app, client):
        response = await client.post(
            path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        # The published slash-less URL is served directly, never redirected.
        assert response.status_code == 401
        assert (
            f'resource_metadata="{PUBLIC}/.well-known/oauth-protected-resource/mcp"'
            in response.headers["www-authenticate"]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/csrf",
        "/api/openapi.json",
        "/api/docs",
        "/health/live",
        "/health/ready",
        "/docs/oauth2-redirect",
        "/redoc",
        "/agent-mcp/",
        "/mcp/anything-else",
        "/mcp/.well-known/openid-configuration",
        "/mcp//authorize",
        "/mcp/authorize/",
        "/.well-known/oauth-protected-resource/../../api/openapi.json",
        "/.well-known/security.txt",
        "/index.html",
    ],
)
async def test_nothing_outside_the_mcp_and_sign_in_paths_answers(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
    path: str,
    logs: LogCapture,
) -> None:
    async with oauth_app as (_app, client):
        response = await client.get(path, headers={"X-Correlation-Id": CORRELATION_ID})
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json() == {
            "type": "urn:sidekick:error:not_found",
            "title": "Not found",
            "status": 404,
            "code": "not_found",
            "correlation_id": CORRELATION_ID,
        }
        assert response.headers["x-correlation-id"] == CORRELATION_ID
        denial = [
            record for record in logs.records if record.getMessage() == "public_surface_denied"
        ]
        assert denial
        for record in denial:
            # The refused path is never logged.
            assert path not in json.dumps(record.__dict__, default=str)


@pytest.mark.asyncio
async def test_a_websocket_upgrade_is_refused(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (app, _client):
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "websocket.connect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await app(
            {"type": "websocket", "path": "/api/v1/chat/ws", "headers": [], "query_string": b""},
            receive,
            send,
        )
        assert sent == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.asyncio
async def test_sign_in_routes_are_reachable_and_only_for_the_claude_callback(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (_app, client):
        bad = await client.post(
            "/mcp/register",
            json={
                "client_name": "attacker",
                "redirect_uris": ["https://attacker.example/cb"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert bad.status_code == 400
        good = await client.post(
            "/mcp/register",
            json={
                "client_name": "Claude",
                "redirect_uris": [CLAUDE_CALLBACK],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert good.status_code == 201
        # Authorize, token and consent exist (a 4xx from the proxy, not the allowlist's 404).
        for method, path in (
            ("GET", "/mcp/authorize"),
            ("POST", "/mcp/token"),
            ("GET", "/mcp/consent"),
        ):
            response = await client.request(method, path)
            assert response.status_code in {400, 401, 405, 422}, (
                method,
                path,
                response.status_code,
            )
            assert "urn:sidekick:error:not_found" not in response.text


@pytest.mark.asyncio
async def test_the_sign_in_flow_binds_the_resource_and_policy_and_asks_github_for_identity_only(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (_app, client):
        registered = await client.post(
            "/mcp/register",
            json={
                "client_name": "Claude",
                "redirect_uris": [CLAUDE_CALLBACK],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        client_id = registered.json()["client_id"]
        assert set(registered.json()["scope"].split()) == POLICY
        verifier = "v" * 50
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CLAUDE_CALLBACK,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "client-state",
            "resource": f"{PUBLIC}/mcp",
        }
        # A scope outside the server policy is refused before anything leaves the process.
        outside = await client.get("/mcp/authorize", params={**params, "scope": "chat:write"})
        assert "error=invalid_scope" in outside.headers["location"]
        # A resource other than this server's is never accepted.
        elsewhere = await client.get(
            "/mcp/authorize", params={**params, "resource": "https://evil.example/mcp"}
        )
        assert "error=" in elsewhere.headers["location"]
        assert elsewhere.headers["location"].startswith(CLAUDE_CALLBACK)

        started = await client.get("/mcp/authorize", params=params)
        consent_url = started.headers["location"]
        assert consent_url.startswith(f"{PUBLIC}/mcp/consent?txn_id=")
        page = await client.get(consent_url.removeprefix(PUBLIC))
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf is not None
        approved = await client.post(
            "/mcp/consent",
            data={
                "action": "approve",
                "txn_id": consent_url.rsplit("=", 1)[1],
                "csrf_token": csrf.group(1),
            },
        )
        upstream = urlsplit(approved.headers["location"])
        query = parse_qs(upstream.query, keep_blank_values=True)
        assert f"{upstream.scheme}://{upstream.netloc}{upstream.path}" == (
            "https://github.com/login/oauth/authorize"
        )
        assert query["client_id"] == ["Ov23liClientId"]
        assert query["redirect_uri"] == [f"{PUBLIC}/mcp/auth/callback"]
        assert query["code_challenge_method"] == ["S256"]
        # GitHub learns nothing but "who is this": no Sidekick scope, no resource.
        assert query["scope"] == [""]
        assert "resource" not in query
        assert CLIENT_SECRET not in approved.headers["location"]


async def mint_session(app: Any, upstream_token: str, lifetime: int = 3600) -> str:
    """A FastMCP-signed access token backed by stored upstream state, as the proxy issues it."""

    provider = app.state.container.settings and fastmcp_provider(app)
    jti = f"jti-{upstream_token}"
    upstream_id = f"upstream-{upstream_token}"
    now = time.time()
    await provider._upstream_token_store.put(  # pyright: ignore[reportPrivateUsage]
        key=upstream_id,
        value=UpstreamTokenSet(
            upstream_token_id=upstream_id,
            access_token=upstream_token,
            refresh_token=None,
            refresh_token_expires_at=None,
            expires_at=now + lifetime,
            token_type="Bearer",
            scope="",
            client_id="test-client",
            created_at=now,
        ),
        ttl=lifetime,
    )
    await provider._jti_mapping_store.put(  # pyright: ignore[reportPrivateUsage]
        key=jti,
        value=JTIMapping(jti=jti, upstream_token_id=upstream_id, created_at=now),
        ttl=lifetime,
    )
    return provider.jwt_issuer.issue_access_token(
        client_id="test-client", scopes=sorted(POLICY), jti=jti, expires_in=lifetime
    )


def fastmcp_provider(app: Any) -> Any:
    for route in app.router.routes:
        sub = getattr(route, "app", None)
        server = getattr(getattr(sub, "state", None), "fastmcp_server", None)
        if getattr(route, "path", None) == "/mcp" and server is not None:
            return server.auth
    raise AssertionError("public MCP application not mounted")


async def list_tools(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )


@pytest.mark.asyncio
async def test_an_allowlisted_session_reaches_the_tools_over_plain_json(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]], logs: LogCapture
) -> None:
    async with oauth_app as (app, client):
        token = await mint_session(app, UPSTREAM_TOKEN_OWNER)
        response = await list_tools(client, token)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert len(response.json()["result"]["tools"]) > 0
        assert_no_credential_or_identity(logs.text())


@pytest.mark.asyncio
async def test_a_validly_signed_session_for_a_stranger_is_refused_without_leaking_who(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]], logs: LogCapture
) -> None:
    async with oauth_app as (app, client):
        token = await mint_session(app, UPSTREAM_TOKEN_STRANGER)
        response = await list_tools(client, token)
        assert response.status_code == 401
        assert str(STRANGER_GITHUB_ID) not in response.text
        refusals = [record for record in logs.records if record.getMessage() == "mcp_auth_refused"]
        assert refusals
        assert refusals[0].__dict__["mcp_auth_reason"] == "identity_not_allowlisted"
        # The refusal carries the request's own correlation id, the one the response returned.
        assert refusals[0].__dict__["correlation_id"] == response.headers["x-correlation-id"]
        assert_no_credential_or_identity(logs.text())


@pytest.mark.asyncio
async def test_a_disabled_user_loses_access_at_once(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with oauth_app as (app, client):
        token = await mint_session(app, UPSTREAM_TOKEN_OWNER)
        assert (await list_tools(client, token)).status_code == 200
        monkeypatch.setattr(app.state.container.auth, "is_user_active", lambda user_id: False)
        assert (await list_tools(client, token)).status_code == 401


@pytest.mark.asyncio
async def test_a_token_signed_with_another_key_or_a_personal_token_is_refused(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (_app, client):
        assert (await list_tools(client, "rsp_" + "a" * 40)).status_code == 401
        assert (await list_tools(client, "not.a.jwt")).status_code == 401


def test_the_oauth_proxy_state_is_encrypted_at_rest(tmp_path: Path) -> None:
    import asyncio

    storage = oauth_module.build_client_storage(tmp_path / "state", b"k" * 44)

    async def write() -> None:
        await storage.put(key="record", value={"secret": "at-rest-sentinel"}, collection="c")

    asyncio.run(write())
    stored = "".join(
        path.read_text(errors="ignore") for path in (tmp_path / "state").rglob("*.json")
    )
    assert stored
    assert "at-rest-sentinel" not in stored
    assert (tmp_path / "state").stat().st_mode & 0o077 == 0


def test_library_loggers_drop_arguments_and_tracebacks_so_codes_cannot_reach_a_sink() -> None:
    oauth_module._redact_library_logs()  # pyright: ignore[reportPrivateUsage]
    capture = LogCapture()
    library = logging.getLogger("fastmcp.server.auth.oauth_proxy.proxy")
    library.addHandler(capture)
    try:
        try:
            raise RuntimeError("upstream said: code=abc-sentinel-code")
        except RuntimeError:
            library.error("Authorization code not found: %s", "abc-sentinel-code", exc_info=True)
    finally:
        library.removeHandler(capture)
    assert capture.records
    assert "abc-sentinel-code" not in capture.text()


@pytest.mark.integration
def test_is_user_active_follows_the_user_row_in_the_database() -> None:
    """DB-backed: the one new AuthService question the OAuth verifier asks."""

    from tests.db import database_factory
    from tests.support.settings import make_settings

    auth = create_app(make_settings(), database_factory()).state.container.auth
    user_id = auth.provision_user("oauth-active", "OAuth Active")
    assert auth.is_user_active(user_id) is True
    assert auth.is_user_active(UUID(int=1)) is False
    assert auth.disable_user(user_id) is True
    assert auth.is_user_active(user_id) is False


# --- the full sign-in, real tokens, and hostile variants ----------------------------------


def pkce_pair() -> tuple[str, str]:
    verifier = "v" * 50
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


async def register_claude(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/mcp/register",
        json={
            "client_name": "Claude",
            "redirect_uris": [CLAUDE_CALLBACK],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    return response.json()["client_id"]


async def sign_in_for_code(client: httpx.AsyncClient, client_id: str, challenge: str) -> str:
    """Drive authorize, consent and the GitHub callback; return the code given to the client."""

    started = await client.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CLAUDE_CALLBACK,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "client-state",
            "resource": f"{PUBLIC}/mcp",
        },
    )
    consent_url = started.headers["location"]
    page = await client.get(consent_url.removeprefix(PUBLIC))
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert csrf is not None
    transaction = consent_url.rsplit("=", 1)[1]
    approved = await client.post(
        "/mcp/consent",
        data={"action": "approve", "txn_id": transaction, "csrf_token": csrf.group(1)},
    )
    state = parse_qs(urlsplit(approved.headers["location"]).query)["state"][0]
    callback = await client.get(
        "/mcp/auth/callback", params={"code": "github-code", "state": state}
    )
    assert callback.status_code == 302
    query = parse_qs(urlsplit(callback.headers["location"]).query)
    assert query["state"] == ["client-state"]
    return query["code"][0]


async def exchange(
    client: httpx.AsyncClient, client_id: str, code: str, verifier: str
) -> httpx.Response:
    return await client.post(
        "/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CLAUDE_CALLBACK,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


@pytest.mark.asyncio
async def test_a_wrong_code_verifier_is_invalid_grant_and_the_right_one_signs_the_owner_in(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (_app, client):
        client_id = await register_claude(client)
        verifier, challenge = pkce_pair()
        code = await sign_in_for_code(client, client_id, challenge)
        wrong = await exchange(client, client_id, code, "w" * 50)
        assert wrong.status_code in {400, 401}, wrong.text
        assert wrong.json()["error"] == "invalid_grant"

        code = await sign_in_for_code(client, client_id, challenge)
        issued = await exchange(client, client_id, code, verifier)
        assert issued.status_code == 200
        token = issued.json()["access_token"]
        assert UPSTREAM_TOKEN_OWNER not in issued.text
        assert (await list_tools(client, token)).status_code == 200
        # A code is single-use.
        replay = await exchange(client, client_id, code, verifier)
        assert replay.status_code in {400, 401}
        assert replay.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_a_tool_outside_the_scope_policy_is_denied_even_for_the_allowlisted_owner(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (app, client):
        token = await mint_session(app, UPSTREAM_TOKEN_OWNER)
        response = await client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_contacts", "arguments": {}},
            },
        )
        assert response.status_code == 200
        outcome = response.json()["result"]
        assert outcome["isError"] is True
        assert outcome["structuredContent"]["code"] == "forbidden"
        assert "contacts" not in json.dumps(outcome["structuredContent"]["message"]).lower()


def _unsigned_token() -> str:
    def part(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    now = int(time.time())
    claims = {
        "iss": f"{PUBLIC}/mcp",
        "aud": f"{PUBLIC}/mcp",
        "client_id": "c",
        "scope": "tasks:read",
        "exp": now + 3600,
        "iat": now,
        "jti": "jti-alg-none",
    }
    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant", ["wrong_key", "wrong_audience", "wrong_issuer", "expired", "alg_none", "refresh"]
)
async def test_forged_or_misused_proxy_tokens_are_401_even_with_valid_stored_state(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]], variant: str
) -> None:
    async with oauth_app as (app, client):
        # Valid mapping and a live owner session exist, so only the token itself is at fault.
        valid = await mint_session(app, UPSTREAM_TOKEN_OWNER)
        assert (await list_tools(client, valid)).status_code == 200
        provider = fastmcp_provider(app)
        key = provider._jwt_signing_key  # pyright: ignore[reportPrivateUsage]
        jti = f"jti-{UPSTREAM_TOKEN_OWNER}"
        issuer = f"{PUBLIC}/mcp"
        if variant == "alg_none":
            token = _unsigned_token()
            await provider._jti_mapping_store.put(  # pyright: ignore[reportPrivateUsage]
                key="jti-alg-none",
                value=JTIMapping(
                    jti="jti-alg-none",
                    upstream_token_id=f"upstream-{UPSTREAM_TOKEN_OWNER}",
                    created_at=time.time(),
                ),
                ttl=3600,
            )
        else:
            forged = JWTIssuer(
                issuer="https://evil.example/mcp" if variant == "wrong_issuer" else issuer,
                audience="https://evil.example/mcp" if variant == "wrong_audience" else issuer,
                signing_key=b"x" * 44 if variant == "wrong_key" else key,
            )
            if variant == "refresh":
                token = forged.issue_refresh_token(
                    client_id="c", scopes=sorted(POLICY), jti=jti, expires_in=3600
                )
            else:
                token = forged.issue_access_token(
                    client_id="c",
                    scopes=sorted(POLICY),
                    jti=jti,
                    expires_in=-60 if variant == "expired" else 3600,
                )
        assert (await list_tools(client, token)).status_code == 401


@pytest.mark.asyncio
async def test_authorize_without_pkce_or_with_plain_pkce_never_reaches_consent(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (_app, client):
        client_id = await register_claude(client)
        _verifier, challenge = pkce_pair()
        base = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CLAUDE_CALLBACK,
            "state": "s",
        }
        for extra in (
            {},
            {"code_challenge": challenge, "code_challenge_method": "plain"},
        ):
            response = await client.get("/mcp/authorize", params={**base, **extra})
            location = response.headers.get("location", "")
            assert "/mcp/consent" not in location
            assert response.status_code == 400 or "error=" in location, (extra, location)


@pytest.mark.asyncio
async def test_personal_token_mode_mounts_no_oauth_discovery_and_leaves_the_api_open() -> None:
    settings = Settings(
        environment="test",
        cursor_signing_secret="session-secret-for-tests-only-123456",
        token_pepper="token-pepper-for-tests-only-12345678",
    )
    app = create_app(settings)
    paths = {getattr(route, "path", "") for route in app.router.routes}
    assert not any(path.startswith("/.well-known") for path in paths)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        assert (await client.get("/api/openapi.json")).status_code == 200
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/.well-known/oauth-protected-resource/mcp")).status_code == 404
        unauthenticated = await client.post("/mcp/", json={})
        assert unauthenticated.status_code == 401
        assert "resource_metadata" not in unauthenticated.headers["www-authenticate"]


def test_a_preexisting_world_readable_storage_directory_is_tightened_to_owner_only(
    tmp_path: Path,
) -> None:
    import asyncio
    import os
    import stat

    directory = tmp_path / "state"
    directory.mkdir()
    os.chmod(directory, 0o755)
    storage = oauth_module.build_client_storage(directory, b"k" * 44)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700

    async def write() -> None:
        await storage.put(key="a", value={"v": "1"}, collection="c1")
        await storage.put(key="b", value={"v": "2"}, collection="c2")

    asyncio.run(write())
    folders = [path for path in directory.rglob("*") if path.is_dir()]
    assert folders
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in folders)


def test_storage_is_refused_when_it_cannot_be_made_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oauth_module, "_tighten", lambda root: None)
    directory = tmp_path / "state"
    directory.mkdir()
    directory.chmod(0o755)
    with pytest.raises(RuntimeError, match="owner-only"):
        oauth_module.build_client_storage(directory, b"k" * 44)


def test_storage_is_refused_when_the_file_store_hook_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def renamed(self: object, collection: str) -> None:  # positional, not keyword-only
        del self, collection

    monkeypatch.setattr(oauth_module.FileTreeStore, "_setup_collection", renamed)
    with pytest.raises(RuntimeError, match="file store changed"):
        oauth_module.build_client_storage(tmp_path / "state", b"k" * 44)
    assert not (tmp_path / "state").exists()


def test_the_installed_file_store_has_the_members_the_owner_only_subclass_uses() -> None:
    oauth_module._require_file_tree_hooks()  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "logger_name",
    [
        "fastmcp.server.auth.oauth_proxy.proxy",
        "fastmcp.server.auth.jwt_issuer",
        "fastmcp.server.auth.middleware",
        "fastmcp.server.auth.ssrf",
        "mcp.server.auth.handlers.authorize",
        "mcp.server.auth.handlers.token",
    ],
)
def test_library_logs_never_carry_a_value_from_an_fstring_or_arguments_or_a_traceback(
    logger_name: str,
) -> None:
    oauth_module._redact_library_logs()  # pyright: ignore[reportPrivateUsage]
    capture = LogCapture()
    library = logging.getLogger(logger_name)
    library.addHandler(capture)
    previous = library.level
    library.setLevel(logging.DEBUG)
    try:
        library.debug(f"debug sentinel-{logger_name}")
        library.error(f"f-string sentinel-code-123 for {logger_name}")
        library.warning("argument %s", "sentinel-code-456")
        try:
            raise RuntimeError("sentinel-code-789")
        except RuntimeError:
            library.exception("with traceback")
    finally:
        library.removeHandler(capture)
        library.setLevel(previous)
    assert len(capture.records) == 3  # the DEBUG record is dropped
    rendered = capture.text()
    for sentinel in ("sentinel-code-123", "sentinel-code-456", "sentinel-code-789", "sentinel-"):
        assert sentinel not in rendered
    assert all(record.exc_info is None for record in capture.records)


# --- session lifetime ---------------------------------------------------------------------

DAY = 24 * 60 * 60
LEGACY_LIFETIME = 365 * DAY  # what the library issued before the configured default


def refreshing_github_token_endpoint() -> httpx2.MockTransport:
    """GitHub with expiring user tokens: the code exchange and the refresh both succeed."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == "https://github.com/login/oauth/access_token"
        return httpx2.Response(
            200,
            json={
                "access_token": UPSTREAM_TOKEN_OWNER,
                "refresh_token": "ghr_upstream_refresh_sentinel",
                "token_type": "bearer",
                "scope": "",
            },
        )

    return httpx2.MockTransport(handler)


def jwt_lifetime(token: str) -> int:
    """Seconds between issue and expiry in a FastMCP-signed token (no verification needed)."""

    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return int(claims["exp"] - claims["iat"])


@pytest.mark.asyncio
async def test_a_new_sign_in_lasts_the_configured_thirty_days_not_a_year(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (_app, client):
        client_id = await register_claude(client)
        verifier, challenge = pkce_pair()
        code = await sign_in_for_code(client, client_id, challenge)
        issued = await exchange(client, client_id, code, verifier)

        assert issued.status_code == 200
        assert issued.json()["expires_in"] == 30 * DAY
        assert jwt_lifetime(issued.json()["access_token"]) == 30 * DAY


@pytest.mark.asyncio
async def test_a_session_issued_before_the_shorter_default_keeps_working(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    """The owner's existing connector holds a year-long token: it is not cut short by the change."""

    async with oauth_app as (app, client):
        legacy = await mint_session(app, UPSTREAM_TOKEN_OWNER, lifetime=LEGACY_LIFETIME)

        assert jwt_lifetime(legacy) == LEGACY_LIFETIME
        assert (await list_tools(client, legacy)).status_code == 200


@pytest.mark.asyncio
async def test_a_refresh_grant_issued_under_the_old_default_still_refreshes(
    oauth_app: AbstractAsyncContextManager[tuple[Any, httpx.AsyncClient]],
) -> None:
    async with oauth_app as (app, client):
        provider = fastmcp_provider(app)
        provider._create_upstream_oauth_client = lambda: AsyncOAuth2Client(  # pyright: ignore[reportPrivateUsage]
            client_id="Ov23liClientId",
            client_secret=CLIENT_SECRET,
            transport=refreshing_github_token_endpoint(),
        )
        configured = (
            provider._fallback_access_token_expiry_seconds,  # pyright: ignore[reportPrivateUsage]
            provider._fallback_refresh_token_expiry_seconds,  # pyright: ignore[reportPrivateUsage]
        )
        assert configured == (30 * DAY, 30 * DAY)

        # Sign in as the previous release would have: library defaults, a year-long refresh token.
        provider._fallback_access_token_expiry_seconds = None  # pyright: ignore[reportPrivateUsage]
        provider._fallback_refresh_token_expiry_seconds = LEGACY_LIFETIME  # pyright: ignore[reportPrivateUsage]
        client_id = await register_claude(client)
        verifier, challenge = pkce_pair()
        code = await sign_in_for_code(client, client_id, challenge)
        issued = (await exchange(client, client_id, code, verifier)).json()
        assert jwt_lifetime(issued["refresh_token"]) == LEGACY_LIFETIME

        # The deployed configuration is back in force; the old grant must refresh under it.
        provider._fallback_access_token_expiry_seconds = configured[0]  # pyright: ignore[reportPrivateUsage]
        provider._fallback_refresh_token_expiry_seconds = configured[1]  # pyright: ignore[reportPrivateUsage]
        refreshed = await client.post(
            "/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": issued["refresh_token"],
                "client_id": client_id,
            },
        )

        assert refreshed.status_code == 200, refreshed.text
        assert (await list_tools(client, refreshed.json()["access_token"])).status_code == 200

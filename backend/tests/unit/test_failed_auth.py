"""The pre-database limit on failed bearer attempts: per client and global, owner unaffected.

The unit tests drive the middleware on a fake clock in front of a stub application that stands in
for the token check (and counts how often it is reached, which is how often the database would be).
The application-level tests at the end count real `verify_personal_token` calls.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

import pytest
from starlette.types import Receive, Scope, Send

from sidekick.api.app import create_app
from sidekick.api.failed_auth import (
    DEFAULT_FAILURES_GLOBAL_PER_MINUTE,
    DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE,
    DEFAULT_RESERVE_PER_MINUTE,
    KNOWN_TOKEN_SECONDS,
    MAX_KNOWN_TOKENS,
    MAX_TRACKED_CLIENTS,
    VERIFIED_BEARER_SCOPE_KEY,
    FailedAuthGuard,
    FailedAuthLimitMiddleware,
)
from sidekick.shared.auth.verification_signal import mark_verified
from sidekick.shared.config import Settings
from sidekick.shared.observability import NoopTelemetryAdapter
from tests.asgi_ingress import Recorder, http_scope, receive

GOOD = b"good-owner-token-canary-0000000000"
BAD_CANARY = "guessed-token-canary-"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TokenCheck:
    """A stub application: 204 for the good token, 401 for any other bearer, counts the calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.good = {GOOD}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.calls += 1
        header = dict(scope["headers"]).get(b"authorization", b"")
        token = header.partition(b" ")[2]
        status = 204 if token in self.good else 401
        if status == 204:
            mark_verified()  # what the real auth code does after verifying a credential
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def build(
    per_client: int = 3, global_limit: int = 8, reserve: int = 0
) -> tuple[FailedAuthLimitMiddleware, TokenCheck, Clock]:
    clock = Clock()
    app = TokenCheck()
    guard = FailedAuthGuard(per_client, global_limit, reserve_per_minute=reserve, clock=clock)
    return FailedAuthLimitMiddleware(app, NoopTelemetryAdapter(), guard, clock=clock), app, clock


async def attempt(
    middleware: FailedAuthLimitMiddleware,
    token: bytes | None,
    client: str = "203.0.113.7",
    method: str = "POST",
    path: str = "/mcp/",
) -> Recorder:
    headers = [(b"authorization", b"Bearer " + token)] if token is not None else []
    scope = http_scope(path, method, headers)
    scope["client"] = (client, 4000)
    recorder = Recorder()
    await middleware(scope, receive, recorder.send)
    return recorder


async def fail(
    middleware: FailedAuthLimitMiddleware, times: int, client: str = "203.0.113.7"
) -> None:
    for index in range(times):
        result = await attempt(middleware, f"{BAD_CANARY}{index}".encode(), client)
        assert result.status == 401


@pytest.mark.asyncio
async def test_a_client_that_keeps_failing_is_429_before_the_app_is_reached() -> None:
    middleware, app, _ = build(per_client=3)
    await fail(middleware, 3)
    assert app.calls == 3
    refused = await attempt(middleware, b"another-guess")
    assert refused.status == 429
    assert app.calls == 3  # no token check, so no database query
    assert refused.body["code"] == "rate_limited"
    assert set(refused.body) == {"type", "title", "status", "code", "correlation_id"}
    assert int(dict(refused.sent[0]["headers"])[b"retry-after"]) >= 1
    assert "another-guess" not in json.dumps(refused.body)


@pytest.mark.asyncio
async def test_the_client_gets_in_again_as_its_failures_age_out() -> None:
    middleware, app, clock = build(per_client=3)
    await fail(middleware, 3)
    assert (await attempt(middleware, b"x")).status == 429
    clock.now += 61
    assert (await attempt(middleware, b"x")).status == 401
    assert app.calls == 4


@pytest.mark.asyncio
async def test_refused_requests_do_not_extend_the_block() -> None:
    middleware, _, clock = build(per_client=2)
    await fail(middleware, 2)
    for _ in range(50):
        clock.now += 1
        if (await attempt(middleware, b"x")).status != 429:
            break
    assert clock.now - 1000.0 <= 61


@pytest.mark.asyncio
async def test_another_client_is_not_blocked_by_one_clients_failures() -> None:
    middleware, _, _ = build(per_client=3, global_limit=100)
    await fail(middleware, 3, client="203.0.113.7")
    assert (await attempt(middleware, b"x", client="203.0.113.7")).status == 429
    assert (await attempt(middleware, b"x", client="198.51.100.9")).status == 401


@pytest.mark.asyncio
async def test_the_global_budget_limits_many_clients_each_below_their_own_budget() -> None:
    middleware, app, _ = build(per_client=5, global_limit=6)
    for index in range(6):
        await fail(middleware, 1, client=f"198.51.100.{index}")
    refused = await attempt(middleware, b"x", client="198.51.100.200")
    assert refused.status == 429
    assert app.calls == 6


@pytest.mark.asyncio
async def test_valid_owner_traffic_is_never_throttled_while_an_attack_runs() -> None:
    middleware, app, _ = build(per_client=3, global_limit=6)
    # The owner has been seen once; then guessers exhaust both budgets.
    assert (await attempt(middleware, GOOD, client="198.51.100.1")).status == 204
    for index in range(6):
        await fail(middleware, 1, client=f"192.0.2.{index}")
    assert (await attempt(middleware, b"unknown", client="198.51.100.2")).status == 429
    # Owner, from the same address the attacker uses and from another one.
    for client in ("198.51.100.1", "192.0.2.0", "192.0.2.77"):
        for _ in range(20):
            assert (await attempt(middleware, GOOD, client=client)).status == 204
    assert app.calls == 1 + 6 + 60


@pytest.mark.asyncio
async def test_successful_requests_alone_never_trip_the_limit() -> None:
    middleware, _, _ = build(per_client=3, global_limit=6)
    for _ in range(200):
        assert (await attempt(middleware, GOOD)).status == 204


@pytest.mark.asyncio
async def test_a_revoked_token_is_forgotten_and_counts_as_a_failure() -> None:
    middleware, app, _ = build(per_client=2, global_limit=100)
    assert (await attempt(middleware, GOOD)).status == 204
    app.good = set()  # revoked
    assert (await attempt(middleware, GOOD)).status == 401
    assert (await attempt(middleware, GOOD)).status == 401
    assert (await attempt(middleware, GOOD)).status == 429


@pytest.mark.asyncio
async def test_a_known_token_is_forgotten_after_its_window() -> None:
    middleware, _, clock = build(per_client=1, global_limit=100)
    assert (await attempt(middleware, GOOD)).status == 204
    await fail(middleware, 1)
    assert (await attempt(middleware, b"x")).status == 429
    assert (await attempt(middleware, GOOD)).status == 204
    clock.now += KNOWN_TOKEN_SECONDS + 1
    # Failures aged out as well; fail again so only the lapsed memory decides.
    await fail(middleware, 1)
    assert (await attempt(middleware, GOOD)).status == 429


class Mounted:
    """`/mcp` answers 307 before any auth, as the mount in front of the endpoint does."""

    def __init__(self, check: TokenCheck) -> None:
        self.check = check

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["path"] == "/mcp":
            await send({"type": "http.response.start", "status": 307, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await self.check(scope, receive, send)


def build_mounted(
    per_client: int = 3, global_limit: int = 6
) -> tuple[FailedAuthLimitMiddleware, TokenCheck, Clock]:
    clock = Clock()
    check = TokenCheck()
    guard = FailedAuthGuard(per_client, global_limit, reserve_per_minute=0, clock=clock)
    return (
        FailedAuthLimitMiddleware(Mounted(check), NoopTelemetryAdapter(), guard, clock=clock),
        check,
        clock,
    )


@pytest.mark.asyncio
async def test_random_tokens_answered_307_on_get_mcp_do_not_evict_the_owner() -> None:
    middleware, _, _ = build_mounted(per_client=3, global_limit=6)
    assert (await attempt(middleware, GOOD, path="/mcp/")).status == 204
    for index in range(MAX_KNOWN_TOKENS + 6):
        redirected = await attempt(
            middleware, f"random-{index}".encode(), method="GET", path="/mcp"
        )
        assert redirected.status == 307
    for index in range(6):
        await fail(middleware, 1, client=f"192.0.2.{index}")
    assert (await attempt(middleware, b"unknown", path="/mcp/")).status == 429
    assert (await attempt(middleware, GOOD, path="/mcp/")).status == 204


@pytest.mark.asyncio
async def test_a_307_on_get_mcp_then_mcp_slash_does_not_bypass_an_exhausted_budget() -> None:
    middleware, app, _ = build_mounted(per_client=3, global_limit=6)
    tokens = [f"pair-{index}".encode() for index in range(10)]
    for token in tokens:
        assert (await attempt(middleware, token, method="GET", path="/mcp")).status == 307
    await fail(middleware, 3)
    calls = app.calls
    for token in tokens:
        assert (await attempt(middleware, token, path="/mcp/")).status == 429
    assert app.calls == calls


@pytest.mark.asyncio
async def test_a_known_token_is_renewed_on_every_use() -> None:
    middleware, _, clock = build(per_client=1, global_limit=100)
    assert (await attempt(middleware, GOOD)).status == 204
    for _ in range(3):  # three hours of use, never idle for an hour
        clock.now += KNOWN_TOKEN_SECONDS - 60
        assert (await attempt(middleware, GOOD)).status == 204
    await fail(middleware, 1)
    assert (await attempt(middleware, b"x")).status == 429
    assert (await attempt(middleware, GOOD)).status == 204


@pytest.mark.asyncio
async def test_the_reserve_lets_a_few_unknown_tokens_through_an_exhausted_budget() -> None:
    middleware, app, clock = build(per_client=1, global_limit=2, reserve=2)
    await fail(middleware, 1)  # budget spent for this client
    for _ in range(2):
        assert (await attempt(middleware, b"reserve-guess")).status == 401  # reached the app
    calls = app.calls
    assert (await attempt(middleware, b"reserve-guess")).status == 429
    assert app.calls == calls
    clock.now += 30  # the reserve refills at reserve/min
    assert (await attempt(middleware, b"reserve-guess")).status == 401


@pytest.mark.asyncio
async def test_a_fresh_owner_token_gets_through_a_sustained_attack_within_seconds() -> None:
    """After a restart the owner's token is unknown; the reserve lets the first valid call in."""

    middleware, _, clock = build(per_client=3, global_limit=6, reserve=5)
    for second in range(120):  # one wrong guess a second for two minutes
        clock.now += 1
        await attempt(middleware, f"attack-{second}".encode(), client=f"192.0.2.{second % 50}")
    assert (await attempt(middleware, b"another")).status == 429
    for _ in range(15):
        # The owner retries every second, ahead of the attacker's next guess in that second.
        clock.now += 1
        result = await attempt(middleware, GOOD, client="198.51.100.1")
        if result.status == 204:
            break
        assert result.status == 429
        await attempt(middleware, b"attack-more", client="192.0.2.1")
    else:
        pytest.fail("the owner was kept out for 15 seconds")
    # From now on the token is known and never throttled.
    for _ in range(20):
        assert (await attempt(middleware, GOOD, client="198.51.100.1")).status == 204


@pytest.mark.asyncio
async def test_only_a_recently_verified_token_is_marked_verified_for_later_layers() -> None:
    seen: list[bool] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(bool(scope.get(VERIFIED_BEARER_SCOPE_KEY)))
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    clock = Clock()
    guard = FailedAuthGuard(clock=clock)
    guard.record_success(guard.fingerprint(GOOD))
    middleware = FailedAuthLimitMiddleware(inner, NoopTelemetryAdapter(), guard, clock=clock)
    for token in (GOOD, b"guess", None):
        await attempt(middleware, token)
    assert seen == [True, False, False]
    clock.now += KNOWN_TOKEN_SECONDS + 1
    await attempt(middleware, GOOD)
    assert seen[-1] is False  # the hour lapsed: no longer known


@pytest.mark.asyncio
async def test_requests_without_a_bearer_token_are_neither_counted_nor_refused() -> None:
    middleware, app, _ = build(per_client=1, global_limit=1)
    await fail(middleware, 1)
    result = await attempt(middleware, None)
    assert result.status == 401 or result.status == 204  # reached the app
    assert app.calls == 2
    # Requests with no credential header do not use up the budget either.
    middleware, _, _ = build(per_client=2, global_limit=2)
    for _ in range(10):
        await attempt(middleware, None)
    await fail(middleware, 2)


@pytest.mark.asyncio
async def test_non_401_answers_are_not_failures() -> None:
    clock = Clock()

    async def forbidden(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 403, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = FailedAuthLimitMiddleware(
        forbidden, NoopTelemetryAdapter(), FailedAuthGuard(1, 1, clock=clock), clock=clock
    )
    for _ in range(5):
        assert (await attempt(middleware, b"some-token")).status == 403


class Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        return " ".join(f"{r.getMessage()} {r.__dict__}" for r in self.records)


@pytest.mark.asyncio
async def test_a_refusal_logs_no_token_and_is_logged_once_per_interval() -> None:
    middleware, _, clock = build(per_client=1, global_limit=100)
    await fail(middleware, 1)
    logger = logging.getLogger("sidekick.http")
    collector = Collector()
    logger.addHandler(collector)
    try:
        for _ in range(5):
            await attempt(middleware, b"secret-guess-canary")
        assert [r.getMessage() for r in collector.records] == ["failed_auth_limited"]
        clock.now += 5  # inside the log interval and still inside the block window
        await attempt(middleware, b"secret-guess-canary")
        assert len(collector.records) == 1
    finally:
        logger.removeHandler(collector)
    assert "secret-guess-canary" not in collector.text
    assert BAD_CANARY not in collector.text
    assert "203.0.113.7" not in collector.text


@pytest.mark.asyncio
async def test_non_http_scopes_pass_straight_through() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    middleware = FailedAuthLimitMiddleware(inner, NoopTelemetryAdapter())
    await middleware({"type": "lifespan"}, receive, Recorder().send)
    assert seen == ["lifespan"]


def test_the_trackers_are_bounded() -> None:
    clock = Clock()
    guard = FailedAuthGuard(2, 10**9, clock=clock)
    for index in range(MAX_TRACKED_CLIENTS + 50):
        guard.record_failure(f"client-{index}", None)
        clock.now += 0.001
    assert len(guard._clients) <= MAX_TRACKED_CLIENTS  # pyright: ignore[reportPrivateUsage]
    for index in range(MAX_KNOWN_TOKENS + 20):
        guard.record_success(guard.fingerprint(str(index).encode()))
    assert len(guard._known) <= MAX_KNOWN_TOKENS  # pyright: ignore[reportPrivateUsage]


def test_the_fingerprint_is_keyed_per_process_and_is_not_the_token() -> None:
    token = b"owner-token-canary"
    first, second = FailedAuthGuard(), FailedAuthGuard()
    assert first.fingerprint(token) == first.fingerprint(token)
    assert first.fingerprint(token) != second.fingerprint(token)
    assert token not in first.fingerprint(token)


def test_settings_carry_safe_defaults_and_bounds() -> None:
    settings = Settings(_env_file=None)
    assert settings.failed_auth_per_client_per_minute == DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE
    assert settings.failed_auth_global_per_minute == DEFAULT_FAILURES_GLOBAL_PER_MINUTE
    assert settings.failed_auth_reserve_per_minute == DEFAULT_RESERVE_PER_MINUTE
    assert DEFAULT_FAILURES_PER_CLIENT_PER_MINUTE < DEFAULT_FAILURES_GLOBAL_PER_MINUTE
    with pytest.raises(ValueError, match="failed_auth_global_per_minute"):
        Settings(_env_file=None, failed_auth_global_per_minute=0)


# --- the real application: failures are cut off before the token check queries the database -----


def app_settings(**overrides: Any) -> Settings:
    return Settings(
        environment="test",
        cursor_signing_secret="session-secret-for-tests-only-123456",
        token_pepper="token-pepper-for-tests-only-12345678",
        mcp_auth_mode="pat",
        failed_auth_per_client_per_minute=3,
        failed_auth_global_per_minute=100,
        failed_auth_reserve_per_minute=0,
        **overrides,
    )


def count_token_checks(monkeypatch: pytest.MonkeyPatch) -> Callable[[], int]:
    from sidekick.shared.auth import AuthService

    calls = 0
    original = AuthService.verify_personal_token

    def counting(self: AuthService, token: str) -> Any:
        nonlocal calls
        calls += 1
        return original(self, token)

    monkeypatch.setattr(AuthService, "verify_personal_token", counting)
    return lambda: calls


@pytest.mark.asyncio
async def test_a_failed_auth_burst_is_limited_before_any_database_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = count_token_checks(monkeypatch)
    app = create_app(app_settings())
    statuses: list[int] = []
    for index in range(12):
        scope = http_scope(
            "/mcp/",
            "POST",
            [
                (b"authorization", f"Bearer {BAD_CANARY}{index}".encode()),
                (b"content-type", b"application/json"),
            ],
        )
        scope["client"] = ("203.0.113.7", 4000)
        recorder = Recorder()
        await app(scope, receive, recorder.send)
        statuses.append(recorder.status)
    assert statuses[:3] == [401, 401, 401]
    assert set(statuses[3:]) == {429}
    assert checks() == 3  # the nine refused attempts never reached the token check


@pytest.mark.asyncio
async def test_the_real_mount_redirect_does_not_teach_the_limiter_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = count_token_checks(monkeypatch)
    app = create_app(app_settings())

    async def get(path: str, token: str) -> int:
        method = "GET" if path == "/mcp" else "POST"
        scope = http_scope(path, method, [(b"authorization", f"Bearer {token}".encode())])
        scope["client"] = ("203.0.113.7", 4000)
        recorder = Recorder()
        await app(scope, receive, recorder.send)
        return recorder.status

    tokens = [f"redirect-{index}" for index in range(10)]
    for token in tokens:
        assert await get("/mcp", token) == 307
    for index in range(3):
        assert await get("/mcp/", f"{BAD_CANARY}{index}") == 401
    seen = checks()
    for token in tokens:
        assert await get("/mcp/", token) == 429
    assert checks() == seen


@pytest.mark.asyncio
@pytest.mark.integration
async def test_valid_owner_traffic_is_unaffected_while_a_failed_auth_burst_is_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import httpx2
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    from sidekick.shared.auth import TOKEN_SCOPES
    from tests.db import database_factory
    from tests.support.settings import make_settings

    checks = count_token_checks(monkeypatch)
    settings = make_settings().model_copy(
        update={
            "failed_auth_per_client_per_minute": 3,
            "failed_auth_global_per_minute": 5,
            "failed_auth_reserve_per_minute": 0,
        }
    )
    app = create_app(settings, database_factory())
    auth = app.state.container.auth
    owner = auth.provision_user("owner", "Owner")
    token = auth.create_personal_token(owner, "owner traffic", TOKEN_SCOPES)

    def client_factory(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver", **kwargs
        )

    transport = StreamableHttpTransport(
        "http://testserver/mcp/",
        headers={"Authorization": f"Bearer {token}"},
        httpx_client_factory=client_factory,
    )
    async with (
        app.router.lifespan_context(app),
        Client(transport) as owner_client,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as attacker,
    ):
        await owner_client.list_tools()
        before = checks()
        statuses = [
            (
                await attacker.post(
                    "/mcp/",
                    headers={"Authorization": f"Bearer {BAD_CANARY}{index}"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )
            ).status_code
            for index in range(12)
        ]
        assert statuses[:3] == [401, 401, 401]
        assert set(statuses[3:]) == {429}
        assert checks() - before == 3  # only the first three guesses reached the database
        # The owner keeps working, from the same address, while the attacker is cut off.
        for _ in range(5):
            assert len(await owner_client.list_tools()) > 0
        refused = await attacker.post(
            "/mcp/",
            headers={"Authorization": "Bearer one-more-guess"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert refused.status_code == 429

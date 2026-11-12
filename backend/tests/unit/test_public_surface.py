"""The public-surface allowlist and rate limit, without any framework app.

Request-body ceilings and read budgets are in test_body_limits.py."""

import pytest

from sidekick.api.public_surface import (
    RATE_LIMIT_PER_MINUTE,
    PublicSurfaceAllowlistMiddleware,
    TokenBucket,
    is_public_path,
)
from sidekick.shared.observability import NoopTelemetryAdapter
from tests.asgi_ingress import Recorder, call


@pytest.mark.parametrize(
    "path",
    [
        "/mcp/",
        "/mcp/authorize",
        "/mcp/token",
        "/mcp/register",
        "/mcp/consent",
        "/mcp/auth/callback",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-authorization-server/mcp",
        "/.well-known/openid-configuration",
        "/.well-known/openid-configuration/mcp",
    ],
)
def test_the_published_paths_are_public(path: str) -> None:
    assert is_public_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/",
        "/mcp",
        "/mcp/../api",
        "/mcp/%2e%2e/api",
        "/mcp/./authorize",
        "//mcp/",
        "//mcp/authorize",
        "/mcp//authorize",
        "/mcp/authorize/",
        "/mcp/authorizeX",
        "/mcp/anything",
        "/MCP/",
        "/api/v1/auth/csrf",
        "/health/live",
        "/agent-mcp/",
        "/.well-known/oauth-protected-resourceX",
        "/.well-known/oauth-protected-resource/../../api",
        "/.well-known/security.txt",
        "/.well-known/",
    ],
)
def test_everything_else_is_not_public(path: str) -> None:
    assert not is_public_path(path)


def build() -> tuple[PublicSurfaceAllowlistMiddleware, Recorder, list[float]]:
    recorder = Recorder()
    clock = [0.0]
    middleware = PublicSurfaceAllowlistMiddleware(
        recorder.app, NoopTelemetryAdapter(), clock=lambda: clock[0]
    )
    return middleware, recorder, clock


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/mcp/../api", "/mcp/%2e%2e/api", "//mcp/", "/api/v1/x"])
@pytest.mark.parametrize("method", ["GET", "POST", "HEAD", "OPTIONS", "DELETE"])
async def test_a_refused_path_is_404_for_every_method_and_never_reaches_the_app(
    path: str, method: str
) -> None:
    middleware, recorder, _clock = build()
    await call(middleware, recorder, path, method=method)
    assert not recorder.reached
    assert recorder.status == 404
    assert recorder.body["correlation_id"] == "corr-unit"


@pytest.mark.asyncio
async def test_the_slashless_mcp_url_is_served_without_a_redirect() -> None:
    middleware, recorder, _clock = build()
    await call(middleware, recorder, "/mcp", method="POST")
    assert recorder.reached
    assert recorder.status == 204


def test_the_token_bucket_spends_its_budget_and_refills_over_time() -> None:
    clock = [0.0]
    bucket = TokenBucket(RATE_LIMIT_PER_MINUTE, lambda: clock[0])
    assert [bucket.take() for _ in range(RATE_LIMIT_PER_MINUTE)] == [True] * RATE_LIMIT_PER_MINUTE
    assert bucket.take() is False
    clock[0] += 2.9
    assert bucket.take() is False
    clock[0] += 0.2  # one token per 3 s
    assert bucket.take() is True
    assert bucket.take() is False
    clock[0] += 3600
    assert sum(bucket.take() for _ in range(100)) == RATE_LIMIT_PER_MINUTE


def test_the_token_bucket_refund_returns_a_token_but_never_exceeds_capacity() -> None:
    clock = [0.0]
    bucket = TokenBucket(3, lambda: clock[0])
    bucket.refund()  # a full bucket stays at capacity
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]
    bucket.refund()
    assert bucket.take() is True
    assert bucket.take() is False
    for _ in range(5):
        bucket.refund()
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]


def test_the_token_bucket_reports_the_seconds_until_one_token_has_refilled() -> None:
    clock = [0.0]
    bucket = TokenBucket(30, lambda: clock[0])  # 0.5 token a second
    assert bucket.seconds_until_budget() == 1
    for _ in range(30):
        assert bucket.take()
    assert bucket.seconds_until_budget() == 2
    clock[0] += 0.5
    assert bucket.seconds_until_budget() == 2  # 0.25 token held, 1.5 s left, rounded up
    clock[0] += 1.0
    assert bucket.seconds_until_budget() == 1
    clock[0] += 0.5
    assert bucket.take() is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), [("POST", "/mcp/register"), ("GET", "/mcp/authorize")])
async def test_unauthenticated_state_creating_endpoints_are_rate_limited_with_a_429(
    method: str, path: str
) -> None:
    middleware, recorder, clock = build()
    headers = [(b"content-length", b"2")]
    for _ in range(RATE_LIMIT_PER_MINUTE):
        recorder.reset()
        await call(middleware, recorder, path, method=method, headers=headers)
        assert recorder.reached
    recorder.reset()
    limited = recorder
    await call(middleware, limited, path, method=method, headers=headers)
    assert not limited.reached
    assert limited.status == 429
    assert limited.body["code"] == "rate_limited"
    assert limited.body["correlation_id"] == "corr-unit"
    assert dict(limited.sent[0]["headers"])[b"retry-after"] == b"60"
    clock[0] += 3.1
    recorder.reset()
    await call(middleware, recorder, path, method=method, headers=headers)
    assert recorder.reached


@pytest.mark.asyncio
async def test_other_paths_are_not_rate_limited() -> None:
    middleware, recorder, _clock = build()
    for _ in range(RATE_LIMIT_PER_MINUTE * 3):
        recorder.reset()
        await call(middleware, recorder, "/mcp/token", method="POST")
        assert recorder.reached

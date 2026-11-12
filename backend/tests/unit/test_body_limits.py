"""Request-body ceilings and read-time budgets, in isolation and through the whole application.

The ceilings and budgets are one ingress middleware that is installed in every auth mode: a
personal-access-token deployment (with or without the companion routes) gets the same protection
as the public GitHub OAuth surface. The application-level tests at the end drive the real ASGI
stack, with no credential at all, so the limits are shown to act before authentication.
"""

import asyncio
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from sidekick.api.app import create_app
from sidekick.api.body_limits import (
    MAX_COMPANION_BODY_BYTES,
    MAX_DEFAULT_BODY_BYTES,
    MAX_MCP_BODY_BYTES,
    RequestBodyLimitMiddleware,
)
from sidekick.api.public_surface import MAX_REGISTER_BODY_BYTES
from sidekick.shared.config import Settings
from sidekick.shared.observability import NoopTelemetryAdapter
from tests.asgi_ingress import Recorder, call, chunked, http_scope, receive


def build() -> tuple[RequestBodyLimitMiddleware, Recorder]:
    recorder = Recorder()
    middleware = RequestBodyLimitMiddleware(
        recorder.app, NoopTelemetryAdapter(), oauth_surface=True
    )
    return middleware, recorder


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ([], 204),  # no declared length: bounded while read (see the chunked tests below)
        ([(b"content-length", b"abc")], 411),
        ([(b"content-length", b"-1")], 411),
        ([(b"content-length", str(MAX_REGISTER_BODY_BYTES + 1).encode())], 413),
        ([(b"content-length", b"99999999999")], 413),
        ([(b"content-length", str(MAX_REGISTER_BODY_BYTES).encode())], 204),
        ([(b"content-length", b"0")], 204),
    ],
)
async def test_register_bounds_its_content_length(
    headers: list[tuple[bytes, bytes]], status: int
) -> None:
    middleware, recorder = build()
    await call(middleware, recorder, "/mcp/register", method="POST", headers=headers)
    assert recorder.status == status
    assert recorder.reached is (status == 204)


PROTECTED_ROUTES = [
    ("POST", "/mcp/", MAX_MCP_BODY_BYTES),
    ("POST", "/mcp", MAX_MCP_BODY_BYTES),
    ("POST", "/mcp/token", MAX_DEFAULT_BODY_BYTES),
    ("POST", "/mcp/consent", MAX_DEFAULT_BODY_BYTES),
    ("POST", "/mcp/authorize", MAX_DEFAULT_BODY_BYTES),
    ("POST", "/mcp/register", MAX_REGISTER_BODY_BYTES),
    ("PUT", "/mcp/token", MAX_DEFAULT_BODY_BYTES),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "limit"), PROTECTED_ROUTES)
async def test_an_oversized_declared_body_is_413_before_the_app_reads_it(
    method: str, path: str, limit: int
) -> None:
    middleware, recorder = build()
    headers = [(b"content-length", str(limit + 1).encode())]
    await call(middleware, recorder, path, method=method, headers=headers)
    assert not recorder.reached
    assert recorder.status == 413
    assert recorder.body["code"] == "payload_too_large"
    assert recorder.body["correlation_id"] == "corr-unit"


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "limit"), PROTECTED_ROUTES)
async def test_an_oversized_chunked_body_without_content_length_is_413(
    method: str, path: str, limit: int
) -> None:
    middleware, recorder = build()
    deliver = chunked(b"x" * limit, b"x")
    await call(middleware, recorder, path, method=method, deliver=deliver)
    assert not recorder.reached
    assert recorder.status == 413
    assert recorder.body["code"] == "payload_too_large"


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "limit"), PROTECTED_ROUTES)
async def test_a_chunked_body_within_the_ceiling_reaches_the_app_intact(
    method: str, path: str, limit: int
) -> None:
    middleware, _recorder = build()
    seen: list[bytes] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append((await receive())["body"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware.app = app
    recorder = Recorder()
    half = limit // 2
    await call(
        middleware,
        recorder,
        path,
        method=method,
        deliver=chunked(b"a" * half, b"b" * (limit - half)),
    )
    assert recorder.status == 204
    assert seen == [b"a" * half + b"b" * (limit - half)]


@pytest.mark.asyncio
async def test_a_disconnect_mid_chunked_body_never_reaches_the_app_as_a_finished_body() -> None:
    middleware, recorder = build()
    seen: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(await receive())

    middleware.app = app
    messages = [
        {"type": "http.request", "body": b"partial", "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def deliver() -> dict[str, Any]:
        return messages.pop(0)

    await call(middleware, recorder, "/mcp/token", method="POST", deliver=deliver)
    assert seen == []
    assert recorder.sent == []


def test_the_caddy_example_body_ceilings_are_binary_and_match_the_api() -> None:
    caddy = (Path(__file__).resolve().parents[3] / "deploy/selfhost/Caddyfile.example").read_text(
        encoding="utf-8"
    )
    sizes = set(re.findall(r"max_size (\S+)", caddy))
    for limit in (MAX_REGISTER_BODY_BYTES, MAX_COMPANION_BODY_BYTES, MAX_MCP_BODY_BYTES):
        unit, divisor = ("MiB", 1024 * 1024) if limit >= 1024 * 1024 else ("KiB", 1024)
        assert limit % divisor == 0
        assert f"{limit // divisor}{unit}" in sizes
    # Caddy reads KB/MB as decimal (1000-based), which would undercut the API's binary ceilings.
    assert not {"16KB", "256KB", "1MB"} & sizes


@pytest.mark.asyncio
async def test_a_body_within_the_declared_ceiling_passes_and_get_is_unbounded() -> None:
    middleware, recorder = build()
    await call(
        middleware,
        recorder,
        "/mcp/token",
        method="POST",
        headers=[(b"content-length", str(MAX_DEFAULT_BODY_BYTES).encode())],
    )
    assert recorder.status == 204
    recorder.reset()
    recorder.sent = []
    await call(
        middleware,
        recorder,
        "/mcp/authorize",
        method="GET",
        headers=[(b"content-length", str(MAX_MCP_BODY_BYTES * 10).encode())],
    )
    assert recorder.status == 204


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks", [False, True])
async def test_companion_routes_get_an_ingress_ceiling_too(chunks: bool) -> None:
    recorder = Recorder()
    middleware = RequestBodyLimitMiddleware(recorder.app, NoopTelemetryAdapter(), companion=True)
    path = "/companion/v1/journal/entries"
    if chunks:
        await call(
            middleware,
            recorder,
            path,
            method="POST",
            deliver=chunked(b"x" * MAX_COMPANION_BODY_BYTES, b"x"),
        )
    else:
        headers = [(b"content-length", str(MAX_COMPANION_BODY_BYTES + 1).encode())]
        await call(middleware, recorder, path, method="POST", headers=headers)
    assert not recorder.reached
    assert recorder.status == 413
    assert recorder.body["code"] == "payload_too_large"


@pytest.mark.asyncio
async def test_a_refused_body_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    middleware, recorder = build()
    secret = b"client_secret=hunter2-" + b"x" * MAX_DEFAULT_BODY_BYTES
    with caplog.at_level("DEBUG"):
        await call(middleware, recorder, "/mcp/token", method="POST", deliver=chunked(secret))
    assert recorder.status == 413
    assert "hunter2" not in caplog.text
    assert "hunter2" not in json.dumps(recorder.body)


def dripping(*, first: bytes = b"x", pause: float = 0.2) -> Any:
    """A `receive` that sends one byte, then stalls for `pause` seconds before every next one."""

    async def deliver() -> dict[str, Any]:
        await asyncio.sleep(pause)  # Kept: a stalled client is what the body budget refuses
        return {"type": "http.request", "body": first, "more_body": True}

    return deliver


def timed(
    *, body: float = 0.05, oauth: float = 0.05, companion: bool = False
) -> tuple[RequestBodyLimitMiddleware, Recorder]:
    recorder = Recorder()
    middleware = RequestBodyLimitMiddleware(
        recorder.app,
        NoopTelemetryAdapter(),
        companion=companion,
        oauth_surface=True,
        body_read_timeout=body,
        oauth_body_read_timeout=oauth,
    )
    return middleware, recorder


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "declared"),
    [
        ("POST", "/mcp/", False),
        ("POST", "/mcp/", True),
        ("POST", "/mcp/token", False),
        ("POST", "/mcp/token", True),
        ("POST", "/mcp/register", True),
    ],
)
async def test_a_body_that_drips_in_too_slowly_is_408_and_never_reaches_the_app(
    method: str, path: str, declared: bool
) -> None:
    middleware, recorder = timed()
    headers = [(b"content-length", b"100")] if declared else []
    await call(middleware, recorder, path, method=method, headers=headers, deliver=dripping())
    assert not recorder.reached
    assert recorder.status == 408
    assert recorder.body["code"] == "request_timeout"
    assert recorder.body["correlation_id"] == "corr-unit"
    assert set(recorder.body) == {"type", "title", "status", "code", "correlation_id"}


@pytest.mark.asyncio
async def test_a_slow_companion_body_is_408_too() -> None:
    middleware, recorder = timed(companion=True)
    headers = [(b"content-length", b"100")]
    await call(
        middleware,
        recorder,
        "/companion/v1/journal/entries",
        method="POST",
        headers=headers,
        deliver=dripping(),
    )
    assert not recorder.reached
    assert recorder.status == 408


@pytest.mark.asyncio
async def test_the_oauth_forms_get_the_shorter_budget() -> None:
    # 0.3 s of body time: inside the MCP budget (1 s) but past the OAuth one (0.1 s).
    async def deliver() -> dict[str, Any]:
        await asyncio.sleep(0.3)  # Kept: a slow body is what the OAuth budget refuses
        return {"type": "http.request", "body": b"ok", "more_body": False}

    middleware, recorder = timed(body=1.0, oauth=0.1)
    await call(middleware, recorder, "/mcp/token", method="POST", deliver=deliver)
    assert recorder.status == 408
    assert not recorder.reached

    middleware, recorder = timed(body=1.0, oauth=0.1)
    await call(middleware, recorder, "/mcp/", method="POST", deliver=deliver)
    assert recorder.status == 204
    assert recorder.reached


@pytest.mark.asyncio
async def test_a_timed_out_body_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    middleware, recorder = timed()
    secret = b"client_secret=hunter2"
    with caplog.at_level("DEBUG"):
        await call(
            middleware, recorder, "/mcp/token", method="POST", deliver=dripping(first=secret)
        )
    assert recorder.status == 408
    assert "hunter2" not in caplog.text
    assert "hunter2" not in json.dumps(recorder.body)


@pytest.mark.asyncio
async def test_a_declared_body_within_budget_reaches_the_app_intact() -> None:
    middleware, _recorder = timed(body=1.0, oauth=1.0)
    seen: list[bytes] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append((await receive())["body"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware.app = app
    recorder = Recorder()
    await call(
        middleware,
        recorder,
        "/mcp/token",
        method="POST",
        headers=[(b"content-length", b"7")],
        deliver=chunked(b"a=1", b"&b=2"),
    )
    assert recorder.status == 204
    assert seen == [b"a=1&b=2"]


def body_of(size: int) -> Any:
    """A body of `size` bytes in 64 KiB chunks, as a client that sends no Content-Length would."""

    remaining = size

    async def deliver() -> dict[str, Any]:
        nonlocal remaining
        part = min(64 * 1024, remaining)
        remaining -= part
        return {"type": "http.request", "body": b"x" * part, "more_body": remaining > 0}

    return deliver


# --- the real application, in every auth mode --------------------------------------------------


def auth_mode_settings(mode: str, tmp_path: Path) -> Settings:
    """Settings for each way the MCP endpoint can be run; short budgets keep the tests quick."""

    if mode == "oauth":
        return Settings(
            environment="test",
            cursor_signing_secret="session-secret-for-tests-only-123456",
            token_pepper="token-pepper-for-tests-only-12345678",
            body_read_timeout_seconds=0.2,
            oauth_body_read_timeout_seconds=0.05,
            mcp_auth_mode="github_oauth",
            mcp_public_base_url="https://box.tail1234.ts.net",
            mcp_oauth_github_client_id="Ov23liClientId",
            mcp_oauth_github_client_secret=SecretStr("github-client-secret-sentinel-0123456789"),
            mcp_oauth_signing_key=SecretStr("mcp-oauth-signing-key-sentinel-0123456789-abc"),
            mcp_oauth_storage_dir=tmp_path / "oauth-state",
            mcp_oauth_allowed_identities="github:4242424=018af000-0000-7000-8000-000000000001",
            mcp_oauth_scopes="projects:read,tasks:read,tasks:write",
            companion_enabled=True,
        )
    return Settings(
        environment="test",
        cursor_signing_secret="session-secret-for-tests-only-123456",
        token_pepper="token-pepper-for-tests-only-12345678",
        body_read_timeout_seconds=0.2,
        oauth_body_read_timeout_seconds=0.05,
        mcp_auth_mode="pat",
        companion_enabled=mode == "pat+companion",
    )


AUTH_MODES = ["pat", "pat+companion", "oauth"]


async def through_the_app(
    settings: Settings, path: str, method: str, *, deliver: Any, headers: list[tuple[bytes, bytes]]
) -> Recorder:
    """One request into the composed ASGI stack, carrying no credential at all."""

    recorder = Recorder()
    await create_app(settings)(http_scope(path, method, headers), deliver, recorder.send)
    return recorder


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", AUTH_MODES)
@pytest.mark.parametrize("declared", [True, False])
async def test_the_mcp_endpoint_has_the_same_body_ceiling_in_every_auth_mode(
    mode: str, declared: bool, tmp_path: Path
) -> None:
    oversize = MAX_MCP_BODY_BYTES + 1
    result = await through_the_app(
        auth_mode_settings(mode, tmp_path),
        "/mcp/",
        "POST",
        deliver=body_of(oversize),
        headers=[(b"content-length", str(oversize).encode())] if declared else [],
    )
    assert result.status == 413
    assert result.body["code"] == "payload_too_large"
    assert result.body["correlation_id"] not in {"corr-unit", "unknown"}  # the real one


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", AUTH_MODES)
async def test_a_path_without_its_own_ceiling_gets_the_small_default_in_every_auth_mode(
    mode: str, tmp_path: Path
) -> None:
    # `/health/live` is no body route: PAT has no allowlist in front of it (OAuth would 404 it),
    # and either way an oversized body must be refused before it is buffered.
    result = await through_the_app(
        auth_mode_settings(mode, tmp_path),
        "/mcp/token" if mode == "oauth" else "/health/live",
        "POST",
        deliver=body_of(MAX_DEFAULT_BODY_BYTES + 1),
        headers=[],
    )
    assert result.status == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pat+companion", "oauth"])
async def test_the_companion_routes_keep_their_ceiling_where_they_are_enabled(
    mode: str, tmp_path: Path
) -> None:
    result = await through_the_app(
        auth_mode_settings(mode, tmp_path),
        "/companion/v1/journal/entries",
        "POST",
        deliver=body_of(MAX_COMPANION_BODY_BYTES + 1),
        headers=[],
    )
    assert result.status == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", AUTH_MODES)
@pytest.mark.parametrize("declared", [True, False])
async def test_a_dripped_mcp_body_is_408_in_every_auth_mode(
    mode: str, declared: bool, tmp_path: Path
) -> None:
    result = await through_the_app(
        auth_mode_settings(mode, tmp_path),
        "/mcp/",
        "POST",
        deliver=dripping(pause=0.5),
        headers=[(b"content-length", b"100")] if declared else [],
    )
    assert result.status == 408
    assert result.body["code"] == "request_timeout"
    assert set(result.body) == {"type", "title", "status", "code", "correlation_id"}


@pytest.mark.asyncio
async def test_the_shorter_oauth_form_budget_applies_only_where_the_oauth_flow_is_served(
    tmp_path: Path,
) -> None:
    async def slow_form() -> dict[str, Any]:
        await asyncio.sleep(0.1)  # past the 0.05 s OAuth budget, inside the 0.2 s general one
        return {"type": "http.request", "body": b"ok", "more_body": False}

    oauth = await through_the_app(
        auth_mode_settings("oauth", tmp_path), "/mcp/token", "POST", deliver=slow_form, headers=[]
    )
    assert oauth.status == 408
    pat = await through_the_app(
        auth_mode_settings("pat", tmp_path), "/health/live", "POST", deliver=slow_form, headers=[]
    )
    assert pat.status != 408


@pytest.fixture
def http_logs() -> Iterator[list[logging.LogRecord]]:
    """Records of the ingress logger, taken from the logger itself (it does not propagate)."""

    records: list[logging.LogRecord] = []
    handler = logging.Handler(logging.DEBUG)
    handler.emit = records.append  # type: ignore[method-assign]
    logger = logging.getLogger("sidekick.http")
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", AUTH_MODES)
async def test_a_refused_body_in_the_app_is_not_logged(
    mode: str, tmp_path: Path, http_logs: list[logging.LogRecord]
) -> None:
    secret = b"client_secret=hunter2-" + b"x" * MAX_MCP_BODY_BYTES
    result = await through_the_app(
        auth_mode_settings(mode, tmp_path),
        "/mcp/",
        "POST",
        deliver=chunked(secret),
        headers=[],
    )
    assert result.status == 413
    refusals = [r for r in http_logs if r.getMessage() == "request_body_refused"]
    assert len(refusals) == 1
    assert refusals[0].__dict__["http_status"] == 413
    everything = json.dumps([r.__dict__ for r in http_logs], default=str) + json.dumps(result.body)
    assert "hunter2" not in everything


@pytest.mark.asyncio
async def test_a_body_within_the_ceiling_passes_through_the_pat_stack_to_the_routes(
    tmp_path: Path,
) -> None:
    result = await through_the_app(
        auth_mode_settings("pat", tmp_path),
        "/health/live",
        "POST",
        deliver=chunked(b"{}"),
        headers=[(b"content-length", b"2")],
    )
    assert result.status == 405  # reached routing: the ceiling did not refuse it


# --- the global cap on bodies being buffered ----------------------------------------------------


def held(release: asyncio.Event) -> Any:
    """A `receive` whose body arrives only once `release` is set (a slow client)."""

    async def deliver() -> dict[str, Any]:
        await release.wait()
        return {"type": "http.request", "body": b"ok", "more_body": False}

    return deliver


@pytest.mark.asyncio
async def test_parallel_slow_bodies_fill_the_buffering_cap_and_the_next_is_503() -> None:
    recorder = Recorder()
    middleware = RequestBodyLimitMiddleware(
        recorder.app, NoopTelemetryAdapter(), body_read_timeout=5, max_buffered_requests=2
    )
    release = asyncio.Event()
    slow = [
        asyncio.create_task(middleware(http_scope("/mcp/", "POST"), held(release), Recorder().send))
        for _ in range(2)
    ]
    await asyncio.sleep(0.05)  # Kept: lets both slow bodies start buffering

    refused = Recorder()
    await middleware(http_scope("/mcp/", "POST"), receive, refused.send)
    assert refused.status == 503
    assert refused.body["code"] == "service_busy"
    assert set(refused.body) == {"type", "title", "status", "code", "correlation_id"}
    assert dict(refused.sent[0]["headers"])[b"retry-after"] == b"1"
    assert not recorder.reached

    release.set()
    await asyncio.gather(*slow)
    assert recorder.reached
    # The slots are free again.
    recorder.reset()
    await call(middleware, recorder, "/mcp/", method="POST")
    assert recorder.status == 204


@pytest.mark.asyncio
async def test_a_timed_out_or_disconnected_body_frees_its_buffering_slot() -> None:
    recorder = Recorder()
    middleware = RequestBodyLimitMiddleware(
        recorder.app, NoopTelemetryAdapter(), body_read_timeout=0.05, max_buffered_requests=1
    )
    for _ in range(3):
        slow = Recorder()
        await middleware(http_scope("/mcp/", "POST"), dripping(), slow.send)
        assert slow.status == 408
    gone = Recorder()
    await middleware(http_scope("/mcp/", "POST"), chunked(b"a"), gone.send)
    await call(middleware, recorder, "/mcp/", method="POST")
    assert recorder.status == 204


@pytest.mark.asyncio
async def test_bodyless_methods_never_take_a_buffering_slot() -> None:
    recorder = Recorder()
    middleware = RequestBodyLimitMiddleware(
        recorder.app, NoopTelemetryAdapter(), body_read_timeout=5, max_buffered_requests=1
    )
    release = asyncio.Event()
    slow = asyncio.create_task(
        middleware(http_scope("/mcp/", "POST"), held(release), Recorder().send)
    )
    await asyncio.sleep(0.05)  # Kept: lets the slow body start buffering
    await call(middleware, recorder, "/mcp/", method="GET")
    assert recorder.status == 204
    release.set()
    await slow


@pytest.mark.asyncio
async def test_the_buffering_cap_comes_from_settings_and_has_a_safe_default() -> None:
    assert Settings(_env_file=None).max_buffered_requests == 32
    with pytest.raises(ValueError, match="max_buffered_requests"):
        Settings(_env_file=None, max_buffered_requests=0)

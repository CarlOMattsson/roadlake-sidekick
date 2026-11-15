"""The webhook entrance's rules without a framework, a database or a clock: token validation, the
scope-to-permission mapping, the per-token rate limit and the public surface and body cap."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from sidekick.api.body_limits import (
    MAX_COMPANION_BODY_BYTES,
    MAX_WEBHOOK_BODY_BYTES,
    RequestBodyLimitMiddleware,
    body_limit,
)
from sidekick.api.companion import CompanionProblem
from sidekick.api.public_surface import (
    WEBHOOK_ROUTES,
    PublicSurfaceAllowlistMiddleware,
    is_webhook_route,
)
from sidekick.api.webhooks import WebhookRateLimiter
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.observability import NoopTelemetryAdapter
from sidekick.webhooks.operations import (
    OPERATIONS,
    SHOPPING_ITEM_ADD,
    TASK_CREATE,
    WebhookScopeMissing,
    operation_actor,
)
from sidekick.webhooks.tokens import (
    MAX_LIFETIME_DAYS,
    MAX_RATE_LIMIT_PER_MINUTE,
    WEBHOOK_SCOPES,
    WEBHOOK_SHOPPING_ADD,
    WEBHOOK_TASKS_CREATE,
    WebhookCredential,
    validate_new_token,
)
from tests.asgi_ingress import Recorder, call


def credential(*scopes: str, rate: int = 30) -> WebhookCredential:
    return WebhookCredential(uuid4(), uuid4(), frozenset(scopes), rate)


def test_a_token_needs_a_clean_label_known_scopes_and_bounded_numbers() -> None:
    label, scopes = validate_new_token("  Home Assistant ", [WEBHOOK_TASKS_CREATE], 30, 10)
    assert (label, scopes) == ("Home Assistant", frozenset({WEBHOOK_TASKS_CREATE}))
    for label, chosen, days, rate in [
        ("", [WEBHOOK_TASKS_CREATE], 30, 10),
        ("x" * 121, [WEBHOOK_TASKS_CREATE], 30, 10),
        ("bad\nlabel", [WEBHOOK_TASKS_CREATE], 30, 10),
        ("ok", [], 30, 10),
        ("ok", ["tasks:write"], 30, 10),
        ("ok", ["companion:tasks:read"], 30, 10),
        ("ok", [WEBHOOK_TASKS_CREATE, "journal:write"], 30, 10),
        ("ok", [WEBHOOK_TASKS_CREATE], 0, 10),
        ("ok", [WEBHOOK_TASKS_CREATE], MAX_LIFETIME_DAYS + 1, 10),
        ("ok", [WEBHOOK_TASKS_CREATE], 30, 0),
        ("ok", [WEBHOOK_TASKS_CREATE], 30, MAX_RATE_LIMIT_PER_MINUTE + 1),
    ]:
        with pytest.raises(InvalidInputError):
            validate_new_token(label, chosen, days, rate)


def test_each_scope_reaches_one_operation_with_only_its_application_scopes() -> None:
    assert {operation.scope for operation in OPERATIONS} == WEBHOOK_SCOPES
    shopping = operation_actor(credential(WEBHOOK_SHOPPING_ADD), SHOPPING_ITEM_ADD)
    task = operation_actor(credential(WEBHOOK_TASKS_CREATE), TASK_CREATE)
    assert shopping.scopes == {"shopping:read", "shopping:write"}
    assert task.scopes == {"tasks:write"}
    # Neither can read a Task or an item, change or remove a record, or touch another room.
    assert not {"tasks:read", "contacts:read", "journal:write"} & (shopping.scopes | task.scopes)


def test_an_operation_refuses_a_token_without_its_scope_and_the_owner_is_the_tokens() -> None:
    held = credential(WEBHOOK_SHOPPING_ADD)
    with pytest.raises(WebhookScopeMissing):
        operation_actor(held, TASK_CREATE)
    assert operation_actor(held, SHOPPING_ITEM_ADD).user_id == held.user_id


def test_the_rate_limit_is_the_tokens_own_budget_per_minute_and_refills() -> None:
    now = [0.0]
    limiter = WebhookRateLimiter(lambda: now[0])
    slow, fast = credential(WEBHOOK_TASKS_CREATE, rate=2), credential(WEBHOOK_TASKS_CREATE, rate=60)
    limiter.check(slow)
    limiter.check(slow)
    with pytest.raises(CompanionProblem) as refused:
        limiter.check(slow)
    assert (refused.value.status, refused.value.code) == (429, "rate_limited")
    assert refused.value.headers is not None
    assert int(refused.value.headers["Retry-After"]) >= 1
    for _ in range(60):
        limiter.check(fast)  # another token's budget is untouched
    now[0] += 30  # a rate of 2 a minute refills one request in 30 s
    limiter.check(slow)
    with pytest.raises(CompanionProblem):
        limiter.check(slow)


def test_the_webhook_surface_is_exactly_two_post_paths() -> None:
    assert {
        ("POST", "/webhooks/v1/shopping-items"),
        ("POST", "/webhooks/v1/tasks"),
    } == WEBHOOK_ROUTES
    assert is_webhook_route("POST", "/webhooks/v1/tasks")
    for method, path in [
        ("GET", "/webhooks/v1/tasks"),
        ("PUT", "/webhooks/v1/tasks"),
        ("POST", "/webhooks/v1/tasks/"),
        ("POST", "/webhooks/v1/tasks/x"),
        ("POST", "/webhooks/v1"),
        ("POST", "/webhooks/v2/tasks"),
        ("POST", "/WEBHOOKS/v1/tasks"),
        ("POST", "/webhooks/v1/../mcp/"),
    ]:
        assert not is_webhook_route(method, path), (method, path)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_a_public_tunnel_answers_the_webhook_paths_only_when_they_are_switched_on(
    enabled: bool,
) -> None:
    recorder = Recorder()
    middleware = PublicSurfaceAllowlistMiddleware(
        recorder.app, NoopTelemetryAdapter(), webhooks=enabled
    )
    await call(middleware, recorder, "/webhooks/v1/tasks", method="POST")
    assert recorder.reached is enabled
    assert recorder.status == (204 if enabled else 404)
    recorder.reset()
    await call(middleware, recorder, "/webhooks/v1/tasks", method="GET")
    assert not recorder.reached
    assert recorder.status == 404


def test_the_webhook_body_cap_is_small_and_only_for_the_webhook_paths() -> None:
    assert body_limit("/webhooks/v1/tasks", companion=False, webhook=True) == MAX_WEBHOOK_BODY_BYTES
    assert MAX_WEBHOOK_BODY_BYTES < MAX_COMPANION_BODY_BYTES
    assert body_limit("/webhooks/v1/tasks", companion=False) != MAX_WEBHOOK_BODY_BYTES


@pytest.mark.asyncio
async def test_a_declared_oversized_webhook_body_is_refused_before_the_application() -> None:
    recorder = Recorder()
    middleware = RequestBodyLimitMiddleware(recorder.app, NoopTelemetryAdapter(), webhooks=True)
    too_big = str(MAX_WEBHOOK_BODY_BYTES + 1).encode()
    await call(
        middleware,
        recorder,
        "/webhooks/v1/tasks",
        method="POST",
        headers=[(b"content-length", too_big)],
    )
    assert not recorder.reached
    assert recorder.status == 413


def test_the_caddy_example_forwards_exactly_the_webhook_routes_as_posts_with_a_small_body() -> None:
    caddy = (Path(__file__).resolve().parents[3] / "deploy/selfhost/Caddyfile.example").read_text(
        encoding="utf-8"
    )
    matcher = caddy.split("@webhooks {", 1)[1].split("}", 1)[0]
    path_line = re.search(r"^\s*path (.+)$", matcher, re.M)
    assert path_line is not None
    assert "method POST" in matcher
    assert set(path_line.group(1).split()) == {path for _method, path in WEBHOOK_ROUTES}
    handler = caddy.split("handle @webhooks {", 1)[1].split("reverse_proxy", 1)[0]
    assert f"max_size {MAX_WEBHOOK_BODY_BYTES // 1024}KB" in handler

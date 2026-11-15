"""The operator commands for webhook tokens: explicit scopes, a token shown once, and a revocation
that stops the token at once."""

from __future__ import annotations

import io
import json
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from sidekick.shared.persistence.models import AuditEventRow, WebhookTokenRow
from sidekick.webhooks.cli import run
from tests.support.webhooks import owner, webhook_app


def invoke(app: Any, argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    code = run(argv, app.state.container.webhook_tokens, out)
    return code, out.getvalue()


@pytest.mark.integration
def test_create_requires_an_explicit_known_scope(capsys: pytest.CaptureFixture[str]) -> None:
    app = webhook_app()
    user_id = owner(app)
    for argv in (
        ["create", "--label", "HA"],
        ["create", "--label", "HA", "--scope", "tasks:write"],
        ["create", "--label", "HA", "--scope", "companion:push"],
        ["create", "--label", "HA", "--scope", "webhook:tasks:create", "--expires-in-days", "0"],
        ["create", "--label", "HA", "--scope", "webhook:tasks:create", "--rate-limit", "601"],
    ):
        with pytest.raises(SystemExit) as exit_info:
            invoke(app, argv)
        assert exit_info.value.code == 2, argv
        capsys.readouterr()
    assert app.state.container.webhook_tokens.list_tokens(user_id) == []


@pytest.mark.integration
def test_a_created_token_is_printed_once_and_only_its_digest_and_prefix_are_stored() -> None:
    app = webhook_app()
    user_id = owner(app)
    code, output = invoke(
        app,
        ["create", "--label", "Tasker", "--scope", "webhook:tasks:create", "--rate-limit", "5"],
    )
    issued = json.loads(output)
    assert code == 0
    assert issued["token"].startswith("rsw_")
    assert (issued["scopes"], issued["rate_limit_per_minute"]) == (["webhook:tasks:create"], 5)
    assert issued["token_prefix"] == issued["token"][:10]
    container = app.state.container
    assert container.webhook_tokens.verify(issued["token"]) is not None
    with container.session_factory() as session:
        row = session.scalars(select(WebhookTokenRow)).one()
        events = list(
            session.scalars(select(AuditEventRow.event).where(AuditEventRow.actor_id == user_id))
        )
    assert issued["token"] not in {value for value in vars(row).values() if isinstance(value, str)}
    assert row.token_digest == container.auth.digest(issued["token"])
    assert "webhook.token_created" in events

    _code, listing = invoke(app, ["list"])
    listed = json.loads(listing)
    assert [entry["id"] for entry in listed] == [issued["id"]]
    assert "token" not in listed[0]
    assert issued["token"] not in listing


@pytest.mark.integration
def test_revoke_stops_the_token_is_idempotent_and_only_reaches_the_owners_own_tokens() -> None:
    app = webhook_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    container = app.state.container
    issued = json.loads(
        invoke(
            app,
            [
                "create",
                "--label",
                "HA",
                "--scope",
                "webhook:tasks:create",
                "--user-id",
                str(user_id),
            ],
        )[1]
    )
    with pytest.raises(SystemExit):
        invoke(app, ["revoke", "--token-id", issued["id"], "--user-id", str(stranger)])
    assert container.webhook_tokens.verify(issued["token"]) is not None
    for _ in range(2):
        code, output = invoke(
            app, ["revoke", "--token-id", issued["id"], "--user-id", str(user_id)]
        )
        assert (code, json.loads(output)) == (0, {"revoked": issued["id"]})
    assert container.webhook_tokens.verify(issued["token"]) is None
    with container.session_factory() as session:
        revoked_events = list(
            session.scalars(
                select(AuditEventRow.event).where(AuditEventRow.event == "webhook.token_revoked")
            )
        )
    assert revoked_events == ["webhook.token_revoked"]
    with pytest.raises(SystemExit):
        invoke(app, ["revoke", "--token-id", str(uuid4()), "--user-id", str(user_id)])


@pytest.mark.integration
def test_without_a_user_id_the_commands_need_exactly_one_active_owner(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = webhook_app()
    owner(app, "first")
    only = ["create", "--label", "HA", "--scope", "webhook:tasks:create"]
    assert invoke(app, only)[0] == 0
    owner(app, "second")
    with pytest.raises(SystemExit) as exit_info:
        invoke(app, only)
    assert exit_info.value.code == 2
    assert "not exactly one active owner" in capsys.readouterr().err

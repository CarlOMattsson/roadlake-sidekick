"""The operator CLI never grants device rights by default (ADR-005)."""

from __future__ import annotations

import io
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from sidekick.companion import cli
from sidekick.companion.cli import run
from sidekick.companion.persistence import CompanionDeviceStore
from sidekick.shared.persistence.models import AuditEventRow
from tests.support.companion import bearer, companion_app, devices, paired_token


def invoke(app, argv: list[str]) -> tuple[int, str]:  # type: ignore[no-untyped-def]
    container = app.state.container
    out, notice = io.StringIO(), io.StringIO()
    code = run(argv, CompanionDeviceStore(container.session_factory), container.auth, out, notice)
    return code, notice.getvalue() + "\x00" + out.getvalue()


def _grant_reasons(app: FastAPI, user_id: UUID) -> list[str]:
    container: Any = app.state.container
    with container.session_factory() as session:
        rows: list[str | None] = list(
            session.scalars(
                select(AuditEventRow.reason).where(
                    AuditEventRow.actor_id == user_id,
                    AuditEventRow.event == "companion.device_scopes_granted",
                )
            )
        )
    return sorted(reason for reason in rows if reason is not None)


@pytest.mark.integration
def test_pair_without_scope_is_an_error_and_issues_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = companion_app()
    app.state.container.auth.provision_user("owner", "Owner")
    with pytest.raises(SystemExit) as exit_info:
        invoke(app, ["pair", "--label", "Samsung"])
    assert exit_info.value.code == 2
    assert "explicit --scope" in capsys.readouterr().err


@pytest.mark.integration
def test_pair_with_an_unknown_scope_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    app = companion_app()
    app.state.container.auth.provision_user("owner", "Owner")
    for scope in ("tasks:write", "mcp:tasks:read", "companion:admin"):
        with pytest.raises(SystemExit) as exit_info:
            invoke(app, ["pair", "--label", "Samsung", "--scope", scope])
        assert exit_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.integration
def test_pair_with_a_scope_shows_the_rights_before_the_secret() -> None:
    app = companion_app()
    app.state.container.auth.provision_user("owner", "Owner")
    code, output = invoke(
        app, ["pair", "--label", "Samsung", "--scope", "companion:tasks:read", "--device-days", "7"]
    )
    assert code == 0
    shown, printed = output.split("\x00")
    assert "rspair_" not in shown
    assert "rättigheter" in shown
    assert "companion:tasks:read" in shown
    assert "läsa uppgifter" in shown
    assert "bocka av" not in shown
    assert "7 dagar" in shown
    assert "10 minuter" in shown
    ticket = json.loads(printed)
    assert ticket["scopes"] == ["companion:tasks:read"]
    assert "pairing_link" not in ticket
    assert "pairing_check" not in ticket
    assert "Kontrollkod" not in shown


@pytest.mark.integration
def test_pair_with_a_server_url_prints_a_link_that_fills_in_the_app() -> None:
    app = companion_app()
    app.state.container.auth.provision_user("owner", "Owner")
    code, output = invoke(
        app,
        [
            "pair",
            "--label",
            "Samsung",
            "--preset",
            "app",
            "--server-url",
            "https://sidekick.example",
        ],
    )
    assert code == 0
    shown, printed = output.split("\x00")
    ticket = json.loads(printed)
    assert ticket["pairing_link"] == cli.pairing_link(
        "https://sidekick.example", ticket["pairing_secret"]
    )
    assert "rspair_" not in shown
    check = cli.pairing_check(ticket["pairing_secret"])
    assert ticket["pairing_check"] == check
    assert f"Kontrollkod: {check}" in shown


@pytest.mark.integration
def test_the_app_preset_grants_read_and_complete_only_when_written() -> None:
    app = companion_app()
    app.state.container.auth.provision_user("owner", "Owner")
    code, output = invoke(app, ["pair", "--label", "Samsung", "--preset", "app"])
    assert code == 0
    shown, printed = output.split("\x00")
    ticket = json.loads(printed)
    assert ticket["scopes"] == [
        "companion:journal:read",
        "companion:journal:write",
        "companion:license",
        "companion:push",
        "companion:shopping:read",
        "companion:shopping:write",
        "companion:tasks:complete",
        "companion:tasks:read",
    ]
    assert set(cli.PRESETS["app"]) == set(ticket["scopes"])
    assert "bocka av" in shown
    assert "inköpslistor" in shown and "dagboksinlägg" in shown


@pytest.mark.integration
def test_grant_adds_rights_to_a_paired_device_and_never_removes_any() -> None:
    app = companion_app()
    user_id = app.state.container.auth.provision_user("owner", "Owner")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=["companion:tasks:read"])
        before = client.get("/companion/v1/shopping/lists", headers=bearer(token))
        assert before.status_code == 403
        device = devices(app).list_devices(user_id)[0]
        code, output = invoke(
            app, ["grant", "--device-id", str(device.id), "--scope", "companion:shopping:read"]
        )
        assert code == 0
        shown, printed = output.split("\x00")
        granted = json.loads(printed)
        assert granted["scopes"] == ["companion:shopping:read", "companion:tasks:read"]
        assert "rättigheter" in shown
        assert "companion:shopping:read: läsa inköpslistor" in shown
        assert "companion:tasks:read: läsa uppgifter" in shown
        assert "companion:shopping:write" not in shown
        assert "rspair_" not in shown and "cht_" not in shown
        # The audit trail names only the scope that was really added.
        assert _grant_reasons(app, user_id) == ["companion:shopping:read"]
        # The same credential works at once; its other rights and its expiry are untouched.
        assert client.get("/companion/v1/shopping/lists", headers=bearer(token)).status_code == 200
        assert granted["expires_at"] == device.expires_at.isoformat()
        # The preset adds the rest; granting again is harmless.
        assert invoke(app, ["grant", "--device-id", str(device.id), "--preset", "app"])[0] == 0
        assert set(devices(app).list_devices(user_id)[0].scopes) == set(cli.PRESETS["app"])
        assert _grant_reasons(app, user_id) == sorted(
            [
                "companion:shopping:read",
                "companion:journal:read",
                "companion:journal:write",
                "companion:license",
                "companion:push",
                "companion:shopping:write",
                "companion:tasks:complete",
            ]
        )
        # Granting what the device already holds adds a row that names nothing.
        assert invoke(app, ["grant", "--device-id", str(device.id), "--preset", "app"])[0] == 0
        assert "no_change" in _grant_reasons(app, user_id)


@pytest.mark.integration
def test_grant_refuses_an_unknown_device_and_an_empty_choice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = companion_app()
    app.state.container.auth.provision_user("owner", "Owner")
    with pytest.raises(SystemExit):
        invoke(app, ["grant", "--device-id", str(uuid4()), "--preset", "app"])
    assert "device not found" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        invoke(app, ["grant", "--device-id", str(uuid4())])
    assert "explicit --scope" in capsys.readouterr().err


@pytest.mark.integration
def test_grant_refuses_a_revoked_device() -> None:
    app = companion_app()
    user_id = app.state.container.auth.provision_user("owner", "Owner")
    with TestClient(app) as client:
        paired_token(client, app, user_id, scopes=["companion:tasks:read"])
        device = devices(app).list_devices(user_id)[0]
        assert devices(app).revoke_device(user_id, device.id)
        with pytest.raises(SystemExit):
            invoke(app, ["grant", "--device-id", str(device.id), "--preset", "app"])
        assert devices(app).list_devices(user_id)[0].scopes == ("companion:tasks:read",)


@pytest.mark.integration
def test_the_rights_notice_follows_the_app_language() -> None:
    app = companion_app()
    app.state.container.auth.provision_user("owner", "Owner")
    container = app.state.container
    out, notice = io.StringIO(), io.StringIO()
    argv = ["pair", "--label", "Samsung", "--scope", "companion:tasks:read", "--device-days", "7"]
    code = run(
        argv,
        CompanionDeviceStore(container.session_factory),
        container.auth,
        out,
        notice,
        locale="en",
    )
    assert code == 0
    shown = notice.getvalue()
    assert 'Device "Samsung" gets the following permissions:' in shown
    assert "read tasks, steps, projects, and today\u2019s agenda" in shown
    assert "valid for 7 days" in shown and "10 minutes" in shown
    assert "rättigheter" not in shown and "rspair_" not in shown
    assert json.loads(out.getvalue())["scopes"] == ["companion:tasks:read"]

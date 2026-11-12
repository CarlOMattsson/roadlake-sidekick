"""The companion operator command (ADR-005; D-077, D-078)."""

from __future__ import annotations

import io
import json
from datetime import timedelta
from uuid import UUID

import pytest

from sidekick.companion.cli import PRESETS, run
from sidekick.companion.persistence import CompanionDeviceStore
from sidekick.companion.service import CompanionDeviceService
from sidekick.shared.auth import AuthService
from sidekick.shared.types import utc_now
from tests.db import database_factory

PEPPER = "token-pepper-for-tests-only-12345678"


@pytest.mark.integration
def test_operator_command_pairs_lists_and_revokes_without_printing_a_device_token() -> None:
    factory = database_factory()
    auth = AuthService(factory, PEPPER)
    user_id = auth.provision_user("owner", "Owner")

    out = io.StringIO()
    pair = ["pair", "--label", "Samsung", "--preset", "app", "--device-days", "7"]
    assert run(pair, factory, auth, out, io.StringIO()) == 0
    ticket = json.loads(out.getvalue())
    assert ticket["pairing_secret"].startswith("rspair_")
    assert ticket["device_lifetime_days"] == 7
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
    assert sorted(PRESETS["app"]) == ticket["scopes"]

    paired = CompanionDeviceService(CompanionDeviceStore(factory), auth).exchange(
        ticket["pairing_secret"]
    )
    assert paired is not None
    assert paired.device.expires_at - utc_now() <= timedelta(days=7)

    listing = io.StringIO()
    run(["list", "--user-id", str(user_id)], factory, auth, listing)
    devices = json.loads(listing.getvalue())
    assert [item["label"] for item in devices] == ["Samsung"]
    assert paired.token not in listing.getvalue()
    assert ticket["pairing_secret"] not in listing.getvalue()

    revoked = io.StringIO()
    run(["revoke", "--device-id", devices[0]["id"]], factory, auth, revoked)
    assert json.loads(revoked.getvalue()) == {"revoked": devices[0]["id"]}
    assert auth.verify_companion_token(paired.token) is None

    read_only = io.StringIO()
    run(
        ["pair", "--label", "Klocka", "--scope", "companion:tasks:read"],
        factory,
        auth,
        read_only,
        io.StringIO(),
    )
    assert json.loads(read_only.getvalue())["scopes"] == ["companion:tasks:read"]

    with pytest.raises(SystemExit):
        run(["revoke", "--device-id", str(UUID(int=7))], factory, auth, io.StringIO())
    auth.provision_user("second", "Second")
    with pytest.raises(SystemExit):
        run(["list"], factory, auth, io.StringIO())

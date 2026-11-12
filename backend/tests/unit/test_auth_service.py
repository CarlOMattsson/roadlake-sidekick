"""Operator provisioning, personal-token scopes and the admin commands."""

import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from sidekick import composition
from sidekick.admin import cli as auth_cli
from sidekick.shared.auth import (
    ALL_SCOPES,
    MCP_SCOPES,
    OPT_IN_SCOPES,
    TOKEN_SCOPES,
    AuthService,
)
from sidekick.shared.db_timeouts import DatabaseTimeouts
from sidekick.shared.persistence.models import MemorySettingsRow, PersonalAccessTokenRow, UserRow
from tests.db import database_factory
from tests.support.settings import make_settings

TOKEN_USER_ID = UUID("018af000-0000-7000-8000-000000000001")


@pytest.mark.integration
def test_ensure_user_is_idempotent_and_keeps_the_existing_user() -> None:
    auth = AuthService(database_factory(), "desktop-pepper-" * 4)
    first_id, first_created = auth.ensure_user("alex", "Alex")
    second_id, second_created = auth.ensure_user("alex", "Alex Updated")
    assert first_created is True
    assert second_created is False
    assert second_id == first_id
    with auth._session_factory() as session:
        user = session.get(UserRow, first_id)
        assert user is not None
        assert user.display_name == "Alex"


@pytest.mark.integration
def test_ensure_user_refuses_a_disabled_user_and_does_not_enable_it() -> None:
    auth = AuthService(database_factory(), "desktop-pepper-" * 4)
    user_id, _ = auth.ensure_user("alex", "Alex")
    auth.disable_user(user_id)

    with pytest.raises(ValueError, match="disabled"):
        auth.ensure_user("alex", "Alex")
    assert auth.is_user_active(user_id) is False


@pytest.mark.integration
def test_a_new_owner_is_provisioned_for_memory_by_the_composed_service() -> None:
    factory = database_factory()
    settings = SimpleNamespace(token_pepper="desktop-pepper-" * 4)
    auth = composition.create_auth_service(factory, settings)  # type: ignore[arg-type]

    for create in (
        lambda name: auth.provision_user(name, name),
        lambda name: auth.ensure_user(name, name)[0],
    ):
        owner_id = create(f"owner-{id(create)}")
        with factory() as session:
            row = session.get(MemorySettingsRow, owner_id)
        assert row is not None
        assert (row.journal, row.contacts, row.projects, row.tasks) == (True,) * 4
        assert (row.paused, row.version) == (False, 1)


@pytest.mark.integration
def test_the_auth_service_runs_exactly_the_hooks_it_is_given_inside_the_user_transaction() -> None:
    factory = database_factory()
    seen: list[UUID] = []

    def record(session: object, owner_id: UUID, now: datetime) -> None:
        del now
        seen.append(owner_id)
        # The user row is already flushed, so the hook can reference it.
        assert session.get(UserRow, owner_id) is not None  # type: ignore[attr-defined]

    plain = AuthService(factory, "desktop-pepper-" * 4)
    hooked = AuthService(factory, "desktop-pepper-" * 4, on_user_provisioned=(record,))
    plain_id = plain.provision_user("plain", "Plain")
    hooked_id = hooked.provision_user("hooked", "Hooked")

    assert seen == [hooked_id]
    with factory() as session:
        assert session.get(MemorySettingsRow, plain_id) is None


def test_the_web_session_surface_of_the_service_is_gone() -> None:
    for name in ("login", "verify_session", "revoke_session", "revoke_user_sessions"):
        assert not hasattr(AuthService, name), name


@pytest.mark.integration
def test_a_token_row_carrying_retired_or_unknown_scopes_validates_and_gains_nothing() -> None:
    auth = AuthService(database_factory(), "desktop-pepper-" * 4)
    user_id, _ = auth.ensure_user("alex", "Alex")
    token = auth.create_personal_token(user_id, "Old", frozenset({"tasks:read"}))
    with auth._session_factory.begin() as session:
        row = session.scalar(select(PersonalAccessTokenRow))
        assert row is not None
        # A row with chat scopes from an older version, plus names no version ever defined or a
        # session-only scope that a personal token must not hold.
        row.scopes = ["tasks:read", "chat:read", "chat:write", "made:up", "preferences:write"]

    actor = auth.verify_personal_token(token)

    assert actor is not None
    assert actor.scopes == frozenset({"tasks:read"})
    assert actor.user_id == user_id


@pytest.fixture
def granted_token_scopes(monkeypatch: pytest.MonkeyPatch) -> list[frozenset[str]]:
    """Replace the database-backed service so create-token runs without PostgreSQL."""

    granted: list[frozenset[str]] = []

    class RecordingAuthService:
        def __init__(self, session_factory: object, settings: object) -> None:
            del session_factory, settings

        def create_personal_token(
            self,
            user_id: UUID,
            label: str,
            scopes: frozenset[str],
            expires_at: object = None,
        ) -> str:
            del user_id, label, expires_at
            granted.append(scopes)
            return "rsp_test_token"

    monkeypatch.setattr(composition, "create_auth_service", RecordingAuthService)
    monkeypatch.setattr(auth_cli, "create_session_factory", lambda _url, **_kw: object())
    monkeypatch.setattr(
        auth_cli,
        "get_admin_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://unused",
            token_pepper="pepper" * 6,
            database_timeouts=DatabaseTimeouts(),
        ),
    )
    return granted


def run_create_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[str, str]:
    argv = [
        "sidekick-admin",
        "create-token",
        "--user-id",
        str(TOKEN_USER_ID),
        "--label",
        "Local MCP",
        *extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    auth_cli.main()
    captured = capsys.readouterr()
    return captured.out, captured.err


def test_admin_cli_refuses_the_ensure_desktop_user_subcommand(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["sidekick-admin", "ensure-desktop-user", "--login", "alex", "--display-name", "Alex"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exit_info:
        auth_cli.main()
    assert exit_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_create_token_without_scope_is_refused_and_issues_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    granted_token_scopes: list[frozenset[str]],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run_create_token(monkeypatch, capsys)

    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "needs at least one --scope" in err
    assert "no scope is granted by default" in err
    assert "tasks:write" in err
    assert "--scope projects:read" in err
    assert granted_token_scopes == []


def test_create_token_with_explicit_scope_grants_only_that_scope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    granted_token_scopes: list[frozenset[str]],
) -> None:
    out, err = run_create_token(monkeypatch, capsys, "--scope", "projects:read")

    assert out == "rsp_test_token\n"
    assert granted_token_scopes == [frozenset({"projects:read"})]
    assert err == ""


@pytest.fixture
def granted_token_expiry(
    monkeypatch: pytest.MonkeyPatch, granted_token_scopes: list[frozenset[str]]
) -> list[datetime | None]:
    del granted_token_scopes
    expiries: list[datetime | None] = []
    now = datetime(2026, 1, 1, tzinfo=UTC)

    class ExpiryRecordingAuthService:
        def __init__(self, session_factory: object, settings: object) -> None:
            del session_factory, settings

        def create_personal_token(
            self,
            user_id: UUID,
            label: str,
            scopes: frozenset[str],
            expires_at: datetime | None = None,
        ) -> str:
            del user_id, label, scopes
            expiries.append(expires_at)
            return "rsp_test_token"

    monkeypatch.setattr(composition, "create_auth_service", ExpiryRecordingAuthService)
    monkeypatch.setattr(auth_cli, "service_now", lambda: now)
    return expiries


def test_create_token_defaults_to_a_ninety_day_lifetime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    granted_token_expiry: list[datetime | None],
) -> None:
    run_create_token(monkeypatch, capsys, "--scope", "tasks:read")

    assert granted_token_expiry == [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=90)]


def test_create_token_lifetime_is_configurable_up_to_a_ceiling(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    granted_token_expiry: list[datetime | None],
) -> None:
    run_create_token(monkeypatch, capsys, "--scope", "tasks:read", "--expires-in-days", "365")
    assert granted_token_expiry == [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=365)]

    for refused in ("366", "0", "-1"):
        with pytest.raises(SystemExit) as exit_info:
            run_create_token(
                monkeypatch, capsys, "--scope", "tasks:read", "--expires-in-days", refused
            )
        assert exit_info.value.code == 2
        capsys.readouterr()
    assert len(granted_token_expiry) == 1


def test_a_token_without_an_end_date_needs_an_explicit_flag_and_warns(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    granted_token_expiry: list[datetime | None],
) -> None:
    out, err = run_create_token(monkeypatch, capsys, "--scope", "tasks:read", "--never-expires")

    assert out == "rsp_test_token\n"
    assert granted_token_expiry == [None]
    assert "never expires" in err
    assert "rsp_test_token" not in err


AUTOMATION_SCOPES = frozenset({"automation:read", "automation:write"})


def test_automation_scopes_are_opt_in_for_personal_tokens_only() -> None:
    assert frozenset({"automation:read", "automation:write"}) == OPT_IN_SCOPES
    assert AUTOMATION_SCOPES <= ALL_SCOPES
    assert set(MCP_SCOPES) >= AUTOMATION_SCOPES
    assert not AUTOMATION_SCOPES & TOKEN_SCOPES
    assert not {"preferences:read", "preferences:write"} & ALL_SCOPES


def test_create_token_with_a_broad_scope_list_still_leaves_out_automation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    granted_token_scopes: list[frozenset[str]],
) -> None:
    run_create_token(monkeypatch, capsys, "--scope", "tasks:read", "--scope", "tasks:write")

    assert not AUTOMATION_SCOPES & granted_token_scopes[0]


def test_create_token_with_explicit_automation_write_grants_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    granted_token_scopes: list[frozenset[str]],
) -> None:
    out, err = run_create_token(monkeypatch, capsys, "--scope", "automation:write")

    assert out == "rsp_test_token\n"
    assert granted_token_scopes == [frozenset({"automation:write"})]
    assert err == ""


class PersistenceUnreachable:
    """Stands in for the session factory; reaching it proves scope validation passed."""

    def begin(self) -> None:
        raise RuntimeError("reached persistence")


def test_create_personal_token_accepts_opt_in_scope_and_still_refuses_session_scope() -> None:
    auth = AuthService(PersistenceUnreachable(), "desktop-pepper-" * 4)  # type: ignore[arg-type]
    user_id = UUID("018af000-0000-7000-8000-000000000001")

    with pytest.raises(RuntimeError, match="reached persistence"):
        auth.create_personal_token(user_id, "Automation", scopes=frozenset({"automation:write"}))
    with pytest.raises(ValueError, match="unknown or empty token scopes"):
        auth.create_personal_token(user_id, "Settings", scopes=frozenset({"preferences:write"}))


def test_create_personal_token_requires_explicit_scopes() -> None:
    auth = AuthService(PersistenceUnreachable(), "desktop-pepper-" * 4)  # type: ignore[arg-type]
    user_id = UUID("018af000-0000-7000-8000-000000000001")

    with pytest.raises(TypeError):
        auth.create_personal_token(user_id, "No scopes")  # type: ignore[call-arg]


def test_create_personal_token_refuses_a_retired_chat_scope() -> None:
    auth = AuthService(PersistenceUnreachable(), "desktop-pepper-" * 4)  # type: ignore[arg-type]
    user_id = UUID("018af000-0000-7000-8000-000000000001")

    for scope in ("chat:read", "chat:write"):
        with pytest.raises(ValueError, match="unknown or empty token scopes"):
            auth.create_personal_token(user_id, "Chat", scopes=frozenset({scope, "tasks:read"}))


def test_the_admin_command_no_longer_offers_a_chat_scope_or_session_revocation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for argv in (
        ["create-token", "--user-id", str(TOKEN_USER_ID), "--label", "x", "--scope", "chat:write"],
        ["revoke-sessions", "--user-id", str(TOKEN_USER_ID)],
    ):
        monkeypatch.setattr(sys, "argv", ["sidekick-admin", *argv])
        with pytest.raises(SystemExit) as exit_info:
            auth_cli.main()
        assert exit_info.value.code == 2
        assert "invalid choice" in capsys.readouterr().err


def test_admin_settings_do_not_require_the_oauth_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The owner's user must be creatable before the identity mapping can name them."""

    from pydantic import ValidationError

    from sidekick.shared.config import Settings, get_admin_settings

    monkeypatch.setenv("SIDEKICK_MCP_AUTH_MODE", "github_oauth")
    monkeypatch.setenv("SIDEKICK_MCP_PUBLIC_BASE_URL", "https://sidekick.example")
    monkeypatch.setenv("SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES", "github:1=replace-with-uuid")

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]
    assert get_admin_settings().mcp_auth_mode == "pat"


def test_admin_settings_still_reject_an_undeclared_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import ValidationError

    from sidekick.shared.config import get_admin_settings

    monkeypatch.setenv("SIDEKICK_NOT_A_SETTING", "x")
    with pytest.raises(ValidationError, match="undeclared SIDEKICK_ setting"):
        get_admin_settings()


def test_create_user_asks_for_no_terminal_input_and_prints_the_uuid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provisioned: list[tuple[str, str]] = []

    class RecordingAuthService:
        def __init__(self, session_factory: object, settings: object) -> None:
            del session_factory, settings

        def provision_user(self, login: str, display_name: str) -> UUID:
            provisioned.append((login, display_name))
            return TOKEN_USER_ID

    def no_prompt(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("create-user must not read from the terminal")

    monkeypatch.setattr(composition, "create_auth_service", RecordingAuthService)
    monkeypatch.setattr(auth_cli, "create_session_factory", lambda _url, **_kw: object())
    monkeypatch.setattr(
        auth_cli,
        "get_admin_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://unused",
            token_pepper="pepper" * 6,
            database_timeouts=DatabaseTimeouts(),
        ),
    )
    monkeypatch.setattr("getpass.getpass", no_prompt)
    monkeypatch.setattr(
        sys,
        "argv",
        ["sidekick-admin", "create-user", "--login", "owner", "--display-name", "Owner"],
    )

    auth_cli.main()

    assert capsys.readouterr().out == f"{TOKEN_USER_ID}\n"
    assert provisioned == [("owner", "Owner")]


def test_the_password_reset_command_is_gone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["sidekick-admin", "reset-password", "--login", "owner"])
    with pytest.raises(SystemExit) as exit_info:
        auth_cli.main()
    assert exit_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.integration
def test_a_seeded_owner_is_provisioned_for_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]))
    from tools.seed import local as seed_local

    factory = database_factory()
    # The session factory is replaced, so no database URL or `.env` is read.
    monkeypatch.setattr(seed_local, "create_session_factory", lambda *_args, **_kw: factory)
    services = seed_local.build_services(make_settings())

    owner_id, _ = services.auth.ensure_user("seeded", "Seeded")

    with factory() as session:
        assert session.get(MemorySettingsRow, owner_id) is not None

"""Personal-token persistence behavior."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from sidekick.shared.auth import TOKEN_SCOPES, AuthService
from sidekick.shared.persistence.models import AuditEventRow, PersonalAccessTokenRow
from sidekick.shared.types import utc_now
from tests.db import database_factory


@pytest.mark.integration
def test_personal_token_maps_to_its_user() -> None:
    auth = AuthService(database_factory(), "pepper" * 8)
    user_id = auth.provision_user("rasmus", "Rasmus")
    personal_token = auth.create_personal_token(user_id, "MCP Inspector", TOKEN_SCOPES)
    mcp_actor = auth.verify_personal_token(personal_token)
    assert mcp_actor is not None and mcp_actor.user_id == user_id
    assert personal_token.startswith("rsp_")


@pytest.mark.integration
def test_invalid_token_fails_closed() -> None:
    auth = AuthService(database_factory(), "pepper" * 8)
    auth.provision_user("owner", "Owner")
    assert auth.verify_personal_token("rsp_not-a-real-token") is None


@pytest.mark.integration
def test_personal_token_lifecycle_and_user_disable() -> None:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    user_id = auth.provision_user("owner", "Owner")
    token = auth.create_personal_token(
        user_id,
        "Read-only client",
        scopes=frozenset({"projects:read"}),
        expires_at=utc_now() + timedelta(days=1),
    )
    actor = auth.verify_personal_token(token)
    listed = auth.list_personal_tokens(user_id)
    assert actor is not None and actor.scopes == frozenset({"projects:read"})
    assert len(listed) == 1 and listed[0].label == "Read-only client"
    assert auth.revoke_personal_token(listed[0].id)
    assert auth.verify_personal_token(token) is None
    assert auth.disable_user(user_id)


@pytest.mark.integration
def test_auth_records_sanitized_events_without_targets_or_secrets() -> None:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    user_id = auth.provision_user("owner", "Owner")
    token = auth.create_personal_token(user_id, "Client", TOKEN_SCOPES)
    auth.disable_user(user_id)
    with factory() as session:
        events = list(session.scalars(select(AuditEventRow).order_by(AuditEventRow.occurred_at)))
        assert [(event.event, event.outcome) for event in events] == [
            ("auth.token_created", "success"),
            ("auth.user_disabled", "success"),
        ]
        assert all(event.target_id is None and event.reason is None for event in events)
        assert token not in repr([vars(event) for event in events])
        assert session.scalar(select(func.count()).select_from(AuditEventRow)) == 2


@pytest.mark.integration
def test_contacts_scopes_are_accepted_and_enforced() -> None:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    user_id = auth.provision_user("owner", "Owner")

    # Verify we can create token with contacts:read and contacts:write
    token = auth.create_personal_token(
        user_id,
        "Contacts Client",
        scopes=frozenset({"contacts:read", "contacts:write"}),
    )
    actor = auth.verify_personal_token(token)
    assert actor is not None
    assert actor.scopes == frozenset({"contacts:read", "contacts:write"})

    # Try an invalid scope and expect validation error
    with pytest.raises(ValueError, match="unknown or empty token scopes"):
        auth.create_personal_token(
            user_id,
            "Invalid Client",
            scopes=frozenset({"invalid_scope"}),
        )


@pytest.mark.integration
def test_personal_token_last_used_is_written_at_most_once_a_minute() -> None:
    auth = AuthService(database_factory(), "pepper" * 8)
    user_id = auth.provision_user("owner", "Owner")
    token = auth.create_personal_token(user_id, "Client", TOKEN_SCOPES)
    assert auth.list_personal_tokens(user_id)[0].last_used_at is None

    assert auth.verify_personal_token(token) is not None
    first = auth.list_personal_tokens(user_id)[0].last_used_at
    assert first is not None

    # A second use within the minute is accepted but does not rewrite the timestamp.
    assert auth.verify_personal_token(token) is not None
    assert auth.list_personal_tokens(user_id)[0].last_used_at == first


@pytest.mark.integration
def test_personal_token_revocation_and_disable_apply_to_every_call_despite_thinned_writes() -> None:
    auth = AuthService(database_factory(), "pepper" * 8)
    user_id = auth.provision_user("owner", "Owner")
    revoked = auth.create_personal_token(user_id, "Revoked", TOKEN_SCOPES)
    kept = auth.create_personal_token(user_id, "Kept", TOKEN_SCOPES)
    assert auth.verify_personal_token(revoked) is not None
    assert auth.verify_personal_token(kept) is not None

    views = {view.label: view for view in auth.list_personal_tokens(user_id)}
    assert auth.revoke_personal_token(views["Revoked"].id)
    # Used a moment ago, so no write would happen; the revoked token is still refused at once.
    assert auth.verify_personal_token(revoked) is None
    assert auth.verify_personal_token(kept) is not None

    assert auth.disable_user(user_id)
    assert auth.verify_personal_token(kept) is None


@pytest.mark.integration
def test_personal_token_last_used_update_is_conditional_in_sql() -> None:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    user_id = auth.provision_user("owner", "Owner")
    token = auth.create_personal_token(user_id, "Client", TOKEN_SCOPES)

    def set_last_used(value: datetime) -> None:
        with factory.begin() as session:
            session.execute(update(PersonalAccessTokenRow).values(last_used_at=value))

    recent = utc_now() - timedelta(seconds=30)
    set_last_used(recent)
    assert auth.verify_personal_token(token) is not None
    assert auth.list_personal_tokens(user_id)[0].last_used_at == recent

    stale = utc_now() - timedelta(minutes=5)
    set_last_used(stale)
    assert auth.verify_personal_token(token) is not None
    refreshed = auth.list_personal_tokens(user_id)[0].last_used_at
    assert refreshed is not None and refreshed > stale

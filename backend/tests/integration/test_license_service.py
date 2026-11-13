"""The instance's license (D-081): storage, the offline state, the clock-rollback
guard, who may set the key, and that neither logs nor audit carry the key."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.license.key import UNLICENSED, LicenseView
from sidekick.license.persistence import LicenseStore
from sidekick.license.public_key import PLACEHOLDER_PUBLIC_KEY
from sidekick.license.service import LicenseService
from sidekick.shared.auth import AuthService
from sidekick.shared.errors import PermissionDeniedError
from sidekick.shared.persistence.models import AuditEventRow, InstanceLicenseRow
from tests.db import database_factory
from tests.support.license_support import (
    LICENSEE,
    OWNER_PUBLIC,
    STRANGER_PRIVATE,
    STRANGER_PUBLIC,
    assert_logs_hold_none_of,
    signature_of,
    signed_key,
    watched,
)

PEPPER = "token-pepper-for-tests-only-12345678"


def at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def service(
    factory: sessionmaker[Session], clock: Clock, public_key: str = OWNER_PUBLIC
) -> LicenseService:
    return LicenseService(LicenseStore(factory), public_key, clock)


def audit_rows(factory: sessionmaker[Session]) -> list[tuple[str, str, str | None]]:
    with factory() as session:
        rows = session.execute(
            select(AuditEventRow.event, AuditEventRow.outcome, AuditEventRow.reason)
            .where(AuditEventRow.target_type == "instance_license")
            .order_by(AuditEventRow.occurred_at, AuditEventRow.id)
        )
        return [(row.event, row.outcome, row.reason) for row in rows]


@pytest.mark.integration
def test_an_instance_without_a_key_is_unlicensed() -> None:
    factory = database_factory()
    assert service(factory, Clock(at(2026, 11, 9))).view() == UNLICENSED


@pytest.mark.integration
def test_a_valid_key_is_stored_for_the_instance_and_read_back() -> None:
    factory = database_factory()
    clock = Clock(at(2026, 11, 9))
    key = signed_key(expires=date(2027, 11, 9), kind="org", licensee="Förening X")
    outcome = service(factory, clock).set_key(key, correlation_id="corr-1")
    expected = LicenseView("licensed", "Förening X", "org", date(2027, 11, 9))
    assert outcome.accepted and outcome.view == expected
    # A fresh service (a restart) reads the same key from the database.
    assert service(factory, clock).view() == expected
    assert audit_rows(factory) == [("license.set", "success", None)]
    with factory() as session:
        row = session.get(InstanceLicenseRow, 1)
        assert row is not None and row.license_key == key


@pytest.mark.integration
def test_entering_the_stored_key_again_changes_and_audits_nothing() -> None:
    factory = database_factory()
    clock = Clock(at(2026, 11, 9))
    key = signed_key()
    first = service(factory, clock).set_key(key)
    # Whitespace around the same key is the same key.
    again = service(factory, clock).set_key(f"  {key}\n")
    assert first == again and again.accepted
    assert audit_rows(factory) == [("license.set", "success", None)]


@pytest.mark.integration
def test_a_key_that_does_not_verify_changes_nothing_and_is_audited_as_denied() -> None:
    factory = database_factory()
    clock = Clock(at(2026, 11, 9))
    good = signed_key(licensee="Riktig Ägare")
    licensed = service(factory, clock)
    licensed.set_key(good)
    for bad in (signed_key(key=STRANGER_PRIVATE), "ROADLAKE-1.abc.def", "hello"):
        outcome = licensed.set_key(bad)
        assert not outcome.accepted
        assert outcome.view.state == "licensed" and outcome.view.licensee == "Riktig Ägare"
    with factory() as session:
        row = session.get(InstanceLicenseRow, 1)
        assert row is not None and row.license_key == good
    assert audit_rows(factory) == [
        ("license.set", "success", None),
        ("license.set", "denied", "bad_signature"),
        ("license.set", "denied", "malformed"),
    ]


@pytest.mark.integration
def test_a_first_key_that_does_not_verify_leaves_the_instance_unlicensed() -> None:
    factory = database_factory()
    outcome = service(factory, Clock(at(2026, 11, 9))).set_key(signed_key(key=STRANGER_PRIVATE))
    assert not outcome.accepted and outcome.view == UNLICENSED


@pytest.mark.integration
def test_an_expired_key_is_stored_and_shows_as_expired() -> None:
    factory = database_factory()
    clock = Clock(at(2027, 2, 1))
    outcome = service(factory, clock).set_key(signed_key(expires=date(2027, 1, 31)))
    assert outcome.accepted
    assert outcome.view == LicenseView("expired", LICENSEE, "personal", date(2027, 1, 31))


@pytest.mark.integration
def test_the_state_follows_the_clock_through_the_last_day() -> None:
    factory = database_factory()
    clock = Clock(at(2027, 1, 30))
    licensed = service(factory, clock)
    licensed.set_key(signed_key(expires=date(2027, 1, 31)))
    assert licensed.view().state == "licensed"
    clock.now = at(2027, 1, 31)
    assert licensed.view().state == "licensed"
    clock.now = at(2027, 2, 1)
    assert licensed.view().state == "expired"


@pytest.mark.integration
def test_turning_the_clock_back_does_not_revive_an_expired_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = database_factory()
    clock = Clock(at(2026, 12, 1))
    first = service(factory, clock)
    first.set_key(signed_key(expires=date(2026, 12, 31)))
    clock.now = at(2027, 1, 5)
    assert first.view().state == "expired"
    with factory() as session:
        row = session.get(InstanceLicenseRow, 1)
        assert row is not None and row.max_seen_on == date(2027, 1, 5)
    # The clock goes back into the licensed period, in the same process and after a restart.
    clock.now = at(2026, 12, 15)
    with watched(caplog):
        assert first.view().state == "expired"
        assert service(factory, clock).view().state == "expired"
    rollback = [r for r in caplog.records if r.getMessage() == "license_clock_behind"]
    assert rollback and getattr(rollback[0], "license_reason", None) == "clock_rollback"
    with factory() as session:
        row = session.get(InstanceLicenseRow, 1)
        assert row is not None and row.max_seen_on == date(2027, 1, 5)
    # A new key that is still valid on the highest date seen is licensed again.
    renewed = first.set_key(signed_key(expires=date(2027, 6, 1)))
    assert renewed.accepted and renewed.view.state == "licensed"


@pytest.mark.integration
def test_the_highest_date_is_kept_when_the_key_is_cleared() -> None:
    factory = database_factory()
    clock = Clock(at(2027, 3, 1))
    licensed = service(factory, clock)
    licensed.set_key(signed_key(expires=date(2027, 12, 31)))
    assert licensed.clear() is True
    assert licensed.clear() is False
    assert licensed.view() == UNLICENSED
    clock.now = at(2026, 1, 1)
    # Entering a key that expired before the highest date seen shows it as expired, not licensed.
    outcome = licensed.set_key(signed_key(expires=date(2026, 6, 1)))
    assert outcome.accepted and outcome.view.state == "expired"
    assert audit_rows(factory)[:2] == [
        ("license.set", "success", None),
        ("license.cleared", "success", None),
    ]


@pytest.mark.integration
def test_another_public_key_makes_a_stored_key_invalid_with_the_reason_only_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = database_factory()
    clock = Clock(at(2026, 11, 9))
    key = signed_key()
    service(factory, clock).set_key(key)
    other = signed_key(key=STRANGER_PRIVATE)
    with watched(caplog):
        view = service(factory, clock, STRANGER_PUBLIC).view()
    assert view == LicenseView("invalid")
    assert view.as_json() == {"state": "invalid"}
    reasons = [getattr(r, "license_reason", None) for r in caplog.records]
    assert "bad_signature" in reasons
    assert_logs_hold_none_of(caplog, key, signature_of(key), other, LICENSEE)


@pytest.mark.integration
def test_the_placeholder_public_key_makes_every_key_unlicensed_and_unsettable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = database_factory()
    clock = Clock(at(2026, 11, 9))
    key = signed_key()
    service(factory, clock).set_key(key)
    with watched(caplog):
        placeholder = service(factory, clock, PLACEHOLDER_PUBLIC_KEY)
        assert placeholder.view() == UNLICENSED
        outcome = placeholder.set_key(key)
    assert not outcome.accepted and outcome.view == UNLICENSED
    reasons = {getattr(r, "license_reason", None) for r in caplog.records}
    assert {"placeholder", "no_public_key"} <= reasons
    assert_logs_hold_none_of(caplog, key, signature_of(key), LICENSEE)


@pytest.mark.integration
def test_only_the_installations_only_active_user_may_set_the_key_through_a_user_channel() -> None:
    factory = database_factory()
    auth = AuthService(factory, PEPPER)
    owner_id = auth.provision_user("owner", "Owner")
    licensed = service(factory, Clock(at(2026, 11, 9)))
    key = signed_key()
    assert licensed.set_by_owner(owner_id, key, correlation_id="c1").accepted
    # Once there are two users, every user is refused.
    stranger = auth.provision_user("second", "Second")
    with pytest.raises(PermissionDeniedError):
        licensed.set_by_owner(stranger, key)
    with pytest.raises(PermissionDeniedError):
        licensed.set_by_owner(owner_id, signed_key(licensee="Annan"))
    assert licensed.view().licensee == LICENSEE
    # The audit names the user who set it.
    with factory() as session:
        actors = list(
            session.scalars(
                select(AuditEventRow.actor_id).where(
                    AuditEventRow.event == "license.set", AuditEventRow.outcome == "success"
                )
            )
        )
    assert actors == [owner_id]


@pytest.mark.integration
def test_neither_logs_nor_audit_carry_the_key_the_signature_or_the_licensee(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = database_factory()
    owner_id = AuthService(factory, PEPPER).provision_user("owner", "Owner")
    licensed = service(factory, Clock(at(2026, 11, 9)))
    key = signed_key()
    junk = signed_key(key=STRANGER_PRIVATE, licensee="Bedragare Hemlig")
    with watched(caplog):
        licensed.set_by_owner(owner_id, key, correlation_id="corr-9")
        licensed.set_by_owner(owner_id, junk, correlation_id="corr-10")
        licensed.view()
        licensed.clear(correlation_id="corr-11")
    messages = {r.getMessage() for r in caplog.records}
    assert {"license_set", "license_rejected", "license_cleared"} <= messages
    assert_logs_hold_none_of(
        caplog, key, junk, signature_of(key), signature_of(junk), LICENSEE, "Bedragare"
    )
    with factory() as session:
        stored = [
            f"{row.event} {row.outcome} {row.reason} {row.correlation_id} {row.target_type}"
            for row in session.scalars(
                select(AuditEventRow).where(AuditEventRow.target_type == "instance_license")
            )
        ]
    assert stored
    assert not any(secret in line for line in stored for secret in (key, junk, LICENSEE))


class _Unreachable:
    def begin(self) -> None:
        raise OperationalError("SELECT 1", {}, Exception("database down"))


@pytest.mark.integration
def test_a_page_never_fails_because_of_the_license() -> None:
    down = LicenseService(
        LicenseStore(_Unreachable()),  # type: ignore[arg-type]
        OWNER_PUBLIC,
    )
    assert down.display() == UNLICENSED
    with pytest.raises(OperationalError):
        down.view()


@pytest.mark.integration
def test_the_table_is_one_row_and_the_app_role_cannot_delete_it() -> None:
    factory = database_factory()
    service(factory, Clock(at(2026, 11, 9))).set_key(signed_key())
    with pytest.raises(ProgrammingError), factory.begin() as session:
        session.execute(text("DELETE FROM sidekick.instance_license"))
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO sidekick.instance_license (id, max_seen_on, updated_at) "
                "VALUES (2, DATE '2026-11-09', now())"
            )
        )
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.execute(text("UPDATE sidekick.instance_license SET license_key = ''"))


@pytest.mark.integration
def test_a_refusal_for_not_being_the_owner_is_audited_with_who_and_why(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = database_factory()
    auth = AuthService(factory, PEPPER)
    first = auth.provision_user("owner", "Owner")
    second = auth.provision_user("second", "Second")
    licensed = service(factory, Clock(at(2026, 11, 9)))
    key = signed_key()
    with watched(caplog):
        for user in (first, second):
            with pytest.raises(PermissionDeniedError):
                licensed.set_by_owner(user, key, correlation_id="c-denied")
    assert audit_rows(factory) == [
        ("license.set", "denied", "not_owner"),
        ("license.set", "denied", "not_owner"),
    ]
    with factory() as session:
        actors = set(session.scalars(select(AuditEventRow.actor_id)))
    assert actors == {first, second}
    reasons = [getattr(r, "license_reason", None) for r in caplog.records]
    assert "not_owner" in reasons
    assert_logs_hold_none_of(caplog, key, signature_of(key), LICENSEE)


@pytest.mark.integration
def test_repeated_refusals_are_audited_once_per_actor_and_reason() -> None:
    factory = database_factory()
    auth = AuthService(factory, PEPPER)
    first = auth.provision_user("owner", "Owner")
    auth.provision_user("second", "Second")
    licensed = service(factory, Clock(at(2026, 11, 9)))
    for _ in range(5):
        with pytest.raises(PermissionDeniedError):
            licensed.set_by_owner(first, signed_key())
        licensed.set_key("junk", actor_id=first)
        licensed.set_key("junk")
    licensed.set_key(signed_key(key=STRANGER_PRIVATE), actor_id=first)
    with factory() as session:
        rows = sorted(
            (row.reason or "", row.actor_id is None)
            for row in session.execute(
                select(AuditEventRow.reason, AuditEventRow.actor_id).where(
                    AuditEventRow.event == "license.set"
                )
            )
        )
    assert rows == [
        ("bad_signature", False),
        ("malformed", False),
        ("malformed", True),
        ("not_owner", False),
    ]


@pytest.mark.integration
def test_one_wrong_jump_forward_in_the_clock_does_not_lock_a_valid_key_out(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = database_factory()
    clock = Clock(at(2026, 11, 9))
    licensed = service(factory, clock)
    licensed.set_key(signed_key(expires=date(2027, 6, 1)))
    assert licensed.view().state == "licensed"
    # The clock runs ten years ahead for a moment: the key reads as expired meanwhile, but the
    # date is not remembered.
    clock.now = at(2036, 11, 9)
    with watched(caplog):
        assert licensed.view().state == "expired"
    ahead = [r for r in caplog.records if r.getMessage() == "license_clock_ahead"]
    assert ahead and getattr(ahead[0], "license_reason", None) == "clock_jump_ignored"
    # Only the message and the fields the service added: the record's own timestamps may hold the
    # digits by chance.
    standard = vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message"}
    extras = [
        f"{key}={value}" for r in ahead for key, value in vars(r).items() if key not in standard
    ]
    assert "2036" not in " ".join([*(r.getMessage() for r in ahead), *extras])
    with factory() as session:
        row = session.get(InstanceLicenseRow, 1)
        assert row is not None and row.max_seen_on == date(2026, 11, 9)
    clock.now = at(2026, 11, 10)
    assert service(factory, clock).view().state == "licensed"
    # A step within the allowance is remembered as before.
    clock.now = at(2027, 11, 9)
    assert licensed.view().state == "expired"
    with factory() as session:
        row = session.get(InstanceLicenseRow, 1)
        assert row is not None and row.max_seen_on == date(2027, 11, 9)


@pytest.mark.integration
def test_reset_clock_sets_the_highest_date_to_today_and_is_audited() -> None:
    factory = database_factory()
    clock = Clock(at(2026, 11, 9))
    licensed = service(factory, clock)
    licensed.set_key(signed_key(expires=date(2027, 6, 1)))
    # A date wrongly remembered far ahead (written by hand, as an older version could have).
    with factory.begin() as session:
        session.execute(text("UPDATE sidekick.instance_license SET max_seen_on = '2030-01-01'"))
    assert licensed.view().state == "expired"
    licensed.reset_clock(correlation_id="c-reset")
    assert licensed.view().state == "licensed"
    with factory() as session:
        row = session.get(InstanceLicenseRow, 1)
        assert row is not None and row.max_seen_on == date(2026, 11, 9)
        assert row.license_key is not None
    assert ("license.clock_reset", "success", None) in audit_rows(factory)


@pytest.mark.integration
def test_reset_clock_on_an_instance_with_no_row_creates_it() -> None:
    factory = database_factory()
    clock = Clock(at(2026, 11, 9))
    service(factory, clock).reset_clock()
    assert service(factory, clock).view() == UNLICENSED

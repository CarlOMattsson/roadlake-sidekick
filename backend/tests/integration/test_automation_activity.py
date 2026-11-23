"""What the automations have been doing, read as counts for the Start view.

Each read is owner-filtered: another owner's runs and suggestions never count. Times are written
relative to the database's own clock so no test depends on the wall time it runs at.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.automations.application.activity import AutomationActivityService
from sidekick.automations.domain.automation import ReportCursor
from sidekick.automations.persistence import AutomationStore, SqlAutomationStore
from sidekick.shared.errors import PermissionDeniedError
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.automation_rows import (
    Sql,
    insert_automation,
    insert_run,
    insert_suggestion,
)
from tests.support.settings import make_settings

READ = frozenset({"automation:read"})


def _ago(interval: str) -> Sql:
    return Sql(f"now() - interval '{interval}'")


@dataclass
class Env:
    factory: sessionmaker[Session]
    store: SqlAutomationStore
    service: AutomationActivityService
    owner: UUID
    other: UUID

    def seed(self, write: Callable[[Session], object]) -> None:
        self.store.transaction(write)

    def actor(self, scopes: frozenset[str] = READ) -> Actor:
        return Actor(self.owner, scopes)


@pytest.fixture
def env() -> Env:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    store = SqlAutomationStore(factory)
    return Env(
        factory,
        store,
        AutomationActivityService(store),
        container.auth.provision_user("activity-owner", "Owner"),
        container.auth.provision_user("activity-other", "Other"),
    )


def _automation(session: Session, owner: UUID, title: str, **overrides: object) -> str:
    return insert_automation(session.connection(), str(owner), title=title, **overrides)


def _run(
    session: Session, owner: UUID, automation: str, key: str, state: str, **overrides: object
) -> str:
    return insert_run(
        session.connection(), str(owner), automation, occurrence_key=key, state=state, **overrides
    )


def _suggestion(
    session: Session, owner: UUID, automation: str, run: str, **overrides: object
) -> str:
    return insert_suggestion(session.connection(), str(owner), automation, run, **overrides)


@pytest.mark.integration
def test_pending_suggestions_are_counted_over_the_owners_automations_only(env: Env) -> None:
    def write(session: Session) -> None:
        for owner, titles in ((env.owner, ("Mail", "Weekly")), (env.other, ("Theirs",))):
            for title in titles:
                automation = _automation(session, owner, title)
                run = _run(session, owner, automation, "d:2026-11-22", "done")
                for _ in range(2 if title == "Mail" else 1):
                    _suggestion(session, owner, automation, run)
                _suggestion(session, owner, automation, run, state="dismissed")

    env.seed(write)

    mine = env.service.pending(env.actor())
    assert (mine.total, mine.automations) == (3, 2)


@pytest.mark.integration
def test_nothing_pending_is_zero_and_zero(env: Env) -> None:
    assert env.service.pending(env.actor()).total == 0


@pytest.mark.integration
def test_the_latest_failed_run_names_its_automation_and_the_newest_summary_is_found(
    env: Env,
) -> None:
    def write(session: Session) -> None:
        mail = _automation(session, env.owner, "Morning mail")
        _run(
            session,
            env.owner,
            mail,
            "d:2026-11-20",
            "done",
            finished_at=_ago("3 days"),
            created_at=_ago("3 days"),
            summary="Old summary",
        )
        _run(
            session,
            env.owner,
            mail,
            "d:2026-11-23",
            "failed",
            finished_at=_ago("1 hour"),
            created_at=_ago("1 hour"),
        )
        weekly = _automation(session, env.owner, "Weekly")
        _run(
            session,
            env.owner,
            weekly,
            "d:2026-11-23",
            "done",
            finished_at=_ago("2 hours"),
            created_at=_ago("2 hours"),
            summary="Found two tasks.",
        )
        archived = _automation(session, env.owner, "Old one", state="archived")
        _run(
            session,
            env.owner,
            archived,
            "d:2026-11-23",
            "failed",
            finished_at=_ago("10 minutes"),
            created_at=_ago("10 minutes"),
        )
        theirs = _automation(session, env.other, "Their failing one")
        _run(
            session,
            env.other,
            theirs,
            "d:2026-11-23",
            "failed",
            finished_at=_ago("5 minutes"),
            created_at=_ago("5 minutes"),
            summary="Their secret",
        )

    env.seed(write)

    facts = env.service.recent(env.actor(), day_start=datetime.now(UTC) - timedelta(hours=3))
    assert facts.failed_today == 1
    assert facts.failed_automation == "Morning mail"
    assert facts.latest_summary == "Found two tasks."


@pytest.mark.integration
def test_an_automation_that_succeeded_after_failing_is_not_failing(env: Env) -> None:
    def write(session: Session) -> None:
        mail = _automation(session, env.owner, "Morning mail")
        _run(
            session,
            env.owner,
            mail,
            "d:2026-11-22",
            "failed",
            finished_at=_ago("30 hours"),
            created_at=_ago("30 hours"),
        )
        _run(
            session,
            env.owner,
            mail,
            "d:2026-11-23",
            "done",
            finished_at=_ago("1 hour"),
            created_at=_ago("1 hour"),
        )

    env.seed(write)

    facts = env.service.recent(env.actor(), day_start=datetime.now(UTC) - timedelta(hours=3))
    assert facts.failed_automation is None
    assert facts.failed_today == 0


@pytest.mark.integration
def test_the_window_counts_what_happened_since_the_owner_last_looked(env: Env) -> None:
    seen = datetime.now(UTC) - timedelta(days=1)

    def write(session: Session) -> None:
        AutomationStore.save_report_cursor(session, ReportCursor(env.owner, seen, 1, seen))
        mail = _automation(session, env.owner, "Morning mail")
        before = _run(session, env.owner, mail, "d:2026-11-20", "done", created_at=_ago("3 days"))
        _suggestion(session, env.owner, mail, before, created_at=_ago("3 days"))
        after = _run(session, env.owner, mail, "d:2026-11-22", "done", created_at=_ago("5 hours"))
        _run(session, env.owner, mail, "d:2026-11-23", "failed", created_at=_ago("1 hour"))
        _suggestion(session, env.owner, mail, after, created_at=_ago("5 hours"))
        _suggestion(
            session,
            env.owner,
            mail,
            after,
            created_at=_ago("4 hours"),
            state="dismissed",
            decided_at=_ago("2 hours"),
            decided_by="you",
            decision_channel="app",
        )
        theirs = _automation(session, env.other, "Theirs")
        _run(session, env.other, theirs, "d:2026-11-23", "failed", created_at=_ago("1 hour"))

    env.seed(write)

    window = env.service.since_last_look(env.actor(), datetime.now(UTC))
    assert window is not None
    assert (window.runs, window.failed_runs) == (2, 1)
    assert (window.suggestions_created, window.suggestions_decided) == (2, 1)
    assert window.since == seen
    assert not window.is_empty


@pytest.mark.integration
def test_before_the_owner_has_looked_there_is_no_window(env: Env) -> None:
    assert env.service.since_last_look(env.actor(), datetime.now(UTC)) is None


@pytest.mark.integration
def test_a_window_with_nothing_in_it_is_empty(env: Env) -> None:
    seen = datetime.now(UTC) - timedelta(hours=1)
    env.seed(
        lambda session: AutomationStore.save_report_cursor(
            session, ReportCursor(env.owner, seen, 1, seen)
        )
    )

    window = env.service.since_last_look(env.actor(), datetime.now(UTC))

    assert window is not None
    assert window.is_empty


@pytest.mark.integration
def test_every_read_needs_the_automation_read_scope(env: Env) -> None:
    nobody = env.actor(frozenset({"tasks:read", "start:read"}))
    now = datetime.now(UTC)

    with pytest.raises(PermissionDeniedError):
        env.service.pending(nobody)
    with pytest.raises(PermissionDeniedError):
        env.service.recent(nobody, day_start=now)
    with pytest.raises(PermissionDeniedError):
        env.service.since_last_look(nobody, now)

"""The automation report against a real database: counts, owner isolation, the mark and Start.

Times are written relative to the database's own clock so no test depends on the wall time it runs
at. Another owner's runs and suggestions never reach a count, a highlight or the mark.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from sidekick.api.app import create_container
from sidekick.automations.application.activity import AutomationActivityService
from sidekick.automations.application.report import AutomationReportService
from sidekick.automations.domain.report import HighlightKind, WindowBasis
from sidekick.automations.report_store import SqlReportStore
from sidekick.shared.errors import (
    ConflictError,
    IdempotencyKeyReusedError,
    PermissionDeniedError,
    ValidationError,
)
from sidekick.shared.types import Actor, SystemClock
from tests.db import database_factory
from tests.support.automation_rows import Sql, insert_automation, insert_run, insert_suggestion
from tests.support.settings import make_settings

READ = frozenset({"automation:read"})
BOTH = frozenset({"automation:read", "automation:write"})


def _ago(interval: str) -> Sql:
    return Sql(f"now() - interval '{interval}'")


@dataclass
class Env:
    store: SqlReportStore
    service: AutomationReportService
    owner: UUID
    other: UUID

    def seed(self, write: Callable[[Session], object]) -> None:
        self.store.transaction(write)

    def actor(self, scopes: frozenset[str] = BOTH, user: UUID | None = None) -> Actor:
        return Actor(user or self.owner, scopes)


@pytest.fixture
def env() -> Env:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    store = SqlReportStore(factory)
    return Env(
        store,
        AutomationReportService(store, SystemClock()),
        container.auth.provision_user("report-owner", "Owner"),
        container.auth.provision_user("report-other", "Other"),
    )


def _since(hours: int = 24) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def _seed_day(env: Env) -> dict[str, str]:
    """Two automations of the owner, one of another owner, and a day of activity."""

    ids: dict[str, str] = {}

    def write(session: Session) -> None:
        connection = session.connection()
        owner = str(env.owner)
        mail = insert_automation(connection, owner, title="Morning mail")
        weekly = insert_automation(connection, owner, title="Weekly", model_tier="strong")
        archived = insert_automation(connection, owner, title="Old", state="archived")
        theirs = insert_automation(connection, str(env.other), title="Their secret one")
        ids.update(mail=mail, weekly=weekly, archived=archived, theirs=theirs)

        done = insert_run(
            connection, owner, mail, occurrence_key="d:1", state="done", created_at=_ago("3 hours"),
            cost_microusd=200_000,
        )  # fmt: skip
        failed = insert_run(
            connection, owner, mail, occurrence_key="d:2", state="failed", outcome="failed",
            summary="Could not read the mail", created_at=_ago("1 hour"),
            finished_at=_ago("1 hour"), cost_microusd=50_000,
        )  # fmt: skip
        old = insert_run(
            connection, owner, mail, occurrence_key="d:0", state="done",
            created_at=_ago("3 days"), cost_microusd=999_000,
        )  # fmt: skip
        insert_run(
            connection,
            owner,
            weekly,
            occurrence_key="d:1",
            state="queued",
            created_at=_ago("2 hours"),
        )
        gone = insert_run(
            connection, owner, archived, occurrence_key="d:1", state="done",
            created_at=_ago("5 hours"), cost_microusd=1_000,
        )  # fmt: skip
        ids.update(done=done, failed=failed, old=old, gone=gone)

        # Created in the window: one flagged and pending, one applied by the policy, one dismissed.
        insert_suggestion(
            connection, owner, mail, done, created_at=_ago("5 hours"),
            screening_flags=["contains_link", "payment_related"],
        )  # fmt: skip
        ids["auto"] = insert_suggestion(
            connection, owner, mail, done, created_at=_ago("4 hours"), state="applied",
            decided_at=_ago("2 hours"), decided_by="policy", decision_channel="policy",
            applied_kind="task", applied_version=1,
            applied_id="00000000-0000-7000-8000-0000000000a1",
        )  # fmt: skip
        insert_suggestion(
            connection, owner, mail, done, created_at=_ago("4 hours"), state="dismissed",
            decided_at=_ago("2 hours"), decided_by="you", decision_channel="app",
            verdict="suspicious",
        )  # fmt: skip
        # Older: it still waits, which is counted, but it was not made or decided in the window.
        insert_suggestion(connection, owner, mail, old, created_at=_ago("3 days"))
        insert_suggestion(
            connection, owner, mail, old, created_at=_ago("3 days"), state="applied",
            decided_at=_ago("3 days"), decided_by="you", decision_channel="app",
            applied_kind="task", applied_version=1,
            applied_id="00000000-0000-7000-8000-0000000000a2",
        )  # fmt: skip
        # Another owner's activity in the window must not show anywhere.
        their_run = insert_run(
            connection, str(env.other), theirs, occurrence_key="d:1", state="failed",
            outcome="failed", summary="Their secret", created_at=_ago("1 hour"),
        )  # fmt: skip
        insert_suggestion(
            connection, str(env.other), theirs, their_run, created_at=_ago("1 hour"),
            screening_flags=["contains_link"],
        )  # fmt: skip

    env.seed(write)
    return ids


@pytest.mark.integration
def test_the_report_counts_the_window_per_automation_and_what_waits_now(env: Env) -> None:
    ids = _seed_day(env)

    report = env.service.report(env.actor(READ), since=_since())

    by_title = {row.title: row for row in report.rows}
    assert set(by_title) == {"Morning mail", "Weekly", "Old"}
    mail = by_title["Morning mail"]
    assert (mail.runs, mail.ok_runs, mail.failed_runs) == (2, 1, 1)
    assert mail.cost_microusd == 250_000
    assert mail.suggestions_created == 3
    assert (mail.applied, mail.dismissed, mail.flagged, mail.auto_applied) == (1, 1, 2, 1)
    # The flagged card and the older card still wait; the older one was made before the window.
    assert mail.pending == 2
    weekly = by_title["Weekly"]
    assert (weekly.runs, weekly.ok_runs, weekly.failed_runs) == (1, 0, 0)
    assert weekly.model_tier.value == "strong"
    assert by_title["Old"].state.value == "archived"
    assert by_title["Old"].cost_microusd == 1_000

    totals = report.totals
    assert (totals.automations, totals.runs, totals.failed_runs) == (3, 4, 1)
    assert (totals.suggestions_created, totals.pending) == (3, 2)
    assert totals.cost_microusd == 251_000
    assert report.window.basis is WindowBasis.GIVEN
    assert str(ids["theirs"]) not in {str(row.automation_id) for row in report.rows}


@pytest.mark.integration
def test_the_highlights_are_failed_runs_then_flagged_cards_then_automatic_ones(env: Env) -> None:
    ids = _seed_day(env)

    report = env.service.report(env.actor(READ), since=_since(), limit=10)

    kinds = [item.kind for item in report.highlights]
    assert kinds == [
        HighlightKind.RUN_FAILED,
        HighlightKind.SUGGESTION_FLAGGED,
        HighlightKind.SUGGESTION_FLAGGED,
        HighlightKind.SUGGESTION_AUTO_APPLIED,
    ]
    failure = report.highlights[0]
    assert str(failure.run_id) == ids["failed"]
    assert (failure.outcome, failure.summary) == ("failed", "Could not read the mail")
    assert failure.automation_title == "Morning mail"
    # Newest first: the card the check called suspicious, then the one the screening flagged.
    suspicious, screened = report.highlights[1], report.highlights[2]
    assert (suspicious.verdict, suspicious.flags) == ("suspicious", ())
    assert (screened.verdict, set(screened.flags)) == (None, {"contains_link", "payment_related"})
    assert str(report.highlights[3].suggestion_id) == ids["auto"]
    assert "Their secret" not in " ".join(
        f"{item.automation_title} {item.summary}" for item in report.highlights
    )
    assert len(env.service.report(env.actor(READ), since=_since(), limit=2).highlights) == 2


@pytest.mark.integration
def test_another_owner_sees_none_of_it(env: Env) -> None:
    _seed_day(env)

    report = env.service.report(env.actor(READ, user=env.other), since=_since())

    assert [row.title for row in report.rows] == ["Their secret one"]
    assert report.totals.runs == 1
    assert [item.summary for item in report.highlights if item.summary] == ["Their secret"]


@pytest.mark.integration
def test_a_quiet_owner_gets_an_empty_report(env: Env) -> None:
    report = env.service.report(env.actor(READ))

    assert (report.rows, report.highlights, report.version) == ([], [], 0)
    assert report.totals.runs == 0
    assert report.window.basis is WindowBasis.FIRST_LOOK


@pytest.mark.integration
def test_reading_needs_the_read_scope_and_marking_needs_the_write_scope(env: Env) -> None:
    now = datetime.now(UTC)
    with pytest.raises(PermissionDeniedError):
        env.service.report(env.actor(frozenset({"automation:write", "tasks:read"})))
    with pytest.raises(PermissionDeniedError):
        env.service.export_html(
            env.actor(frozenset({"tasks:read"})), since=None, locale="en", zone=UTC
        )
    with pytest.raises(PermissionDeniedError):
        env.service.mark_seen(
            env.actor(READ), seen_until=now, expected_version=0, idempotency_key="key-read-only"
        )


@pytest.mark.integration
def test_the_window_follows_the_mark_and_the_mark_is_versioned(env: Env) -> None:
    _seed_day(env)
    seen = datetime.now(UTC) - timedelta(minutes=90)

    first = env.service.mark_seen(
        env.actor(), seen_until=seen, expected_version=0, idempotency_key="mark-key-0001"
    )
    report = env.service.report(env.actor(READ))

    assert (first.version, first.seen_until) == (1, seen)
    assert report.version == 1
    assert report.window.basis is WindowBasis.LAST_SEEN
    assert report.window.since == seen
    # Only what began in the last 90 minutes: the failed run and nothing else of the day.
    assert [row.title for row in report.rows if row.runs] == ["Morning mail"]
    assert report.totals.runs == 1
    assert report.totals.failed_runs == 1

    later = datetime.now(UTC)
    second = env.service.mark_seen(
        env.actor(), seen_until=later, expected_version=1, idempotency_key="mark-key-0002"
    )
    assert (second.version, second.seen_until) == (2, later)


@pytest.mark.integration
def test_a_stale_version_a_move_back_and_a_future_mark_are_refused(env: Env) -> None:
    now = datetime.now(UTC)
    env.service.mark_seen(
        env.actor(),
        seen_until=now - timedelta(hours=1),
        expected_version=0,
        idempotency_key="k-first-0001",
    )

    with pytest.raises(ConflictError) as stale:
        env.service.mark_seen(
            env.actor(), seen_until=now, expected_version=0, idempotency_key="k-stale-0001"
        )
    assert stale.value.reason == "stale_version"
    with pytest.raises(ValidationError):
        env.service.mark_seen(
            env.actor(),
            seen_until=now - timedelta(hours=2),
            expected_version=1,
            idempotency_key="k-back-0001",
        )
    with pytest.raises(ValidationError):
        env.service.mark_seen(
            env.actor(),
            seen_until=now + timedelta(hours=1),
            expected_version=1,
            idempotency_key="k-future-0001",
        )


@pytest.mark.integration
def test_marking_twice_with_one_key_marks_once_and_a_changed_request_is_refused(env: Env) -> None:
    seen = datetime.now(UTC) - timedelta(hours=1)
    kwargs = {"seen_until": seen, "expected_version": 0, "idempotency_key": "same-key-0001"}

    first = env.service.mark_seen(env.actor(), **kwargs)
    again = env.service.mark_seen(env.actor(), **kwargs)

    assert (first.version, again.version) == (1, 1)
    with pytest.raises(IdempotencyKeyReusedError):
        env.service.mark_seen(env.actor(), **{**kwargs, "seen_until": seen + timedelta(minutes=5)})


@pytest.mark.integration
def test_each_owner_has_a_mark_of_their_own(env: Env) -> None:
    seen = datetime.now(UTC) - timedelta(hours=1)
    env.service.mark_seen(
        env.actor(), seen_until=seen, expected_version=0, idempotency_key="mine-key-0001"
    )

    theirs = env.service.report(env.actor(READ, user=env.other))

    assert theirs.version == 0
    assert theirs.window.basis is WindowBasis.FIRST_LOOK


@pytest.mark.integration
def test_marking_is_audited_by_name_and_owner_only(env: Env) -> None:
    env.service.mark_seen(
        env.actor(),
        seen_until=datetime.now(UTC) - timedelta(minutes=1),
        expected_version=0,
        idempotency_key="audit-key-0001",
        correlation_id="corr-report-1",
    )

    def read(session: Session) -> list[tuple[object, ...]]:
        rows = session.execute(
            text(
                "SELECT actor_id, event, outcome, target_type, target_id, correlation_id "
                "FROM sidekick.audit_events WHERE event = 'automation.report_seen'"
            )
        )
        return [tuple(row) for row in rows]

    assert env.store.transaction(read) == [
        (env.owner, "automation.report_seen", "success", "automation_report", None, "corr-report-1")
    ]


@pytest.mark.integration
def test_the_start_view_shows_what_happened_after_the_mark(env: Env) -> None:
    _seed_day(env)
    activity = AutomationActivityService(env.store)
    # Before the first mark there is no window to show.
    assert activity.since_last_look(env.actor(READ), datetime.now(UTC)) is None

    env.service.mark_seen(
        env.actor(),
        seen_until=datetime.now(UTC) - timedelta(minutes=90),
        expected_version=0,
        idempotency_key="start-key-0001",
    )

    window = activity.since_last_look(env.actor(READ), datetime.now(UTC))
    assert window is not None
    assert not window.is_empty
    assert (window.runs, window.failed_runs) == (1, 1)

    env.service.mark_seen(
        env.actor(),
        seen_until=datetime.now(UTC),
        expected_version=1,
        idempotency_key="start-key-0002",
    )
    quiet = activity.since_last_look(env.actor(READ), datetime.now(UTC))
    assert quiet is not None
    assert quiet.is_empty

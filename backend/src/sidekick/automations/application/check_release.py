"""Ending a run's wait for its check: the way out when the check does not happen.

A run that ended with proposals waits in the state `checking`, and its cards cannot be decided
until each has a check or is shown as "Not checked". When the check is switched off, when no worker
takes the run, or when a run has waited longer than the owner's limit, nobody would ever finish it.
`release_run` shows the waiting cards as not checked and ends the run, so that nothing is held back
for good and nothing is approved on the strength of a missing answer.

`close_checked_run` is the end shared with a run whose check ran to the end: the run is saved as
done, the cards that qualify for the high-confidence group become eligible, and the end is audited.
"""

import logging
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sidekick.automations.domain.automation import Automation
from sidekick.automations.domain.grouping import with_bulk_eligibility
from sidekick.automations.domain.runs import AutomationRun
from sidekick.automations.domain.suggestion import Suggestion, SuggestionState
from sidekick.shared.errors import ConflictError
from sidekick.shared.observability import safe_log_fields
from sidekick.shared.types import AuditingStore, TxSession, new_uuid7

LOGGER = logging.getLogger("sidekick.automations.checks")

CHECKED = "automation.run_checked"
RELEASED = "automation.run_released"


class RunClosingStore(AuditingStore, Protocol):
    def get_automation(
        self, session: TxSession, owner_id: UUID, automation_id: UUID, *, lock: bool = False
    ) -> Automation: ...
    def get_run(
        self, session: TxSession, owner_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> AutomationRun: ...
    def save_run(
        self, session: TxSession, run: AutomationRun, expected_version: int | None = None
    ) -> None: ...
    def list_suggestions(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        states: Collection[SuggestionState] | None = None,
        automation_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = ...,
    ) -> list[Suggestion]: ...
    def save_suggestion(
        self,
        session: TxSession,
        suggestion: Suggestion,
        now: datetime,
        expected_version: int | None = None,
    ) -> None: ...


class ReleaseStore(RunClosingStore, Protocol):
    def list_unattended_runs(
        self, session: TxSession, owner_id: UUID, now: datetime, *, idle_since: datetime | None
    ) -> list[AutomationRun]: ...


def close_checked_run(
    store: RunClosingStore,
    session: TxSession,
    before: AutomationRun,
    done: AutomationRun,
    *,
    now: datetime,
    event: str,
    outcome: str,
) -> None:
    """Save the run as done, turn on the group for the cards that qualify, and audit the end."""

    owner_id = before.owner_id
    store.save_run(session, done, expected_version=before.version)
    automation = store.get_automation(session, owner_id, before.automation_id)
    for card in store.list_suggestions(
        session, owner_id, run_id=before.id, states=[SuggestionState.PENDING]
    ):
        eligible = with_bulk_eligibility(card, automation.spec, run_done=True)
        if eligible.bulk_eligible == card.bulk_eligible:
            continue
        try:
            store.save_suggestion(session, eligible, now, expected_version=card.version)
        except ConflictError:
            continue  # the owner decided it in the meantime: it is no longer a candidate
    store.append_audit(
        session,
        actor_id=owner_id,
        event=event,
        outcome="success",
        target_type="automation_run",
        target_id=before.id,
        related_id=before.automation_id,
        correlation_id=str(new_uuid7()),
    )
    LOGGER.info(
        event.replace(".", "_"),
        extra=safe_log_fields({"automation_run_id": str(before.id), "outcome": outcome}),
    )


def release_run(
    store: RunClosingStore,
    session: TxSession,
    run: AutomationRun,
    *,
    now: datetime,
    checker_enabled: bool,
    release_after: timedelta,
) -> bool:
    """End the wait of `run` for its check when nobody is doing the check. The waiting cards are
    shown as not checked and no check row is written, for no checker answered. False when the run
    is not releasable: it left `checking`, a worker holds it, or its wait is within the limit."""

    owner_id = run.owner_id
    locked = store.get_run(session, owner_id, run.id, lock=True)
    if not locked.releasable(now, checker_enabled=checker_enabled, release_after=release_after):
        return False
    for card in store.list_suggestions(
        session, owner_id, run_id=locked.id, states=[SuggestionState.CHECKING]
    ):
        failed = card.fail_check(expected_version=card.version)
        store.save_suggestion(session, failed, now, expected_version=card.version)
    close_checked_run(
        store,
        session,
        locked,
        locked.release_unchecked(now=now),
        now=now,
        event=RELEASED,
        outcome="released",
    )
    return True


def release_stale_checks(
    store: ReleaseStore,
    session: TxSession,
    owner_id: UUID,
    *,
    now: datetime,
    checker_enabled: bool,
    release_after: timedelta,
) -> int:
    """End the wait of every run of the owner that nobody checks, and say how many ended.

    Called where the owner meets proposals, so that a run held for a check that does not happen
    never keeps them back, whatever the worker is doing. With the check off every run that no
    worker holds is released; with it on, only a run that waited longer than `release_after`."""

    idle_since = now - release_after if checker_enabled else None
    released = 0
    for run in store.list_unattended_runs(session, owner_id, now, idle_since=idle_since):
        if release_run(
            store,
            session,
            run,
            now=now,
            checker_enabled=checker_enabled,
            release_after=release_after,
        ):
            released += 1
    return released

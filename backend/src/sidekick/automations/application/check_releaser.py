"""The worker's second duty beside the check: end the wait of runs that nobody checks.

With the check off, every run that waits for it and that no worker holds is ended. With the check
on, only a run that has waited longer than the owner's limit, which means no worker took it.
"""

from datetime import datetime
from typing import Protocol

from sidekick.automations.application.check_release import ReleaseStore, release_run
from sidekick.automations.application.runs import AutomationRunLimits
from sidekick.automations.domain.runs import AutomationRun
from sidekick.shared.types import Clock, TransactionalStore, TxSession


class ReleaseQueue(ReleaseStore, TransactionalStore, Protocol):
    def next_unattended_run(
        self, session: TxSession, now: datetime, *, idle_since: datetime | None
    ) -> AutomationRun | None: ...


class CheckReleaseService:
    """Ends the wait of runs that nobody checks, one run at a time."""

    def __init__(self, store: ReleaseQueue, clock: Clock, limits: AutomationRunLimits) -> None:
        self.store = store
        self.clock = clock
        self.limits = limits

    def run_next(self, worker_id: str) -> bool:
        """End the wait of one run and say so. With the check off every run that no worker holds
        is ended; with it on, only a run that waited longer than the limit."""

        del worker_id  # a release is not held by a worker; the run's lock is enough
        return self.store.transaction(self._release_one)

    def _release_one(self, session: TxSession) -> bool:
        now = self.clock.now()
        limits = self.limits
        idle_since = None if not limits.checker_enabled else now - limits.check_release_after
        run = self.store.next_unattended_run(session, now, idle_since=idle_since)
        if run is None:
            return False
        return release_run(
            self.store,
            session,
            run,
            now=now,
            checker_enabled=limits.checker_enabled,
            release_after=limits.check_release_after,
        )

"""What the check of a run asks the database beyond the automation store: which run is next.

The rest of what a check reads and writes (the run, its cards, the check rows, the spend) is the
automation store's. Owner-filtered like it, and nothing here logs.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.automations.domain.runs import AutomationRun
from sidekick.automations.persistence import AutomationStore, run_from_row, unattended_conditions
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.persistence.models import AutomationRunRow
from sidekick.shared.persistence.stores.base import StoreBase


class CheckStore(AutomationStore):
    """The automation operations plus the queue of runs that wait for their check."""

    @staticmethod
    def next_checking_run(session: Session, now: datetime) -> AutomationRun | None:
        """The run that has waited longest for its check and that no worker holds, locked.

        A run is free when no worker ever took it or when the lease of the one that did has run
        out. A row another worker has locked is skipped, so two workers never take the same one.
        """

        row = session.scalar(
            select(AutomationRunRow)
            .where(*unattended_conditions(now, None))
            .order_by(AutomationRunRow.updated_at, AutomationRunRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return run_from_row(row) if row is not None else None

    @staticmethod
    def next_unattended_run(
        session: Session, now: datetime, *, idle_since: datetime | None
    ) -> AutomationRun | None:
        """A run that waits for a check and that no worker holds, locked, oldest first.

        `idle_since` limits it to runs not touched since then; None takes any such run, which is
        what the end of a switched-off check needs. A row another worker has locked is skipped.
        """

        row = session.scalar(
            select(AutomationRunRow)
            .where(*unattended_conditions(now, idle_since))
            .order_by(AutomationRunRow.updated_at, AutomationRunRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return run_from_row(row) if row is not None else None


class SqlCheckStore(CheckStore, StoreBase):
    """The check operations with the transaction, idempotency and audit of `StoreBase`."""

    def __init__(
        self, session_factory: sessionmaker[Session], telemetry: TelemetryPort | None = None
    ) -> None:
        super().__init__(session_factory, telemetry)

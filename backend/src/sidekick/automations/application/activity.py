"""What the automations have been doing, read for an overview such as the Start view.

Every read needs `automation:read`, like the registry, and is owner-filtered in the store. The
answers are counts, a title and the latest run's own summary; nothing a run read or proposed.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sidekick.automations.domain.activity import PendingSuggestions, RunFacts, WindowCounts
from sidekick.automations.domain.automation import ReportCursor
from sidekick.shared.types import Actor, TransactionalStore, TxSession

READ_SCOPE = "automation:read"


class AutomationActivityStore(TransactionalStore, Protocol):
    def pending_suggestion_overview(
        self, session: TxSession, owner_id: UUID
    ) -> PendingSuggestions: ...
    def recent_run_facts(
        self, session: TxSession, owner_id: UUID, day_start: datetime
    ) -> RunFacts: ...
    def window_counts(
        self, session: TxSession, owner_id: UUID, since: datetime, until: datetime
    ) -> WindowCounts: ...
    def get_report_cursor(self, session: TxSession, owner_id: UUID) -> ReportCursor | None: ...


class AutomationActivityService:
    def __init__(self, store: AutomationActivityStore) -> None:
        self.store = store

    def pending(self, actor: Actor) -> PendingSuggestions:
        """The suggestions that wait for a decision, over every automation."""

        actor.require(READ_SCOPE)
        return self.store.transaction(
            lambda session: self.store.pending_suggestion_overview(session, actor.user_id)
        )

    def recent(self, actor: Actor, *, day_start: datetime) -> RunFacts:
        """Failed runs since `day_start`, the automation whose latest run failed, a summary."""

        actor.require(READ_SCOPE)
        return self.store.transaction(
            lambda session: self.store.recent_run_facts(session, actor.user_id, day_start)
        )

    def since_last_look(self, actor: Actor, until: datetime) -> WindowCounts | None:
        """What happened up to `until` since the owner last marked the report as seen.

        None before the first time the owner marked it.
        """

        actor.require(READ_SCOPE)

        def read(session: TxSession) -> WindowCounts | None:
            cursor = self.store.get_report_cursor(session, actor.user_id)
            if cursor is None:
                return None
            return self.store.window_counts(session, actor.user_id, cursor.seen_until, until)

        return self.store.transaction(read)

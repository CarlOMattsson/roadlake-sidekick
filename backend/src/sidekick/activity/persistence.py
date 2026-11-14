"""Owner-filtered reads and writes of the activity history."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sidekick.activity.application.service import (
    ActivityEntry,
    NewActivity,
)
from sidekick.shared.persistence.models import (
    ActivityEntryRow,
    DomainEventRow,
)
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.persistence.stores.keyset import rows_after
from sidekick.shared.types import KeyValue

# Every new entry is applied; the other states exist only on history the retired automation
# engine left behind.
APPLIED = "applied"


class ActivityStore(StoreBase):
    """The activity ledger and its read projection, over the shared session and idempotency."""

    @staticmethod
    def append_activity(session: Session, activity: NewActivity) -> None:
        """Insert the ledger event, then its activity entry, in the open transaction."""

        event = DomainEventRow(
            id=activity.event_id,
            owner_id=activity.owner_id,
            aggregate_type=activity.aggregate_type,
            aggregate_id=activity.aggregate_id,
            aggregate_version=activity.aggregate_version,
            event_type=activity.event_type,
            schema_version=1,
            actor_type=activity.actor_type,
            actor_id=activity.actor_id,
            command_id=activity.command_id,
            correlation_id=activity.correlation_id,
            payload=activity.payload,
            occurred_at=activity.occurred_at,
        )
        session.add(event)
        # The projection has a RESTRICT foreign key to the ledger row.  Flush the
        # append explicitly so SQLAlchemy cannot choose the projection insert first
        # when both rows enter the unit of work together.
        session.flush([event])
        session.add(
            ActivityEntryRow(
                id=activity.entry_id,
                owner_id=activity.owner_id,
                domain_event_id=activity.event_id,
                category=activity.category,
                source=activity.actor_type,
                operation=activity.operation,
                state=APPLIED,
                aggregate_type=activity.aggregate_type,
                aggregate_id=activity.aggregate_id,
                summary=activity.summary,
                before_values=activity.before_values,
                after_values=activity.after_values,
                evidence=activity.evidence,
                correlation_id=activity.correlation_id,
                occurred_at=activity.occurred_at,
            )
        )

    @staticmethod
    def activity_entries(
        session: Session,
        owner: UUID,
        *,
        aggregate_types: Sequence[str] | None,
        category: str | None,
        state: str | None,
        after: tuple[KeyValue, ...] | None,
        limit: int,
    ) -> list[ActivityEntry]:
        """The owner's activity entries, newest first, after the (occurred_at, id) in `after`;
        at most `limit` rows.

        `aggregate_types` None keeps every type; a sequence keeps only those types.
        """

        statement = select(ActivityEntryRow).where(ActivityEntryRow.owner_id == owner)
        if aggregate_types is not None:
            statement = statement.where(ActivityEntryRow.aggregate_type.in_(aggregate_types))
        if category is not None:
            statement = statement.where(ActivityEntryRow.category == category)
        if state is not None:
            statement = statement.where(ActivityEntryRow.state == state)
        if after is not None:
            statement = statement.where(
                rows_after(
                    (ActivityEntryRow.occurred_at, ActivityEntryRow.id), after, descending=True
                )
            )
        rows = session.scalars(
            statement.order_by(
                ActivityEntryRow.occurred_at.desc(), ActivityEntryRow.id.desc()
            ).limit(limit)
        )
        return [_activity(row) for row in rows]


def _activity(row: ActivityEntryRow) -> ActivityEntry:
    return ActivityEntry(
        id=row.id,
        domain_event_id=row.domain_event_id,
        category=row.category,
        source=row.source,
        operation=row.operation,
        state=row.state,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        summary=row.summary,
        before_values=row.before_values,
        after_values=row.after_values,
        evidence=row.evidence,
        policy_mode=row.policy_mode,
        correlation_id=row.correlation_id,
        occurred_at=row.occurred_at,
    )

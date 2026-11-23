"""Reading suggestions, owner-filtered: a card, a list, what the policy applied, what is known.

Part of the automation store (`AutomationStore` builds on it). A purged payload reads as an empty
one. Text columns are the owner's data or text an AI wrote; nothing here logs them.
"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sidekick.automations.domain.effects import EffectKind
from sidekick.automations.domain.screening import ScreeningFlag
from sidekick.automations.domain.suggestion import (
    ApplyError,
    CheckState,
    DecidedBy,
    DecisionChannel,
    Suggestion,
    SuggestionState,
    Verdict,
)
from sidekick.shared.errors import NotFoundError
from sidekick.shared.persistence.models import AutomationSuggestionRow
from sidekick.shared.types import validate_limit

MAX_LIST_ROWS = 200
"""The most rows one list read returns."""


def suggestion_from_row(row: AutomationSuggestionRow) -> Suggestion:
    """A purged payload (kept as NULL with `payload_purged_at`) reads as an empty one."""

    return Suggestion(
        id=row.id,
        owner_id=row.owner_id,
        automation_id=row.automation_id,
        run_id=row.run_id,
        effect=EffectKind(row.effect),
        effect_version=row.effect_version,
        payload=row.payload or {},
        proposed_payload=row.proposed_payload or {},
        rationale=row.rationale or "",
        datapoint_ids=tuple(row.datapoint_ids),
        dedupe_fingerprint=row.dedupe_fingerprint,
        state=SuggestionState(row.state),
        expires_at=row.expires_at,
        screening_flags=tuple(ScreeningFlag(flag) for flag in row.screening_flags),
        check_state=CheckState(row.check_state),
        verdict=Verdict(row.verdict) if row.verdict else None,
        confidence=row.confidence,
        bulk_eligible=row.bulk_eligible,
        decided_at=row.decided_at,
        decided_by=DecidedBy(row.decided_by) if row.decided_by else None,
        decision_channel=DecisionChannel(row.decision_channel) if row.decision_channel else None,
        applied_kind=row.applied_kind,
        applied_id=row.applied_id,
        applied_version=row.applied_version,
        undone_at=row.undone_at,
        apply_error=ApplyError(row.apply_error) if row.apply_error else None,
        version=row.version,
    )


class SuggestionQueries:
    """The read operations on suggestions; static and owner-filtered."""

    @staticmethod
    def get_suggestion(
        session: Session, owner_id: UUID, suggestion_id: UUID, *, lock: bool = False
    ) -> Suggestion:
        statement = select(AutomationSuggestionRow).where(
            AutomationSuggestionRow.id == suggestion_id,
            AutomationSuggestionRow.owner_id == owner_id,
        )
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise NotFoundError("suggestion not found")
        return suggestion_from_row(row)

    @staticmethod
    def list_suggestions(
        session: Session,
        owner_id: UUID,
        *,
        states: Collection[SuggestionState] | None = None,
        automation_id: UUID | None = None,
        run_id: UUID | None = None,
        bulk_eligible: bool | None = None,
        expires_after: datetime | None = None,
        limit: int = MAX_LIST_ROWS,
        offset: int = 0,
    ) -> list[Suggestion]:
        statement = select(AutomationSuggestionRow).where(
            AutomationSuggestionRow.owner_id == owner_id
        )
        if bulk_eligible is not None:
            statement = statement.where(AutomationSuggestionRow.bulk_eligible == bulk_eligible)
        if expires_after is not None:
            statement = statement.where(AutomationSuggestionRow.expires_at > expires_after)
        if states is not None:
            statement = statement.where(
                AutomationSuggestionRow.state.in_([item.value for item in states])
            )
        if automation_id is not None:
            statement = statement.where(AutomationSuggestionRow.automation_id == automation_id)
        if run_id is not None:
            statement = statement.where(AutomationSuggestionRow.run_id == run_id)
        rows = session.scalars(
            statement.order_by(AutomationSuggestionRow.created_at, AutomationSuggestionRow.id)
            .offset(offset)
            .limit(validate_limit(limit, maximum=MAX_LIST_ROWS))
        )
        return [suggestion_from_row(row) for row in rows]

    @staticmethod
    def count_auto_applied_since(session: Session, owner_id: UUID, since: datetime) -> int:
        """How many suggestions the policy applied since `since`, those the owner undid included:
        an undo does not make room for another automatic apply."""

        total = session.scalar(
            select(func.count())
            .select_from(AutomationSuggestionRow)
            .where(
                AutomationSuggestionRow.owner_id == owner_id,
                AutomationSuggestionRow.decided_by == DecidedBy.POLICY.value,
                AutomationSuggestionRow.decided_at >= since,
            )
        )
        return int(total or 0)

    @staticmethod
    def list_auto_applied(
        session: Session,
        owner_id: UUID,
        *,
        since: datetime | None = None,
        automation_id: UUID | None = None,
        limit: int = MAX_LIST_ROWS,
    ) -> list[Suggestion]:
        """The suggestions the policy applied, newest first; applied and undone ones alike."""

        statement = select(AutomationSuggestionRow).where(
            AutomationSuggestionRow.owner_id == owner_id,
            AutomationSuggestionRow.decided_by == DecidedBy.POLICY.value,
        )
        if since is not None:
            statement = statement.where(AutomationSuggestionRow.decided_at > since)
        if automation_id is not None:
            statement = statement.where(AutomationSuggestionRow.automation_id == automation_id)
        rows = session.scalars(
            statement.order_by(
                AutomationSuggestionRow.decided_at.desc(), AutomationSuggestionRow.id.desc()
            ).limit(validate_limit(limit, maximum=MAX_LIST_ROWS))
        )
        return [suggestion_from_row(row) for row in rows]

    @staticmethod
    def known_fingerprints(session: Session, owner_id: UUID, automation_id: UUID) -> frozenset[str]:
        """Every dedupe fingerprint the automation has ever had, in any state."""

        return frozenset(
            session.scalars(
                select(AutomationSuggestionRow.dedupe_fingerprint).where(
                    AutomationSuggestionRow.owner_id == owner_id,
                    AutomationSuggestionRow.automation_id == automation_id,
                )
            )
        )

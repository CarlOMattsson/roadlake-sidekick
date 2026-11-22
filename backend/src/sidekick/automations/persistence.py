"""The automation registry, suggestions and checks, read and written owner-filtered.

Every statement names the owner, and a row of another owner answers as not found, so no id
reveals whether a row exists. A check is appended and never changed: the application role has no
UPDATE on `automation_checks`, and this store has no operation that would try. Text columns are
the owner's data or text an AI wrote; nothing here logs them.
"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sidekick.automations.domain.automation import Automation, SuggestionCheck
from sidekick.automations.domain.effects import EffectKind
from sidekick.automations.domain.screening import ScreeningFlag
from sidekick.automations.domain.spec import (
    AutomationSpecV1,
    AutomationState,
    parse_spec,
)
from sidekick.automations.domain.suggestion import (
    ApplyError,
    CheckState,
    DecidedBy,
    DecisionChannel,
    Suggestion,
    SuggestionState,
    Verdict,
)
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.models import (
    AutomationCheckRow,
    AutomationRow,
    AutomationSuggestionRow,
    Base,
)
from sidekick.shared.types import validate_limit

MAX_LIST_ROWS = 200
"""The most rows one list read returns."""


def spec_columns(spec: AutomationSpecV1) -> dict[str, object]:
    """The registry columns a spec fills. No cadence is stored as an empty object."""

    values = spec.model_dump(mode="json", exclude={"spec_version"})
    values["cadence"] = values["cadence"] or {}
    return values


def spec_from_columns(row: AutomationRow) -> AutomationSpecV1:
    return parse_spec(
        {
            "purpose": row.purpose,
            "instruction": row.instruction,
            "sources": row.sources,
            "runner": row.runner,
            "cadence": row.cadence or None,
            "allowed_effects": row.allowed_effects,
            "apply_mode": row.apply_mode,
            "auto_effects": row.auto_effects,
            "bulk_threshold": row.bulk_threshold,
            "auto_threshold": row.auto_threshold,
            "max_suggestions_per_run": row.max_suggestions_per_run,
            "run_budget_microusd": row.run_budget_microusd,
            "model_tier": row.model_tier,
        }
    )


def automation_from_row(row: AutomationRow) -> Automation:
    return Automation(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        spec=spec_from_columns(row),
        state=AutomationState(row.state),
        spec_digest=row.spec_digest,
        approved_digest=row.approved_digest,
        approved_at=row.approved_at,
        last_run_at=row.last_run_at,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply_automation(row: AutomationRow, automation: Automation) -> None:
    for column, value in spec_columns(automation.spec).items():
        setattr(row, column, value)
    row.title = automation.title
    row.state = automation.state.value
    row.spec_digest = automation.spec_digest
    row.approved_digest = automation.approved_digest
    row.approved_at = automation.approved_at
    row.last_run_at = automation.last_run_at
    row.updated_at = automation.updated_at
    row.version = automation.version


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


def _apply_suggestion(row: AutomationSuggestionRow, suggestion: Suggestion, now: datetime) -> None:
    """Copies every changeable field. A purged payload is never written back."""

    if row.payload_purged_at is None:
        row.payload = dict(suggestion.payload)
        row.proposed_payload = dict(suggestion.proposed_payload)
    row.rationale = suggestion.rationale or None
    row.datapoint_ids = list(suggestion.datapoint_ids)
    row.state = suggestion.state.value
    row.screening_flags = [flag.value for flag in suggestion.screening_flags]
    row.check_state = suggestion.check_state.value
    row.verdict = suggestion.verdict.value if suggestion.verdict else None
    row.confidence = suggestion.confidence
    row.bulk_eligible = suggestion.bulk_eligible
    row.decided_at = suggestion.decided_at
    row.decided_by = suggestion.decided_by.value if suggestion.decided_by else None
    row.decision_channel = (
        suggestion.decision_channel.value if suggestion.decision_channel else None
    )
    row.applied_kind = suggestion.applied_kind
    row.applied_id = suggestion.applied_id
    row.applied_version = suggestion.applied_version
    row.undone_at = suggestion.undone_at
    row.apply_error = suggestion.apply_error.value if suggestion.apply_error else None
    row.expires_at = suggestion.expires_at
    row.updated_at = now
    row.version = suggestion.version


def check_from_row(row: AutomationCheckRow) -> SuggestionCheck:
    return SuggestionCheck(
        id=row.id,
        owner_id=row.owner_id,
        suggestion_id=row.suggestion_id,
        run_id=row.run_id,
        attempt=row.attempt,
        checker=row.checker,
        model=row.model,
        verdict=row.verdict,
        confidence=row.confidence,
        reason_codes=tuple(row.reason_codes),
        checked_at=row.checked_at,
    )


def _insert(session: Session, row: Base, primary_key: str, not_found: str) -> None:
    """Add the row. An id that another owner already holds answers as not found.

    The lookup before it names the owner, so no foreign row is locked or read; only the
    primary key can reveal a clash, and it is reported exactly as a missing row is. Any other
    constraint failure (a run or automation of another owner, say) stays an `IntegrityError`.
    """

    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as error:
        diag = getattr(error.orig, "diag", None)
        if getattr(diag, "constraint_name", None) == primary_key:
            raise NotFoundError(not_found) from None
        raise


class AutomationStore:
    """Automations, suggestions and their checks.

    The operations are static and owner-filtered; a store that adds the transaction boundary
    (`StoreBase`) is built on them.
    """

    @staticmethod
    def get_automation(session: Session, owner_id: UUID, automation_id: UUID) -> Automation:
        row = session.scalar(
            select(AutomationRow).where(
                AutomationRow.id == automation_id, AutomationRow.owner_id == owner_id
            )
        )
        if row is None:
            raise NotFoundError("automation not found")
        return automation_from_row(row)

    @staticmethod
    def list_automations(
        session: Session,
        owner_id: UUID,
        *,
        states: Collection[AutomationState] | None = None,
        limit: int = MAX_LIST_ROWS,
    ) -> list[Automation]:
        statement = select(AutomationRow).where(AutomationRow.owner_id == owner_id)
        if states is not None:
            statement = statement.where(AutomationRow.state.in_([item.value for item in states]))
        rows = session.scalars(
            statement.order_by(AutomationRow.created_at, AutomationRow.id).limit(
                validate_limit(limit, maximum=MAX_LIST_ROWS)
            )
        )
        return [automation_from_row(row) for row in rows]

    @staticmethod
    def save_automation(
        session: Session, automation: Automation, expected_version: int | None = None
    ) -> None:
        """Insert the automation, or update it when the stored version is `expected_version`."""

        row = session.scalar(
            select(AutomationRow)
            .where(AutomationRow.id == automation.id, AutomationRow.owner_id == automation.owner_id)
            .with_for_update()
        )
        if row is None:
            row = AutomationRow(
                id=automation.id,
                owner_id=automation.owner_id,
                created_at=automation.created_at,
            )
            _apply_automation(row, automation)
            _insert(session, row, "automations_pkey", "automation not found")
            return
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale automation version", reason="stale_version")
        _apply_automation(row, automation)

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
        limit: int = MAX_LIST_ROWS,
    ) -> list[Suggestion]:
        statement = select(AutomationSuggestionRow).where(
            AutomationSuggestionRow.owner_id == owner_id
        )
        if states is not None:
            statement = statement.where(
                AutomationSuggestionRow.state.in_([item.value for item in states])
            )
        if automation_id is not None:
            statement = statement.where(AutomationSuggestionRow.automation_id == automation_id)
        rows = session.scalars(
            statement.order_by(
                AutomationSuggestionRow.created_at, AutomationSuggestionRow.id
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

    @staticmethod
    def save_suggestion(
        session: Session,
        suggestion: Suggestion,
        now: datetime,
        expected_version: int | None = None,
    ) -> None:
        """Insert the suggestion, or update it when the stored version is `expected_version`.

        The run and the automation it names must be the owner's: the composite foreign key
        refuses any other pair.
        """

        row = session.scalar(
            select(AutomationSuggestionRow)
            .where(
                AutomationSuggestionRow.id == suggestion.id,
                AutomationSuggestionRow.owner_id == suggestion.owner_id,
            )
            .with_for_update()
        )
        if row is None:
            row = AutomationSuggestionRow(
                id=suggestion.id,
                owner_id=suggestion.owner_id,
                automation_id=suggestion.automation_id,
                run_id=suggestion.run_id,
                effect=suggestion.effect.value,
                effect_version=suggestion.effect_version,
                dedupe_fingerprint=suggestion.dedupe_fingerprint,
                created_at=now,
            )
            _apply_suggestion(row, suggestion, now)
            _insert(session, row, "automation_suggestions_pkey", "suggestion not found")
            return
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale suggestion version", reason="stale_version")
        _apply_suggestion(row, suggestion, now)

    @staticmethod
    def append_check(session: Session, check: SuggestionCheck) -> None:
        """Add one check. There is no way to change or remove one."""

        session.add(
            AutomationCheckRow(
                id=check.id,
                owner_id=check.owner_id,
                suggestion_id=check.suggestion_id,
                run_id=check.run_id,
                attempt=check.attempt,
                checker=check.checker,
                model=check.model,
                verdict=check.verdict,
                confidence=check.confidence,
                reason_codes=list(check.reason_codes),
                checked_at=check.checked_at,
            )
        )

    @staticmethod
    def list_checks(session: Session, owner_id: UUID, suggestion_id: UUID) -> list[SuggestionCheck]:
        rows = session.scalars(
            select(AutomationCheckRow)
            .where(
                AutomationCheckRow.owner_id == owner_id,
                AutomationCheckRow.suggestion_id == suggestion_id,
            )
            .order_by(AutomationCheckRow.attempt)
        )
        return [check_from_row(row) for row in rows]

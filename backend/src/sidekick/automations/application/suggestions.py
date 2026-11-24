"""Deciding suggestions: approve and apply, dismiss, approve a group, undo.

Only the owner decides. A decision is the owner's own in the app; a model may decide up to three
cards per call, and never a flagged one, one it proposed in its own session, or one it edited. Every
card is decided under the row's lock and at the version the caller saw, and applying it creates its
record through the use case that owns the record, in the same transaction: a retry, a second
worker or a group that overlaps a single call finds the card already decided and creates nothing.
A card that cannot be applied stays pending and shows a closed code.

Text of a suggestion is never written to a log, a metric, an audit event or a replay record; those
hold ids and closed codes only.
"""

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sidekick.automations.application.runs import RunKeys
from sidekick.automations.application.suggestion_reads import (
    MAX_CANDIDATES,
    Lookup,
    SuggestionReads,
    SuggestionReadStore,
)
from sidekick.automations.domain.datapoints import source_infos
from sidekick.automations.domain.effects import (
    CATALOGUE,
    CreateTaskV1,
    ParsedPayload,
    PayloadProblem,
    contact_email,
    parse_payload,
    project_reference,
)
from sidekick.automations.domain.fingerprints import keyed_hash
from sidekick.automations.domain.grouping import (
    MAX_GROUP_SIZE,
    AutoApplyRefusal,
    auto_apply_refusal,
    check_group,
)
from sidekick.automations.domain.runs import AutomationRun, RunState
from sidekick.automations.domain.screening import (
    ScreeningContext,
    SourceInfo,
    contact_domain_matches_sender,
    flags_for_edit,
)
from sidekick.automations.domain.spec import ApplyMode, AutomationState
from sidekick.automations.domain.suggestion import (
    AppliedRecord,
    ApplyError,
    Decision,
    DecisionChannel,
    DecisionContext,
    DecisionRefusal,
    Suggestion,
    SuggestionRefusedError,
    SuggestionState,
)
from sidekick.automations.domain.text import match_key, normalise_line
from sidekick.contacts.domain.normalization import normalize_email
from sidekick.lifecycle.domain import RecordKind, TrashItem
from sidekick.shared.config import Settings
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from sidekick.shared.errors.core import SidekickError
from sidekick.shared.observability import TelemetryPort, safe_log_fields
from sidekick.shared.owner_day import day_start
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    Clock,
    CursorCodec,
    IdempotentStore,
    TxSession,
)

LOGGER = logging.getLogger("sidekick.automations.suggestions")

WRITE_SCOPE = "automation:write"
MAX_DECISIONS_PER_CALL = 3
"""Decisions one call may take, in the app and from a model alike."""
_OWNER_CHANNELS = (DecisionChannel.APP, DecisionChannel.COMPANION)


class ItemError(StrEnum):
    """Why one item of a decision was not taken. The card is unchanged, or pending with the
    `apply_error:` code. The values are the codes a client is shown."""

    NEEDS_APP = "needs_app"
    NEEDS_CONFIRMATION = "needs_confirmation"
    SAME_SESSION = "same_session"
    STALE = "stale"
    NOT_PENDING = "not_pending"
    EXPIRED = "expired"
    INVALID_EDIT = "invalid_edit"
    APPLY_PROJECT_GONE = "apply_error:project_gone"
    APPLY_CONFLICT = "apply_error:conflict"
    APPLY_INVALID_PAYLOAD = "apply_error:invalid_payload"
    APPLY_NOT_PERMITTED = "apply_error:not_permitted"


_ITEM_ERRORS_BY_REFUSAL: Mapping[DecisionRefusal, ItemError] = {
    DecisionRefusal.NEEDS_APP: ItemError.NEEDS_APP,
    DecisionRefusal.NOT_ALLOWED: ItemError.NEEDS_APP,
    DecisionRefusal.NEEDS_CONFIRMATION: ItemError.NEEDS_CONFIRMATION,
    DecisionRefusal.SAME_SESSION: ItemError.SAME_SESSION,
    DecisionRefusal.STALE: ItemError.STALE,
    DecisionRefusal.EXPIRED: ItemError.EXPIRED,
}
_ITEM_ERRORS_BY_APPLY: Mapping[ApplyError, ItemError] = {
    ApplyError.PROJECT_GONE: ItemError.APPLY_PROJECT_GONE,
    ApplyError.CONFLICT: ItemError.APPLY_CONFLICT,
    ApplyError.INVALID_PAYLOAD: ItemError.APPLY_INVALID_PAYLOAD,
    ApplyError.NOT_PERMITTED: ItemError.APPLY_NOT_PERMITTED,
}
_ITEM_ERROR_ORDER = tuple(ItemError)


class SuggestionStore(SuggestionReadStore, IdempotentStore, AuditingStore, Protocol):
    def save_suggestion(
        self,
        session: TxSession,
        suggestion: Suggestion,
        now: datetime,
        expected_version: int | None = None,
    ) -> None: ...
    def usable_project_ids(
        self, session: TxSession, owner_id: UUID, project_ids: Collection[UUID]
    ) -> frozenset[UUID]: ...
    def existing_contact_email_keys(
        self, session: TxSession, owner_id: UUID, email_keys: Collection[str]
    ) -> frozenset[str]: ...
    def open_task_titles(
        self, session: TxSession, owner_id: UUID, lowered_titles: Collection[str]
    ) -> list[str]: ...
    def has_attachments(
        self, session: TxSession, owner_id: UUID, kind: str, record_id: UUID
    ) -> bool: ...
    def save_run(
        self, session: TxSession, run: AutomationRun, expected_version: int | None = None
    ) -> None: ...
    def count_auto_applied_since(
        self, session: TxSession, owner_id: UUID, since: datetime
    ) -> int: ...
    def lock_owner_auto_apply(self, session: TxSession, owner_id: UUID) -> None: ...


class EffectApplier(Protocol):
    """Creates the record an effect describes, in the caller's open transaction."""

    def create(
        self, session: TxSession, actor: Actor, parsed: ParsedPayload, correlation_id: str | None
    ) -> AppliedRecord: ...


class RecordTrash(Protocol):
    """Moves one record into the trash, in the caller's open transaction."""

    def get_trash_item(
        self, session: TxSession, owner_id: UUID, kind: RecordKind, record_id: UUID
    ) -> TrashItem: ...
    def set_trashed(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
        trashed: bool,
        now: datetime,
    ) -> TrashItem: ...


@dataclass(frozen=True, slots=True)
class DecisionItem:
    suggestion_id: UUID
    expected_version: int
    decision: Decision
    edits: Mapping[str, object] | None = None
    """Fields of the payload to change before approving; the owner's, in the app only."""
    confirmed: bool = False
    """The owner's second tap on a card the checker called suspicious."""


@dataclass(frozen=True, slots=True)
class ItemOutcome:
    suggestion_id: UUID
    suggestion: Suggestion
    """The card as it is now."""
    error: ItemError | None


@dataclass(frozen=True, slots=True)
class UndoOutcome:
    suggestion: Suggestion


@dataclass(frozen=True, slots=True)
class AutoApplyOutcome:
    """What the policy did for one finished run: the cards it applied, how many stayed pending for
    each closed reason, and how many it could not apply (they show the code on the card)."""

    applied: tuple[UUID, ...] = ()
    refused: Mapping[AutoApplyRefusal, int] = field(default_factory=dict[AutoApplyRefusal, int])
    failed: int = 0


class _ApplyFailed(SidekickError):
    def __init__(self, error: ApplyError) -> None:
        super().__init__(error.value)
        self.error = error


class _EditRefused(SidekickError):
    """The edit is not a valid payload, or names a project the owner cannot use."""


class SuggestionService(SuggestionReads):
    def __init__(
        self,
        store: SuggestionStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        applier: EffectApplier,
        trash: RecordTrash,
        keys: RunKeys,
        telemetry: TelemetryPort,
        owner_timezone: tzinfo,
    ) -> None:
        super().__init__(store, clock, cursor_codec)
        self.store: SuggestionStore = store
        self.applier = applier
        self.trash = trash
        self.keys = keys
        self.telemetry = telemetry
        self.owner_timezone = owner_timezone

    @classmethod
    def from_settings(
        cls,
        store: SuggestionStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        applier: EffectApplier,
        trash: RecordTrash,
        settings: Settings,
        telemetry: TelemetryPort,
    ) -> "SuggestionService":
        return cls(
            store,
            clock,
            cursor_codec,
            applier,
            trash,
            RunKeys.from_secret(settings.token_pepper),
            telemetry,
            settings.owner_zone,
        )

    # --- decide -------------------------------------------------------------------------------

    def decide(
        self,
        actor: Actor,
        items: Sequence[DecisionItem],
        *,
        channel: DecisionChannel,
        session_id: str | None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> tuple[ItemOutcome, ...]:
        """Approve or dismiss one to three cards, each answered on its own.

        An approval applies the card's effect. An item that is refused, stale or cannot be applied
        is answered with a closed code and changes nothing else; the other items still go through.
        A call without a `automation:write` scope, or an approval without the write scope of its
        effect's domain, is refused as a whole.
        """

        actor.require(WRITE_SCOPE)
        if not 1 <= len(items) <= MAX_DECISIONS_PER_CALL:
            raise ValidationError(f"a call decides one to {MAX_DECISIONS_PER_CALL} suggestions")
        if len({item.suggestion_id for item in items}) != len(items):
            raise ValidationError("a suggestion is named once in a call")
        if any(item.edits and item.decision is not Decision.APPROVE for item in items):
            raise ValidationError("an edit belongs to an approval")
        payload = {
            "channel": channel.value,
            "items": [
                {
                    "id": str(item.suggestion_id),
                    "version": item.expected_version,
                    "decision": item.decision.value,
                    "edits": dict(item.edits) if item.edits else None,
                    "confirmed": item.confirmed,
                }
                for item in items
            ],
        }
        return self._decisions(
            actor,
            "decide_suggestions",
            idempotency_key,
            payload,
            lambda session: self._decide_all(
                session, actor, items, channel, session_id, correlation_id
            ),
        )

    def approve_group(
        self,
        actor: Actor,
        *,
        group_digest: str,
        suggestion_ids: Sequence[UUID],
        idempotency_key: str,
        channel: DecisionChannel = DecisionChannel.APP,
        correlation_id: str | None = None,
    ) -> tuple[ItemOutcome, ...]:
        """Approve the group the owner saw, in the app or on the paired phone (`channel`).

        The cards are read again under their locks: one that changed, left the group or is no
        longer eligible, or a group of another size, refuses the whole call and nothing is
        applied. Each card is then applied on its own, as in `decide`.
        """

        actor.require(WRITE_SCOPE)
        if channel not in _OWNER_CHANNELS:
            raise ValidationError("a group is approved by the owner, in the app or on the phone")
        if not 1 <= len(suggestion_ids) <= MAX_GROUP_SIZE:
            raise SuggestionRefusedError(DecisionRefusal.GROUP_TOO_LARGE)
        if len(set(suggestion_ids)) != len(suggestion_ids):
            raise SuggestionRefusedError(DecisionRefusal.GROUP_CHANGED)
        payload = {
            "digest": group_digest,
            "ids": sorted(str(item) for item in suggestion_ids),
            "channel": channel.value,
        }
        return self._decisions(
            actor,
            "approve_suggestion_group",
            idempotency_key,
            payload,
            lambda session: self._approve_group(
                session, actor, group_digest, suggestion_ids, channel, correlation_id
            ),
        )

    def undo(
        self,
        actor: Actor,
        suggestion_id: UUID,
        *,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> UndoOutcome:
        """Take back a decision: the record an applied suggestion created goes to the trash, and a
        dismissed suggestion is pending again.

        An applied suggestion is refused unless the record is exactly as it was created and not in
        the trash already; the owner then uses the trash for the record itself. A dismissed one is
        refused once its time to live has passed. The card is read at the version the caller saw,
        so one decided or changed since is refused as stale.
        """

        actor.require(WRITE_SCOPE)

        def execute(session: TxSession) -> dict[str, Any]:
            # Only the card is locked, last in the order every writer takes (automation, run,
            # card): nothing is read or written on the run or the automation here.
            card = self.store.get_suggestion(session, actor.user_id, suggestion_id, lock=True)
            now = self.clock.now()
            if card.state in (SuggestionState.DISMISSED, SuggestionState.EXPIRED):
                # A dismissal created nothing, so taking it back needs no domain write scope.
                reopened = card.undo_dismissal(now=now, expected_version=expected_version)
                self.store.save_suggestion(session, reopened, now, expected_version=card.version)
                self._audit(session, reopened, "suggestion.dismissal_undone", correlation_id)
                self._count("dismissal_undone", reopened)
                return {"id": str(card.id)}
            actor.require(CATALOGUE[card.effect].write_scope)
            kind, version, trashed = self._created_record(session, card)
            undone = card.undo(
                record_version=version,
                record_trashed=trashed,
                now=now,
                expected_version=expected_version,
            )
            self._trash_record(session, actor, card, kind, now, correlation_id)
            self.store.save_suggestion(session, undone, now, expected_version=card.version)
            self._audit(session, undone, "suggestion.undone", correlation_id)
            self._count("undone", undone)
            return {"id": str(card.id)}

        def run(session: TxSession) -> UndoOutcome:
            record = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="undo_suggestion",
                key=idempotency_key,
                payload={"id": str(suggestion_id), "version": expected_version},
                execute=lambda: execute(session),
                replay=lambda result: result,
            )
            card = self.store.get_suggestion(session, actor.user_id, UUID(str(record["id"])))
            return UndoOutcome(card)

        return self.store.transaction(run)

    def _created_record(self, session: TxSession, card: Suggestion) -> tuple[RecordKind, int, bool]:
        """The record the card created, its version now, and whether it is in the trash."""

        if card.state is not SuggestionState.APPLIED or card.applied_id is None:
            raise SuggestionRefusedError(DecisionRefusal.NOT_APPLIED)
        kind = RecordKind(CATALOGUE[card.effect].record_kind)
        try:
            item = self.trash.get_trash_item(session, card.owner_id, kind, card.applied_id)
        except NotFoundError:
            raise SuggestionRefusedError(DecisionRefusal.CHANGED_SINCE_APPLY) from None
        # A step or a link added to the record does not raise its version, and is the owner's.
        if self.store.has_attachments(session, card.owner_id, kind.value, card.applied_id):
            raise SuggestionRefusedError(DecisionRefusal.CHANGED_SINCE_APPLY)
        return kind, item.version, item.trashed_at is not None

    def _trash_record(
        self,
        session: TxSession,
        actor: Actor,
        card: Suggestion,
        kind: RecordKind,
        now: datetime,
        correlation_id: str | None,
    ) -> None:
        if card.applied_id is None or card.applied_version is None:
            raise SuggestionRefusedError(DecisionRefusal.NOT_APPLIED)
        try:
            self.trash.set_trashed(
                session,
                actor.user_id,
                kind,
                card.applied_id,
                version=card.applied_version,
                trashed=True,
                now=now,
            )
        except ConflictError:
            raise SuggestionRefusedError(DecisionRefusal.CHANGED_SINCE_APPLY) from None
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event=f"{kind.value}.trashed",
            outcome="success",
            target_type=kind.value,
            target_id=card.applied_id,
            correlation_id=correlation_id,
        )

    # --- the one transaction of a decision ---------------------------------------------------

    def _decisions(
        self,
        actor: Actor,
        operation: str,
        idempotency_key: str,
        payload: dict[str, Any],
        execute: Callable[[TxSession], dict[str, Any]],
    ) -> tuple[ItemOutcome, ...]:
        """Run the decisions once per key; a retry answers with each card as it is now."""

        def run(session: TxSession) -> tuple[ItemOutcome, ...]:
            record = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation=operation,
                key=idempotency_key,
                payload=payload,
                execute=lambda: execute(session),
                replay=lambda result: result,
            )
            return tuple(self._outcome(session, actor, item) for item in record["items"])

        return self.store.transaction(run)

    def _outcome(self, session: TxSession, actor: Actor, item: Mapping[str, Any]) -> ItemOutcome:
        suggestion_id = UUID(str(item["id"]))
        code = item["code"]
        error = _ITEM_ERROR_ORDER[int(code)] if code is not None else None
        card = self.store.get_suggestion(session, actor.user_id, suggestion_id)
        return ItemOutcome(suggestion_id, card, error)

    def _decide_all(
        self,
        session: TxSession,
        actor: Actor,
        items: Sequence[DecisionItem],
        channel: DecisionChannel,
        session_id: str | None,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        self._require_known_and_scoped(session, actor, items)
        now = self.clock.now()
        # Locks are taken in id order, so two calls over the same cards cannot wait on each other.
        errors: dict[UUID, ItemError | None] = {}
        for item in sorted(items, key=lambda entry: entry.suggestion_id):
            errors[item.suggestion_id] = self._decide_one(
                session, actor, item, channel, session_id, now, correlation_id
            )
        return _record([(item.suggestion_id, errors[item.suggestion_id]) for item in items])

    def _require_known_and_scoped(
        self, session: TxSession, actor: Actor, items: Sequence[DecisionItem]
    ) -> None:
        """Every card is the owner's (a missing one answers not found for the whole call), and an
        approval needs the write scope of the domain its effect writes to."""

        for item in items:
            card = self.store.get_suggestion(session, actor.user_id, item.suggestion_id)
            if item.decision is Decision.APPROVE:
                actor.require(CATALOGUE[card.effect].write_scope)

    def _approve_group(
        self,
        session: TxSession,
        actor: Actor,
        presented_digest: str,
        suggestion_ids: Sequence[UUID],
        channel: DecisionChannel,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        owner_id = actor.user_id
        cards = [
            self.store.get_suggestion(session, owner_id, suggestion_id, lock=True)
            for suggestion_id in sorted(suggestion_ids, key=str)
        ]
        automation = self.store.get_automation(session, owner_id, cards[0].automation_id)
        lookup = Lookup(self.store, session, owner_id)
        run_done = all(lookup.run_done(run_id) for run_id in {card.run_id for card in cards})
        check_group(presented_digest, cards, automation.spec, run_done=run_done)
        now = self.clock.now()
        errors: list[tuple[UUID, ItemError | None]] = []
        for card in cards:
            actor.require(CATALOGUE[card.effect].write_scope)
            item = DecisionItem(card.id, card.version, Decision.APPROVE)
            errors.append(
                (
                    card.id,
                    self._decide_one(session, actor, item, channel, None, now, correlation_id),
                )
            )
        return _record(errors)

    def _decide_one(
        self,
        session: TxSession,
        actor: Actor,
        item: DecisionItem,
        channel: DecisionChannel,
        session_id: str | None,
        now: datetime,
        correlation_id: str | None,
    ) -> ItemError | None:
        """One decision in its own savepoint. Returns the closed code of a refusal, else `None`."""

        card = self.store.get_suggestion(session, actor.user_id, item.suggestion_id, lock=True)
        approving = item.decision is Decision.APPROVE
        try:
            with session.begin_nested():
                decided = self._take(
                    session, actor, card, item, channel, session_id, now, correlation_id
                )
                self.store.save_suggestion(session, decided, now, expected_version=card.version)
                event = "suggestion.applied" if approving else "suggestion.dismissed"
                self._audit(session, decided, event, correlation_id)
                self._count("applied" if approving else "dismissed", decided)
        except SuggestionRefusedError as refusal:
            return _ITEM_ERRORS_BY_REFUSAL.get(refusal.refusal, ItemError.NOT_PENDING)
        except _EditRefused:
            return ItemError.INVALID_EDIT
        except _ApplyFailed as failed:
            failure = card.apply_failed(failed.error, expected_version=card.version)
            self.store.save_suggestion(session, failure, now, expected_version=card.version)
            self._audit(session, failure, "suggestion.apply_failed", correlation_id)
            self._count("apply_failed", failure)
            return _ITEM_ERRORS_BY_APPLY[failed.error]
        return None

    def _take(
        self,
        session: TxSession,
        actor: Actor,
        card: Suggestion,
        item: DecisionItem,
        channel: DecisionChannel,
        session_id: str | None,
        now: datetime,
        correlation_id: str | None,
    ) -> Suggestion:
        """The card after the decision. Raises before anything is created when it is not allowed."""

        context = self._context(session, card, channel, session_id, item.confirmed)
        card.check_decision(context, item.decision, now=now, expected_version=item.expected_version)
        if item.decision is Decision.DISMISS:
            return card.dismiss(context, now=now, expected_version=card.version)
        current = card
        if item.edits:
            if channel not in _OWNER_CHANNELS:
                raise SuggestionRefusedError(DecisionRefusal.NEEDS_APP)
            current = self._edited(session, card, item.edits)
            self._audit(session, current, "suggestion.edited", correlation_id)
        applied = self._apply(session, actor, current, correlation_id)
        return current.approve(context, applied, now=now, expected_version=current.version)

    def _context(
        self,
        session: TxSession,
        card: Suggestion,
        channel: DecisionChannel,
        session_id: str | None,
        confirmed: bool,
    ) -> DecisionContext:
        """Who decides. A model's session counts as the running one unless it is known to differ:
        a transport that cannot say leaves the owner to decide in the app."""

        if channel is not DecisionChannel.MODEL:
            return DecisionContext(channel, confirmed=confirmed)
        run = self.store.get_run(session, card.owner_id, card.run_id)
        same = (
            run.session_digest is None
            or session_id is None
            or run.session_digest == keyed_hash(self.keys.session, session_id)
        )
        return DecisionContext(channel, session_matches_run=same)

    # --- applying without the owner -----------------------------------------------------------

    def auto_apply_run(
        self,
        owner_id: UUID,
        run_id: UUID,
        *,
        checker_configured: bool,
        correlation_id: str | None = None,
    ) -> AutoApplyOutcome:
        """Apply the cards of a finished run that the owner's opt-in policy allows, and no others.

        Only an automation the owner approved with apply mode `auto_low_risk` takes part, and only
        cards the checker called `ok` that are bulk eligible (`grouping.auto_apply_refusal` holds
        every rule and the caps). Each card goes through the path an owner's approval takes
        (`_apply`) and ends as an applied card decided by the policy, so the owner's undo works on
        it unchanged. A card the policy may not apply stays pending, untouched. With no checker,
        or a run whose check did not finish, nothing is applied.
        """

        return self.store.transaction(
            lambda session: self._auto_apply_run(
                session, owner_id, run_id, checker_configured, correlation_id
            )
        )

    def _auto_apply_run(
        self,
        session: TxSession,
        owner_id: UUID,
        run_id: UUID,
        checker_configured: bool,
        correlation_id: str | None,
    ) -> AutoApplyOutcome:
        # The owner's lock first: the daily count below is read and extended under it.
        self.store.lock_owner_auto_apply(session, owner_id)
        # The automation first, then the run: the order every writer of a run takes its locks in.
        automation_id = self.store.get_run(session, owner_id, run_id).automation_id
        automation = self.store.get_automation(session, owner_id, automation_id, lock=True)
        run = self.store.get_run(session, owner_id, run_id, lock=True)
        if run.automation_id != automation_id:
            raise ConflictError("the run belongs to another automation", reason="stale_version")
        spec = automation.spec
        if (
            run.state is not RunState.DONE
            or spec.apply_mode is not ApplyMode.AUTO_LOW_RISK
            or not checker_configured
        ):
            return AutoApplyOutcome()
        now = self.clock.now()
        cards = self.store.list_suggestions(
            session,
            owner_id,
            states=(SuggestionState.PENDING,),
            run_id=run_id,
            bulk_eligible=True,
            limit=MAX_CANDIDATES,
        )
        # The policy acts as the owner with the write scope of the effects it may apply, no more.
        actor = Actor(
            owner_id, frozenset(CATALOGUE[kind].write_scope for kind in spec.auto_effects)
        )
        today = self.store.count_auto_applied_since(
            session, owner_id, day_start(now, self.owner_timezone)
        )
        applied: list[UUID] = []
        refused: dict[AutoApplyRefusal, int] = {}
        failed = 0
        # Locks are taken in id order, as in every decision.
        for listed in sorted(cards, key=lambda card: card.id):
            card = self.store.get_suggestion(session, owner_id, listed.id, lock=True)
            refusal = auto_apply_refusal(
                card,
                spec,
                now=now,
                approved_digest=automation.approved_digest,
                automation_active=automation.state is AutomationState.ACTIVE,
                checker_configured=checker_configured,
                contact_domain_matches_sender=self._sender_match(session, card),
                auto_applied_in_run=run.auto_applied_count + len(applied),
                auto_applied_today=today + len(applied),
            )
            if refusal is not None:
                refused[refusal] = refused.get(refusal, 0) + 1
                continue
            try:
                with session.begin_nested():
                    done = card.auto_apply(
                        self._apply(session, actor, card, correlation_id),
                        now=now,
                        expected_version=card.version,
                    )
                    self.store.save_suggestion(session, done, now, expected_version=card.version)
                    self._audit(session, done, "suggestion.auto_applied", correlation_id)
                    self._count("auto_applied", done)
            except _ApplyFailed as problem:
                failure = card.apply_failed(problem.error, expected_version=card.version)
                self.store.save_suggestion(session, failure, now, expected_version=card.version)
                self._audit(session, failure, "suggestion.apply_failed", correlation_id)
                self._count("apply_failed", failure)
                failed += 1
            else:
                applied.append(card.id)
        if applied:
            self.store.save_run(
                session,
                run.with_auto_applied(len(applied), now=now),
                expected_version=run.version,
            )
        return AutoApplyOutcome(tuple(applied), refused, failed)

    def _sender_match(self, session: TxSession, card: Suggestion) -> bool | None:
        """For a contact with an e-mail address: whether it is on the domain of the mail it came
        from. None for a card with nothing to compare."""

        parsed = parse_payload(card.effect, card.payload)
        if isinstance(parsed, PayloadProblem):
            return None
        points = self.store.get_datapoints(session, card.owner_id, card.datapoint_ids)
        return contact_domain_matches_sender(parsed, list(source_infos(points).values()))

    # --- applying and editing ----------------------------------------------------------------

    def _apply(
        self, session: TxSession, actor: Actor, card: Suggestion, correlation_id: str | None
    ) -> AppliedRecord:
        parsed = parse_payload(card.effect, card.payload)
        if isinstance(parsed, PayloadProblem):
            raise _ApplyFailed(ApplyError.INVALID_PAYLOAD)
        project = project_reference(parsed)
        if project is not None and project not in self.store.usable_project_ids(
            session, card.owner_id, {project}
        ):
            raise _ApplyFailed(ApplyError.PROJECT_GONE)
        try:
            return self.applier.create(session, actor, parsed, correlation_id)
        except NotFoundError:
            raise _ApplyFailed(ApplyError.PROJECT_GONE) from None
        except ConflictError:
            raise _ApplyFailed(ApplyError.CONFLICT) from None
        except ValidationError:
            raise _ApplyFailed(ApplyError.INVALID_PAYLOAD) from None
        except PermissionDeniedError:
            raise _ApplyFailed(ApplyError.NOT_PERMITTED) from None

    def _edited(
        self, session: TxSession, card: Suggestion, edits: Mapping[str, object]
    ) -> Suggestion:
        """The card with the owner's edit: validated, screened again, out of any group."""

        merged = {**card.payload, **edits}
        parsed = parse_payload(card.effect, merged)
        if isinstance(parsed, PayloadProblem):
            raise _EditRefused
        project = project_reference(parsed)
        if project is not None and project not in self.store.usable_project_ids(
            session, card.owner_id, {project}
        ):
            raise _EditRefused
        points = self.store.get_datapoints(session, card.owner_id, card.datapoint_ids)
        sources = source_infos(points)
        flags = flags_for_edit(
            parsed,
            card.rationale,
            merged,
            list(sources.values()),
            self._edit_context(session, card, parsed, sources),
        )
        return card.edit(parsed, flags, expected_version=card.version)

    def _edit_context(
        self,
        session: TxSession,
        card: Suggestion,
        parsed: ParsedPayload,
        sources: Mapping[UUID, SourceInfo],
    ) -> ScreeningContext:
        """What flagging an edit needs of the owner's records: the contacts and tasks it repeats."""

        email = contact_email(parsed)
        email_key = normalize_email(email)[1] if email else None
        value = parsed.value
        titles: set[str] = (
            {normalise_line(value.title).lower()} if isinstance(value, CreateTaskV1) else set()
        )
        return ScreeningContext(
            allowed_effects=frozenset(),
            run_open=False,
            max_suggestions=0,
            already_recorded=0,
            datapoint_sources=sources,
            existing_contact_email_keys=self.store.existing_contact_email_keys(
                session, card.owner_id, {email_key} if email_key else set[str]()
            ),
            open_task_title_keys=frozenset(
                match_key(title)
                for title in self.store.open_task_titles(session, card.owner_id, titles)
            ),
        )

    # --- shared -------------------------------------------------------------------------------

    def _audit(
        self, session: TxSession, card: Suggestion, event: str, correlation_id: str | None
    ) -> None:
        """One audit event by ids only; the transport sets who made the change."""

        self.store.append_audit(
            session,
            actor_id=card.owner_id,
            event=event,
            outcome="success",
            target_type="automation_suggestion",
            target_id=card.id,
            related_id=card.automation_id,
            correlation_id=correlation_id,
        )

    def _count(self, outcome: str, card: Suggestion) -> None:
        self.telemetry.count(
            "sidekick.automations.suggestions", {"effect": card.effect.value, "outcome": outcome}
        )
        LOGGER.info(
            "automation_suggestion_decided",
            extra=safe_log_fields({"automation_suggestion_id": str(card.id), "outcome": outcome}),
        )


def _record(errors: Sequence[tuple[UUID, ItemError | None]]) -> dict[str, Any]:
    """The replay record of a decision: each card's id and the place of its code in the closed
    list. Ids and numbers only, so no text of a card is kept."""

    return {
        "items": [
            {
                "id": str(suggestion_id),
                "code": _ITEM_ERROR_ORDER.index(error) if error is not None else None,
            }
            for suggestion_id, error in errors
        ]
    }

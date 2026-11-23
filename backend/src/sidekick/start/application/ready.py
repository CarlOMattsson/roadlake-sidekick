"""Ready conversations: listing, drafting and changing a schedule, starting and skipping a day.

A ready conversation is the owner's standing prompt for Claude on a schedule (an evening review, a
morning plan). Claude drafts and edits it with the same tools the owner's apps call; nothing here
acts for the owner, so the writes need only `start:write`. Starting one composes its summary from
the owner's records at that moment (`ingredients.compose_ingredients`), marks the day started and
returns the owner's instruction with the blocks; the summary is never stored. Skipping a day, and
undoing the skip, is one row per conversation and day.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from itertools import islice
from typing import Any, Protocol
from uuid import UUID

from sidekick.shared.change_source import current_change_source
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.observability import log_failure
from sidekick.shared.replay import id_replay_record, id_result, record_id
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    Clock,
    IdempotentStore,
    TransactionalStore,
    TxSession,
    UnsetType,
    new_uuid7,
)
from sidekick.start.application.ingredients import (
    IngredientSources,
    compose_ingredients,
)
from sidekick.start.domain.ready import (
    DAY_RETENTION_DAYS,
    MAX_OPEN_CONVERSATIONS,
    DayState,
    Ingredient,
    ReadyBlock,
    ReadyChange,
    ReadyConversation,
    ReadyDay,
    ReadyResult,
    ReadyState,
    change,
    create,
    is_ready,
    skip_day,
    start_day,
)

LOGGER = logging.getLogger(__name__)

READ_SCOPE = "start:read"
WRITE_SCOPE = "start:write"
READY_NOW_LIMIT = 2
"""The most conversations the Start view shows as ready."""


class ReadyStoreProtocol(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def get_conversation(
        self, session: TxSession, owner_id: UUID, conversation_id: UUID, *, lock: bool = ...
    ) -> ReadyConversation: ...
    def list_conversations(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        states: Collection[ReadyState] | None = ...,
        limit: int = ...,
    ) -> list[ReadyConversation]: ...
    def count_open_conversations(self, session: TxSession, owner_id: UUID) -> int: ...
    def save_conversation(
        self,
        session: TxSession,
        conversation: ReadyConversation,
        expected_version: int | None = None,
    ) -> None: ...
    def get_days(self, session: TxSession, owner_id: UUID, day: date) -> dict[UUID, ReadyDay]: ...
    def get_day(
        self, session: TxSession, owner_id: UUID, conversation_id: UUID, day: date
    ) -> ReadyDay | None: ...
    def save_day(self, session: TxSession, owner_id: UUID, value: ReadyDay) -> None: ...
    def prune_days(self, session: TxSession, owner_id: UUID, before: date) -> int: ...


@dataclass(frozen=True, slots=True)
class ReadyView:
    """A conversation with what became of `day` and whether it is ready now."""

    conversation: ReadyConversation
    day: date
    day_state: DayState | None
    ready: bool
    """True only today, from the cadence's time, while neither skipped nor started."""


@dataclass(frozen=True, slots=True)
class StartedConversation:
    view: ReadyView
    blocks: tuple[ReadyBlock, ...]
    unavailable: tuple[Ingredient, ...]
    truncated: bool
    """True when lines had to go to keep the answer within its size."""


class ReadyConversationService:
    def __init__(
        self,
        store: ReadyStoreProtocol,
        clock: Clock,
        zone: tzinfo,
        sources: IngredientSources,
    ) -> None:
        self.store = store
        self.clock = clock
        self.zone = zone
        self.sources = sources

    # --- reads ----------------------------------------------------------------------------

    def _today(self, now: datetime) -> date:
        return now.astimezone(self.zone).date()

    def _view(
        self, conversation: ReadyConversation, now: datetime, day: date, state: DayState | None
    ) -> ReadyView:
        today = self._today(now)
        anchor = conversation.created_at.astimezone(self.zone).date()
        ready = day == today and is_ready(
            conversation,
            anchor=anchor,
            today=today,
            local_now=now.astimezone(self.zone).time().replace(tzinfo=None),
            day_state=state,
        )
        return ReadyView(conversation, day, state, ready)

    def _views_today(
        self,
        session: TxSession,
        owner_id: UUID,
        conversations: list[ReadyConversation],
        now: datetime,
    ) -> list[ReadyView]:
        today = self._today(now)
        days = self.store.get_days(session, owner_id, today)
        return [
            self._view(item, now, today, days[item.id].state if item.id in days else None)
            for item in conversations
        ]

    def list_conversations(
        self, actor: Actor, *, state: ReadyState | None = None
    ) -> list[ReadyView]:
        """The owner's conversations (active and paused unless `state` is given) with today's
        state and whether each is ready now."""

        actor.require(READ_SCOPE)
        now = self.clock.now()
        states = (state,) if state else (ReadyState.ACTIVE, ReadyState.PAUSED)

        def read(session: TxSession) -> list[ReadyView]:
            conversations = self.store.list_conversations(session, actor.user_id, states=states)
            return self._views_today(session, actor.user_id, conversations, now)

        return self.store.transaction(read)

    def ready_now(self, actor: Actor, *, limit: int = READY_NOW_LIMIT) -> list[ReadyView]:
        """The conversations that are ready now, the earliest cadence time first."""

        actor.require(READ_SCOPE)
        now = self.clock.now()

        def read(session: TxSession) -> list[ReadyView]:
            conversations = self.store.list_conversations(
                session, actor.user_id, states=(ReadyState.ACTIVE,)
            )
            views = self._views_today(session, actor.user_id, conversations, now)
            ready = [view for view in views if view.ready]
            ready.sort(
                key=lambda view: (view.conversation.cadence.local_time, view.conversation.id)
            )
            return list(islice(ready, limit))

        return self.store.transaction(read)

    def _read_view(
        self, session: TxSession, owner_id: UUID, conversation_id: UUID, day: date
    ) -> ReadyView:
        conversation = self.store.get_conversation(session, owner_id, conversation_id)
        state = self.store.get_day(session, owner_id, conversation_id, day)
        return self._view(conversation, self.clock.now(), day, state.state if state else None)

    # --- writes ---------------------------------------------------------------------------

    def save(
        self,
        actor: Actor,
        conversation_id: UUID | None,
        *,
        expected_version: int | None,
        requested: ReadyChange,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> ReadyView:
        """Create a conversation (leave out the id), or change one at `expected_version`.

        Pausing, resuming, archiving and restoring are changes too. An archived conversation can
        only be restored.
        """

        actor.require(WRITE_SCOPE)
        if conversation_id is not None and expected_version is None:
            raise ValidationError("expected_version is required to change a ready conversation")

        def operation(session: TxSession) -> dict[str, str]:
            now = self.clock.now()
            if conversation_id is None:
                self._require_room(session, actor.user_id)
                created = create(
                    conversation_id=new_uuid7(),
                    owner_id=actor.user_id,
                    title=requested.title,
                    kind=requested.kind,
                    instruction=(
                        requested.instruction if isinstance(requested.instruction, str) else None
                    ),
                    ingredients=requested.ingredients,
                    cadence=requested.cadence,
                    now=now,
                    source=current_change_source(),
                )
                self._persist(session, actor, created, None, correlation_id)
                return id_result(created.conversation.id)
            current = self.store.get_conversation(
                session, actor.user_id, conversation_id, lock=True
            )
            if current.version != expected_version:
                raise ConflictError("stale ready conversation version", reason="stale_version")
            changed = change(current, requested, now=now, source=current_change_source())
            if (
                current.state is ReadyState.ARCHIVED
                and changed.conversation.state is not ReadyState.ARCHIVED
            ):
                self._require_room(session, actor.user_id)
            self._persist(session, actor, changed, current.version, correlation_id)
            return id_result(conversation_id)

        payload: dict[str, Any] = {
            "conversation_id": str(conversation_id) if conversation_id else None,
            "expected_version": expected_version,
            "title": requested.title,
            "kind": requested.kind.value if requested.kind else None,
            "instruction": (
                "<unset>" if isinstance(requested.instruction, UnsetType) else requested.instruction
            ),
            "ingredients": (
                [item.value for item in requested.ingredients]
                if requested.ingredients is not None
                else None
            ),
            "cadence": requested.cadence.model_dump(mode="json") if requested.cadence else None,
            "paused": requested.paused,
            "archived": requested.archived,
        }
        return self._idempotent(
            actor, "save_ready_conversation", idempotency_key, payload, operation, day=None
        )

    def skip(
        self,
        actor: Actor,
        conversation_id: UUID,
        *,
        day: date | None,
        undo: bool,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> ReadyView:
        """Skip the conversation on `day` (the owner's today when left out), or undo that skip.

        The schedule stays; only that day changes.
        """

        actor.require(WRITE_SCOPE)
        now = self.clock.now()
        target = day or self._today(now)

        def operation(session: TxSession) -> dict[str, str]:
            conversation = self.store.get_conversation(
                session, actor.user_id, conversation_id, lock=True
            )
            current = self.store.get_day(session, actor.user_id, conversation_id, target)
            updated = skip_day(
                conversation,
                current,
                target,
                undo=undo,
                today=self._today(now),
                anchor=conversation.created_at.astimezone(self.zone).date(),
                now=now,
            )
            if updated is not None and updated is not current:
                self._write_day(
                    session,
                    actor,
                    updated,
                    "skip_undone" if undo else "skipped",
                    now,
                    correlation_id,
                )
            return id_result(conversation_id)

        payload = {
            "conversation_id": str(conversation_id),
            "day": target.isoformat(),
            "undo": undo,
        }
        return self._idempotent(
            actor, "skip_ready_conversation", idempotency_key, payload, operation, day=target
        )

    def start(
        self,
        actor: Actor,
        conversation_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> StartedConversation:
        """Mark today started and compose the summary of the ingredients the caller may read.

        Starting the same day again returns a fresh summary and changes nothing more. The summary
        is composed after the day is marked, from the records as they are now.
        """

        actor.require(WRITE_SCOPE)
        now = self.clock.now()
        today = self._today(now)

        def operation(session: TxSession) -> dict[str, str]:
            conversation = self.store.get_conversation(
                session, actor.user_id, conversation_id, lock=True
            )
            current = self.store.get_day(session, actor.user_id, conversation_id, today)
            started = start_day(conversation, current, today, now=now)
            if started is not current:
                self._write_day(session, actor, started, "started", now, correlation_id)
            return id_result(conversation_id)

        view = self._idempotent(
            actor,
            "start_ready_conversation",
            idempotency_key,
            {"conversation_id": str(conversation_id), "day": today.isoformat()},
            operation,
            day=today,
        )

        def note_failure(ingredient: Ingredient, error: Exception) -> None:
            log_failure(
                LOGGER,
                "ready_ingredient_unavailable",
                error,
                correlation_id=correlation_id,
                operation=f"start_ready_conversation.{ingredient.value}",
            )

        composition = compose_ingredients(
            actor, now, self.zone, view.conversation.ingredients, self.sources, note_failure
        )
        return StartedConversation(
            view, composition.blocks, composition.unavailable, composition.truncated
        )

    # --- helpers --------------------------------------------------------------------------

    def _require_room(self, session: TxSession, owner_id: UUID) -> None:
        if self.store.count_open_conversations(session, owner_id) >= MAX_OPEN_CONVERSATIONS:
            raise ValidationError(
                f"at most {MAX_OPEN_CONVERSATIONS} ready conversations can be active or paused"
            )

    def _idempotent(
        self,
        actor: Actor,
        operation_name: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
        operation: Callable[[TxSession], dict[str, str]],
        *,
        day: date | None,
    ) -> ReadyView:
        """Run a write once per key; a retry returns the conversation as it is now."""

        def run(session: TxSession) -> ReadyView:
            record: Mapping[str, object] = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation=operation_name,
                key=idempotency_key,
                payload=dict(payload),
                execute=lambda: operation(session),
                replay=id_replay_record,
            )
            identity = record_id(record)
            when = day or self._today(self.clock.now())
            return self._read_view(session, actor.user_id, identity, when)

        return self.store.transaction(run)

    def _persist(
        self,
        session: TxSession,
        actor: Actor,
        result: ReadyResult,
        expected_version: int | None,
        correlation_id: str | None,
    ) -> None:
        """Save the conversation and audit each event, by id and event name only, never any text."""

        if not result.events:
            return
        self.store.save_conversation(session, result.conversation, expected_version)
        for event in result.events:
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event=f"ready_conversation.{event.value}",
                outcome="success",
                target_type="ready_conversation",
                target_id=result.conversation.id,
                correlation_id=correlation_id,
            )

    def _write_day(
        self,
        session: TxSession,
        actor: Actor,
        value: ReadyDay,
        event: str,
        now: datetime,
        correlation_id: str | None,
    ) -> None:
        """Save the day, drop day rows past their retention and audit the change."""

        self.store.save_day(session, actor.user_id, value)
        self.store.prune_days(
            session, actor.user_id, self._today(now) - timedelta(days=DAY_RETENTION_DAYS)
        )
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event=f"ready_conversation.{event}",
            outcome="success",
            target_type="ready_conversation",
            target_id=value.conversation_id,
            correlation_id=correlation_id,
        )

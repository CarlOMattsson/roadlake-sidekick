"""The registry of automations: reading it, drafting and changing an automation, and its approval.

The owner's Claude drafts an automation (`save_automation`); only the owner approves it, in the
app, and the approval is bound to the exact digest of the spec the owner was shown. A change to the
spec withdraws the approval, so a model can never widen what an approved automation does. Nothing
here runs an automation.
"""

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sidekick.automations.domain.automation import Automation
from sidekick.automations.domain.registry import (
    RegistryChange,
    RegistryResult,
    approve_current,
    change,
    create,
)
from sidekick.automations.domain.spec import (
    MICROUSD_PER_USD,
    AutomationState,
    required_write_scopes,
)
from sidekick.shared.config import Settings
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.replay import id_replay_record, id_result, record_id
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    Clock,
    CursorCodec,
    IdempotentStore,
    Page,
    TransactionalStore,
    TxSession,
    new_uuid7,
    paginate,
    validate_limit,
)

READ_SCOPE = "automation:read"
WRITE_SCOPE = "automation:write"
MAX_PAGE = 50
LISTED_BY_DEFAULT = (AutomationState.DRAFT, AutomationState.ACTIVE, AutomationState.PAUSED)
"""Archived automations are listed only when asked for by state."""


class AutomationRegistryStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def get_automation(
        self, session: TxSession, owner_id: UUID, automation_id: UUID
    ) -> Automation: ...
    def list_automations(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        states: Collection[AutomationState] | None = None,
        limit: int = ...,
        offset: int = 0,
    ) -> list[Automation]: ...
    def pending_suggestion_counts(
        self, session: TxSession, owner_id: UUID, automation_ids: Collection[UUID]
    ) -> dict[UUID, int]: ...
    def save_automation(
        self, session: TxSession, automation: Automation, expected_version: int | None = None
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AutomationView:
    """An automation as the registry reads it, with what is waiting on it."""

    automation: Automation
    pending_suggestions: int


class AutomationRegistryService:
    def __init__(
        self,
        store: AutomationRegistryStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        *,
        run_budget_cap_microusd: int,
    ) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec
        self.run_budget_cap_microusd = run_budget_cap_microusd

    @classmethod
    def from_settings(
        cls,
        store: AutomationRegistryStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        settings: Settings,
    ) -> "AutomationRegistryService":
        return cls(
            store,
            clock,
            cursor_codec,
            run_budget_cap_microusd=round(
                settings.ai_automation_monthly_cap_usd * MICROUSD_PER_USD
            ),
        )

    def _view(self, session: TxSession, owner_id: UUID, automation_id: UUID) -> AutomationView:
        automation = self.store.get_automation(session, owner_id, automation_id)
        counts = self.store.pending_suggestion_counts(session, owner_id, [automation_id])
        return AutomationView(automation, counts.get(automation_id, 0))

    def get(self, actor: Actor, automation_id: UUID) -> AutomationView:
        actor.require(READ_SCOPE)
        return self.store.transaction(lambda s: self._view(s, actor.user_id, automation_id))

    def list(
        self,
        actor: Actor,
        *,
        state: AutomationState | None = None,
        limit: int = 25,
        cursor: str | None = None,
    ) -> Page[AutomationView]:
        actor.require(READ_SCOPE)
        validate_limit(limit, maximum=MAX_PAGE)
        key = f"automations:v1:state={state.value if state else '*'}"
        offset = self.cursor_codec.decode(actor.user_id, cursor, key)
        states = (state,) if state else LISTED_BY_DEFAULT

        def read(session: TxSession) -> Page[AutomationView]:
            rows = self.store.list_automations(
                session, actor.user_id, states=states, limit=limit + 1, offset=offset
            )
            page, more = paginate(
                rows, limit, lambda _: self.cursor_codec.encode(actor.user_id, offset + limit, key)
            )
            counts = self.store.pending_suggestion_counts(
                session, actor.user_id, [item.id for item in page]
            )
            return Page([AutomationView(item, counts.get(item.id, 0)) for item in page], more)

        return self.store.transaction(read)

    def save(
        self,
        actor: Actor,
        automation_id: UUID | None,
        *,
        expected_version: int | None,
        requested: RegistryChange,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> AutomationView:
        """Draft a new automation, or change one at `expected_version`.

        A change to the spec withdraws the owner's approval. Returns the automation as it is now.
        """

        actor.require(WRITE_SCOPE)
        if automation_id is not None and expected_version is None:
            raise ValidationError("expected_version is required to change an automation")

        def operation(session: TxSession) -> dict[str, str]:
            now = self.clock.now()
            if automation_id is None:
                created = create(
                    automation_id=new_uuid7(),
                    owner_id=actor.user_id,
                    title=requested.title,
                    spec_fields=requested.spec_fields,
                    run_budget_cap_microusd=self.run_budget_cap_microusd,
                    now=now,
                )
                self._persist(session, actor, created, None, correlation_id)
                return id_result(created.automation.id)
            current = self.store.get_automation(session, actor.user_id, automation_id)
            if current.version != expected_version:
                raise ConflictError("stale automation version", reason="stale_version")
            changed = change(
                current, requested, run_budget_cap_microusd=self.run_budget_cap_microusd, now=now
            )
            self._persist(session, actor, changed, current.version, correlation_id)
            return id_result(automation_id)

        payload: dict[str, Any] = {
            "automation_id": str(automation_id) if automation_id else None,
            "expected_version": expected_version,
            "title": requested.title,
            "spec_fields": dict(requested.spec_fields),
            "paused": requested.paused,
            "archived": requested.archived,
        }
        return self._idempotent(actor, "save_automation", idempotency_key, payload, operation)

    def approve(
        self,
        actor: Actor,
        automation_id: UUID,
        *,
        spec_digest: str,
        idempotency_key: str,
        auto_apply_confirmed: bool = False,
        correlation_id: str | None = None,
    ) -> AutomationView:
        """Approve the automation whose spec has this digest.

        The actor also needs the write scope of every effect the automation may propose. The
        digest is what the owner saw: a spec that changed since is refused. A spec that applies
        suggestions without a click is approved only with `auto_apply_confirmed`.
        """

        actor.require(WRITE_SCOPE)

        def operation(session: TxSession) -> dict[str, str]:
            current = self.store.get_automation(session, actor.user_id, automation_id)
            for scope in sorted(required_write_scopes(current.spec)):
                actor.require(scope)
            approved = approve_current(
                current,
                spec_digest,
                run_budget_cap_microusd=self.run_budget_cap_microusd,
                now=self.clock.now(),
                auto_apply_confirmed=auto_apply_confirmed,
            )
            self._persist(session, actor, approved, current.version, correlation_id)
            return id_result(automation_id)

        payload = {
            "automation_id": str(automation_id),
            "spec_digest": spec_digest,
            "auto_apply_confirmed": auto_apply_confirmed,
        }
        return self._idempotent(actor, "approve_automation", idempotency_key, payload, operation)

    def _idempotent(
        self,
        actor: Actor,
        operation_name: str,
        idempotency_key: str,
        payload: dict[str, Any],
        operation: Callable[[TxSession], dict[str, str]],
    ) -> AutomationView:
        """Run a write once per key; a retry returns the automation as it is now."""

        def run(session: TxSession) -> AutomationView:
            record: Mapping[str, object] = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation=operation_name,
                key=idempotency_key,
                payload=payload,
                execute=lambda: operation(session),
                replay=id_replay_record,
            )
            return self._view(session, actor.user_id, record_id(record))

        return self.store.transaction(run)

    def _persist(
        self,
        session: TxSession,
        actor: Actor,
        result: RegistryResult,
        expected_version: int | None,
        correlation_id: str | None,
    ) -> None:
        """Save the automation and audit each event, by id and event name only, never any text."""

        if not result.events:
            return
        self.store.save_automation(session, result.automation, expected_version)
        for event in result.events:
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event=f"automation.{event.value}",
                outcome="success",
                target_type="automation",
                target_id=result.automation.id,
                correlation_id=correlation_id,
            )

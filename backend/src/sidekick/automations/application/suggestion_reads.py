"""Reading suggestions: the owner's inbox of proposals, its groups, and one card in full.

A suggestion's text was written by an AI from untrusted sources. It is read here exactly as stored
(already normalised and inert) and never changed, and a reader sees a payload only when it holds
the read scope of the domain the effect would write to: a card of another domain is counted, not
shown. Whether a card is in the high-confidence group is worked out from the card, the
automation's current thresholds and the run's state when it is read, never taken from the stored
flag alone.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sidekick.automations.domain.automation import Automation, SuggestionCheck
from sidekick.automations.domain.datapoints import Datapoint
from sidekick.automations.domain.effects import CATALOGUE, EffectKind
from sidekick.automations.domain.grouping import (
    MAX_GROUP_SIZE,
    BulkBlocker,
    bulk_blockers,
    group_digest,
)
from sidekick.automations.domain.runs import AutomationRun, RunState
from sidekick.automations.domain.suggestion import Suggestion, SuggestionState
from sidekick.shared.types import (
    Actor,
    Clock,
    CursorCodec,
    Page,
    TransactionalStore,
    TxSession,
    paginate,
    validate_limit,
)

READ_SCOPE = "automation:read"
MAX_PAGE = 25
MAX_AUTO_APPLIED = 50
"""The most auto-applied cards one read returns."""
MAX_CANDIDATES = 200
"""The most eligible cards one read looks at when it builds the groups."""


class GroupFilter(StrEnum):
    HIGH_CONFIDENCE = "high_confidence"
    SINGLE = "single"
    ALL = "all"


class SuggestionReadStore(TransactionalStore, Protocol):
    def get_automation(
        self, session: TxSession, owner_id: UUID, automation_id: UUID, *, lock: bool = False
    ) -> Automation: ...
    def get_run(
        self, session: TxSession, owner_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> AutomationRun: ...
    def get_suggestion(
        self, session: TxSession, owner_id: UUID, suggestion_id: UUID, *, lock: bool = False
    ) -> Suggestion: ...
    def list_suggestions(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        states: Collection[SuggestionState] | None = None,
        automation_id: UUID | None = None,
        run_id: UUID | None = None,
        bulk_eligible: bool | None = None,
        expires_after: datetime | None = None,
        limit: int = ...,
        offset: int = 0,
    ) -> list[Suggestion]: ...
    def list_auto_applied(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        since: datetime | None = None,
        automation_id: UUID | None = None,
        limit: int = ...,
    ) -> list[Suggestion]: ...
    def list_checks(
        self, session: TxSession, owner_id: UUID, suggestion_id: UUID
    ) -> list[SuggestionCheck]: ...
    def get_datapoints(
        self, session: TxSession, owner_id: UUID, datapoint_ids: Collection[UUID]
    ) -> list[Datapoint]: ...


class Lookup:
    """The automations and runs of one transaction, each read once."""

    def __init__(self, store: SuggestionReadStore, session: TxSession, owner_id: UUID) -> None:
        self._store = store
        self._session = session
        self._owner_id = owner_id
        self._automations: dict[UUID, Automation] = {}
        self._runs: dict[UUID, AutomationRun] = {}

    def automation(self, automation_id: UUID) -> Automation:
        if automation_id not in self._automations:
            self._automations[automation_id] = self._store.get_automation(
                self._session, self._owner_id, automation_id
            )
        return self._automations[automation_id]

    def run_done(self, run_id: UUID) -> bool:
        if run_id not in self._runs:
            self._runs[run_id] = self._store.get_run(self._session, self._owner_id, run_id)
        return self._runs[run_id].state is RunState.DONE

    def blockers(self, suggestion: Suggestion) -> tuple[BulkBlocker, ...]:
        """Why the card is not in the high-confidence group; empty when it is."""

        return bulk_blockers(
            suggestion,
            self.automation(suggestion.automation_id).spec,
            run_done=self.run_done(suggestion.run_id),
        )


@dataclass(frozen=True, slots=True)
class SuggestionView:
    """A card as the owner reads it, with the title of the automation it came from."""

    suggestion: Suggestion
    automation_title: str
    source_label: str | None
    blockers: tuple[BulkBlocker, ...]

    @property
    def bulk_eligible(self) -> bool:
        return not self.blockers


@dataclass(frozen=True, slots=True)
class SuggestionGroup:
    """The cards of one automation that may be approved together, and what the owner saw of them.

    `digest` covers exactly `suggestion_ids` at their current versions; approving the group
    presents it back."""

    automation_id: UUID
    automation_title: str
    suggestion_ids: tuple[UUID, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class SuggestionList:
    page: Page[SuggestionView]
    groups: tuple[SuggestionGroup, ...]
    hidden: int
    """Cards on this page of a domain the reader may not read."""


@dataclass(frozen=True, slots=True)
class AutoAppliedList:
    """What the opt-in policy applied, newest first. A card that is still `applied` can be undone
    by the owner; one that is `undone` shows that it was."""

    items: tuple[SuggestionView, ...]
    hidden: int
    """Cards of a domain the reader may not read: counted, not shown."""


@dataclass(frozen=True, slots=True)
class SuggestionDetail:
    view: SuggestionView
    datapoints: tuple[Datapoint, ...]
    checks: tuple[SuggestionCheck, ...]


def readable_effects(actor: Actor) -> frozenset[EffectKind]:
    """The effects whose payload the actor may read."""

    return frozenset(kind for kind, entry in CATALOGUE.items() if entry.read_scope in actor.scopes)


class SuggestionReads:
    def __init__(self, store: SuggestionReadStore, clock: Clock, cursor_codec: CursorCodec) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec

    def list_suggestions(
        self,
        actor: Actor,
        *,
        state: SuggestionState = SuggestionState.PENDING,
        automation_id: UUID | None = None,
        group: GroupFilter = GroupFilter.ALL,
        limit: int = MAX_PAGE,
        cursor: str | None = None,
    ) -> SuggestionList:
        """One page of the owner's suggestions, oldest first, and the groups of the eligible ones.

        The group filter reads the eligibility stored with each card; every card shown carries
        the eligibility worked out now.
        """

        actor.require(READ_SCOPE)
        validate_limit(limit, maximum=MAX_PAGE)
        key = f"suggestions:v1:{state.value}:{automation_id or '*'}:{group.value}"
        offset = self.cursor_codec.decode(actor.user_id, cursor, key)
        stored = {GroupFilter.HIGH_CONFIDENCE: True, GroupFilter.SINGLE: False}.get(group)

        def read(session: TxSession) -> SuggestionList:
            now = self.clock.now()
            pending = state is SuggestionState.PENDING
            rows = self.store.list_suggestions(
                session,
                actor.user_id,
                states=(state,),
                automation_id=automation_id,
                bulk_eligible=stored,
                expires_after=now if pending else None,
                limit=limit + 1,
                offset=offset,
            )
            cards, next_cursor = paginate(
                rows, limit, lambda _: self.cursor_codec.encode(actor.user_id, offset + limit, key)
            )
            readable = readable_effects(actor)
            shown = [card for card in cards if card.effect in readable]
            lookup = Lookup(self.store, session, actor.user_id)
            views = self._views(session, actor.user_id, lookup, shown)
            if group is GroupFilter.HIGH_CONFIDENCE:
                views = [view for view in views if view.bulk_eligible]
            groups = (
                self._groups(session, actor, lookup, automation_id, now)
                if pending and group is not GroupFilter.SINGLE
                else ()
            )
            return SuggestionList(Page(views, next_cursor), groups, len(cards) - len(shown))

        return self.store.transaction(read)

    def list_auto_applied(
        self,
        actor: Actor,
        *,
        since: datetime | None = None,
        automation_id: UUID | None = None,
        limit: int = MAX_AUTO_APPLIED,
    ) -> AutoAppliedList:
        """The suggestions the policy applied after `since` (all when None), newest first.

        This is what a report lists as applied without the owner, each with its undo. Text of a
        card is shown only to a reader of the domain the card wrote to.
        """

        actor.require(READ_SCOPE)
        validate_limit(limit, maximum=MAX_AUTO_APPLIED)

        def read(session: TxSession) -> AutoAppliedList:
            cards = self.store.list_auto_applied(
                session, actor.user_id, since=since, automation_id=automation_id, limit=limit
            )
            readable = readable_effects(actor)
            shown = [card for card in cards if card.effect in readable]
            lookup = Lookup(self.store, session, actor.user_id)
            views = self._views(session, actor.user_id, lookup, shown)
            return AutoAppliedList(tuple(views), len(cards) - len(shown))

        return self.store.transaction(read)

    def get(self, actor: Actor, suggestion_id: UUID) -> SuggestionDetail:
        """One suggestion in full: payload, rationale, the datapoints it rests on and its checks."""

        actor.require(READ_SCOPE)

        def read(session: TxSession) -> SuggestionDetail:
            card = self.store.get_suggestion(session, actor.user_id, suggestion_id)
            actor.require(CATALOGUE[card.effect].read_scope)
            lookup = Lookup(self.store, session, actor.user_id)
            (view,) = self._views(session, actor.user_id, lookup, [card])
            points = self.store.get_datapoints(session, actor.user_id, card.datapoint_ids)
            checks = self.store.list_checks(session, actor.user_id, card.id)
            return SuggestionDetail(view, tuple(points), tuple(checks))

        return self.store.transaction(read)

    def _views(
        self, session: TxSession, owner_id: UUID, lookup: Lookup, cards: Sequence[Suggestion]
    ) -> list[SuggestionView]:
        ids = {point_id for card in cards for point_id in card.datapoint_ids}
        labels = {
            point.id: point.source_label
            for point in self.store.get_datapoints(session, owner_id, ids)
        }
        return [
            SuggestionView(
                card,
                lookup.automation(card.automation_id).title,
                next((labels[ref] for ref in card.datapoint_ids if labels.get(ref)), None),
                lookup.blockers(card),
            )
            for card in cards
        ]

    def _groups(
        self,
        session: TxSession,
        actor: Actor,
        lookup: Lookup,
        automation_id: UUID | None,
        now: datetime,
    ) -> tuple[SuggestionGroup, ...]:
        """The cards that may be approved together now, grouped by automation."""

        readable = readable_effects(actor)
        candidates = self.store.list_suggestions(
            session,
            actor.user_id,
            states=(SuggestionState.PENDING,),
            automation_id=automation_id,
            bulk_eligible=True,
            expires_after=now,
            limit=MAX_CANDIDATES,
        )
        members: dict[UUID, list[Suggestion]] = {}
        for card in candidates:
            if card.effect in readable and not lookup.blockers(card):
                members.setdefault(card.automation_id, []).append(card)
        return tuple(
            SuggestionGroup(
                group_automation,
                lookup.automation(group_automation).title,
                tuple(card.id for card in cards[:MAX_GROUP_SIZE]),
                group_digest(cards[:MAX_GROUP_SIZE]),
            )
            for group_automation, cards in members.items()
        )

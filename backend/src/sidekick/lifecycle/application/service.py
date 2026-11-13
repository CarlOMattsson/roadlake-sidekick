"""Owner-scoped archive/trash lifecycle without a generic mutation framework."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sidekick.lifecycle.domain import (
    ChangeAction,
    ChangeActor,
    ChangeRecordView,
    RecentChange,
    RecordKind,
    TrashItem,
    TrashPosition,
)
from sidekick.shared.errors import ValidationError
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale
from sidekick.shared.replay import id_replay_record
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    Clock,
    CursorCodec,
    IdempotentStore,
    Page,
    TransactionalStore,
    TxSession,
    paginate,
    validate_limit,
)

CHANGE_MAX_SCAN = 200
"""Audit rows read per call before the owner's change list is cut to the requested limit."""

#: Audit events that are owner-visible changes, mapped to (record kind, action). Journal sources
#: are left out on purpose: their only text is the raw source, which must never be echoed.
CHANGE_EVENTS: dict[str, tuple[str, ChangeAction]] = {
    "task.created": ("task", "created"),
    "task.updated": ("task", "updated"),
    "task.completed": ("task", "completed"),
    "task.archived": ("task", "archived"),
    "task.restored": ("task", "restored"),
    "project.created": ("project", "created"),
    "project.updated": ("project", "updated"),
    "project.completed": ("project", "completed"),
    "project.archived": ("project", "archived"),
    "project.restored": ("project", "restored"),
    "contact.created": ("contact", "created"),
    "contact.updated": ("contact", "updated"),
    "contact.archived": ("contact", "archived"),
    "contact.restored": ("contact", "restored"),
    # Alias and link rows carry the record id that is read (alias id, contact id, reference id)
    # and, for link events, the related id (task or project) that names the other side. Rows
    # without a related id keep the old text; alias removals without one are left out.
    "contact.alias_added": ("contact_alias", "created"),
    "contact.alias_removed": ("contact_alias_removed", "updated"),
    "contact.task_linked": ("contact_task_link", "created"),
    "contact.task_unlinked": ("contact_link", "updated"),
    "contact.project_linked": ("contact_project_link", "created"),
    "contact.project_unlinked": ("contact_link", "updated"),
    "external_reference.linked": ("external_reference_link", "created"),
    "external_reference.unlinked": ("external_reference", "updated"),
    "journal.manual_entry_created": ("journal_entry", "created"),
    "journal.entry_updated": ("journal_entry", "updated"),
    "shopping.list_created": ("shopping_list", "created"),
    "shopping.list_updated": ("shopping_list", "updated"),
    "shopping.item_added": ("shopping_item", "created"),
    "shopping.item_updated": ("shopping_item", "updated"),
    # A purchase bumps the item's version, and a purchase is the item's newest event, so the row
    # shows the version after the action: the one the opposite `set_shopping_item_purchased`
    # call must carry.
    "shopping.item_purchased": ("shopping_item", "purchased"),
    "shopping.item_reopened": ("shopping_item", "reopened"),
}
for _kind in RecordKind:
    if _kind is not RecordKind.JOURNAL_SOURCE:
        CHANGE_EVENTS[f"{_kind.value}.trashed"] = (_kind.value, "trashed")
        CHANGE_EVENTS[f"{_kind.value}.restored"] = (_kind.value, "restored")

T = TypeVar("T")


class LifecycleStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def list_trash(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        kinds: frozenset[RecordKind],
        limit: int,
        after: TrashPosition | None = None,
    ) -> list[TrashItem]: ...

    def set_trashed(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
        trashed: bool,
        now: Any,
    ) -> TrashItem: ...

    def get_trash_item(
        self, session: TxSession, owner_id: UUID, kind: RecordKind, record_id: UUID
    ) -> TrashItem: ...

    def permanently_remove(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
    ) -> None: ...

    def list_trash_owner_ids(self, session: TxSession) -> list[UUID]: ...

    def list_change_audit(
        self, session: TxSession, owner_id: UUID, *, events: frozenset[str], limit: int
    ) -> list[tuple[str, UUID, UUID | None, datetime, str | None]]: ...

    def load_change_records(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: str,
        keys: frozenset[tuple[UUID, UUID | None]],
        locale: AppLocale,
    ) -> dict[tuple[UUID, UUID | None], ChangeRecordView]: ...


_READ_SCOPE = {
    RecordKind.DOMAIN: "projects:read",
    RecordKind.PROCESS: "projects:read",
    RecordKind.PROJECT: "projects:read",
    RecordKind.TASK: "tasks:read",
    RecordKind.STEP: "tasks:read",
    RecordKind.ACTION: "tasks:read",
    RecordKind.CONTACT: "contacts:read",
    RecordKind.JOURNAL_SOURCE: "journal:read",
    RecordKind.JOURNAL_ENTRY: "journal:read",
    RecordKind.SHOPPING_ITEM: "shopping:read",
}
_WRITE_SCOPE = {
    RecordKind.DOMAIN: "projects:write",
    RecordKind.PROCESS: "projects:write",
    RecordKind.PROJECT: "projects:write",
    RecordKind.TASK: "tasks:write",
    RecordKind.STEP: "tasks:write",
    RecordKind.ACTION: "tasks:write",
    RecordKind.CONTACT: "contacts:write",
    RecordKind.JOURNAL_SOURCE: "journal:write",
    RecordKind.JOURNAL_ENTRY: "journal:write",
    RecordKind.SHOPPING_ITEM: "shopping:write",
}
#: The read and the write scopes of the lifecycle kinds (also read by the MCP tool reference).
READ_SCOPES = frozenset(_READ_SCOPE.values())
WRITE_SCOPES = frozenset(_WRITE_SCOPE.values())
#: Every read and write scope of the lifecycle kinds, for the operator sweep that acts for owners.
LIFECYCLE_SCOPES = READ_SCOPES | WRITE_SCOPES
#: Every scope a kind needs to be shown: a link names both of its sides, so it needs both reads.
_CHANGE_SCOPE: dict[str, tuple[str, ...]] = {
    **{kind.value: (scope,) for kind, scope in _READ_SCOPE.items()},
    "shopping_list": ("shopping:read",),
    "contact_alias": ("contacts:read",),
    "contact_alias_removed": ("contacts:read",),
    "contact_link": ("contacts:read",),
    "contact_task_link": ("contacts:read", "tasks:read"),
    "contact_project_link": ("contacts:read", "projects:read"),
    "external_reference": ("tasks:read",),
    "external_reference_link": ("tasks:read",),
}
#: Every read scope the change list can use, each for the kinds that need it.
CHANGE_SCOPES = frozenset(scope for scopes in _CHANGE_SCOPE.values() for scope in scopes)
#: The model-visible undo of a purchase or put-back: the same tool with the opposite value. The
#: link undo tools (`unlink_*`) are app-only and are never named; the text says "undo in the app".
# The stored audit source mapped to the actor a change reports; a missing source is unknown.
_ACTORS: dict[str | None, ChangeActor] = {"you": "you", "claude": "claude"}

_UNDO_TOOL: dict[tuple[str, ChangeAction], str] = {
    ("shopping_item", "purchased"): "set_shopping_item_purchased",
    ("shopping_item", "reopened"): "set_shopping_item_purchased",
}


class RecordLifecycleService:
    """Trash is a state transition; permanent removal is a guarded terminal action."""

    def __init__(
        self,
        store: LifecycleStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        *,
        contact_removal_guard: Callable[[Any, UUID, UUID], None] | None = None,
        task_removal_hook: Callable[[Any, UUID, UUID], None] | None = None,
        locale: AppLocale = DEFAULT_LOCALE,
    ) -> None:
        self.locale: AppLocale = locale
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec
        self.contact_removal_guard = contact_removal_guard
        self.task_removal_hook = task_removal_hook

    def list_trash(
        self,
        actor: Actor,
        *,
        kind: RecordKind | None = None,
        limit: int = 100,
        within: frozenset[RecordKind] | None = None,
        cursor: str | None = None,
    ) -> Page[TrashItem]:
        """One page of the owner's trash, newest first, continued with the cursor of the last page.

        The cursor is a keyset over (trashed_at, kind, id), bound to the owner and the kind and
        scope filters, so a record restored or trashed between pages never shifts the next page.
        """

        actor.require(_READ_SCOPE[kind] if kind else "projects:read")
        validate_limit(
            limit,
            maximum=100,
            message="trash limit must be between 1 and 100",
            error=ValidationError,
        )
        # The readable kinds are narrowed in the query, so rows of an unreadable kind can never
        # fill the page and hide readable records behind the limit. `within` narrows the same way
        # for callers that expose only a subset of kinds (e.g. the MCP surface).
        allowed = frozenset(
            k
            for k in RecordKind
            if _READ_SCOPE[k] in actor.scopes and (within is None or k in within)
        )
        kinds = allowed if kind is None else frozenset({kind}) & allowed
        query_key = "trash:v1:kinds=" + ",".join(sorted(k.value for k in kinds))
        after = self._decode_position(actor, cursor, query_key)
        items = self.store.transaction(
            lambda session: self.store.list_trash(
                session, actor.user_id, kinds=kinds, limit=limit + 1, after=after
            )
        )
        return Page(
            *paginate(
                items,
                limit,
                lambda last: self.cursor_codec.encode_position(
                    actor.user_id, TrashPosition.of(last).to_token(), query_key
                ),
            )
        )

    def _decode_position(
        self, actor: Actor, cursor: str | None, query_key: str
    ) -> TrashPosition | None:
        try:
            token = self.cursor_codec.decode_position(actor.user_id, cursor, query_key)
            return None if token is None else TrashPosition.from_token(token)
        except ValueError as error:
            raise ValidationError("invalid pagination cursor") from error

    def list_recent_changes(self, actor: Actor, *, limit: int = 5) -> list[RecentChange]:
        """The owner's newest changes, newest first, over every kind the actor may read.

        Events come from the audit trail; the title and version are read from the record now, so
        the audit text never reaches the caller. A kind without its read scope, or a record that
        is gone, is left out without an error. Each record appears once, with its newest event, so
        several edits of one record do not fill the limit.
        """

        validate_limit(
            limit,
            maximum=20,
            message="change limit must be between 1 and 20",
            error=ValidationError,
        )
        readable = frozenset(
            kind
            for kind, scopes in _CHANGE_SCOPE.items()
            if all(scope in actor.scopes for scope in scopes)
        )

        def operation(session: TxSession) -> list[RecentChange]:
            # The SQL LIMIT (CHANGE_MAX_SCAN = 200) is applied before the read-scope filter below
            # and before the per-record dedup, so unreadable kinds use up scan rows and the answer
            # can hold fewer than `limit` changes even when more readable history exists.
            audit = self.store.list_change_audit(
                session, actor.user_id, events=frozenset(CHANGE_EVENTS), limit=CHANGE_MAX_SCAN
            )
            entries: list[tuple[str, ChangeAction, UUID, UUID | None, datetime, ChangeActor]] = []
            keys_by_kind: dict[str, set[tuple[UUID, UUID | None]]] = {}
            # A link is one record per (kind, record, related), so repeated edits of one link merge.
            seen: set[tuple[str, UUID, UUID | None]] = set()
            for event, record_id, related_id, occurred_at, source in audit:
                kind, action = CHANGE_EVENTS[event]
                if kind not in readable:
                    continue
                # Audit rows are newest first, so the first row per record is its latest change.
                if (kind, record_id, related_id) in seen:
                    continue
                seen.add((kind, record_id, related_id))
                entries.append(
                    (
                        kind,
                        action,
                        record_id,
                        related_id,
                        occurred_at,
                        _ACTORS.get(source, "unknown"),
                    )
                )
                keys_by_kind.setdefault(kind, set()).add((record_id, related_id))
            views: dict[tuple[str, UUID, UUID | None], ChangeRecordView] = {}
            for kind, keys in keys_by_kind.items():
                loaded = self.store.load_change_records(
                    session, actor.user_id, kind, frozenset(keys), self.locale
                )
                views.update(
                    {
                        (kind, record_id, related_id): view
                        for (record_id, related_id), view in loaded.items()
                    }
                )
            changes: list[RecentChange] = []
            for kind, action, record_id, related_id, occurred_at, actor_kind in entries:
                view = views.get((kind, record_id, related_id))
                if view is None:
                    continue
                changes.append(
                    RecentChange(
                        kind=kind,
                        id=record_id,
                        title=view.title,
                        version=view.version,
                        action=action,
                        state="trashed" if view.trashed else "active",
                        occurred_at=occurred_at,
                        related_id=related_id,
                        actor=actor_kind,
                        undo_tool=_UNDO_TOOL.get((kind, action)),
                    )
                )
                if len(changes) == limit:
                    break
            return changes

        return self.store.transaction(operation)

    def trash(
        self,
        actor: Actor,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> TrashItem:
        return self._transition(
            actor,
            kind,
            record_id,
            version=version,
            trashed=True,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def restore(
        self,
        actor: Actor,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> TrashItem:
        return self._transition(
            actor,
            kind,
            record_id,
            version=version,
            trashed=False,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def permanently_remove(
        self,
        actor: Actor,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> None:
        actor.require(_WRITE_SCOPE[kind])
        if kind in {RecordKind.SHOPPING_ITEM, RecordKind.JOURNAL_ENTRY}:
            # The application role holds no DELETE on these tables (the shopping tables and
            # `journal_entries`, 0.1.0 baseline), so refuse here with a safe error instead of
            # letting the database reject the statement.
            label = "shopping items" if kind is RecordKind.SHOPPING_ITEM else "journal entries"
            raise ValidationError(f"{label} cannot be removed permanently")
        payload = {"kind": kind.value, "record_id": str(record_id), "version": version}

        def operation(session: TxSession) -> dict[str, Any]:
            if kind is RecordKind.CONTACT and self.contact_removal_guard is not None:
                self.contact_removal_guard(session, actor.user_id, record_id)
            if kind is RecordKind.TASK and self.task_removal_hook is not None:
                # Releases pointers that only this Task used, in the same transaction.
                self.task_removal_hook(session, actor.user_id, record_id)
            self.store.permanently_remove(session, actor.user_id, kind, record_id, version=version)
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event=f"{kind.value}.permanently_removed",
                outcome="success",
                target_type=kind.value,
                target_id=record_id,
                correlation_id=correlation_id,
            )
            return {"removed": True}

        self.store.transaction(
            lambda session: self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="permanently_remove_record",
                key=idempotency_key,
                payload=payload,
                execute=lambda: operation(session),
            )
        )

    def _transition(
        self,
        actor: Actor,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
        trashed: bool,
        idempotency_key: str,
        correlation_id: str | None,
    ) -> TrashItem:
        actor.require(_WRITE_SCOPE[kind])
        payload = {
            "kind": kind.value,
            "record_id": str(record_id),
            "version": version,
            "trashed": trashed,
        }

        def operation(session: TxSession) -> dict[str, Any]:
            item = self.store.set_trashed(
                session,
                actor.user_id,
                kind,
                record_id,
                version=version,
                trashed=trashed,
                now=self.clock.now(),
            )
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event=f"{kind.value}.{'trashed' if trashed else 'restored'}",
                outcome="success",
                target_type=kind.value,
                target_id=record_id,
                correlation_id=correlation_id,
            )
            return {
                "kind": item.kind.value,
                "id": str(item.id),
                "label": item.label,
                "trashed_at": item.trashed_at.isoformat() if item.trashed_at else None,
                "version": item.version,
            }

        def replayed(session: TxSession) -> TrashItem:
            record = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="trash_record" if trashed else "restore_record",
                key=idempotency_key,
                payload=payload,
                execute=lambda: operation(session),
                replay=id_replay_record,
            )
            # The record keeps only the id; kind and label are read again, so a retry shows the
            # record as it is now.
            return self.store.get_trash_item(session, actor.user_id, kind, UUID(record["id"]))

        return self.store.transaction(replayed)

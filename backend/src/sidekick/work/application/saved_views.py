"""Validated, non-executable saved Work view use cases."""

import json
from typing import Any, Protocol, TypeVar, cast
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.shared.replay import id_replay_record
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    Clock,
    IdempotentStore,
    TransactionalStore,
    TxSession,
    new_uuid7,
)
from sidekick.work.domain.saved_view import SavedView

T = TypeVar("T")
MAX_BYTES = 8192
ALLOWED = {
    "name",
    "view",
    "context",
    "status",
    "priority",
    "priorities",
    "attention",
    "archive",
    "kind",
    "q",
    "sort",
    "group",
    "version",
    # Planning filters: a saved view may name them, never anything executable.
    "tags",
    "tag_match",
    "actionable",
    "waiting",
    "estimate",
}
MAX_SAVED_VIEW_TAGS = 5


class SavedViewStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def list_saved_views(
        self, session: TxSession, owner_id: UUID, include_archived: bool = False
    ) -> list[SavedView]: ...
    def get_saved_view(self, session: TxSession, owner_id: UUID, view_id: UUID) -> SavedView: ...
    def save_saved_view(
        self, session: TxSession, item: SavedView, expected_version: int | None = None
    ) -> None: ...


def validate_definition(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) - ALLOWED:
        raise ValidationError("saved view contains unsupported fields")
    if value.get("view") not in {"dashboard", "hierarchy", "list", "board", "agenda"}:
        raise ValidationError("saved view has an invalid view")
    if value.get("context") not in {"all", "domain", "process", "project", "task"}:
        raise ValidationError("saved view has an invalid context")
    if "actionable" in value and value["actionable"] not in {"all", "now", "later"}:
        raise ValidationError("saved view has an invalid actionable filter")
    if "waiting" in value and value["waiting"] not in {"all", "waiting", "not_waiting"}:
        raise ValidationError("saved view has an invalid waiting filter")
    if "estimate" in value and value["estimate"] not in {"all", "estimated", "unestimated"}:
        raise ValidationError("saved view has an invalid estimate filter")
    if "tag_match" in value and value["tag_match"] not in {"any", "all"}:
        raise ValidationError("saved view has an invalid tag match mode")
    tags = value.get("tags")
    if tags is not None:
        if not isinstance(tags, list):
            raise ValidationError("saved view tags must be a list of slugs")
        slugs = cast(list[object], tags)
        if not all(isinstance(item, str) for item in slugs):
            raise ValidationError("saved view tags must be a list of slugs")
        if len(slugs) > MAX_SAVED_VIEW_TAGS:
            raise ValidationError("saved view names too many tags")
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode()) > MAX_BYTES:
        raise ValidationError("saved view is too large")
    return value


class SavedViewService:
    def __init__(self, store: SavedViewStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    def _replayed(self, session: TxSession, actor: Actor, record: dict[str, Any]) -> SavedView:
        """The saved view a (possibly replayed) write refers to, re-read by id.

        The idempotency record keeps only the id, so a retry returns the view as it is now.
        """

        return self.store.get_saved_view(session, actor.user_id, UUID(record["id"]))

    def list(self, actor: Actor, *, include_archived: bool = False) -> list[SavedView]:
        actor.require("projects:read")
        return self.store.transaction(
            lambda s: self.store.list_saved_views(s, actor.user_id, include_archived)
        )

    def _audit(
        self,
        session: TxSession,
        actor: Actor,
        event: str,
        view_id: UUID,
        correlation_id: str | None,
    ) -> None:
        """One content-free audit event: the view id and correlation id, never its name or filters.

        Callers sit inside the idempotent `execute`, so a replay records no second event.
        """

        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event=event,
            outcome="success",
            target_type="saved_view",
            target_id=view_id,
            correlation_id=correlation_id,
        )

    def create(
        self,
        actor: Actor,
        *,
        name: str,
        definition: dict[str, Any],
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> SavedView:
        actor.require("projects:write")
        if not name.strip() or len(name.strip()) > 120:
            raise ValidationError("saved view name must contain 1-120 characters")
        checked = validate_definition({**definition, "name": name.strip(), "version": 1})
        item = SavedView(new_uuid7(), actor.user_id, name.strip(), checked, 1)
        payload = {"name": item.name, "definition": item.definition}
        return self.store.transaction(
            lambda s: self._replayed(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="create_saved_view",
                    key=idempotency_key,
                    payload=payload,
                    execute=lambda: self._save_result(s, actor, item, correlation_id),
                    replay=id_replay_record,
                ),
            )
        )

    def update(
        self,
        actor: Actor,
        view_id: UUID,
        *,
        version: int,
        name: str | None,
        definition: dict[str, Any] | None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> SavedView:
        actor.require("projects:write")
        if name is not None and (not name.strip() or len(name.strip()) > 120):
            raise ValidationError("saved view name must contain 1-120 characters")

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.get_saved_view(session, actor.user_id, view_id)
            if current.archived_at is not None:
                raise ValidationError("archived saved view must be restored before editing")
            next_name = name.strip() if name is not None else current.name
            next_definition = validate_definition(
                {
                    **(definition if definition is not None else current.definition),
                    "name": next_name,
                    "version": version + 1,
                }
            )
            updated = SavedView(
                current.id,
                current.owner_id,
                next_name,
                next_definition,
                current.version + 1,
                None,
            )
            self.store.save_saved_view(session, updated, expected_version=version)
            self._audit(session, actor, "saved_view.updated", view_id, correlation_id)
            return self._result(updated)

        return self.store.transaction(
            lambda s: self._replayed(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="update_saved_view",
                    key=idempotency_key,
                    payload={
                        "id": str(view_id),
                        "version": version,
                        "name": name,
                        "definition": definition,
                    },
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def archive(
        self,
        actor: Actor,
        view_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> SavedView:
        return self._set_archive(
            actor,
            view_id,
            version=version,
            archived=True,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def restore(
        self,
        actor: Actor,
        view_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> SavedView:
        return self._set_archive(
            actor,
            view_id,
            version=version,
            archived=False,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def _set_archive(
        self,
        actor: Actor,
        view_id: UUID,
        *,
        version: int,
        archived: bool,
        idempotency_key: str,
        correlation_id: str | None,
    ) -> SavedView:
        actor.require("projects:write")

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.get_saved_view(session, actor.user_id, view_id)
            updated = SavedView(
                current.id,
                current.owner_id,
                current.name,
                current.definition,
                current.version + 1,
                self.clock.now() if archived else None,
            )
            self.store.save_saved_view(session, updated, expected_version=version)
            self._audit(
                session,
                actor,
                "saved_view.archived" if archived else "saved_view.restored",
                view_id,
                correlation_id,
            )
            return self._result(updated)

        return self.store.transaction(
            lambda s: self._replayed(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="archive_saved_view" if archived else "restore_saved_view",
                    key=idempotency_key,
                    payload={"id": str(view_id), "version": version},
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def _save_result(
        self, session: TxSession, actor: Actor, item: SavedView, correlation_id: str | None
    ) -> dict[str, Any]:
        self.store.save_saved_view(session, item)
        self._audit(session, actor, "saved_view.created", item.id, correlation_id)
        return self._result(item)

    @staticmethod
    def _result(item: SavedView) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "owner_id": str(item.owner_id),
            "name": item.name,
            "definition": item.definition,
            "version": item.version,
            "archived_at": item.archived_at.isoformat() if item.archived_at else None,
        }

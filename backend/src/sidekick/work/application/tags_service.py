"""Owner-scoped tag vocabulary use cases.

Resolution is owner-scoped by construction: an unknown slug becomes a new vocabulary entry for
the acting owner, never a reference to somebody else's tag, and the composite owner-consistent
foreign keys remain the last line of defence. Record assignment lives in
`sidekick.work.domain.tag_assignment`.
"""

from collections.abc import Mapping
from typing import Protocol, TypedDict, TypeVar
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.shared.replay import id_replay_record, id_result, record_id
from sidekick.shared.types import (
    NAMED_KEY,
    Actor,
    Clock,
    CursorCodec,
    IdempotentStore,
    KeyValue,
    Page,
    TransactionalStore,
    TxSession,
    new_uuid7,
)
from sidekick.work.domain.planning import WorkTag, normalize_tag_slug

T = TypeVar("T")

MAX_TAG_PAGE = 100


class TagStore(TransactionalStore, IdempotentStore, Protocol):
    def get_work_tag(self, session: TxSession, owner_id: UUID, tag_id: UUID) -> WorkTag: ...
    def find_work_tag_by_slug(
        self, session: TxSession, owner_id: UUID, slug: str
    ) -> WorkTag | None: ...
    def list_work_tags(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[WorkTag]: ...
    def save_work_tag(
        self, session: TxSession, tag: WorkTag, expected_version: int | None = None
    ) -> None: ...
    def replace_record_tags(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: str,
        record_id: UUID,
        tag_ids: tuple[UUID, ...],
    ) -> None: ...
    def list_record_tags(
        self, session: TxSession, owner_id: UUID, kind: str, record_id: UUID
    ) -> list[WorkTag]: ...
    def record_tag_slugs(
        self, session: TxSession, owner_id: UUID, limit: int = 5000
    ) -> dict[tuple[str, UUID], tuple[str, ...]]: ...


class WorkTagService:
    """Vocabulary maintenance: list, create, rename, archive, restore."""

    def __init__(self, store: TagStore, clock: Clock, cursor_codec: CursorCodec) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec

    def _replayed(self, session: TxSession, actor: Actor, record: Mapping[str, object]) -> WorkTag:
        """The tag a (possibly replayed) write refers to, re-read by id.

        The idempotency record keeps only the id, so a retry returns the tag as it is now.
        """

        return self.store.get_work_tag(session, actor.user_id, record_id(record))

    def list(
        self,
        actor: Actor,
        *,
        limit: int = 50,
        cursor: str | None = None,
        include_archived: bool = False,
    ) -> Page[WorkTag]:
        actor.require("projects:read")
        if not 1 <= limit <= MAX_TAG_PAGE:
            raise ValidationError(f"tag page size must be between 1 and {MAX_TAG_PAGE}")
        key = f"work-tags:v1:archived={include_archived}"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, key, kinds=NAMED_KEY)
        rows = self.store.transaction(
            lambda session: self.store.list_work_tags(
                session, actor.user_id, limit + 1, after, include_archived
            )
        )
        return Page(
            rows[:limit],
            self.cursor_codec.encode_keyset(
                actor.user_id, (rows[limit - 1].label, rows[limit - 1].id), key
            )
            if len(rows) > limit
            else None,
        )

    def get(self, actor: Actor, tag_id: UUID) -> WorkTag:
        actor.require("projects:read")
        return self.store.transaction(
            lambda session: self.store.get_work_tag(session, actor.user_id, tag_id)
        )

    def slug_map(self, actor: Actor) -> dict[tuple[str, UUID], tuple[str, ...]]:
        """All tag slugs per tagged record, for bounded list projections."""

        actor.require("projects:read")
        return self.store.transaction(
            lambda session: self.store.record_tag_slugs(session, actor.user_id)
        )

    def require_record_tags_readable(self, actor: Actor) -> None:
        """Refuse an actor that may not read record tags.

        A write tool answers with the written record's tags (`for_record`), so it calls this
        before the write: the refusal then leaves nothing committed.
        """

        actor.require("projects:read")

    def for_record(self, actor: Actor, kind: str, record_id: UUID) -> "list[WorkTag]":
        """The tags linked to one owned record, for detail projections."""

        self.require_record_tags_readable(actor)
        return self.store.transaction(
            lambda session: self.store.list_record_tags(session, actor.user_id, kind, record_id)
        )

    def create(self, actor: Actor, *, label: str, idempotency_key: str) -> WorkTag:
        actor.require("projects:write")
        slug = normalize_tag_slug(label)

        def operation(session: TxSession) -> WorkTag:
            existing = self.store.find_work_tag_by_slug(session, actor.user_id, slug)
            if existing is not None:
                return existing
            now = self.clock.now()
            tag = WorkTag(
                id=new_uuid7(),
                owner_id=actor.user_id,
                slug=slug,
                label=label,
                created_at=now,
                updated_at=now,
            )
            self.store.save_work_tag(session, tag)
            return tag

        return self.store.transaction(
            lambda session: self._replayed(
                session,
                actor,
                self.store.idempotent(
                    session,
                    actor_id=actor.user_id,
                    operation="create_work_tag",
                    key=idempotency_key,
                    payload={"slug": slug},
                    execute=lambda: id_result(operation(session).id),
                    replay=id_replay_record,
                ),
            )
        )

    def rename(
        self, actor: Actor, tag_id: UUID, *, version: int, label: str, idempotency_key: str
    ) -> WorkTag:
        actor.require("projects:write")
        slug = normalize_tag_slug(label)

        def operation(session: TxSession) -> WorkTag:
            current = self.store.get_work_tag(session, actor.user_id, tag_id)
            clash = self.store.find_work_tag_by_slug(session, actor.user_id, slug)
            if clash is not None and clash.id != current.id:
                raise ValidationError("another tag already uses that name")
            renamed = current.rename(now=self.clock.now(), label=label)
            self.store.save_work_tag(session, renamed, expected_version=version)
            return renamed

        return self.store.transaction(
            lambda session: self._replayed(
                session,
                actor,
                self.store.idempotent(
                    session,
                    actor_id=actor.user_id,
                    operation="rename_work_tag",
                    key=idempotency_key,
                    payload={"tag_id": str(tag_id), "version": version, "slug": slug},
                    execute=lambda: id_result(operation(session).id),
                    replay=id_replay_record,
                ),
            )
        )

    def archive(self, actor: Actor, tag_id: UUID, *, version: int, idempotency_key: str) -> WorkTag:
        return self._set_archive(
            actor, tag_id, version=version, archived=True, idempotency_key=idempotency_key
        )

    def restore(self, actor: Actor, tag_id: UUID, *, version: int, idempotency_key: str) -> WorkTag:
        return self._set_archive(
            actor, tag_id, version=version, archived=False, idempotency_key=idempotency_key
        )

    def _set_archive(
        self, actor: Actor, tag_id: UUID, *, version: int, archived: bool, idempotency_key: str
    ) -> WorkTag:
        actor.require("projects:write")

        def operation(session: TxSession) -> WorkTag:
            current = self.store.get_work_tag(session, actor.user_id, tag_id)
            now = self.clock.now()
            updated = current.archive(now=now) if archived else current.restore(now=now)
            if updated is not current:
                self.store.save_work_tag(session, updated, expected_version=version)
            return updated

        return self.store.transaction(
            lambda session: self._replayed(
                session,
                actor,
                self.store.idempotent(
                    session,
                    actor_id=actor.user_id,
                    operation="archive_work_tag" if archived else "restore_work_tag",
                    key=idempotency_key,
                    payload={"tag_id": str(tag_id), "version": version},
                    execute=lambda: id_result(operation(session).id),
                    replay=id_replay_record,
                ),
            )
        )


class TagPublicData(TypedDict):
    """A tag's public contract: no internal ownership fields."""

    id: str
    slug: str
    label: str
    created_at: str
    updated_at: str
    archived_at: str | None
    version: int


def tag_public_data(tag: WorkTag) -> TagPublicData:
    return {
        "id": str(tag.id),
        "slug": tag.slug,
        "label": tag.label,
        "created_at": tag.created_at.isoformat(),
        "updated_at": tag.updated_at.isoformat(),
        "archived_at": tag.archived_at.isoformat() if tag.archived_at else None,
        "version": tag.version,
    }

"""Record tag assignment: the complete intended tag set for one owned record.

Assignment resolves the intended tag set inside the record's own update use case, so one
optimistic version and one idempotency key cover the whole change. It sits in the Work domain,
behind a small store port, so the Task, Project and Work use cases share it without importing
each other's application layer.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sidekick.shared.types import TxSession, new_uuid7
from sidekick.work.domain.planning import WorkTag, normalize_tag_selection


class RecordTagStore(Protocol):
    """The store operations tag assignment needs."""

    def find_work_tag_by_slug(
        self, session: TxSession, owner_id: UUID, slug: str
    ) -> WorkTag | None: ...
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


class RecordTagReader(RecordTagStore, Protocol):
    """Tag assignment plus the read that shows a record's tags."""

    def list_record_tags(
        self, session: TxSession, owner_id: UUID, kind: str, record_id: UUID
    ) -> list[WorkTag]: ...


def apply_record_tags(
    store: RecordTagStore,
    session: TxSession,
    *,
    owner_id: UUID,
    kind: str,
    record_id: UUID,
    values: tuple[str, ...] | list[str] | None,
    now: datetime,
) -> tuple[str, ...]:
    """Persist the complete intended tag set for one owned record.

    Returns the normalized slugs that are now linked. Missing vocabulary entries are
    created for this owner in the same transaction; archived entries are reused.
    """

    slugs = normalize_tag_selection(list(values or ()))
    tag_ids: list[UUID] = []
    for slug in slugs:
        existing = store.find_work_tag_by_slug(session, owner_id, slug)
        if existing is None:
            existing = WorkTag(
                id=new_uuid7(),
                owner_id=owner_id,
                slug=slug,
                label=slug,
                created_at=now,
                updated_at=now,
            )
            store.save_work_tag(session, existing)
        tag_ids.append(existing.id)
    store.replace_record_tags(session, owner_id, kind, record_id, tuple(tag_ids))
    return slugs

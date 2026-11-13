"""The owner's tag vocabulary and its links to the tagged records.

A tag is one vocabulary entry (`work_tags`); a record of any tagged kind links to it through that
kind's own link table. The vocabulary lives with Work, where tags began, and Contacts and Journal
entries link to the same entries.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, distinct, exists, false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sidekick.shared.persistence.models import (
    ContactRow,
    ContactTagRow,
    DomainRow,
    DomainTagRow,
    JournalEntryRow,
    JournalEntryTagRow,
    ProcessRow,
    ProcessTagRow,
    ProjectRow,
    ProjectTagRow,
    TaskRow,
    TaskTagRow,
    WorkTagRow,
)
from sidekick.shared.persistence.stores.keyset import rows_after
from sidekick.shared.types import KeyValue, utc_now
from sidekick.work.domain.planning import WorkTag


def work_tag_from_row(row: WorkTagRow) -> WorkTag:
    return WorkTag(
        id=row.id,
        owner_id=row.owner_id,
        slug=row.slug,
        label=row.label,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
        archived_at=row.archived_at,
    )


TAG_LINKS: dict[str, tuple[type[Any], str]] = {
    "domain": (DomainTagRow, "domain_id"),
    "process": (ProcessTagRow, "process_id"),
    "project": (ProjectTagRow, "project_id"),
    "task": (TaskTagRow, "task_id"),
    "contact": (ContactTagRow, "contact_id"),
    "journal_entry": (JournalEntryTagRow, "journal_entry_id"),
}
"""The tagged kinds. Steps and Actions inherit context from their Task."""

_LISTED: dict[str, tuple[Any, tuple[ColumnElement[bool], ...]]] = {
    "domain": (DomainRow, (DomainRow.status != "archived", DomainRow.trashed_at.is_(None))),
    "process": (ProcessRow, (ProcessRow.status != "archived", ProcessRow.trashed_at.is_(None))),
    "project": (
        ProjectRow,
        (ProjectRow.archived_at.is_(None), ProjectRow.trashed_at.is_(None)),
    ),
    "task": (TaskRow, (TaskRow.archived_at.is_(None), TaskRow.trashed_at.is_(None))),
    "contact": (ContactRow, (ContactRow.archived.is_(False), ContactRow.trashed_at.is_(None))),
    "journal_entry": (
        JournalEntryRow,
        (JournalEntryRow.archived_at.is_(None), JournalEntryRow.trashed_at.is_(None)),
    ),
}
"""Per tagged kind: the record table and what a list shows by default (live, not archived)."""

WORK_TAG_KINDS = ("domain", "process", "project", "task")
"""The tagged kinds that Work lists show tags for."""


def tag_condition(
    kind: str, record_id: Any, owner_id: UUID, tags: tuple[str, ...], match: str
) -> ColumnElement[bool]:
    """Whether the record carries any (or every) wanted tag; a kind without tags carries none."""

    if kind not in TAG_LINKS:
        return false()
    link_row, column = TAG_LINKS[kind]
    linked = (
        link_row.owner_id == owner_id,
        getattr(link_row, column) == record_id,
        WorkTagRow.id == link_row.tag_id,
        WorkTagRow.owner_id == link_row.owner_id,
        WorkTagRow.slug.in_(tags),
    )
    if match == "all":
        wanted = select(func.count(distinct(WorkTagRow.slug))).where(*linked).scalar_subquery()
        return wanted == len(tags)
    return exists(select(1).where(*linked))


class WorkTagStore:
    """Tags and their links to the tagged records.

    Mixin composed into ``SqlAlchemyStore``; methods are static and owner-filtered.
    """

    @staticmethod
    def get_work_tag(session: Session, owner_id: UUID, tag_id: UUID) -> WorkTag:
        row = session.scalar(
            select(WorkTagRow).where(WorkTagRow.id == tag_id, WorkTagRow.owner_id == owner_id)
        )
        if row is None:
            raise NotFoundError("tag not found")
        return work_tag_from_row(row)

    @staticmethod
    def find_work_tag_by_slug(session: Session, owner_id: UUID, slug: str) -> WorkTag | None:
        row = session.scalar(
            select(WorkTagRow).where(WorkTagRow.owner_id == owner_id, WorkTagRow.slug == slug)
        )
        return work_tag_from_row(row) if row is not None else None

    @staticmethod
    def list_work_tags(
        session: Session,
        owner_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
        readable_kinds: Sequence[str] | None = None,
    ) -> list[WorkTag]:
        """The owner's tags in label order.

        `readable_kinds` limits the page to tags the caller may know of: a tag that is linked
        only to kinds outside it is left out, as its name would tell what those records hold. A
        tag with no link at all stays. None means every kind is readable.
        """

        statement = select(WorkTagRow).where(WorkTagRow.owner_id == owner_id)
        if not include_archived:
            statement = statement.where(WorkTagRow.archived_at.is_(None))
        if readable_kinds is not None and set(readable_kinds) != set(TAG_LINKS):
            statement = statement.where(_visible_to(owner_id, readable_kinds))
        if after is not None:
            statement = statement.where(
                rows_after((WorkTagRow.label, WorkTagRow.id), after, descending=False)
            )
        rows = session.scalars(
            statement.order_by(WorkTagRow.label.asc(), WorkTagRow.id.asc()).limit(limit)
        )
        return [work_tag_from_row(row) for row in rows]

    @staticmethod
    def save_work_tag(session: Session, tag: WorkTag, expected_version: int | None = None) -> None:
        row = session.scalar(select(WorkTagRow).where(WorkTagRow.id == tag.id).with_for_update())
        if row is None:
            session.add(
                WorkTagRow(
                    id=tag.id,
                    owner_id=tag.owner_id,
                    slug=tag.slug,
                    label=tag.label,
                    created_at=tag.created_at,
                    updated_at=tag.updated_at,
                    archived_at=tag.archived_at,
                    version=tag.version,
                )
            )
            _flush_tag_write(session)
            return
        if row.owner_id != tag.owner_id:
            raise NotFoundError("tag not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale tag version")
        for field in ("slug", "label", "updated_at", "archived_at", "version"):
            setattr(row, field, getattr(tag, field))
        _flush_tag_write(session)

    @staticmethod
    def replace_record_tags(
        session: Session, owner_id: UUID, kind: str, record_id: UUID, tag_ids: tuple[UUID, ...]
    ) -> None:
        """Apply the intended tag set for one record inside its own transaction."""

        link_row, column = _tag_link(kind)
        target = getattr(link_row, column)
        current = {
            row.tag_id
            for row in session.scalars(
                select(link_row).where(link_row.owner_id == owner_id, target == record_id)
            )
        }
        wanted = set(tag_ids)
        for tag_id in current - wanted:
            session.execute(
                delete(link_row).where(
                    link_row.owner_id == owner_id,
                    link_row.tag_id == tag_id,
                    target == record_id,
                )
            )
        for tag_id in wanted - current:
            session.add(
                link_row(
                    **{
                        "owner_id": owner_id,
                        "tag_id": tag_id,
                        column: record_id,
                        "created_at": utc_now(),
                    }
                )
            )
        _flush_tag_write(session)

    @staticmethod
    def list_record_tags(
        session: Session, owner_id: UUID, kind: str, record_id: UUID
    ) -> list[WorkTag]:
        link_row, column = _tag_link(kind)
        target = getattr(link_row, column)
        rows = session.scalars(
            select(WorkTagRow)
            .join(
                link_row,
                (link_row.tag_id == WorkTagRow.id) & (link_row.owner_id == WorkTagRow.owner_id),
            )
            .where(link_row.owner_id == owner_id, target == record_id)
            .order_by(WorkTagRow.label.asc(), WorkTagRow.id.asc())
        )
        return [work_tag_from_row(row) for row in rows]

    @staticmethod
    def record_tag_slugs(
        session: Session,
        owner_id: UUID,
        limit: int = 5000,
        record_ids: Mapping[str, Sequence[UUID]] | None = None,
    ) -> dict[tuple[str, UUID], tuple[str, ...]]:
        """Tag slugs per tagged record, for owner-scoped projections.

        With `record_ids` (record ids per tagged kind) only those records are read, one query
        per kind that names any; without it every tagged Work record of the owner is read, up to
        `limit` links per kind.
        """

        result: dict[tuple[str, UUID], list[str]] = {}
        for kind, (link_row, column) in TAG_LINKS.items():
            if record_ids is None and kind not in WORK_TAG_KINDS:
                continue
            target = getattr(link_row, column)
            statement = (
                select(target, WorkTagRow.slug)
                .join(
                    link_row,
                    (link_row.tag_id == WorkTagRow.id) & (link_row.owner_id == WorkTagRow.owner_id),
                )
                .where(link_row.owner_id == owner_id)
            )
            if record_ids is not None:
                wanted = record_ids.get(kind, ())
                if not wanted:
                    continue
                statement = statement.where(target.in_(list(wanted)))
            rows = session.execute(statement.order_by(WorkTagRow.slug.asc()).limit(limit)).all()
            for record_id, slug in rows:
                result.setdefault((kind, record_id), []).append(slug)
        return {key: tuple(value) for key, value in result.items()}

    @staticmethod
    def tag_usage(
        session: Session, owner_id: UUID, tag_ids: Sequence[UUID], kinds: Sequence[str]
    ) -> dict[UUID, dict[str, int]]:
        """How many records of each kind carry each of the tags: `{tag_id: {kind: count}}`.

        Only the records a list shows by default count: not archived, not in the trash. Every
        kind in `kinds` is present for every tag, with 0 where nothing uses it.
        """

        usage: dict[UUID, dict[str, int]] = {tag_id: dict.fromkeys(kinds, 0) for tag_id in tag_ids}
        if not usage:
            return usage
        for kind in kinds:
            link_row, column = TAG_LINKS[kind]
            target, listed = _LISTED[kind]
            rows = session.execute(
                select(link_row.tag_id, func.count())
                .join(
                    target,
                    (target.id == getattr(link_row, column))
                    & (target.owner_id == link_row.owner_id),
                )
                .where(
                    link_row.owner_id == owner_id,
                    link_row.tag_id.in_(list(usage)),
                    *listed,
                )
                .group_by(link_row.tag_id)
            )
            for tag_id, count in rows:
                usage[tag_id][kind] = count
        return usage


def _linked(kind: str, owner_id: UUID) -> ColumnElement[bool]:
    link_row, _ = TAG_LINKS[kind]
    return exists(select(1).where(link_row.owner_id == owner_id, link_row.tag_id == WorkTagRow.id))


def _visible_to(owner_id: UUID, readable_kinds: Sequence[str]) -> ColumnElement[bool]:
    """A tag with a link in a readable kind, or with no link in any kind."""

    readable = [_linked(kind, owner_id) for kind in TAG_LINKS if kind in readable_kinds]
    unused = ~or_(*(_linked(kind, owner_id) for kind in TAG_LINKS))
    return or_(*readable, unused)


def _tag_link(kind: str) -> tuple[type[Any], str]:
    try:
        return TAG_LINKS[kind]
    except KeyError as error:
        raise ValidationError("this kind of record cannot carry tags") from error


def _flush_tag_write(session: Session) -> None:
    """Surface owner-consistency and uniqueness violations as safe domain errors."""

    try:
        session.flush()
    except IntegrityError as error:
        raise ValidationError("tag write violates owner consistency or uniqueness") from error

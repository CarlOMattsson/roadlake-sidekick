"""Trash, restore, permanent removal and the change feed over the audit log."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sidekick.lifecycle.domain import ChangeRecordView, RecordKind, TrashItem, TrashPosition
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale, LocalizedText, localized
from sidekick.shared.persistence.models import (
    ActionRow,
    AuditEventRow,
    ContactAliasRow,
    ContactRow,
    DomainRow,
    JournalEntryContactRow,
    JournalEntryProjectRow,
    JournalEntryRow,
    JournalEntryTaskRow,
    JournalSourceRow,
    ProcessRow,
    ProjectContactRow,
    ProjectRow,
    StepRow,
    TaskContactRow,
    TaskRow,
)
from sidekick.shopping.persistence.rows import ShoppingItemRow

LIFECYCLE_ROWS: dict[RecordKind, tuple[type[Any], str]] = {
    RecordKind.DOMAIN: (DomainRow, "name"),
    RecordKind.PROCESS: (ProcessRow, "name"),
    RecordKind.PROJECT: (ProjectRow, "title"),
    RecordKind.TASK: (TaskRow, "title"),
    RecordKind.STEP: (StepRow, "title"),
    RecordKind.ACTION: (ActionRow, "title"),
    RecordKind.CONTACT: (ContactRow, "display_name"),
    RecordKind.JOURNAL_SOURCE: (JournalSourceRow, "raw_text"),
    RecordKind.JOURNAL_ENTRY: (JournalEntryRow, "title"),
    RecordKind.SHOPPING_ITEM: (ShoppingItemRow, "name"),
}


HISTORY_TITLES: dict[str, LocalizedText] = {
    "alias": {"sv": "Alias '{alias}' för {name}", "en": "Nickname \u201c{alias}\u201d for {name}"},
    "alias_removed": {"sv": "Alias borttaget för {name}", "en": "Nickname removed for {name}"},
    "contact_unlinked": {
        "sv": "Kontakt {name}: koppling borttagen",
        "en": "Contact {name}: link removed",
    },
    "reference_unlinked": {
        "sv": "Referens '{title}': koppling borttagen",
        "en": "Reference \u201c{title}\u201d: link removed",
    },
    "reference_link": {
        "sv": "Referens '{title}' \u2194 {task}",
        "en": "Reference \u201c{title}\u201d \u2194 {task}",
    },
}
"""Change-feed titles built when the feed is read, so they follow the app language at that time."""


CHANGE_ROWS: dict[str, tuple[type[Any], str]] = {
    kind.value: row for kind, row in LIFECYCLE_ROWS.items() if kind is not RecordKind.JOURNAL_SOURCE
}
"""Row type and title field for each kind that `list_recent_changes` may name."""


class LifecycleStore:
    """Trash, restore, permanent removal and the change feed over the audit log.

    Mixin composed into ``SqlAlchemyStore``; methods are static and owner-filtered.
    """

    @staticmethod
    def _after_position(row_type: Any, kind: RecordKind, after: TrashPosition | None) -> Any:
        """Keyset predicate: rows that sort strictly after `after` in (trashed_at, kind, id) desc.

        Kinds are separate tables, so the kind part of the key is decided here in Python.
        """

        if after is None:
            return true()
        if kind.value > after.kind.value:
            return row_type.trashed_at < after.trashed_at
        if kind.value < after.kind.value:
            return row_type.trashed_at <= after.trashed_at
        return or_(
            row_type.trashed_at < after.trashed_at,
            and_(row_type.trashed_at == after.trashed_at, row_type.id < after.id),
        )

    @staticmethod
    def list_trash(
        session: Session,
        owner_id: UUID,
        *,
        kinds: frozenset[RecordKind],
        limit: int,
        after: TrashPosition | None = None,
    ) -> list[TrashItem]:
        """Read only explicitly trashed records of the given kinds, never normal projections.

        Newest trash first, ordered totally by (trashed_at, kind, id) descending, and continued
        after `after` with a keyset predicate, so the page never repeats or skips a record.
        """

        result: list[TrashItem] = []
        for item_kind in (k for k in LIFECYCLE_ROWS if k in kinds):
            row_type, label_field = LIFECYCLE_ROWS[item_kind]
            rows = session.scalars(
                select(row_type)
                .where(
                    row_type.owner_id == owner_id,
                    row_type.trashed_at.is_not(None),
                    LifecycleStore._after_position(row_type, item_kind, after),
                )
                .order_by(row_type.trashed_at.desc(), row_type.id.desc())
                .limit(limit)
            )
            for row in rows:
                result.append(
                    TrashItem(
                        kind=item_kind,
                        id=row.id,
                        label=(
                            row.raw_text[:80] + ("…" if len(row.raw_text) > 80 else "")
                            if item_kind is RecordKind.JOURNAL_SOURCE
                            else str(getattr(row, label_field))
                        ),
                        trashed_at=row.trashed_at,
                        version=int(getattr(row, "version", 1)),
                    )
                )
        result.sort(key=lambda item: TrashPosition.of(item).sort_key(), reverse=True)
        return result[:limit]

    @staticmethod
    def list_trash_owner_ids(session: Session) -> list[UUID]:
        """Owners that have at least one trashed record, for the operator's trash sweep only.

        Deliberately not owner-scoped: the only caller is `sidekick-admin empty-trash`, which acts
        for the person who runs the server. It reads ids, never titles or text.
        """

        owners: set[UUID] = set()
        for row_type, _ in LIFECYCLE_ROWS.values():
            owners.update(
                session.scalars(
                    select(row_type.owner_id).where(row_type.trashed_at.is_not(None)).distinct()
                )
            )
        return sorted(owners)

    @staticmethod
    def list_change_audit(
        session: Session,
        owner_id: UUID,
        *,
        events: frozenset[str],
        limit: int,
    ) -> list[tuple[str, UUID, UUID | None, datetime, str | None]]:
        """The owner's successful audit events of the given names, newest first.

        Each row is (event, target id, related id, time, source); the related id is None for old
        rows, and the source is None for rows written before it was recorded.
        """

        rows = session.execute(
            select(
                AuditEventRow.event,
                AuditEventRow.target_id,
                AuditEventRow.related_id,
                AuditEventRow.occurred_at,
                AuditEventRow.source,
            )
            .where(
                AuditEventRow.actor_id == owner_id,
                AuditEventRow.outcome == "success",
                AuditEventRow.event.in_(events),
                AuditEventRow.target_id.is_not(None),
            )
            .order_by(AuditEventRow.occurred_at.desc(), AuditEventRow.id.desc())
            .limit(limit)
        ).all()
        return [
            (row.event, row.target_id, row.related_id, row.occurred_at, row.source) for row in rows
        ]

    @staticmethod
    def _link_change_views(
        session: Session,
        owner_id: UUID,
        kind: str,
        keys: frozenset[tuple[UUID, UUID | None]],
        locale: AppLocale,
    ) -> dict[tuple[UUID, UUID | None], ChangeRecordView]:
        """Titles for alias and link changes, one batched read per kind (no per-row lookups).

        A key is (record id, related id). Alias changes name the alias and its contact. Alias
        removals name the contact only, because the alias row is gone. Link changes name both sides
        when the row has a related id. Unlink changes, and rows without a related id, name only the
        contact or the reference, as before, because the other party is not in the unlink text.
        The words around the names follow `locale`; they are built on every read and not stored.
        """

        target_ids = frozenset(target for target, _ in keys)
        related_ids = frozenset(related for _, related in keys if related is not None)
        if kind == "contact_alias":
            return _alias_views(session, owner_id, target_ids, locale)
        if kind == "contact_alias_removed":
            return _alias_removed_views(session, owner_id, keys, related_ids, locale)
        if kind in ("contact_link", "contact_task_link", "contact_project_link"):
            return _contact_link_views(
                session, owner_id, kind, keys, target_ids, related_ids, locale
            )
        return _reference_views(session, owner_id, kind, keys, target_ids, related_ids, locale)

    @staticmethod
    def load_change_records(
        session: Session,
        owner_id: UUID,
        kind: str,
        keys: frozenset[tuple[UUID, UUID | None]],
        locale: AppLocale = DEFAULT_LOCALE,
    ) -> dict[tuple[UUID, UUID | None], ChangeRecordView]:
        """Current title, version and trash state of the owner's records of one kind.

        A key is (record id, related id); the related id is None for changes that have one record.
        """

        if kind in (
            "contact_alias",
            "contact_alias_removed",
            "contact_link",
            "contact_task_link",
            "contact_project_link",
            "external_reference",
            "external_reference_link",
        ):
            return LifecycleStore._link_change_views(session, owner_id, kind, keys, locale)
        if kind == "shopping_list":
            # Imported here because shopping.persistence.store imports this module at load time.
            from sidekick.shopping.persistence.rows import ShoppingListRow

            row_type, label_field = ShoppingListRow, "name"
        else:
            row_type, label_field = CHANGE_ROWS[kind]
        record_ids = frozenset(target for target, _ in keys)
        views: dict[tuple[UUID, UUID | None], ChangeRecordView] = {}
        for row in session.scalars(
            select(row_type).where(row_type.owner_id == owner_id, row_type.id.in_(record_ids))
        ):
            label = str(getattr(row, label_field))
            views[(row.id, None)] = ChangeRecordView(
                title=label[:80] + ("…" if len(label) > 80 else ""),
                version=int(getattr(row, "version", 1)),
                trashed=getattr(row, "trashed_at", None) is not None,
            )
        return views

    @staticmethod
    def _lifecycle_row(
        session: Session, owner_id: UUID, kind: RecordKind, record_id: UUID, *, lock: bool = True
    ) -> Any:
        row_type, _ = LIFECYCLE_ROWS[kind]
        statement = select(row_type).where(row_type.id == record_id, row_type.owner_id == owner_id)
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise NotFoundError(f"{kind.value} not found")
        return row

    @staticmethod
    def _lifecycle_label(kind: RecordKind, row: Any) -> str:
        field = LIFECYCLE_ROWS[kind][1]
        value = getattr(row, field)
        return (
            value[:80] + ("…" if len(value) > 80 else "")
            if kind is RecordKind.JOURNAL_SOURCE
            else str(value)
        )

    @staticmethod
    def set_trashed(
        session: Session,
        owner_id: UUID,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
        trashed: bool,
        now: datetime,
    ) -> TrashItem:
        row = LifecycleStore._lifecycle_row(session, owner_id, kind, record_id)
        current_version = int(getattr(row, "version", 1))
        if current_version != version:
            raise ConflictError(f"stale {kind.value} version")
        if trashed and row.trashed_at is not None:
            raise ConflictError(f"{kind.value} is already in trash")
        if not trashed and row.trashed_at is None:
            raise ConflictError(f"{kind.value} is not in trash")
        row.trashed_at = now if trashed else None
        if hasattr(row, "version"):
            row.version = current_version + 1
        if hasattr(row, "updated_at"):
            row.updated_at = now
        session.flush()
        return LifecycleStore._trash_item(kind, row)

    @staticmethod
    def get_trash_item(
        session: Session, owner_id: UUID, kind: RecordKind, record_id: UUID
    ) -> TrashItem:
        """One owned record as a trash entry, in the trash or not (a replayed trash/restore)."""

        row = LifecycleStore._lifecycle_row(session, owner_id, kind, record_id, lock=False)
        return LifecycleStore._trash_item(kind, row)

    @staticmethod
    def _trash_item(kind: RecordKind, row: Any) -> TrashItem:
        return TrashItem(
            kind=kind,
            id=row.id,
            label=LifecycleStore._lifecycle_label(kind, row),
            trashed_at=row.trashed_at,
            version=int(getattr(row, "version", 1)),
        )

    @staticmethod
    def _child_count(session: Session, owner_id: UUID, kind: RecordKind, record_id: UUID) -> int:
        checks: dict[RecordKind, tuple[type[Any], Any]] = {
            RecordKind.DOMAIN: (ProcessRow, ProcessRow.domain_id == record_id),
            RecordKind.PROCESS: (TaskRow, TaskRow.process_id == record_id),
            RecordKind.PROJECT: (TaskRow, TaskRow.project_id == record_id),
            RecordKind.TASK: (StepRow, StepRow.task_id == record_id),
            RecordKind.STEP: (ActionRow, ActionRow.step_id == record_id),
            RecordKind.CONTACT: (ContactAliasRow, ContactAliasRow.contact_id == record_id),
            RecordKind.JOURNAL_SOURCE: (JournalEntryRow, JournalEntryRow.source_id == record_id),
            RecordKind.JOURNAL_ENTRY: (
                JournalEntryProjectRow,
                JournalEntryProjectRow.entry_id == record_id,
            ),
        }
        total = 0
        if kind in checks:
            row_type, predicate = checks[kind]
            total += int(
                session.scalar(
                    select(func.count())
                    .select_from(row_type)
                    .where(row_type.owner_id == owner_id, predicate)
                )
                or 0
            )
        if kind is RecordKind.DOMAIN:
            total += int(
                session.scalar(
                    select(func.count())
                    .select_from(ProjectRow)
                    .where(ProjectRow.owner_id == owner_id, ProjectRow.domain_id == record_id)
                )
                or 0
            )
        if kind is RecordKind.CONTACT:
            total += int(
                session.scalar(
                    select(func.count())
                    .select_from(ProjectContactRow)
                    .where(
                        ProjectContactRow.owner_id == owner_id,
                        ProjectContactRow.contact_id == record_id,
                    )
                )
                or 0
            ) + int(
                session.scalar(
                    select(func.count())
                    .select_from(TaskContactRow)
                    .where(
                        TaskContactRow.owner_id == owner_id,
                        TaskContactRow.contact_id == record_id,
                    )
                )
                or 0
            )
        if kind is RecordKind.JOURNAL_ENTRY:
            total += int(
                session.scalar(
                    select(func.count())
                    .select_from(JournalEntryTaskRow)
                    .where(
                        JournalEntryTaskRow.owner_id == owner_id,
                        JournalEntryTaskRow.entry_id == record_id,
                    )
                )
                or 0
            ) + int(
                session.scalar(
                    select(func.count())
                    .select_from(JournalEntryContactRow)
                    .where(
                        JournalEntryContactRow.owner_id == owner_id,
                        JournalEntryContactRow.entry_id == record_id,
                    )
                )
                or 0
            )
        if kind is RecordKind.JOURNAL_SOURCE:
            total += int(
                session.scalar(
                    select(func.count())
                    .select_from(JournalSourceRow)
                    .where(
                        JournalSourceRow.owner_id == owner_id,
                        JournalSourceRow.replaces_source_id == record_id,
                    )
                )
                or 0
            )
        return total

    @staticmethod
    def permanently_remove(
        session: Session,
        owner_id: UUID,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
    ) -> None:
        row = LifecycleStore._lifecycle_row(session, owner_id, kind, record_id)
        if row.trashed_at is None:
            raise ValidationError("only a trashed record can be permanently removed")
        if int(getattr(row, "version", 1)) != version:
            raise ConflictError(f"stale {kind.value} version")
        child_count = LifecycleStore._child_count(session, owner_id, kind, record_id)
        if child_count:
            raise ConflictError("remove descendants before permanently removing this record")
        try:
            # A savepoint keeps the session usable when a foreign key the count above does not
            # cover (for example a Journal link to a Task, ON DELETE RESTRICT) refuses the delete.
            with session.begin_nested():
                session.delete(row)
                session.flush()
        except IntegrityError as error:
            raise ConflictError(
                "remove linked records before permanently removing this record"
            ) from error


def _words(key: str, locale: AppLocale, **names: str) -> str:
    return localized(HISTORY_TITLES[key], locale).format(**names)


def _shorten(text: str) -> str:
    return text[:80] + ("…" if len(text) > 80 else "")


def _titles_by_id(
    session: Session, owner_id: UUID, row_type: Any, identifiers: frozenset[UUID]
) -> dict[UUID, str]:
    """Titles of task or project rows, empty when there is nothing to look up."""
    if not identifiers:
        return {}
    return {
        row.id: row.title
        for row in session.execute(
            select(row_type.id, row_type.title).where(
                row_type.owner_id == owner_id, row_type.id.in_(identifiers)
            )
        ).all()
    }


def _alias_views(
    session: Session, owner_id: UUID, target_ids: frozenset[UUID], locale: AppLocale
) -> dict[tuple[UUID, UUID | None], ChangeRecordView]:
    alias_rows = session.execute(
        select(
            ContactAliasRow.id,
            ContactAliasRow.display_value,
            ContactRow.display_name,
            ContactRow.version,
        )
        .join(
            ContactRow,
            and_(
                ContactRow.id == ContactAliasRow.contact_id,
                ContactRow.owner_id == ContactAliasRow.owner_id,
            ),
        )
        .where(ContactAliasRow.owner_id == owner_id, ContactAliasRow.id.in_(target_ids))
    ).all()
    return {
        (alias.id, None): ChangeRecordView(
            title=_shorten(
                _words("alias", locale, alias=alias.display_value, name=alias.display_name)
            ),
            version=int(alias.version),
            trashed=False,
        )
        for alias in alias_rows
    }


def _contact_rows(
    session: Session, owner_id: UUID, identifiers: frozenset[UUID]
) -> dict[UUID, Any]:
    return {
        row.id: row
        for row in session.execute(
            select(ContactRow.id, ContactRow.display_name, ContactRow.version).where(
                ContactRow.owner_id == owner_id, ContactRow.id.in_(identifiers)
            )
        ).all()
    }


def _alias_removed_views(
    session: Session,
    owner_id: UUID,
    keys: frozenset[tuple[UUID, UUID | None]],
    related_ids: frozenset[UUID],
    locale: AppLocale,
) -> dict[tuple[UUID, UUID | None], ChangeRecordView]:
    contact_rows = _contact_rows(session, owner_id, related_ids)
    views: dict[tuple[UUID, UUID | None], ChangeRecordView] = {}
    for alias_id, contact_id in keys:
        if contact_id is None or contact_id not in contact_rows:
            continue
        contact = contact_rows[contact_id]
        views[(alias_id, contact_id)] = ChangeRecordView(
            title=_shorten(_words("alias_removed", locale, name=contact.display_name)),
            version=int(contact.version),
            trashed=False,
        )
    return views


def _contact_link_views(
    session: Session,
    owner_id: UUID,
    kind: str,
    keys: frozenset[tuple[UUID, UUID | None]],
    target_ids: frozenset[UUID],
    related_ids: frozenset[UUID],
    locale: AppLocale,
) -> dict[tuple[UUID, UUID | None], ChangeRecordView]:
    contact_rows = _contact_rows(session, owner_id, target_ids)
    other_titles: dict[UUID, str] = {}
    if kind == "contact_task_link":
        other_titles = _titles_by_id(session, owner_id, TaskRow, related_ids)
    elif kind == "contact_project_link":
        other_titles = _titles_by_id(session, owner_id, ProjectRow, related_ids)
    views: dict[tuple[UUID, UUID | None], ChangeRecordView] = {}
    for contact_id, related_id in keys:
        if contact_id not in contact_rows:
            continue
        contact = contact_rows[contact_id]
        if kind == "contact_link":
            views[(contact_id, related_id)] = ChangeRecordView(
                title=_shorten(_words("contact_unlinked", locale, name=contact.display_name)),
                version=int(contact.version),
                trashed=False,
            )
            continue
        if related_id is None or related_id not in other_titles:
            continue
        views[(contact_id, related_id)] = ChangeRecordView(
            title=_shorten(f"{contact.display_name} ↔ {other_titles[related_id]}"),
            version=int(contact.version),
            trashed=False,
        )
    return views


def _reference_views(
    session: Session,
    owner_id: UUID,
    kind: str,
    keys: frozenset[tuple[UUID, UUID | None]],
    target_ids: frozenset[UUID],
    related_ids: frozenset[UUID],
    locale: AppLocale,
) -> dict[tuple[UUID, UUID | None], ChangeRecordView]:
    # Imported here because references.persistence imports this module at load time.
    from sidekick.references.persistence import ExternalReferenceRow

    reference_rows = {
        row.id: row
        for row in session.execute(
            select(
                ExternalReferenceRow.id,
                ExternalReferenceRow.title,
                ExternalReferenceRow.version,
            ).where(
                ExternalReferenceRow.owner_id == owner_id,
                ExternalReferenceRow.id.in_(target_ids),
            )
        ).all()
    }
    task_titles: dict[UUID, str] = {}
    if kind == "external_reference_link":
        task_titles = _titles_by_id(session, owner_id, TaskRow, related_ids)
    views: dict[tuple[UUID, UUID | None], ChangeRecordView] = {}
    for reference_id, related_id in keys:
        if reference_id not in reference_rows:
            continue
        reference = reference_rows[reference_id]
        if kind == "external_reference":
            views[(reference_id, related_id)] = ChangeRecordView(
                title=_shorten(_words("reference_unlinked", locale, title=reference.title)),
                version=int(reference.version),
                trashed=False,
            )
            continue
        if related_id is None or related_id not in task_titles:
            continue
        views[(reference_id, related_id)] = ChangeRecordView(
            title=_shorten(
                _words(
                    "reference_link",
                    locale,
                    title=reference.title,
                    task=task_titles[related_id],
                )
            ),
            version=int(reference.version),
            trashed=False,
        )
    return views

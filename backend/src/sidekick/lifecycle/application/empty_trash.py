"""Operator sweep that empties the trash through the existing permanent-removal use case.

Run by whoever runs the server (`sidekick-admin empty-trash`; D-031: permanent removal is a server
command, never an MCP tool). It never deletes on its own: every record goes through
`RecordLifecycleService.permanently_remove`, which accepts only a trashed record, checks descendants
first, and writes an audit row. A dry run reads counts only. The result holds counts per record kind
and never a title, text or id.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sidekick.lifecycle.application.service import LIFECYCLE_SCOPES, RecordLifecycleService
from sidekick.lifecycle.domain import RecordKind, TrashItem
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.types import Actor

#: Children before parents, so a trashed parent whose descendants are trashed too goes in one run.
REMOVAL_ORDER: tuple[RecordKind, ...] = (
    RecordKind.ACTION,
    RecordKind.STEP,
    RecordKind.TASK,
    RecordKind.PROCESS,
    RecordKind.PROJECT,
    RecordKind.DOMAIN,
    RecordKind.JOURNAL_SOURCE,
    RecordKind.CONTACT,
)
#: The application role holds no DELETE on the shopping or Journal entry tables (a Journal entry is
#: never erased by the runtime), so these are never removed here; the sweep counts them as kept.
NOT_REMOVABLE: frozenset[RecordKind] = frozenset(
    {RecordKind.SHOPPING_ITEM, RecordKind.JOURNAL_ENTRY}
)

_PAGE = 100


@dataclass(slots=True)
class EmptyTrashResult:
    """Counts per record kind; `removed` and `kept` are filled only by a real removal."""

    matched: Counter[RecordKind] = field(default_factory=Counter[RecordKind])
    removed: Counter[RecordKind] = field(default_factory=Counter[RecordKind])
    kept: Counter[RecordKind] = field(default_factory=Counter[RecordKind])


def empty_trash(
    lifecycle: RecordLifecycleService,
    *,
    remove: bool,
    older_than: timedelta | None = None,
    correlation_id: str | None = None,
) -> EmptyTrashResult:
    """Count (`remove=False`) or permanently remove every owner's trashed records.

    `older_than` keeps records trashed more recently than that. A record the removal rules refuse
    (it still has descendants or links, or it is a shopping item or a Journal entry) is counted as
    kept, not forced.
    Safe to run again: removed records are gone, and a record trashed or restored meanwhile is
    judged by its own version.
    """

    cutoff = None if older_than is None else lifecycle.clock.now() - older_than
    result = EmptyTrashResult()
    owner_ids = lifecycle.store.transaction(lifecycle.store.list_trash_owner_ids)
    for owner_id in owner_ids:
        actor = Actor(owner_id, LIFECYCLE_SCOPES)
        for item in _ordered(_trashed_items(lifecycle, actor, cutoff)):
            result.matched[item.kind] += 1
            if not remove:
                continue
            if item.kind in NOT_REMOVABLE or not _remove(
                lifecycle, actor, item, correlation_id=correlation_id
            ):
                result.kept[item.kind] += 1
            else:
                result.removed[item.kind] += 1
    return result


def _trashed_items(
    lifecycle: RecordLifecycleService, actor: Actor, cutoff: datetime | None
) -> list[TrashItem]:
    """The owner's whole trash, read before any removal so paging never shifts under it."""

    items: list[TrashItem] = []
    cursor: str | None = None
    while True:
        page = lifecycle.list_trash(actor, limit=_PAGE, cursor=cursor)
        items.extend(
            item
            for item in page.items
            if cutoff is None or (item.trashed_at is not None and item.trashed_at <= cutoff)
        )
        if page.next_cursor is None:
            return items
        cursor = page.next_cursor


def _ordered(items: Iterable[TrashItem]) -> list[TrashItem]:
    rank = {kind: position for position, kind in enumerate((*REMOVAL_ORDER, *NOT_REMOVABLE))}
    return sorted(items, key=lambda item: rank[item.kind])


def _remove(
    lifecycle: RecordLifecycleService,
    actor: Actor,
    item: TrashItem,
    *,
    correlation_id: str | None,
) -> bool:
    try:
        lifecycle.permanently_remove(
            actor,
            item.kind,
            item.id,
            version=item.version,
            idempotency_key=f"empty-trash-{item.id}-{item.version}",
            correlation_id=correlation_id,
        )
    except (ConflictError, ValidationError, NotFoundError):
        return False
    return True

"""Recoverable record lifecycle rules without transport or a database."""

from datetime import timedelta
from uuid import UUID

import pytest

from sidekick.lifecycle import RecordKind, RecordLifecycleService, TrashItem, TrashPosition
from sidekick.shared.errors import PermissionDeniedError, ValidationError
from sidekick.shared.types import Actor, CursorCodec, new_uuid7
from tests.support.record_lifecycle import (
    NOW,
    FakeLifecycleStore,
    FixedClock,
)


def make_service() -> tuple[RecordLifecycleService, FakeLifecycleStore, Actor, TrashItem]:
    store = FakeLifecycleStore()
    service = RecordLifecycleService(store, FixedClock(), CursorCodec("unit-test-cursor-secret"))
    actor = Actor(
        new_uuid7(),
        frozenset({"projects:read", "tasks:read", "tasks:write"}),
    )
    return service, store, actor, store.items[0]


def test_trash_is_versioned_audited_and_idempotent() -> None:
    service, store, actor, item = make_service()

    trashed = service.trash(
        actor,
        item.kind,
        item.id,
        version=item.version,
        idempotency_key="trash-task-1",
    )
    replay = service.trash(
        actor,
        item.kind,
        item.id,
        version=item.version,
        idempotency_key="trash-task-1",
    )

    assert trashed == replay
    assert trashed.trashed_at == NOW
    assert trashed.version == item.version + 1
    assert store.audit == [("task.trashed", "success")]
    assert service.list_trash(actor).items == [trashed]


def test_restore_and_permanent_remove_are_separate_transitions() -> None:
    service, store, actor, item = make_service()
    trashed = service.trash(
        actor, item.kind, item.id, version=item.version, idempotency_key="trash-task-2"
    )

    restored = service.restore(
        actor,
        item.kind,
        item.id,
        version=trashed.version,
        idempotency_key="restore-task-1",
    )
    assert restored.trashed_at is None
    assert service.list_trash(actor).items == []

    trashed_again = service.trash(
        actor,
        item.kind,
        item.id,
        version=restored.version,
        idempotency_key="trash-task-3",
    )
    service.permanently_remove(
        actor,
        item.kind,
        item.id,
        version=trashed_again.version,
        idempotency_key="remove-task-1",
    )

    assert store.removed == [item.id]
    assert service.list_trash(actor).items == []
    assert store.audit == [
        ("task.trashed", "success"),
        ("task.restored", "success"),
        ("task.trashed", "success"),
        ("task.permanently_removed", "success"),
    ]


def test_kind_specific_reads_and_writes_require_the_matching_scope() -> None:
    service, _, _, item = make_service()
    actor = Actor(new_uuid7(), frozenset({"projects:read", "projects:write"}))

    with pytest.raises(PermissionDeniedError):
        service.list_trash(actor, kind=RecordKind.TASK)
    with pytest.raises(PermissionDeniedError):
        service.trash(
            actor,
            item.kind,
            item.id,
            version=item.version,
            idempotency_key="forbidden-task",
        )


def test_an_unfiltered_trash_listing_only_shows_kinds_the_caller_may_read() -> None:
    service, store, _, _ = make_service()
    store.items.append(TrashItem(RecordKind.CONTACT, new_uuid7(), "Ada", NOW, 2))
    store.items[0] = TrashItem(RecordKind.TASK, store.items[0].id, "Prepare pitch", NOW, 3)

    projects_only = Actor(new_uuid7(), frozenset({"projects:read"}))
    with_tasks = Actor(new_uuid7(), frozenset({"projects:read", "tasks:read"}))
    everything = Actor(new_uuid7(), frozenset({"projects:read", "tasks:read", "contacts:read"}))

    assert service.list_trash(projects_only).items == []
    assert {i.kind for i in service.list_trash(with_tasks).items} == {RecordKind.TASK}
    assert {i.kind for i in service.list_trash(everything).items} == {
        RecordKind.TASK,
        RecordKind.CONTACT,
    }


def test_unreadable_kinds_do_not_fill_the_page_and_hide_readable_records() -> None:
    service, store, _, _ = make_service()
    store.items.clear()
    # 101 newer trashed contacts the caller cannot read would fill a 100-item page on their own.
    for i in range(101):
        store.items.append(
            TrashItem(
                RecordKind.CONTACT, new_uuid7(), f"Contact {i}", NOW + timedelta(seconds=i + 1), 2
            )
        )
    readable = [
        TrashItem(RecordKind.TASK, new_uuid7(), f"Task {i}", NOW - timedelta(seconds=i), 2)
        for i in range(5)
    ]
    store.items.extend(readable)
    actor = Actor(new_uuid7(), frozenset({"projects:read", "tasks:read"}))

    page = service.list_trash(actor)

    assert [item.id for item in page.items] == [item.id for item in readable]
    assert page.next_cursor is None


def test_a_replayed_trash_keeps_only_the_id_and_reads_the_record_again() -> None:
    service, store, actor, item = make_service()

    first = service.trash(
        actor, item.kind, item.id, version=item.version, idempotency_key="trash-replay-1"
    )
    _, recorded = store.idempotency[(actor.user_id, "trash_record", "trash-replay-1")]
    assert recorded == {"id": str(item.id)}, "no label or other text is kept"
    # The record changed after the first answer; the retry shows it as it is now.
    stored = store.items.index(first)
    store.items[stored] = TrashItem(
        first.kind, first.id, "Nytt namn", first.trashed_at, first.version + 1
    )

    replayed = service.trash(
        actor, item.kind, item.id, version=item.version, idempotency_key="trash-replay-1"
    )

    assert replayed.label == "Nytt namn"
    assert replayed.version == first.version + 1


def test_a_within_filter_narrows_the_query_so_excluded_kinds_do_not_fill_the_page() -> None:
    service, store, _, _ = make_service()
    store.items.clear()
    # 101 newer trashed Journal sources would fill a 5-item page on their own if they were read.
    for i in range(101):
        store.items.append(
            TrashItem(
                RecordKind.JOURNAL_SOURCE,
                new_uuid7(),
                f"Source {i}",
                NOW + timedelta(seconds=i + 1),
                1,
            )
        )
    readable = [
        TrashItem(RecordKind.TASK, new_uuid7(), f"Task {i}", NOW - timedelta(seconds=i), 2)
        for i in range(5)
    ]
    store.items.extend(readable)
    actor = Actor(new_uuid7(), frozenset({"projects:read", "tasks:read", "journal:read"}))
    without_sources = frozenset(RecordKind) - {RecordKind.JOURNAL_SOURCE}

    page = service.list_trash(actor, limit=5, within=without_sources)

    assert [item.id for item in page.items] == [item.id for item in readable]
    assert page.next_cursor is None
    narrowed = service.list_trash(
        actor, kind=RecordKind.JOURNAL_SOURCE, limit=5, within=without_sources
    )
    assert narrowed.items == []


def _trashed(kind: RecordKind, offset_seconds: int, label: str) -> TrashItem:
    return TrashItem(kind, new_uuid7(), label, NOW + timedelta(seconds=offset_seconds), 2)


def _walk(service: RecordLifecycleService, actor: Actor, limit: int) -> list[list[UUID]]:
    pages: list[list[UUID]] = []
    cursor: str | None = None
    while True:
        page = service.list_trash(actor, limit=limit, cursor=cursor)
        pages.append([item.id for item in page.items])
        cursor = page.next_cursor
        if cursor is None:
            return pages


def test_trash_pages_follow_the_cursor_without_gaps_or_repeats_across_shared_timestamps() -> None:
    service, store, _, _ = make_service()
    store.items.clear()
    # Seven records share two trash times, so only the (kind, id) tiebreak keeps the order total.
    for i in range(4):
        store.items.append(_trashed(RecordKind.TASK, 10, f"Task {i}"))
    for kind in (RecordKind.PROJECT, RecordKind.CONTACT, RecordKind.ACTION):
        store.items.append(_trashed(kind, 5, kind.value))
    actor = Actor(new_uuid7(), frozenset({"projects:read", "tasks:read", "contacts:read"}))

    pages = _walk(service, actor, 2)

    expected = [
        item.id
        for item in sorted(
            store.items, key=lambda item: TrashPosition.of(item).sort_key(), reverse=True
        )
    ]
    assert [len(page) for page in pages] == [2, 2, 2, 1]
    assert [item_id for page in pages for item_id in page] == expected


def test_a_trash_cursor_survives_a_restore_between_pages() -> None:
    service, store, actor, _ = make_service()
    store.items.clear()
    for i in range(5):
        store.items.append(_trashed(RecordKind.TASK, i, f"Task {i}"))
    first = service.list_trash(actor, limit=2)
    assert first.next_cursor is not None
    # The newest record, already served, is restored; an offset cursor would now skip one record.
    service.restore(
        actor,
        first.items[0].kind,
        first.items[0].id,
        version=first.items[0].version,
        idempotency_key="restore-between-pages",
    )

    second = service.list_trash(actor, limit=2, cursor=first.next_cursor)

    assert [item.label for item in first.items] == ["Task 4", "Task 3"]
    assert [item.label for item in second.items] == ["Task 2", "Task 1"]


def test_a_trash_cursor_is_bound_to_the_owner_the_kind_and_the_signature() -> None:
    service, store, actor, _ = make_service()
    store.items.clear()
    for i in range(3):
        store.items.append(_trashed(RecordKind.TASK, i, f"Task {i}"))
    cursor = service.list_trash(actor, limit=1).next_cursor
    assert cursor is not None
    other_owner = Actor(new_uuid7(), actor.scopes)

    with pytest.raises(ValidationError, match="invalid pagination cursor"):
        service.list_trash(other_owner, limit=1, cursor=cursor)
    with pytest.raises(ValidationError, match="invalid pagination cursor"):
        service.list_trash(actor, kind=RecordKind.TASK, limit=1, cursor=cursor)
    with pytest.raises(ValidationError, match="invalid pagination cursor"):
        service.list_trash(actor, limit=1, cursor=cursor[:-2] + "AA")
    with pytest.raises(ValidationError, match="invalid pagination cursor"):
        service.list_trash(actor, limit=1, cursor="not-a-cursor")
    offset_cursor = service.cursor_codec.encode(actor.user_id, 1, "trash:v1:kinds=task")
    with pytest.raises(ValidationError, match="invalid pagination cursor"):
        service.list_trash(actor, kind=RecordKind.TASK, limit=1, cursor=offset_cursor)
    forged = service.cursor_codec.encode_position(
        actor.user_id, "no|such|position", "trash:v1:kinds=action,domain,process,project,step,task"
    )
    with pytest.raises(ValidationError, match="invalid pagination cursor"):
        service.list_trash(actor, limit=1, cursor=forged)

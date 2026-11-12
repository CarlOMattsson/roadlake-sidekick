"""The operator trash sweep and its `sidekick-admin empty-trash` command, without a database."""

import sys
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from sidekick import composition
from sidekick.lifecycle import RecordKind, RecordLifecycleService, TrashItem
from sidekick.lifecycle.application.empty_trash import empty_trash
from sidekick.shared.auth import cli as auth_cli
from sidekick.shared.db_timeouts import DatabaseTimeouts
from sidekick.shared.errors import ConflictError
from sidekick.shared.types import CursorCodec, new_uuid7
from tests.support.record_lifecycle import NOW, FakeLifecycleStore, FixedClock

OWNER = new_uuid7()
SECRET_TITLE = "PRIVATE_TITLE_NEVER_PRINTED"


class RefusingStore(FakeLifecycleStore):
    """Refuses to remove one kind, like a contact that still has aliases."""

    def __init__(self, refused: RecordKind) -> None:
        super().__init__()
        self.refused = refused

    def permanently_remove(
        self, session: Any, owner_id: UUID, kind: RecordKind, record_id: UUID, *, version: int
    ) -> None:
        if kind is self.refused:
            raise ConflictError("remove descendants before permanently removing this record")
        super().permanently_remove(session, owner_id, kind, record_id, version=version)


def trashed(kind: RecordKind, days_ago: int, label: str = SECRET_TITLE) -> TrashItem:
    return TrashItem(kind, new_uuid7(), label, NOW - timedelta(days=days_ago), 2)


def make(store: FakeLifecycleStore, *items: TrashItem) -> RecordLifecycleService:
    store.items = list(items)
    store.owner_ids = [OWNER]
    return RecordLifecycleService(store, FixedClock(), CursorCodec("unit-test-cursor-secret"))


def test_a_dry_run_counts_the_trash_and_removes_and_audits_nothing() -> None:
    store = FakeLifecycleStore()
    service = make(
        store,
        trashed(RecordKind.TASK, 1),
        trashed(RecordKind.TASK, 40),
        trashed(RecordKind.STEP, 2),
    )

    result = empty_trash(service, remove=False)

    assert dict(result.matched) == {RecordKind.TASK: 2, RecordKind.STEP: 1}
    assert not result.removed
    assert store.removed == []
    assert store.audit == []
    assert len(store.items) == 3


def test_removal_goes_through_the_lifecycle_use_case_children_first_and_is_audited() -> None:
    store = FakeLifecycleStore()
    task, step = trashed(RecordKind.TASK, 5), trashed(RecordKind.STEP, 5)
    service = make(store, task, step)

    result = empty_trash(service, remove=True)

    assert dict(result.removed) == {RecordKind.TASK: 1, RecordKind.STEP: 1}
    assert store.removed == [step.id, task.id]
    assert store.audit == [
        ("step.permanently_removed", "success"),
        ("task.permanently_removed", "success"),
    ]
    assert empty_trash(service, remove=True).matched == {}  # idempotent: a second run finds nothing


def test_untrashed_records_are_never_selected_or_removed() -> None:
    store = FakeLifecycleStore()
    active = TrashItem(RecordKind.TASK, new_uuid7(), "Active", None, 1)
    service = make(store, active, trashed(RecordKind.TASK, 3))

    empty_trash(service, remove=True)

    assert store.items == [active]


def test_older_than_keeps_recent_trash() -> None:
    store = FakeLifecycleStore()
    recent, old = trashed(RecordKind.TASK, 2), trashed(RecordKind.TASK, 31)
    service = make(store, recent, old)

    result = empty_trash(service, remove=True, older_than=timedelta(days=30))

    assert store.removed == [old.id]
    assert store.items == [recent]
    assert result.removed[RecordKind.TASK] == 1


def test_records_the_removal_rules_refuse_are_kept_not_forced() -> None:
    store = RefusingStore(RecordKind.CONTACT)
    service = make(
        store,
        trashed(RecordKind.CONTACT, 9),
        trashed(RecordKind.SHOPPING_ITEM, 9),
        trashed(RecordKind.TASK, 9),
    )

    result = empty_trash(service, remove=True)

    assert dict(result.removed) == {RecordKind.TASK: 1}
    assert dict(result.kept) == {RecordKind.CONTACT: 1, RecordKind.SHOPPING_ITEM: 1}
    assert len(store.items) == 2


def run_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    service: RecordLifecycleService,
    *args: str,
) -> str:
    monkeypatch.setattr(composition, "create_admin_lifecycle_service", lambda *_a: service)
    monkeypatch.setattr(auth_cli, "create_session_factory", lambda _url, **_kw: object())
    monkeypatch.setattr(
        auth_cli,
        "get_admin_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://unused", database_timeouts=DatabaseTimeouts()
        ),
    )
    monkeypatch.setattr(sys, "argv", ["sidekick-admin", "empty-trash", *args])
    auth_cli.main()
    captured = capsys.readouterr()
    assert SECRET_TITLE not in captured.out + captured.err
    return captured.out


def test_the_command_without_yes_prints_counts_per_kind_and_deletes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = FakeLifecycleStore()
    service = make(store, trashed(RecordKind.TASK, 1), trashed(RecordKind.TASK, 2))

    out = run_cli(monkeypatch, capsys, service)

    assert "Dry run: nothing was deleted. 2 in the trash:" in out
    assert "  task: 2" in out
    assert store.removed == []


def test_the_command_with_yes_removes_and_reports_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = FakeLifecycleStore()
    service = make(store, trashed(RecordKind.TASK, 1), trashed(RecordKind.TASK, 60))

    out = run_cli(monkeypatch, capsys, service, "--yes", "--older-than", "30")

    assert "Permanently removed 1 record(s):" in out
    assert "  task: 1" in out
    assert len(store.removed) == 1

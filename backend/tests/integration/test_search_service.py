"""Search use case: per-kind scopes, explicit-kind denial, bound cursors and sanitized logging."""

import base64
import json
import logging
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest

from sidekick.api.app import create_app
from sidekick.search.domain import KIND_SCOPE, Kind
from sidekick.search.schemas import SearchResult
from sidekick.shared.errors import PermissionDeniedError, ValidationError
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.search_fixtures import insert_entry, insert_source
from tests.support.settings import make_settings

LOGGER_NAME = "sidekick.search"
OWNER_SCOPES = frozenset({"tasks:read", "tasks:write"})
PAGE_FIELD = {
    Kind.TASK: "tasks",
    Kind.PROJECT: "projects",
    Kind.CONTACT: "contacts",
    Kind.JOURNAL: "journal",
}


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(name="search_logs")
def _search_logs() -> Iterator[_Collector]:
    """Attach to the search logger directly. `configure_observability` (run by `create_app`)
    sets `propagate = False` on the `sidekick` logger, so `caplog` never sees these records."""

    collector = _Collector()
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(collector)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous)


def _container(factory: Any) -> Any:
    return create_app(make_settings(), factory).state.container


def _provision(container: Any, username: str) -> UUID:
    return container.auth.provision_user(username, username.title())


def _task(container: Any, owner: Actor, title: str, key: str) -> UUID:
    return container.tasks.create(
        owner, title=title, description=None, idempotency_key=f"task-{key}"
    ).id


def test_each_kind_is_searched_only_with_its_own_scope() -> None:
    factory = database_factory()
    container = _container(factory)
    owner_id = _provision(container, "search-scope-owner")
    for kind in Kind:
        actor = Actor(owner_id, frozenset({KIND_SCOPE[kind]}))

        result: SearchResult = container.search.search(actor, "Kvartalsplan")

        assert result.searched == [kind]
        searched_pages = [
            field for field in PAGE_FIELD.values() if getattr(result, field) is not None
        ]
        assert searched_pages == [PAGE_FIELD[kind]]


def test_actor_without_any_search_scope_is_forbidden() -> None:
    factory = database_factory()
    container = _container(factory)
    owner_id = _provision(container, "search-no-scope-owner")

    with pytest.raises(PermissionDeniedError):
        container.search.search(Actor(owner_id, frozenset()), "Kvartalsplan")


def test_explicit_kind_without_scope_rejects_the_whole_call() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = Actor(_provision(container, "search-explicit-owner"), OWNER_SCOPES)
    _task(container, owner, "Kvartalsplan drift", "explicit")
    tasks_only = Actor(owner.user_id, frozenset({"tasks:read"}))

    with pytest.raises(PermissionDeniedError):
        container.search.search(tasks_only, "Kvartalsplan", ["task", "contact"])

    # The same actor may still search the kind it holds scope for.
    allowed = container.search.search(tasks_only, "Kvartalsplan", ["task"])
    assert allowed.searched == [Kind.TASK]
    assert allowed.tasks is not None and len(allowed.tasks.hits) == 1


def test_omitted_kinds_are_skipped_silently_and_listed_in_searched() -> None:
    factory = database_factory()
    container = _container(factory)
    owner_id = _provision(container, "search-omitted-owner")
    actor = Actor(owner_id, frozenset({"tasks:read", "contacts:read"}))

    result = container.search.search(actor, "Kvartalsplan")

    assert result.searched == [Kind.TASK, Kind.CONTACT]
    assert result.tasks is not None
    assert result.contacts is not None
    assert result.projects is None
    assert result.journal is None


def test_cursor_is_bound_to_its_query_and_actor() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = Actor(_provision(container, "search-cursor-owner"), OWNER_SCOPES)
    other_id = _provision(container, "search-cursor-other")
    for index, name in enumerate(("alpha", "beta", "gamma")):
        _task(container, owner, f"Matchklockan {name}", f"cursor-{index}")
    reader = Actor(owner.user_id, frozenset({"tasks:read"}))

    first = container.search.search(reader, "Matchklockan", ["task"], limit=1)
    assert first.tasks is not None
    assert len(first.tasks.hits) == 1
    cursor = first.tasks.next_cursor
    assert cursor is not None

    second = container.search.search(reader, "Matchklockan", ["task"], limit=1, cursor=cursor)
    assert second.tasks is not None
    assert second.tasks.hits[0].id != first.tasks.hits[0].id

    with pytest.raises(ValidationError):
        container.search.search(reader, "Ringa leverantoren", ["task"], limit=1, cursor=cursor)

    other_reader = Actor(other_id, frozenset({"tasks:read"}))
    with pytest.raises(ValidationError):
        container.search.search(other_reader, "Matchklockan", ["task"], limit=1, cursor=cursor)

    both = Actor(owner.user_id, frozenset({"tasks:read", "contacts:read"}))
    with pytest.raises(ValidationError):
        container.search.search(both, "Matchklockan", ["task", "contact"], limit=1, cursor=cursor)


def test_limit_and_query_bounds_are_validated() -> None:
    factory = database_factory()
    container = _container(factory)
    actor = Actor(_provision(container, "search-bounds-owner"), frozenset({"tasks:read"}))

    for limit in (0, 26):
        with pytest.raises(ValidationError):
            container.search.search(actor, "Kvartalsplan", ["task"], limit=limit)
    with pytest.raises(ValidationError):
        container.search.search(actor, "a", ["task"])
    with pytest.raises(ValidationError):
        container.search.search(actor, "!!", ["task"])


def test_logs_carry_lengths_and_counts_but_never_the_query(
    search_logs: _Collector,
) -> None:
    factory = database_factory()
    container = _container(factory)
    owner = Actor(_provision(container, "search-log-owner"), OWNER_SCOPES)
    _task(container, owner, "Kvartalsplanen för drift", "log")
    reader = Actor(owner.user_id, frozenset({"tasks:read"}))
    query = "Kvartalsplanen drift"
    search_logs.records.clear()

    result = container.search.search(reader, query, ["task"], limit=5)

    assert result.tasks is not None and len(result.tasks.hits) == 1
    completed = [record for record in search_logs.records if record.name == LOGGER_NAME]
    assert len(completed) == 1
    record = completed[0]
    assert record.getMessage() == "search_completed"
    assert record.query_length == len(query)  # type: ignore[attr-defined]
    assert record.term_count == 2  # type: ignore[attr-defined]
    assert record.hit_counts == {"task": 1}  # type: ignore[attr-defined]
    rendered = " ".join(f"{item.getMessage()} {item.__dict__}" for item in search_logs.records)
    for forbidden in (query, "kvartalsplanen", "drift"):
        assert forbidden.lower() not in rendered.lower()


def _tamper_cursor(cursor: str, *, offset: int | None = None, flip_signature: bool = False) -> str:
    """Rebuild a signed cursor with its payload offset or its signature altered."""

    padded = cursor + "=" * (-len(cursor) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode())
    payload, signature = decoded[:-32], decoded[-32:]
    if offset is not None:
        data = json.loads(payload)
        data["offset"] = offset
        payload = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    if flip_signature:
        signature = bytes([signature[0] ^ 0x01]) + signature[1:]
    return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")


def test_tampered_cursor_is_rejected_with_validation_error() -> None:
    factory = database_factory()
    container = _container(factory)
    owner = Actor(_provision(container, "search-tamper-owner"), OWNER_SCOPES)
    for index, name in enumerate(("alpha", "beta", "gamma")):
        _task(container, owner, f"Matchklockan {name}", f"tamper-{index}")
    reader = Actor(owner.user_id, frozenset({"tasks:read"}))

    first = container.search.search(reader, "Matchklockan", ["task"], limit=1)
    assert first.tasks is not None
    cursor = first.tasks.next_cursor
    assert cursor is not None
    valid = container.search.search(reader, "Matchklockan", ["task"], limit=1, cursor=cursor)
    assert valid.tasks is not None and len(valid.tasks.hits) == 1

    with pytest.raises(ValidationError):
        container.search.search(
            reader, "Matchklockan", ["task"], limit=1, cursor=_tamper_cursor(cursor, offset=0)
        )
    with pytest.raises(ValidationError):
        container.search.search(
            reader,
            "Matchklockan",
            ["task"],
            limit=1,
            cursor=_tamper_cursor(cursor, flip_signature=True),
        )


def test_journal_hits_carry_entry_title_and_never_summary_or_raw_text() -> None:
    factory = database_factory()
    container = _container(factory)
    owner_id = _provision(container, "search-journal-title-owner")
    owner = Actor(owner_id, frozenset({KIND_SCOPE[Kind.JOURNAL]}))
    source_id = insert_source(factory, owner_id, "Mötesanteckningar med hemlig brödtext")
    entry_id = insert_entry(
        factory, owner_id, source_id, "Revisionsmötet", summary="Sammanfattningssentinel"
    )
    bare_source_id = insert_source(factory, owner_id, "Bilmekanik och oljebyte idag")

    entry_result = container.search.search(owner, "revision", [Kind.JOURNAL.value])
    source_result = container.search.search(owner, "bilmekanik", [Kind.JOURNAL.value])

    assert entry_result.journal is not None and source_result.journal is not None
    [entry_hit] = entry_result.journal.hits
    [source_hit] = source_result.journal.hits
    assert (entry_hit.id, entry_hit.id_type, entry_hit.title) == (
        entry_id,
        "entry",
        "Revisionsmötet",
    )
    assert (source_hit.id, source_hit.id_type, source_hit.title) == (
        bare_source_id,
        "source",
        None,
    )
    dumped_entry = entry_result.model_dump(mode="json")["journal"]["hits"][0]
    dumped_source = source_result.model_dump(mode="json")["journal"]["hits"][0]
    assert set(dumped_entry) == {"id", "id_type", "journal_date", "matched_in", "title"}
    assert dumped_source["title"] is None
    for dumped in (dumped_entry, dumped_source):
        rendered = json.dumps(dumped, ensure_ascii=False)
        for forbidden in ("Sammanfattningssentinel", "brödtext", "oljebyte"):
            assert forbidden not in rendered

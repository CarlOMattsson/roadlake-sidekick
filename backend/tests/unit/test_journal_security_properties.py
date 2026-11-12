"""Journal security and bounded privacy boundaries."""

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sidekick.journal.application.paging import validate_list_bounds
from sidekick.journal.application.relations import bounded_unique_ids
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.records import EntryRelations
from sidekick.mcp.results import error_result
from sidekick.shared.errors import NotFoundError, PermissionDeniedError, ValidationError
from sidekick.shared.types import Actor, CursorCodec
from sidekick.structured.journal import JournalEntryRecord, entry_record

OWNER_ID = UUID("018af000-0000-7000-8000-000000000001")
OTHER_ID = UUID("018af000-0000-7000-8000-000000000002")


@given(st.integers(min_value=366, max_value=2_000))
@settings(max_examples=50)
def test_journal_date_ranges_never_exceed_366_inclusive_days(day_span: int) -> None:
    start = date(2026, 1, 1)
    with pytest.raises(ValidationError, match="at most 366"):
        validate_list_bounds(start, start + timedelta(days=day_span), 100)


@given(st.integers(min_value=26, max_value=100))
def test_relation_inputs_are_bounded_and_unique(relation_count: int) -> None:
    values = tuple(UUID(int=index + 1) for index in range(relation_count))
    with pytest.raises(ValidationError, match="at most 25"):
        bounded_unique_ids(values, "project_ids")

    with pytest.raises(ValidationError, match="unique"):
        bounded_unique_ids(values[:1] * 2, "project_ids")


@given(st.sampled_from(["journal:read", "journal:write", "projects:read", "tasks:read"]))
def test_missing_scope_never_falls_back_to_another_scope(scope: str) -> None:
    actor = Actor(OWNER_ID, frozenset())
    with pytest.raises(PermissionDeniedError, match=scope):
        actor.require(scope)


@given(st.integers(min_value=0, max_value=100), st.text(min_size=0, max_size=40))
def test_cursors_are_bound_to_actor_and_query(offset: int, query_key: str) -> None:
    codec = CursorCodec("security-property-test-secret")
    cursor = codec.encode(OWNER_ID, offset, query_key)

    assert codec.decode(OWNER_ID, cursor, query_key) == offset
    with pytest.raises(ValueError):
        codec.decode(OTHER_ID, cursor, query_key)
    with pytest.raises(ValueError):
        codec.decode(OWNER_ID, cursor, query_key + "-changed")


def _entry() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        source_id=uuid4(),
        journal_date=date(2026, 7, 21),
        occurred_at=None,
        title="Private title",
        summary="Private summary",
        key_points=(KeyPoint(KeyPointKind.DECISION, "Private point"),),
        archived_at=None,
        version=1,
    )


@pytest.mark.parametrize("include_content", [False, True])
def test_content_flag_is_explicit_and_bounded(include_content: bool) -> None:
    output = entry_record(
        _entry(),
        EntryRelations(),
        include_content=include_content,
    )
    assert isinstance(output, JournalEntryRecord)
    if include_content:
        assert output.summary == "Private summary"
        assert [point.text for point in output.key_points] == ["Private point"]
    else:
        assert output.summary is None
        assert output.key_points == []


def test_error_projection_redacts_inaccessible_identifiers() -> None:
    response = error_result(NotFoundError("private source sentinel"))
    assert response.is_error is True
    assert response.structured_content == {
        "code": "not_found",
        "message": "I could not find that. Check the name or search again.",
        "correlation_id": response.structured_content["correlation_id"],
    }
    assert "private source sentinel" not in str(response)

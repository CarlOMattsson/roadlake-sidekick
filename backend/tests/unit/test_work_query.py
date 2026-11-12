"""Closed Work query and ordering rules."""

import pytest

from sidekick.shared.errors import ValidationError
from sidekick.shared.types import new_uuid7
from sidekick.work.application.models import WorkQuery


def test_work_query_rejects_unsupported_projection_inputs() -> None:
    with pytest.raises(ValidationError):
        WorkQuery(sort="sql").validate()
    with pytest.raises(ValidationError):
        WorkQuery(group="expression").validate()
    with pytest.raises(ValidationError):
        WorkQuery(limit=101).validate()


def test_work_query_key_changes_with_filters() -> None:
    base = WorkQuery().validate().key()
    changed = WorkQuery(status="blocked").validate().key()
    assert base != changed


def test_work_query_key_changes_with_project_filter() -> None:
    base = WorkQuery().validate().key()
    scoped = WorkQuery(project_id=new_uuid7()).validate().key()
    assert base != scoped


def test_work_query_key_changes_with_max_minutes_and_undated() -> None:
    base = WorkQuery().validate().key()
    assert WorkQuery(max_minutes=15).validate().key() != base
    assert WorkQuery(include_undated=True).validate().key() != base


def test_work_query_rejects_an_out_of_range_max_minutes() -> None:
    with pytest.raises(ValidationError):
        WorkQuery(max_minutes=0).validate()
    with pytest.raises(ValidationError):
        WorkQuery(max_minutes=12_001).validate()

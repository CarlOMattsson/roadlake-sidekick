"""Work planning rules without database, transport, or providers.

Everything here is a pure function of stored values plus an explicit `now`: a
passing timestamp never writes, and no derived reason touches stored intent.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import new_uuid7
from sidekick.tasks.domain import Priority, Task, TaskStatus
from sidekick.work.domain import (
    Action,
    ActionStatus,
    Domain,
    DomainStatus,
    Process,
    ProcessStatus,
    Step,
)
from sidekick.work.domain.planning import (
    ESTIMATE_PRESETS,
    MAX_ESTIMATED_MINUTES,
    MAX_TAG_FILTER_VALUES,
    MAX_TAGS_PER_RECORD,
    Cadence,
    WorkTag,
    is_actionable_now,
    is_review_due,
    matches_tag_filter,
    normalize_tag_filter,
    normalize_tag_selection,
    normalize_tag_slug,
    parse_cadence,
    validate_estimated_minutes,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def make_domain(**overrides: object) -> Domain:
    values: dict[str, object] = {
        "id": new_uuid7(),
        "owner_id": new_uuid7(),
        "name": "Northwind",
        "description": None,
        "status": DomainStatus.ACTIVE,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return Domain(**values)  # type: ignore[arg-type]


def make_task(**overrides: object) -> Task:
    values: dict[str, object] = {
        "id": new_uuid7(),
        "owner_id": new_uuid7(),
        "project_id": None,
        "title": "Follow up invoices",
        "description": None,
        "status": TaskStatus.IN_PROGRESS,
        "priority": Priority.NORMAL,
        "due_at": None,
        "completed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return Task(**values)  # type: ignore[arg-type]


def make_project(**overrides: object) -> Project:
    values: dict[str, object] = {
        "id": new_uuid7(),
        "owner_id": new_uuid7(),
        "title": "Move the office",
        "description": None,
        "status": ProjectStatus.ACTIVE,
        "start_date": None,
        "target_date": None,
        "created_at": NOW,
        "updated_at": NOW,
        "domain_id": new_uuid7(),
    }
    values.update(overrides)
    return Project(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------- cadence


def test_cadence_intervals_are_fixed_and_documented() -> None:
    assert Cadence.DAILY.interval == timedelta(days=1)
    assert Cadence.WEEKLY.interval == timedelta(days=7)
    assert Cadence.BIWEEKLY.interval == timedelta(days=14)
    assert Cadence.MONTHLY.interval == timedelta(days=30)
    assert Cadence.QUARTERLY.interval == timedelta(days=90)
    assert Cadence.YEARLY.interval == timedelta(days=365)


def test_unsupported_cadence_value_is_rejected() -> None:
    assert parse_cadence("weekly") is Cadence.WEEKLY
    assert parse_cadence(None) is None
    with pytest.raises(ValidationError):
        parse_cadence("fortnightly")


# ----------------------------------------------------------------- review_due


def test_review_is_due_when_the_declared_interval_has_elapsed() -> None:
    domain = make_domain(review_cadence=Cadence.WEEKLY, last_reviewed_at=NOW - timedelta(days=8))
    assert domain.review_due(now=NOW) is True


def test_review_is_not_due_inside_the_interval() -> None:
    domain = make_domain(review_cadence=Cadence.WEEKLY, last_reviewed_at=NOW - timedelta(days=2))
    assert domain.review_due(now=NOW) is False


def test_a_cadence_without_any_recorded_review_is_due() -> None:
    domain = make_domain(review_cadence=Cadence.MONTHLY, last_reviewed_at=None)
    assert domain.review_due(now=NOW) is True


def test_no_cadence_means_no_review_reason() -> None:
    domain = make_domain(last_reviewed_at=NOW - timedelta(days=900))
    assert domain.review_due(now=NOW) is False


def test_archived_domains_never_demand_review() -> None:
    domain = make_domain(
        status=DomainStatus.ARCHIVED, review_cadence=Cadence.DAILY, last_reviewed_at=None
    )
    assert domain.review_due(now=NOW) is False


def test_recording_a_review_silences_the_reason_until_the_next_period() -> None:
    domain = make_domain(review_cadence=Cadence.WEEKLY)
    assert domain.review_due(now=NOW) is True

    reviewed = domain.update(now=NOW, last_reviewed_at=NOW)

    assert reviewed.review_due(now=NOW) is False
    assert reviewed.review_due(now=NOW + timedelta(days=8)) is True
    assert reviewed.version == domain.version + 1


def test_review_derivation_is_pure() -> None:
    assert (
        is_review_due(review_cadence=Cadence.DAILY, last_reviewed_at=None, archived=False, now=NOW)
        is True
    )
    assert (
        is_review_due(review_cadence=None, last_reviewed_at=None, archived=False, now=NOW) is False
    )


# --------------------------------------------------------------- earliest start


def test_earliest_start_later_than_the_deadline_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_task(not_before=NOW + timedelta(days=3), due_at=NOW)


def test_earliest_start_never_changes_stored_state_when_it_passes() -> None:
    task = make_task(not_before=NOW + timedelta(hours=2))

    assert is_actionable_now(task.not_before, NOW) is False
    assert is_actionable_now(task.not_before, NOW + timedelta(hours=3)) is True
    assert task.status is TaskStatus.IN_PROGRESS
    assert task.updated_at == NOW


def test_project_earliest_start_is_validated_against_its_target_date() -> None:
    with pytest.raises(ValidationError):
        make_project(start_date=date(2026, 9, 1), target_date=date(2026, 8, 1))

    project = make_project(start_date=date(2026, 8, 1))
    with pytest.raises(ValidationError):
        project.update(now=NOW, target_date=date(2026, 7, 1))


def test_project_definition_of_done_is_bounded() -> None:
    project = make_project()
    updated = project.update(now=NOW, definition_of_done="Keys handed over")
    assert updated.definition_of_done == "Keys handed over"
    with pytest.raises(ValidationError):
        project.update(now=NOW, definition_of_done="x" * 2001)


# -------------------------------------------------------------------- estimates


def test_estimate_bounds() -> None:
    assert validate_estimated_minutes(None) is None
    assert validate_estimated_minutes(45) == 45
    assert validate_estimated_minutes(MAX_ESTIMATED_MINUTES) == MAX_ESTIMATED_MINUTES
    for invalid in (0, -5, MAX_ESTIMATED_MINUTES + 1):
        with pytest.raises(ValidationError):
            validate_estimated_minutes(invalid)


def test_every_preset_is_a_valid_stored_estimate() -> None:
    assert all(validate_estimated_minutes(preset) == preset for preset in ESTIMATE_PRESETS)


def test_estimates_exist_on_tasks_only() -> None:
    task = make_task().update(now=NOW, estimated_minutes=30)
    assert task.estimated_minutes == 30
    assert not hasattr(make_domain(), "estimated_minutes")
    assert not hasattr(make_project(), "estimated_minutes")


# ---------------------------------------------------------------------- waiting


def test_waiting_is_orthogonal_to_status() -> None:
    task = make_task(waiting_since=NOW, follow_up_at=NOW + timedelta(days=3))

    assert task.waiting is True
    assert task.status is TaskStatus.IN_PROGRESS


def test_completed_tasks_are_not_waiting() -> None:
    task = make_task(status=TaskStatus.COMPLETED, completed_at=NOW, waiting_since=NOW)
    assert task.waiting is False
    assert task.follow_up_due(now=NOW + timedelta(days=30)) is False


def test_follow_up_is_derived_not_stored() -> None:
    task = make_task(waiting_since=NOW, follow_up_at=NOW + timedelta(days=2))

    assert task.follow_up_due(now=NOW) is False
    assert task.follow_up_due(now=NOW + timedelta(days=2)) is True
    assert task.attention_requested is False


def test_follow_up_or_contact_without_waiting_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_task(follow_up_at=NOW)
    with pytest.raises(ValidationError):
        make_task(waiting_on_contact_id=new_uuid7())
    task = make_task(waiting_since=NOW)
    with pytest.raises(ValidationError):
        task.update(now=NOW, follow_up_at=NOW, waiting_since=None)


def test_clearing_waiting_clears_all_three_values_at_once() -> None:
    contact_id = new_uuid7()
    task = make_task(
        waiting_since=NOW, follow_up_at=NOW + timedelta(days=1), waiting_on_contact_id=contact_id
    )

    cleared = task.update(now=NOW, waiting_since=None)

    assert cleared.waiting_since is None
    assert cleared.follow_up_at is None
    assert cleared.waiting_on_contact_id is None
    assert cleared.status is task.status


def test_marking_waiting_keeps_status_and_bumps_the_version() -> None:
    task = make_task()
    contact_id = new_uuid7()

    waiting = task.update(
        now=NOW,
        waiting_since=NOW,
        follow_up_at=NOW + timedelta(days=4),
        waiting_on_contact_id=contact_id,
    )

    assert waiting.status is TaskStatus.IN_PROGRESS
    assert waiting.waiting_on_contact_id == contact_id
    assert waiting.version == task.version + 1


# ------------------------------------------------------------------------- tags


def test_slug_normalization_collapses_case_and_whitespace() -> None:
    assert normalize_tag_slug("Ekonomi") == "ekonomi"
    assert normalize_tag_slug("  ekonomi  ") == "ekonomi"
    assert normalize_tag_slug("Vänta   på  svar") == "vänta-på-svar"
    with pytest.raises(ValidationError):
        normalize_tag_slug("   ")
    with pytest.raises(ValidationError):
        normalize_tag_slug("x" * 61)


def test_tag_labels_keep_the_owners_writing_and_are_bounded() -> None:
    tag = WorkTag(
        id=new_uuid7(),
        owner_id=new_uuid7(),
        slug="Ekonomi",
        label="Ekonomi",
        created_at=NOW,
        updated_at=NOW,
    )
    assert (tag.slug, tag.label) == ("ekonomi", "Ekonomi")

    renamed = tag.rename(now=NOW, label="Privat ekonomi")
    assert (renamed.slug, renamed.label) == ("privat-ekonomi", "Privat ekonomi")
    assert renamed.version == tag.version + 1

    with pytest.raises(ValidationError):
        tag.rename(now=NOW, label="x" * 41)


def test_archiving_a_tag_keeps_it_readable() -> None:
    tag = WorkTag(
        id=new_uuid7(),
        owner_id=new_uuid7(),
        slug="telefon",
        label="Telefon",
        created_at=NOW,
        updated_at=NOW,
    )
    archived = tag.archive(now=NOW)
    assert archived.archived is True
    assert archived.slug == "telefon"
    assert archived.restore(now=NOW).archived is False


def test_tag_assignment_is_deduplicated_and_bounded() -> None:
    assert normalize_tag_selection(["Ekonomi", "ekonomi", "Telefon"]) == ("ekonomi", "telefon")
    with pytest.raises(ValidationError):
        normalize_tag_selection([f"tag-{index}" for index in range(MAX_TAGS_PER_RECORD + 1)])


def test_tag_filter_is_bounded_with_an_explicit_match_mode() -> None:
    assert normalize_tag_filter(["Ekonomi", "ekonomi"]) == (("ekonomi",), "any")
    assert normalize_tag_filter(["a", "b"], "all") == (("a", "b"), "all")
    assert normalize_tag_filter(None) == ((), "any")
    with pytest.raises(ValidationError):
        normalize_tag_filter(["a"], "either")
    with pytest.raises(ValidationError):
        normalize_tag_filter([f"tag-{index}" for index in range(MAX_TAG_FILTER_VALUES + 1)])


def test_tag_matching_honours_any_and_all() -> None:
    record = ("ekonomi", "telefon")
    assert matches_tag_filter(record, (), "any") is True
    assert matches_tag_filter(record, ("ekonomi", "hemma"), "any") is True
    assert matches_tag_filter(record, ("ekonomi", "hemma"), "all") is False
    assert matches_tag_filter(record, ("ekonomi", "telefon"), "all") is True


# ------------------------------------------------------- step and action fields


def test_step_instruction_and_action_note_are_bounded() -> None:
    step = Step(
        id=new_uuid7(),
        owner_id=new_uuid7(),
        task_id=new_uuid7(),
        title="Review the diff",
        status=TaskStatus.TODO,
        position=0,
        due_at=None,
        attention_requested=False,
        created_at=NOW,
        updated_at=NOW,
    )
    assert step.update(now=NOW, instruction="Read the tests first").instruction is not None
    with pytest.raises(ValidationError):
        step.update(now=NOW, instruction="x" * 2001)

    action = Action(
        id=new_uuid7(),
        owner_id=new_uuid7(),
        step_id=new_uuid7(),
        title="Call the supplier",
        status=ActionStatus.OPEN,
        position=0,
        due_at=None,
        attention_requested=False,
        created_at=NOW,
        updated_at=NOW,
    )
    assert action.update(now=NOW, note="Ask for the invoice number").note is not None
    with pytest.raises(ValidationError):
        action.update(now=NOW, note="x" * 501)


def test_process_domain_carries_the_next_expected_run_marker() -> None:
    process = Process(
        id=new_uuid7(),
        owner_id=new_uuid7(),
        domain_id=new_uuid7(),
        name="Monthly bookkeeping",
        description=None,
        status=ProcessStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    updated = process.update(now=NOW, cadence=Cadence.MONTHLY)

    assert updated.cadence is Cadence.MONTHLY
    assert updated.next_expected_run_at is None

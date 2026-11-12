"""Row to domain mappers for domains, processes, runs, steps and actions."""

from sidekick.shared.persistence.models import (
    ActionRow,
    DomainRow,
    ProcessRow,
    ProcessRunOutboxRow,
    ProcessRunRow,
    ProcessRunTemplateRow,
    StepRow,
)
from sidekick.tasks.domain import Priority, TaskStatus
from sidekick.work.domain import (
    Action,
    ActionStatus,
    Domain,
    DomainStatus,
    Process,
    ProcessRun,
    ProcessRunOutbox,
    ProcessRunTemplate,
    ProcessStatus,
    Step,
    run_steps_from_data,
)
from sidekick.work.domain.planning import parse_cadence


def domain_from_row(row: DomainRow) -> Domain:
    return Domain(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        description=row.description,
        status=DomainStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
        review_cadence=parse_cadence(row.review_cadence),
        last_reviewed_at=row.last_reviewed_at,
        accent=row.accent,
    )


def domain_to_row(domain: Domain) -> DomainRow:
    return DomainRow(
        id=domain.id,
        owner_id=domain.owner_id,
        name=domain.name,
        description=domain.description,
        status=domain.status.value,
        created_at=domain.created_at,
        updated_at=domain.updated_at,
        version=domain.version,
        review_cadence=domain.review_cadence.value if domain.review_cadence else None,
        last_reviewed_at=domain.last_reviewed_at,
        accent=domain.accent,
    )


def process_from_row(row: ProcessRow) -> Process:
    return Process(
        id=row.id,
        owner_id=row.owner_id,
        domain_id=row.domain_id,
        name=row.name,
        description=row.description,
        status=ProcessStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
        cadence=parse_cadence(row.cadence),
        next_expected_run_at=row.next_expected_run_at,
    )


def process_to_row(process: Process) -> ProcessRow:
    return ProcessRow(
        id=process.id,
        owner_id=process.owner_id,
        domain_id=process.domain_id,
        name=process.name,
        description=process.description,
        status=process.status.value,
        created_at=process.created_at,
        updated_at=process.updated_at,
        version=process.version,
        cadence=process.cadence.value if process.cadence else None,
        next_expected_run_at=process.next_expected_run_at,
    )


def process_run_template_from_row(row: ProcessRunTemplateRow) -> ProcessRunTemplate:
    return ProcessRunTemplate(
        id=row.id,
        owner_id=row.owner_id,
        process_id=row.process_id,
        title=row.title,
        description=row.description,
        priority=Priority(row.priority),
        estimated_minutes=row.estimated_minutes,
        due_after_days=row.due_after_days,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        steps=run_steps_from_data(row.structure),
    )


def process_run_from_row(row: ProcessRunRow) -> ProcessRun:
    return ProcessRun(
        id=row.id,
        owner_id=row.owner_id,
        process_id=row.process_id,
        task_id=row.task_id,
        scheduled_for=row.scheduled_for,
        template_version=row.template_version,
        created_at=row.created_at,
    )


def process_run_outbox_from_row(row: ProcessRunOutboxRow) -> ProcessRunOutbox:
    return ProcessRunOutbox(
        id=row.id,
        owner_id=row.owner_id,
        process_id=row.process_id,
        scheduled_for=row.scheduled_for,
        status=row.status,
        attempts=row.attempts,
        worker_id=row.worker_id,
        claimed_at=row.claimed_at,
        processed_at=row.processed_at,
        process_run_id=row.process_run_id,
        last_error=row.last_error,
    )


def step_from_row(row: StepRow) -> Step:
    return Step(
        row.id,
        row.owner_id,
        row.task_id,
        row.title,
        TaskStatus(row.status),
        row.position,
        row.due_at,
        row.attention_requested,
        row.created_at,
        row.updated_at,
        row.version,
        row.archived_at,
        row.instruction,
        row.completed_at,
    )


def step_to_row(step: Step) -> StepRow:
    return StepRow(
        id=step.id,
        owner_id=step.owner_id,
        task_id=step.task_id,
        title=step.title,
        status=step.status.value,
        position=step.position,
        due_at=step.due_at,
        attention_requested=step.attention_requested,
        created_at=step.created_at,
        updated_at=step.updated_at,
        version=step.version,
        archived_at=step.archived_at,
        instruction=step.instruction,
        completed_at=step.completed_at,
    )


def action_from_row(row: ActionRow) -> Action:
    return Action(
        row.id,
        row.owner_id,
        row.step_id,
        row.title,
        ActionStatus(row.status),
        row.position,
        row.due_at,
        row.attention_requested,
        row.created_at,
        row.updated_at,
        row.version,
        row.archived_at,
        row.note,
    )


def action_to_row(action: Action) -> ActionRow:
    return ActionRow(
        id=action.id,
        owner_id=action.owner_id,
        step_id=action.step_id,
        title=action.title,
        status=action.status.value,
        position=action.position,
        due_at=action.due_at,
        attention_requested=action.attention_requested,
        created_at=action.created_at,
        updated_at=action.updated_at,
        version=action.version,
        archived_at=action.archived_at,
        note=action.note,
    )

"""The structured content of the Work reads and writes, shared by MCP tools and the companion API.

Each function calls the same application use case for both interfaces and returns the closed
record payload; the MCP tools add their card text on top."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sidekick.projects.application.service import project_public_data
from sidekick.projects.domain import Project
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.text_excerpt import excerpt
from sidekick.shared.types import Actor
from sidekick.structured.work_records import (
    ActionRecord,
    DomainOutput,
    DomainRecord,
    HierarchyNodeRecord,
    HierarchyOutput,
    HierarchyTaskRecord,
    ListedStepPageOutput,
    ListedStepRecord,
    ProcessOutput,
    ProcessRecord,
    ProjectDetailOutput,
    ProjectDetailRecord,
    StepOutput,
    StepRecord,
    TaskChanges,
    TaskDetailOutput,
    TaskDetailRecord,
    TaskListRecord,
    TaskOutput,
    TaskPageOutput,
    TaskRecord,
    WorkItemPageOutput,
    WorkItemRecord,
    end_of_day_due_at,
)
from sidekick.tasks.application import UpdateTaskCommand
from sidekick.tasks.application.models import TaskDetailRead
from sidekick.tasks.application.serialization import task_public_data
from sidekick.tasks.domain import Priority, TaskStatus
from sidekick.work.application.models import HierarchyNode, WorkQuery, WorkRow
from sidekick.work.application.serialization import (
    clipped_project_title,
    domain_public_data,
    process_hierarchy_node,
    process_public_data,
)
from sidekick.work.domain import Action, ActionCounts, Step
from sidekick.work.listing import (
    WorkActionable,
    WorkArchive,
    WorkAttention,
    WorkEstimate,
    WorkGroup,
    WorkKind,
    WorkSort,
    WorkTagMatch,
    WorkWaiting,
)

if TYPE_CHECKING:
    from sidekick.composition import Container

RECORD_STEP_LIMIT = 50


def with_tags(data: dict[str, Any], tags: list[str] | None) -> dict[str, Any]:
    """Attach the record's tag slugs to a public contract payload."""

    return {**data, "tags": list(tags or [])}


def applied_filters(
    values: Mapping[str, Any], defaults: Mapping[str, Any]
) -> dict[str, str | list[str]]:
    """The filter arguments a read narrowed by, in the form the tool takes them.

    Empty values and values equal to the tool's default are left out, so a plain read echoes {}.
    This goes only into structuredContent, which the card reads to repeat the same read; the
    model-facing card text never carries it.
    """
    applied: dict[str, str | list[str]] = {}
    for name, value in values.items():
        if value is None or value == "" or value == []:
            continue
        if name in defaults and value == defaults[name]:
            continue
        if isinstance(value, list):
            applied[name] = [str(item) for item in cast(list[object], value)]
        else:
            applied[name] = str(value)
    return applied


def waiting_contact_names(
    container: Container, actor: Actor, rows: Sequence[WorkRow]
) -> dict[UUID, str]:
    """Return the display name of each Contact a record waits on, by id.

    Empty without the contacts:read scope, so a session that cannot read Contacts still sees the
    waiting record, only without the name. An archived Contact keeps its name.
    """

    if "contacts:read" not in actor.scopes:
        return {}
    wanted = [row.waiting_on_contact_id for row in rows if row.waiting_on_contact_id is not None]
    if not wanted:
        return {}
    return dict(container.contacts.waiting_contact_names(actor, wanted))


def work_item_record(row: WorkRow, names: Mapping[UUID, str]) -> WorkItemRecord:
    """The structured record of a Work row: the one place a row becomes plain data."""

    data = row.to_data()
    if row.waiting_on_contact_id is not None:
        data["waiting_on_contact_name"] = names.get(row.waiting_on_contact_id)
    return WorkItemRecord.model_validate(data)


@dataclass(frozen=True, slots=True)
class WorkAgendaArguments:
    """The arguments of `get_work_agenda`, with its defaults. Bounds are checked by each caller's
    own schema (the MCP tool signature, the companion query parameters), which a test keeps equal.
    """

    limit: int = 25
    q: str | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    attention: WorkAttention = "all"
    archive: WorkArchive = "active"
    kind: WorkKind = "all"
    sort: WorkSort = "due_asc"
    group: WorkGroup = "none"
    tags: tuple[str, ...] | None = None
    tag_match: WorkTagMatch = "any"
    actionable: WorkActionable = "all"
    waiting: WorkWaiting = "all"
    estimate: WorkEstimate = "all"
    cursor: str | None = None
    max_minutes: int | None = None
    include_undated: bool = False


def work_agenda_structured(
    container: Container, actor: Actor, arguments: WorkAgendaArguments
) -> WorkItemPageOutput:
    """The structured content of `get_work_agenda`; the companion adapter answers the same."""

    a = arguments
    status = a.status.value if a.status else None
    priority = a.priority.value if a.priority else None
    tags = list(a.tags) if a.tags is not None else None
    page = container.work_lists.work_agenda_page(
        actor,
        WorkQuery(
            q=a.q,
            status=status,
            priority=priority,
            attention=a.attention,
            archive=a.archive,
            kind=a.kind,
            sort=a.sort,
            group=a.group,
            limit=a.limit,
            cursor=a.cursor,
            tags=tuple(tags or ()),
            tag_match=a.tag_match,
            actionable=a.actionable,
            waiting=a.waiting,
            estimate=a.estimate,
            max_minutes=a.max_minutes,
            include_undated=a.include_undated,
        ),
    )
    filters = applied_filters(
        {
            "q": a.q,
            "status": status,
            "priority": priority,
            "attention": a.attention,
            "archive": a.archive,
            "kind": a.kind,
            "sort": a.sort,
            "group": a.group,
            "tags": tags,
            "tag_match": a.tag_match,
            "actionable": a.actionable,
            "waiting": a.waiting,
            "estimate": a.estimate,
            "max_minutes": a.max_minutes,
            "include_undated": a.include_undated or None,
        },
        {
            "attention": "all",
            "archive": "active",
            "kind": "all",
            "sort": "due_asc",
            "group": "none",
            "tag_match": "any",
            "actionable": "all",
            "waiting": "all",
            "estimate": "all",
        },
    )
    names = waiting_contact_names(container, actor, page.items)
    return WorkItemPageOutput(
        items=[work_item_record(row, names) for row in page.items],
        next_cursor=page.next_cursor,
        filters=filters,
    )


def task_detail_structured(
    container: Container, actor: Actor, task_id: UUID
) -> tuple[TaskDetailOutput, TaskDetailRead]:
    """The structured content of `get_task`, and the detail read it came from (for the text)."""

    # One transaction for the Task, tags, Project title, Step counts and the first Steps.
    detail = container.tasks.get_detail(actor, task_id, step_limit=RECORD_STEP_LIMIT + 1)
    task_data = with_tags(task_public_data(detail.task), [tag.slug for tag in detail.tags])
    task_data["project_title"] = clipped_project_title(detail.project_title)
    task_data.update(detail.step_counts)
    structured = TaskDetailOutput(task=TaskDetailRecord.model_validate(task_data))
    return structured, detail


def complete_task_structured(
    container: Container,
    actor: Actor,
    task_id: UUID,
    *,
    version: int,
    idempotency_key: str,
    correlation_id: str | None = None,
) -> TaskOutput:
    """Complete one Task through `TaskService.complete`; the structured content of
    `complete_task`. Version check, transaction, audit, recurrence and durable idempotency are
    the use case's own."""

    # The reply lists the record's tags (projects:read); refuse before anything is written.
    container.work_tags.require_record_tags_readable(actor, "task")
    task = container.tasks.complete(
        actor,
        task_id,
        version=version,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    slugs = [tag.slug for tag in container.work_tags.for_record(actor, "task", task_id)]
    return TaskOutput(task=TaskRecord.model_validate(with_tags(task_public_data(task), slugs)))


def update_task_structured(
    container: Container,
    actor: Actor,
    task_id: UUID,
    *,
    version: int,
    idempotency_key: str,
    changes: TaskChanges,
    correlation_id: str | None = None,
    only_if_status: TaskStatus | None = None,
) -> TaskOutput:
    """Update one Task through `TaskService.update`; the structured content of `update_task`.

    `only_if_status` is the use case's own atomic status guard (the companion's reopen).
    """

    # The reply lists the record's tags (projects:read); refuse before anything is written.
    container.work_tags.require_record_tags_readable(actor, "task")
    patch = changes.model_dump(exclude_unset=True)
    if "due_at" in patch:
        patch["due_at"] = end_of_day_due_at(patch["due_at"], container.settings.owner_zone)
    if "tags" in patch:
        patch["tags"] = tuple(patch["tags"] or ())
    if patch.get("priority") is not None:
        patch["priority"] = Priority(patch["priority"])
    task = container.tasks.update(
        actor,
        task_id,
        version=version,
        idempotency_key=idempotency_key,
        command=UpdateTaskCommand(**patch),
        correlation_id=correlation_id,
        only_if_status=only_if_status,
    )
    slugs = [tag.slug for tag in container.work_tags.for_record(actor, "task", task_id)]
    return TaskOutput(task=TaskRecord.model_validate(with_tags(task_public_data(task), slugs)))


def task_steps_structured(
    container: Container,
    actor: Actor,
    task_id: UUID,
    *,
    limit: int = 100,
    cursor: str | None = None,
) -> ListedStepPageOutput:
    """The structured content of `list_task_steps`: Steps with their active Action counts."""

    page, action_counts = container.steps.list_steps_with_action_counts(
        actor, task_id, limit=limit, cursor=cursor
    )
    no_actions = ActionCounts(0, 0)
    return ListedStepPageOutput(
        items=[
            ListedStepRecord(
                **step_record(step).model_dump(),
                action_count=action_counts.get(step.id, no_actions).active,
                action_done_count=action_counts.get(step.id, no_actions).completed,
            )
            for step in page.items
        ],
        next_cursor=page.next_cursor,
    )


def project_detail_structured(
    container: Container, actor: Actor, project_id: UUID
) -> tuple[ProjectDetailOutput, Project]:
    """The structured content of `get_project`, and the Project it came from (for the text)."""

    project = container.projects.get(actor, project_id)
    slugs = [tag.slug for tag in container.work_tags.for_record(actor, "project", project_id)]
    estimate_totals = container.contexts.estimate_totals(
        actor, scope="project_open_tasks", project_id=project_id
    )
    project_data = with_tags(project_public_data(project), slugs)
    project_data["estimate_totals"] = estimate_totals.to_data()
    project_data.update(container.contexts.project_task_counts(actor, project_id))
    structured = ProjectDetailOutput(project=ProjectDetailRecord.model_validate(project_data))
    return structured, project


def domain_structured(container: Container, actor: Actor, domain_id: UUID) -> DomainOutput:
    """The structured content of `get_domain`."""

    domain = container.contexts.get_domain(actor, domain_id)
    slugs = [tag.slug for tag in container.work_tags.for_record(actor, "domain", domain_id)]
    return DomainOutput(domain=DomainRecord.model_validate(domain_public_data(domain, slugs)))


def process_structured(container: Container, actor: Actor, process_id: UUID) -> ProcessOutput:
    """The structured content of `get_process`."""

    process = container.contexts.get_process(actor, process_id)
    slugs = [tag.slug for tag in container.work_tags.for_record(actor, "process", process_id)]
    return ProcessOutput(process=ProcessRecord.model_validate(process_public_data(process, slugs)))


_HIERARCHY_TASK_LIMIT = 200
_HIERARCHY_STEP_LIMIT = 20
_HIERARCHY_TASK_SCAN_LIMIT = 1000


def hierarchy_nodes_structured(
    nodes: Sequence[HierarchyNode], next_cursor: str | None
) -> HierarchyOutput:
    """The structured content of `get_work_hierarchy` without tasks (`tasks` is left unset)."""

    return HierarchyOutput(
        nodes=[HierarchyNodeRecord.model_validate(node.to_data()) for node in nodes],
        truncated=next_cursor is not None,
        next_cursor=next_cursor,
    )


def work_hierarchy_structured(
    container: Container,
    actor: Actor,
    *,
    limit: int,
    cursor: str | None,
    include_tasks: bool,
    process_id: UUID | None = None,
) -> HierarchyOutput:
    """The structured content of `get_work_hierarchy`, shared by the MCP tool and the companion.

    Without `include_tasks` the result's `tasks` is unset: dump it with `exclude_unset=True`.

    `process_id` narrows the Tasks to the ones filed under that Process (the Process must be the
    caller's own); it only means something together with `include_tasks`, so alone it is refused.
    With it the page is that one Process node and `limit` and `cursor` do not apply.
    """

    if process_id is not None and not include_tasks:
        raise InvalidInputError("process_id needs include_tasks")
    if process_id is not None:
        # An unknown or foreign Process is a not-found here, before any Task is read.
        process = container.contexts.get_process(actor, process_id)
        nodes, next_cursor = [process_hierarchy_node(process)], None
    else:
        nodes, next_cursor = container.contexts.hierarchy_page(actor, limit=limit, cursor=cursor)
    if not include_tasks:
        return hierarchy_nodes_structured(nodes, next_cursor)
    tasks, tasks_truncated = hierarchy_tasks(container, actor, nodes, process_id=process_id)
    return HierarchyOutput(
        nodes=[HierarchyNodeRecord.model_validate(node.to_data()) for node in nodes],
        truncated=next_cursor is not None or tasks_truncated,
        next_cursor=next_cursor,
        tasks=tasks,
    )


def hierarchy_tasks(
    container: Container,
    actor: Actor,
    nodes: Sequence[HierarchyNode],
    *,
    process_id: UUID | None = None,
) -> tuple[list[HierarchyTaskRecord], bool]:
    """Return the active Tasks under the page's Projects and Processes, and whether a cap cut them.

    Tasks come from the same use case as `list_tasks`, read 100 at a time, and Steps from the
    use case behind `list_task_steps`; both leave archived and trashed records out. A Task
    whose Project and Process are not on the node page is not shown. The scan stops after
    `_HIERARCHY_TASK_SCAN_LIMIT` Tasks, so the result is bounded even for many unparented Tasks.

    With `process_id` the Tasks are the Process's own, read through the `list_tasks` filter; the
    caller has already checked that the Process is the owner's and passes only its node.
    """

    parent_ids = {str(node.id) for node in nodes if node.kind in ("project", "process")}
    tasks: list[HierarchyTaskRecord] = []
    scanned = 0
    cut_tasks = False
    cut_steps = False
    cursor: str | None = None
    while True:
        page = container.tasks.list(actor, limit=100, cursor=cursor, process_id=process_id)
        for item in page.items:
            scanned += 1
            data = task_public_data(item)
            # A Task has at most one of project, process or domain (Task validation): never both.
            parent_id = data["project_id"] or data["process_id"]
            if parent_id is None or parent_id not in parent_ids:
                continue
            if len(tasks) == _HIERARCHY_TASK_LIMIT:
                cut_tasks = True
                break
            steps = container.steps.list_steps(
                actor, item.id, limit=_HIERARCHY_STEP_LIMIT + 1
            ).items
            if len(steps) > _HIERARCHY_STEP_LIMIT:
                cut_steps = True
            task = HierarchyTaskRecord.model_validate(
                {
                    "id": data["id"],
                    "parent_id": parent_id,
                    "title": data["title"],
                    "status": data["status"],
                    "version": data["version"],
                    "due_at": data["due_at"],
                    "steps": [
                        {"id": step.id, "title": step.title, "status": step.status.value}
                        for step in steps[:_HIERARCHY_STEP_LIMIT]
                    ],
                }
            )
            tasks.append(task)
        if cut_tasks or page.next_cursor is None:
            break
        if scanned >= _HIERARCHY_TASK_SCAN_LIMIT:
            cut_tasks = True
            break
        cursor = page.next_cursor
    return tasks, cut_tasks or cut_steps


def with_description_excerpt(data: Mapping[str, Any]) -> dict[str, Any]:
    """A record's data with its `description` replaced by `description_excerpt` and
    `description_truncated`: the list shape, so a page of rows stays small."""

    row = dict(data)
    shortened, truncated = excerpt(row.pop("description", None))
    row["description_excerpt"] = shortened
    row["description_truncated"] = truncated
    return row


def _task_page(
    container: Container,
    actor: Actor,
    *,
    limit: int,
    project_id: UUID | None,
    process_id: UUID | None,
    status: TaskStatus | None,
    cursor: str | None,
    unsorted: bool,
) -> tuple[list[dict[str, Any]], str | None]:
    """One authorized page of Tasks as public data with their tags, and the next cursor."""

    page = container.tasks.list(
        actor,
        limit=limit,
        project_id=project_id,
        process_id=process_id,
        status=status,
        cursor=cursor,
        unsorted=unsorted,
    )
    slugs = container.work_tags.slug_map(actor)
    rows = [
        with_tags(task_public_data(item), list(slugs.get(("task", item.id), ())))
        for item in page.items
    ]
    return rows, page.next_cursor


def task_page_structured(
    container: Container,
    actor: Actor,
    *,
    limit: int = 25,
    project_id: UUID | None = None,
    process_id: UUID | None = None,
    status: TaskStatus | None = None,
    cursor: str | None = None,
    unsorted: bool = False,
) -> TaskPageOutput:
    """The structured content of `list_tasks`, shared with the companion's Project Tasks page:
    each row carries a description excerpt, not the whole description (`get_task` has it)."""

    rows, next_cursor = _task_page(
        container,
        actor,
        limit=limit,
        project_id=project_id,
        process_id=process_id,
        status=status,
        cursor=cursor,
        unsorted=unsorted,
    )
    return TaskPageOutput(
        tasks=[TaskListRecord.model_validate(with_description_excerpt(row)) for row in rows],
        next_cursor=next_cursor,
    )


def complete_step_structured(
    container: Container,
    actor: Actor,
    step_id: UUID,
    *,
    version: int,
    idempotency_key: str,
    correlation_id: str | None = None,
) -> StepOutput:
    """Complete one Step through `StepsService.complete_step`; the structured content of
    `complete_task_step`."""

    step = container.steps.complete_step(
        actor,
        step_id,
        version=version,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return StepOutput(step=step_record(step))


def reopen_step_structured(
    container: Container,
    actor: Actor,
    step_id: UUID,
    *,
    version: int,
    idempotency_key: str,
    correlation_id: str | None = None,
) -> StepOutput:
    """Set a completed Step back to "todo": `update_task_step` with exactly `status = todo`,
    guarded by the use case so it only ever applies to a completed Step."""

    step = container.steps.update_step(
        actor,
        step_id,
        version=version,
        idempotency_key=idempotency_key,
        status=TaskStatus.TODO,
        only_if_status=TaskStatus.COMPLETED,
        correlation_id=correlation_id,
    )
    return StepOutput(step=step_record(step))


def step_record(step: Step) -> StepRecord:
    return StepRecord.model_validate(
        {
            "id": step.id,
            "task_id": step.task_id,
            "title": step.title,
            "status": step.status.value,
            "position": step.position,
            "due_at": step.due_at,
            "version": step.version,
            "attention_requested": step.attention_requested,
            "archived_at": step.archived_at,
            "instruction": step.instruction,
        }
    )


def action_record(action: Action) -> ActionRecord:
    return ActionRecord.model_validate(
        {
            "id": action.id,
            "step_id": action.step_id,
            "title": action.title,
            "status": action.status.value,
            "position": action.position,
            "due_at": action.due_at,
            "version": action.version,
            "attention_requested": action.attention_requested,
            "archived_at": action.archived_at,
            "note": action.note,
        }
    )

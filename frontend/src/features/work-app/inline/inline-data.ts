import type { ContactLinkCounts, InlineSummaryData } from "./inline-summary";
import type {
  WorkContactContext,
  WorkProject,
  WorkTask,
} from "../transport/transport";

/**
 * The inline summary fields of a Task; a Task's due date is an instant. The Project title and the
 * Step counts come from get_task; without Steps the progress line is left out rather than "0 of 0".
 */
export function taskInlineSummary(task: WorkTask): InlineSummaryData {
  const steps =
    task.steps_total !== undefined && task.steps_total > 0
      ? { done: task.steps_done ?? 0, total: task.steps_total }
      : undefined;
  return {
    kind: "task",
    title: task.title,
    status: task.status,
    dueDate: task.due_at,
    version: task.version,
    priority: task.priority,
    description: task.description,
    projectTitle: task.project_title,
    datapoints: { steps },
  };
}

/**
 * The inline summary fields of a Project; its target date is a calendar date. The Task counts come
 * from get_project; without Tasks the progress count is left out rather than "0 of 0".
 */
export function projectInlineSummary(project: WorkProject): InlineSummaryData {
  const tasks =
    project.tasks_total !== undefined && project.tasks_total > 0
      ? { done: project.tasks_done ?? 0, total: project.tasks_total }
      : undefined;
  return {
    kind: "project",
    title: project.title,
    status: project.status,
    dueDate: project.target_date,
    datapoints: { tasks, overdue: project.tasks_overdue },
  };
}

/** How many Projects and Tasks a carried Contact context links, with "+" marks for further pages. */
export function contactLinkCounts(
  context: WorkContactContext,
): ContactLinkCounts {
  return {
    projects: context.projects.items.length,
    projectsMore: Boolean(context.projects.next_cursor),
    tasks: context.tasks.items.length,
    tasksMore: context.tasks.next_cursor !== null,
  };
}

/** The id and display name of each Contact, as the inline Contact summary lists them. */
export function contactNames(items: { id: string; display_name: string }[]) {
  return items.map((item) => ({ id: item.id, name: item.display_name }));
}

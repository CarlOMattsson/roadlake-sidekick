import type { WorkTaskSummary } from "../transport/transport";

/** A Project's or Process's Tasks in the order its page shows them: the open ones, then the completed ones. */
export type OrderedGroupTasks = {
  open: WorkTaskSummary[];
  done: WorkTaskSummary[];
};

/** The due time of a Task as a number to sort by; a Task without a readable due time has none. */
function dueTime(task: WorkTaskSummary): number | undefined {
  const time = task.due_at ? Date.parse(task.due_at) : Number.NaN;
  return Number.isNaN(time) ? undefined : time;
}

/**
 * Splits a Project's or Process's Tasks into the open ones and the completed ones, by the status the list was read with.
 * The open ones are ordered by due time, earliest first, so the overdue ones (the earliest) come first with the oldest
 * on top, then the ones due later; Tasks without a due time come last, and Tasks with the same due time (or none) keep
 * the order the server gave them (the sort is stable). The completed ones keep the server's order.
 */
export function orderGroupTasks(tasks: WorkTaskSummary[]): OrderedGroupTasks {
  const open = tasks.filter((task) => task.status !== "completed");
  const done = tasks.filter((task) => task.status === "completed");
  open.sort((a, b) => {
    const first = dueTime(a);
    const second = dueTime(b);
    if (first === undefined || second === undefined) {
      return first === second ? 0 : first === undefined ? 1 : -1;
    }
    return first - second;
  });
  return { open, done };
}

/**
 * The tags every one of `tasks` has, in the first Task's order. Fewer than two Tasks share nothing: one Task's tag is
 * only that Task's. Tasks read without tags (an older server) have none, so nothing is shared.
 */
export function sharedTaskTags(tasks: WorkTaskSummary[]): string[] {
  const [first, ...rest] = tasks;
  if (!first || rest.length === 0) return [];
  return (first.tags ?? []).filter((tag) =>
    rest.every((task) => task.tags?.includes(tag)),
  );
}

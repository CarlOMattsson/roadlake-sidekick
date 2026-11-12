/** Pure helpers of the board: reading and patching a board page, with no React and no tool calls. */
import { cardKey, shownOrder } from "./work-items";
import type { AgendaUndo } from "./agenda-undo";
import type {
  TaskStatusValue,
  WorkBoardFrame,
  WorkBoardPlacement,
  WorkBoardPlacementItem,
  WorkFilters,
  WorkItemRecord,
  WorkTask,
} from "./transport";

export type BoardPage = WorkBoardFrame["page"];

/**
 * An Undo the board offers on a card. In the single layout `at` is the section the card was in and `index` its
 * place there: the card stays there with "Klar · Ångra" while the Undo lasts (designsystem §3 "Tillstånd").
 */
export type BoardUndo = AgendaUndo & { at?: string; index: number };

/** Where a Task lands in its column: a place among the other cards, or a step from where it stands when the write runs. */
export type ReorderTo = number | { by: -1 | 1 };

/** The filters a read of this board repeats: its own, with the tab row's search as `q` (it wins over a saved view's `q`). */
export function boardReadFilters(source: WorkBoardFrame): WorkFilters {
  return source.search
    ? { ...source.filters, q: source.search }
    : source.filters;
}

/** The Task with this id on the board, if it is one. */
export function findTaskCard(
  id: string,
  from: BoardPage,
): WorkItemRecord | undefined {
  return Object.values(from.columns)
    .flat()
    .find((item) => item.kind === "task" && item.id === id);
}

/**
 * The column's Tasks in their order with versions, or undefined when the column is not whole on the board
 * (a next page, a filter, or a record that is not a Task with a version). On the phone (`single`) the order is the
 * one shown: Flytta upp/ned in a section sorted by date writes what the user sees, with the one row moved a step,
 * so nothing else jumps.
 */
export function completeColumn(
  source: WorkBoardFrame,
  status: TaskStatusValue,
  single: boolean,
): WorkBoardPlacementItem[] | undefined {
  const filtered = Object.values(source.filters).some((value) =>
    typeof value === "string" ? value !== "" : value.length > 0,
  );
  if (source.page.next_cursor || filtered || source.search) return undefined;
  const items: WorkBoardPlacementItem[] = [];
  const column = source.page.columns[status] ?? [];
  for (const item of single
    ? shownOrder(source.page, status, column)
    : column) {
    if (item.kind !== "task" || typeof item.version !== "number")
      return undefined;
    items.push({ taskId: item.id, version: item.version });
  }
  return items;
}

/**
 * The Tasks of one column in their new order: the dragged Task leaves its place and lands at `to`, the position
 * among the other cards (or a step from its place). Read from `source`, the board as it is when the write runs.
 * Undefined when the column cannot be ordered (see `completeColumn`).
 */
export function reorderedColumn(
  status: TaskStatusValue,
  taskId: string,
  to: ReorderTo,
  source: WorkBoardFrame,
  single: boolean,
): WorkBoardPlacementItem[] | undefined {
  const items = completeColumn(source, status, single);
  if (!items) return undefined;
  const from = items.findIndex((item) => item.taskId === taskId);
  if (from === -1) return undefined;
  const toIndex = typeof to === "number" ? to : from + to.by;
  if (toIndex < 0 || toIndex >= items.length) return undefined;
  const [moved] = items.splice(from, 1);
  if (!moved) return undefined;
  items.splice(toIndex, 0, moved);
  return items;
}

/** A write succeeded: its Task is in its new column, with the version the answer gave. Undefined when it is not on the page. */
export function withTaskMoved(
  now: BoardPage,
  task: WorkTask,
): BoardPage | undefined {
  let found: WorkItemRecord | undefined;
  const columns: Record<string, WorkItemRecord[]> = {};
  for (const [status, list] of Object.entries(now.columns))
    columns[status] = list.filter((item) => {
      const hit = item.kind === "task" && item.id === task.id;
      if (hit) found = item;
      return !hit;
    });
  if (!found) return undefined;
  const moved = { ...found, status: task.status, version: task.version };
  columns[task.status] = [...(columns[task.status] ?? []), moved];
  return { ...now, columns };
}

/** A Step was checked or unchecked: its card moves to the column of its new status, with the version the answer gave. */
export function withStepMoved(
  now: BoardPage,
  key: string,
  base: WorkItemRecord,
  step: { status: string; version: number },
): BoardPage {
  const columns: Record<string, WorkItemRecord[]> = {};
  for (const [status, list] of Object.entries(now.columns))
    columns[status] = list.filter((item) => cardKey(item) !== key);
  columns[step.status] = [
    ...(columns[step.status] ?? []),
    { ...base, status: step.status, version: step.version },
  ];
  return { ...now, columns };
}

/** A column order was written: the column shows the answer's order and versions (else the order it sent). */
export function withColumnPlaced(
  now: BoardPage,
  status: TaskStatusValue,
  answer: WorkBoardPlacement[],
  sent: WorkBoardPlacementItem[],
): BoardPage {
  const order = answer.length
    ? answer.map((placement) => placement.task_id)
    : sent.map((item) => item.taskId);
  const rank = new Map(order.map((id, at) => [id, at]));
  const versions = new Map(
    answer.map((placement) => [placement.task_id, placement.version]),
  );
  const column = (now.columns[status] ?? [])
    .map((item) => {
      const version = versions.get(item.id);
      return version === undefined ? item : { ...item, version };
    })
    .sort(
      (a, b) =>
        (rank.get(a.id) ?? order.length) - (rank.get(b.id) ?? order.length),
    );
  // The column is the user's order from now on, as the server says at its next read.
  return {
    ...now,
    columns: { ...now.columns, [status]: column },
    manually_ordered: (now.manually_ordered ?? []).concat(status),
  };
}

/**
 * The cards a section of the single layout shows: its own, without those that stay in another section while their
 * Undo lasts, and with those that stay here, at the place they had.
 */
export function shownIn(
  segment: string,
  base: WorkItemRecord[],
  undos: Record<string, BoardUndo>,
  page: BoardPage,
): WorkItemRecord[] {
  const list = base.filter(
    (item) => (undos[cardKey(item)]?.at ?? segment) === segment,
  );
  for (const entry of Object.values(undos)
    .filter((entry) => entry.at === segment)
    .sort((a, b) => a.index - b.index)) {
    const item = findTaskCard(entry.taskId, page);
    if (item && !list.includes(item))
      list.splice(Math.min(entry.index, list.length), 0, item);
  }
  return list;
}

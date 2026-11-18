/** Pure helpers of the board: reading and patching a board page, with no React and no tool calls. */
import { appendBoardPage, cardKey, shownOrder } from "../shared/work-items";
import type { AgendaUndo } from "../agenda/agenda-undo";
import {
  isTaskStatus,
  type TaskStatusValue,
  type WorkBoardFrame,
  type WorkBoardPlacement,
  type WorkBoardPlacementItem,
  type WorkFilters,
  type WorkItemRecord,
  type WorkTask,
} from "../transport/transport";

export type BoardPage = WorkBoardFrame["page"];

/**
 * An Undo the board offers on a card. In the single layout `at` is the section the card was in and `index` its
 * place there: the card stays there with `completed` and `undo` while the Undo lasts (designsystem §3 "Tillstånd").
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

/** A read of the whole board: its page, and every column read again from the start (see `columnCursors`). */
export function withBoardRead(
  source: WorkBoardFrame,
  page: BoardPage,
): WorkBoardFrame {
  return { ...source, page, columnCursors: undefined };
}

/**
 * How the next records of one column are read, or undefined when the column is whole on the board. The board's
 * pages run across every column, so its cursor cannot tell which column goes on: a Task status column reads its own
 * pages (`status`, the board's filters with that status). The Projects segment, and a board already filtered to the
 * column's status, read the board's next page (`board`).
 */
export function columnMore(
  source: WorkBoardFrame,
  column: string,
): "status" | "board" | undefined {
  const { page } = source;
  if (!page.next_cursor) return undefined;
  // With the server's totals, only a column that holds more than it shows offers more.
  if (page.column_totals && unshownIn(page, column) === 0) return undefined;
  if (!isTaskStatus(column)) return "board";
  const status = source.filters.status;
  if (typeof status === "string" && status !== "")
    return status === column ? "board" : undefined;
  return source.columnCursors?.[column] === null ? undefined : "status";
}

/**
 * How many records of a board segment are not on the page yet: the server's total less those read, per status column
 * (`column_totals`). A Task status segment counts its own column; the Projects segment every column that is not a Task
 * status. 0 without totals (an older server), where the board counts what it has read.
 */
export function unshownIn(page: BoardPage, segment: string): number {
  const totals = page.column_totals;
  if (!totals) return 0;
  const columns = isTaskStatus(segment)
    ? [segment]
    : Object.keys(totals).filter((column) => !isTaskStatus(column));
  return columns.reduce(
    (sum, column) =>
      sum +
      Math.max(0, (totals[column] ?? 0) - (page.columns[column]?.length ?? 0)),
    0,
  );
}

/** The totals after one record moved from one status column to another on the page (see column_totals). */
function totalsMoved(
  totals: BoardPage["column_totals"],
  from: string,
  to: string,
): BoardPage["column_totals"] {
  if (!totals || from === to) return totals;
  return {
    ...totals,
    [from]: Math.max(0, (totals[from] ?? 0) - 1),
    [to]: (totals[to] ?? 0) + 1,
  };
}

/**
 * A page of one column added to the board: the records not shown yet join their columns, while the board's own cursor
 * and column orders stay (they are the board's, not the column's). `added` counts the records that were new.
 */
export function withColumnPage(
  shown: BoardPage,
  later: BoardPage,
): { page: BoardPage; added: number } {
  const merged = appendBoardPage(shown, later);
  const count = (page: BoardPage) =>
    Object.values(page.columns).reduce((sum, list) => sum + list.length, 0);
  return {
    page: { ...shown, columns: merged.columns },
    added: count(merged) - count(shown),
  };
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
 * (a next page, a filter, or a record that is not a Task with a version). The order is the one shown (shownOrder, the
 * same in both layouts): a drag or Flytta upp/ned in a column sorted by date writes what the user sees, with the one
 * card moved, so nothing else jumps.
 */
export function completeColumn(
  source: WorkBoardFrame,
  status: TaskStatusValue,
): WorkBoardPlacementItem[] | undefined {
  const filtered = Object.values(source.filters).some((value) =>
    typeof value === "string" ? value !== "" : value.length > 0,
  );
  if (source.page.next_cursor || filtered || source.search) return undefined;
  const items: WorkBoardPlacementItem[] = [];
  const column = source.page.columns[status] ?? [];
  for (const item of shownOrder(source.page, status, column)) {
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
): WorkBoardPlacementItem[] | undefined {
  const items = completeColumn(source, status);
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
  return {
    ...now,
    columns,
    column_totals: totalsMoved(now.column_totals, found.status, task.status),
  };
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

/**
 * Pure drag logic for the Work board. No DOM, no React, no tool calls.
 *
 * The caller measures geometry, feeds pointer events into `reduceBoardDrag`, and performs the
 * write itself when the ended outcome is a move. Index semantics: `index` counts the other cards
 * in the target column whose midpoint lies above the pointer, so it is the position the card
 * takes once the dragged card is removed from its origin.
 */

export type Point = { x: number; y: number };
export type Rect = { left: number; top: number; width: number; height: number };

export type CardGeometry = { id: string; rect: Rect };
export type ColumnGeometry = { id: string; rect: Rect; cards: CardGeometry[] };
/** Columns are listed left to right; their order decides which column an edge drag moves to. */
export type BoardGeometry = { rect: Rect; columns: ColumnGeometry[] };

export type DropTarget = { column: string; index: number };

/** The data the caller turns into an update_task call (later, a column reorder). */
export type BoardMove = {
  taskId: string;
  fromColumn: string;
  toColumn: string;
  toIndex: number;
};

export type DragPointer = "touch" | "pen" | "mouse";

/** A touch must stay still this long before it becomes a drag; otherwise it is a tap or a scroll. */
export const LONG_PRESS_MS = 250;
/** A touch that moves further than this before the long press is a scroll, not a drag. */
export const LONG_PRESS_MOVE_TOLERANCE_PX = 10;
/** A mouse or pen drag starts after this much movement; there is no long press for them. */
export const MOUSE_DRAG_START_PX = 4;
/** Width of the strip at each board edge that moves the card to the adjacent column. */
export const EDGE_ZONE_PX = 32;
/** The pointer must stay in an edge strip this long before the column changes. */
export const EDGE_DWELL_MS = 600;

export type BoardDragOutcome =
  | { type: "move"; move: BoardMove }
  | {
      type: "none";
      reason: "tap" | "scroll" | "cancelled" | "outside" | "unchanged";
    };

export type BoardDragState =
  | { phase: "idle" }
  | {
      phase: "pending";
      taskId: string;
      pointerType: DragPointer;
      origin: Point;
      startedAt: number;
      fromColumn: string;
      fromIndex: number;
    }
  | {
      phase: "dragging";
      taskId: string;
      fromColumn: string;
      fromIndex: number;
      pointer: Point;
      column: string;
      index: number;
      edgeDirection: -1 | 0 | 1;
      edgeSince: number | null;
    }
  | { phase: "ended"; outcome: BoardDragOutcome };

export type BoardDragEvent =
  | {
      type: "down";
      taskId: string;
      point: Point;
      time: number;
      pointerType: DragPointer;
      board: BoardGeometry;
    }
  | { type: "move"; point: Point; time: number; board: BoardGeometry }
  | { type: "tick"; time: number; board: BoardGeometry }
  | { type: "up"; point: Point; time: number; board: BoardGeometry }
  | { type: "escape" }
  | { type: "leave" };

export const initialBoardDrag: BoardDragState = { phase: "idle" };

function insideRect(rect: Rect, point: Point): boolean {
  return (
    point.x >= rect.left &&
    point.x < rect.left + rect.width &&
    point.y >= rect.top &&
    point.y < rect.top + rect.height
  );
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** The column whose horizontal span holds x, or the nearest one when x falls in a gap. */
function columnAtX(
  columns: ColumnGeometry[],
  x: number,
): ColumnGeometry | undefined {
  let best: ColumnGeometry | undefined;
  let bestGap = Infinity;
  for (const column of columns) {
    const left = column.rect.left;
    const right = left + column.rect.width;
    const gap = x < left ? left - x : x >= right ? x - right : 0;
    if (gap < bestGap) {
      best = column;
      bestGap = gap;
    }
  }
  return best;
}

function columnById(
  board: BoardGeometry,
  id: string,
): ColumnGeometry | undefined {
  return board.columns.find((column) => column.id === id);
}

/** Position among the column's other cards: how many of them have their midpoint above y. */
function indexInColumn(
  column: ColumnGeometry,
  y: number,
  taskId: string,
): number {
  let index = 0;
  for (const card of column.cards) {
    if (card.id === taskId) continue;
    if (card.rect.top + card.rect.height / 2 < y) index += 1;
  }
  return index;
}

/**
 * Target column and position for a card dragged to `point`. Null when the pointer is outside the
 * board or the board has no columns.
 */
export function computeDrop(
  point: Point,
  board: BoardGeometry,
  taskId: string,
): DropTarget | null {
  if (!insideRect(board.rect, point)) return null;
  const column = columnAtX(board.columns, point.x);
  if (!column) return null;
  return { column: column.id, index: indexInColumn(column, point.y, taskId) };
}

/** Where a task sits now, in the same index terms as computeDrop. */
function locate(
  board: BoardGeometry,
  taskId: string,
): { column: ColumnGeometry; index: number } | undefined {
  for (const column of board.columns) {
    const card = column.cards.find((item) => item.id === taskId);
    if (!card) continue;
    const midY = card.rect.top + card.rect.height / 2;
    return { column, index: indexInColumn(column, midY, taskId) };
  }
  return undefined;
}

function edgeDirectionAt(point: Point, rect: Rect): -1 | 0 | 1 {
  const nearLeft = point.x - rect.left < EDGE_ZONE_PX;
  const nearRight = rect.left + rect.width - point.x < EDGE_ZONE_PX;
  if (nearLeft === nearRight) return 0;
  return nearLeft ? -1 : 1;
}

function adjacentColumn(
  columns: ColumnGeometry[],
  currentId: string,
  direction: -1 | 1,
): string {
  const at = columns.findIndex((column) => column.id === currentId);
  if (at === -1) return currentId;
  const next =
    columns[Math.min(columns.length - 1, Math.max(0, at + direction))];
  return next?.id ?? currentId;
}

function ended(outcome: BoardDragOutcome): BoardDragState {
  return { phase: "ended", outcome };
}

function cancelled(
  state: BoardDragState,
  reason: "cancelled" | "outside",
): BoardDragState {
  if (state.phase === "pending" || state.phase === "dragging") {
    return ended({ type: "none", reason });
  }
  return state;
}

function startPending(
  state: BoardDragState,
  event: Extract<BoardDragEvent, { type: "down" }>,
): BoardDragState {
  if (state.phase === "pending" || state.phase === "dragging") return state;
  const located = locate(event.board, event.taskId);
  if (!located) return state;
  return {
    phase: "pending",
    taskId: event.taskId,
    pointerType: event.pointerType,
    origin: event.point,
    startedAt: event.time,
    fromColumn: located.column.id,
    fromIndex: located.index,
  };
}

function startDragging(
  state: Extract<BoardDragState, { phase: "pending" }>,
  point: Point,
  time: number,
  board: BoardGeometry,
): BoardDragState {
  const dragging: BoardDragState = {
    phase: "dragging",
    taskId: state.taskId,
    fromColumn: state.fromColumn,
    fromIndex: state.fromIndex,
    pointer: state.origin,
    column: state.fromColumn,
    index: state.fromIndex,
    edgeDirection: 0,
    edgeSince: null,
  };
  return updateTarget(dragging, point, time, board);
}

/**
 * Applies a pointer position to a dragging state. Leaving the board ends the drag. Inside an edge
 * strip the column changes to the adjacent one only after the pointer has dwelled there; elsewhere
 * the column follows the pointer's x position.
 */
function updateTarget(
  state: Extract<BoardDragState, { phase: "dragging" }>,
  point: Point,
  time: number,
  board: BoardGeometry,
): BoardDragState {
  if (!insideRect(board.rect, point)) return cancelled(state, "outside");

  const edgeDirection = edgeDirectionAt(point, board.rect);
  let column = state.column;
  let edgeSince = state.edgeSince;

  if (edgeDirection === 0) {
    column = columnAtX(board.columns, point.x)?.id ?? state.column;
    edgeSince = null;
  } else if (edgeDirection !== state.edgeDirection || edgeSince === null) {
    edgeSince = time;
  } else if (time - edgeSince >= EDGE_DWELL_MS) {
    column = adjacentColumn(board.columns, column, edgeDirection);
    edgeSince = time;
  }

  const target = columnById(board, column);
  const index = target
    ? indexInColumn(target, point.y, state.taskId)
    : state.index;

  return {
    ...state,
    pointer: point,
    column,
    index,
    edgeDirection,
    edgeSince,
  };
}

function onMove(
  state: BoardDragState,
  point: Point,
  time: number,
  board: BoardGeometry,
): BoardDragState {
  if (state.phase === "pending") {
    const moved = distance(point, state.origin);
    if (state.pointerType === "touch") {
      return moved > LONG_PRESS_MOVE_TOLERANCE_PX
        ? ended({ type: "none", reason: "scroll" })
        : state;
    }
    return moved >= MOUSE_DRAG_START_PX
      ? startDragging(state, point, time, board)
      : state;
  }
  if (state.phase === "dragging") {
    return updateTarget(state, point, time, board);
  }
  return state;
}

function onTick(
  state: BoardDragState,
  time: number,
  board: BoardGeometry,
): BoardDragState {
  if (
    state.phase === "pending" &&
    state.pointerType === "touch" &&
    time - state.startedAt >= LONG_PRESS_MS
  ) {
    return startDragging(state, state.origin, time, board);
  }
  if (state.phase === "dragging") {
    return updateTarget(state, state.pointer, time, board);
  }
  return state;
}

function onUp(
  state: BoardDragState,
  event: Extract<BoardDragEvent, { type: "up" }>,
): BoardDragState {
  if (state.phase === "pending") {
    return ended({ type: "none", reason: "tap" });
  }
  if (state.phase !== "dragging") return state;

  const next = updateTarget(state, event.point, event.time, event.board);
  if (next.phase !== "dragging") return next;
  if (next.column === state.fromColumn && next.index === state.fromIndex) {
    return ended({ type: "none", reason: "unchanged" });
  }
  return ended({
    type: "move",
    move: {
      taskId: state.taskId,
      fromColumn: state.fromColumn,
      toColumn: next.column,
      toIndex: next.index,
    },
  });
}

/** Advances the board drag by one pointer or timer event. Pure; the caller owns timers and DOM. */
export function reduceBoardDrag(
  state: BoardDragState,
  event: BoardDragEvent,
): BoardDragState {
  switch (event.type) {
    case "down":
      return startPending(state, event);
    case "move":
      return onMove(state, event.point, event.time, event.board);
    case "tick":
      return onTick(state, event.time, event.board);
    case "up":
      return onUp(state, event);
    case "escape":
      return cancelled(state, "cancelled");
    case "leave":
      return cancelled(state, "outside");
  }
}

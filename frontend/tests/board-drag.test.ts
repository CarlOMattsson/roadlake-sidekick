import { describe, expect, it } from "vitest";

import {
  EDGE_DWELL_MS,
  LONG_PRESS_MS,
  computeDrop,
  initialBoardDrag,
  reduceBoardDrag,
  type BoardDragEvent,
  type BoardDragState,
  type BoardGeometry,
  type DragPointer,
  type Point,
  type Rect,
} from "../src/features/work-app/board/board-drag";

const rect = (
  left: number,
  top: number,
  width: number,
  height: number,
): Rect => ({
  left,
  top,
  width,
  height,
});

const card = (id: string, left: number, top: number) => ({
  id,
  rect: rect(left, top, 84, 40),
});

// Three columns side by side, 100px wide each, in a 300x400 board.
// Card midpoints: t1 20, t2 70, t3 120 in "todo"; d1 20 in "doing".
const board: BoardGeometry = {
  rect: rect(0, 0, 300, 400),
  columns: [
    {
      id: "todo",
      rect: rect(0, 0, 100, 400),
      cards: [card("t1", 8, 0), card("t2", 8, 50), card("t3", 8, 100)],
    },
    {
      id: "doing",
      rect: rect(100, 0, 100, 400),
      cards: [card("d1", 108, 0)],
    },
    { id: "done", rect: rect(200, 0, 100, 400), cards: [] },
  ],
};

const down = (
  taskId: string,
  point: Point,
  time = 0,
  pointerType: DragPointer = "mouse",
): BoardDragEvent => ({
  type: "down",
  taskId,
  point,
  time,
  pointerType,
  board,
});
const move = (point: Point, time = 0): BoardDragEvent => ({
  type: "move",
  point,
  time,
  board,
});
const tick = (time: number): BoardDragEvent => ({ type: "tick", time, board });
const up = (point: Point, time = 0): BoardDragEvent => ({
  type: "up",
  point,
  time,
  board,
});

function run(events: BoardDragEvent[]): BoardDragState {
  return events.reduce(reduceBoardDrag, initialBoardDrag);
}

function outcomeOf(state: BoardDragState) {
  return state.phase === "ended" ? state.outcome : undefined;
}

describe("computeDrop", () => {
  it("returns the column under the pointer and the index among the other cards", () => {
    // Dragging t1: t2 (midpoint 70) is above y=80, t3 (120) is not.
    expect(computeDrop({ x: 50, y: 80 }, board, "t1")).toEqual({
      column: "todo",
      index: 1,
    });
  });

  it("does not count the dragged card itself", () => {
    // Dragging t1 down to y=130: both t2 and t3 are above, t1 is not counted.
    expect(computeDrop({ x: 50, y: 130 }, board, "t1")).toEqual({
      column: "todo",
      index: 2,
    });
  });

  it("moves to another column when the pointer's x changes column", () => {
    expect(computeDrop({ x: 250, y: 150 }, board, "t1")).toEqual({
      column: "done",
      index: 0,
    });
  });

  it("returns null when the pointer is outside the board", () => {
    expect(computeDrop({ x: 400, y: 50 }, board, "t1")).toBeNull();
    expect(computeDrop({ x: 50, y: 500 }, board, "t1")).toBeNull();
  });

  it("uses the nearest column when the pointer is in a gap between columns", () => {
    const gapped: BoardGeometry = {
      rect: rect(0, 0, 220, 400),
      columns: [
        { id: "a", rect: rect(0, 0, 100, 400), cards: [] },
        { id: "b", rect: rect(120, 0, 100, 400), cards: [] },
      ],
    };
    expect(computeDrop({ x: 115, y: 10 }, gapped, "x")?.column).toBe("b");
    expect(computeDrop({ x: 105, y: 10 }, gapped, "x")?.column).toBe("a");
  });
});

describe("touch long press", () => {
  it("does not start a drag when the touch moves before the long press (scroll)", () => {
    let state = run([down("t1", { x: 50, y: 80 }, 0, "touch")]);
    state = reduceBoardDrag(state, move({ x: 50, y: 120 }, 100));
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "scroll" });

    state = reduceBoardDrag(state, tick(LONG_PRESS_MS + 500));
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "scroll" });
  });

  it("stays pending until the long press time has passed while still", () => {
    let state = run([down("t1", { x: 50, y: 80 }, 0, "touch")]);
    state = reduceBoardDrag(state, tick(LONG_PRESS_MS - 1));
    expect(state.phase).toBe("pending");

    state = reduceBoardDrag(state, tick(LONG_PRESS_MS));
    expect(state.phase).toBe("dragging");
  });

  it("keeps the long press when the finger jitters within the tolerance", () => {
    let state = run([down("t1", { x: 50, y: 80 }, 0, "touch")]);
    state = reduceBoardDrag(state, move({ x: 53, y: 84 }, 100));
    expect(state.phase).toBe("pending");

    state = reduceBoardDrag(state, tick(LONG_PRESS_MS));
    expect(state.phase).toBe("dragging");
  });

  it("treats a short touch as a tap, not a drag", () => {
    const state = run([
      down("t1", { x: 50, y: 80 }, 0, "touch"),
      up({ x: 50, y: 80 }, 100),
    ]);
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "tap" });
  });
});

describe("drag outcomes", () => {
  it("starts a mouse drag from a small movement without a long press", () => {
    const state = run([
      down("t1", { x: 50, y: 80 }),
      move({ x: 50, y: 86 }, 10),
    ]);
    expect(state.phase).toBe("dragging");
  });

  it("does nothing for a task that is not on the board", () => {
    const state = run([
      down("missing", { x: 50, y: 80 }),
      move({ x: 250, y: 150 }),
    ]);
    expect(state).toEqual(initialBoardDrag);
  });

  it("moves a card to another column as data", () => {
    const state = run([
      down("t1", { x: 50, y: 80 }),
      move({ x: 250, y: 150 }, 10),
      up({ x: 250, y: 150 }, 20),
    ]);
    expect(outcomeOf(state)).toEqual({
      type: "move",
      move: { taskId: "t1", fromColumn: "todo", toColumn: "done", toIndex: 0 },
    });
  });

  it("moves within the same column to a different index", () => {
    const state = run([
      down("t1", { x: 50, y: 80 }),
      move({ x: 50, y: 130 }, 10),
      up({ x: 50, y: 130 }, 20),
    ]);
    expect(outcomeOf(state)).toEqual({
      type: "move",
      move: { taskId: "t1", fromColumn: "todo", toColumn: "todo", toIndex: 2 },
    });
  });

  it("treats a release in the same column and position as a no-op", () => {
    // t1 starts at index 0 in "todo"; y=10 is still above every other card's midpoint.
    const state = run([
      down("t1", { x: 50, y: 80 }),
      move({ x: 50, y: 10 }, 10),
      up({ x: 50, y: 10 }, 20),
    ]);
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "unchanged" });
  });

  it("treats a release back on the origin position as a no-op", () => {
    // Drag down past t2 (index 1), then return to the origin at index 0 before releasing.
    const state = run([
      down("t1", { x: 50, y: 20 }),
      move({ x: 50, y: 100 }, 10),
      move({ x: 50, y: 20 }, 20),
      up({ x: 50, y: 20 }, 30),
    ]);
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "unchanged" });
  });
});

describe("aborts", () => {
  it("Escape cancels a drag and a later release does not move the card", () => {
    let state = run([
      down("t1", { x: 50, y: 80 }),
      move({ x: 250, y: 150 }, 10),
    ]);
    state = reduceBoardDrag(state, { type: "escape" });
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "cancelled" });

    state = reduceBoardDrag(state, up({ x: 250, y: 150 }, 20));
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "cancelled" });
  });

  it("moving the pointer off the board cancels the drag", () => {
    const state = run([
      down("t1", { x: 50, y: 80 }),
      move({ x: 400, y: 50 }, 10),
    ]);
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "outside" });
  });

  it("the pointer leaving the window cancels the drag", () => {
    const state = reduceBoardDrag(
      run([down("t1", { x: 50, y: 80 }), move({ x: 250, y: 150 }, 10)]),
      { type: "leave" },
    );
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "outside" });
  });
});

describe("edge column change", () => {
  // Start on d1 in "doing", move into the left edge strip and dwell there.
  it("moves to the adjacent column only after dwelling in the edge strip", () => {
    let state = run([down("d1", { x: 150, y: 30 }), move({ x: 5, y: 200 }, 0)]);
    state = reduceBoardDrag(state, tick(EDGE_DWELL_MS - 1));
    expect(state.phase === "dragging" && state.column).toBe("doing");

    state = reduceBoardDrag(state, tick(EDGE_DWELL_MS));
    expect(state.phase === "dragging" && state.column).toBe("todo");

    state = reduceBoardDrag(state, up({ x: 5, y: 200 }, EDGE_DWELL_MS + 10));
    expect(outcomeOf(state)).toEqual({
      type: "move",
      move: { taskId: "d1", fromColumn: "doing", toColumn: "todo", toIndex: 3 },
    });
  });

  it("does not move past the first column", () => {
    let state = run([down("t1", { x: 50, y: 80 }), move({ x: 5, y: 20 }, 0)]);
    state = reduceBoardDrag(state, tick(EDGE_DWELL_MS));
    state = reduceBoardDrag(state, up({ x: 5, y: 20 }, EDGE_DWELL_MS + 10));
    expect(outcomeOf(state)).toEqual({ type: "none", reason: "unchanged" });
  });
});

import { act, fireEvent, screen } from "@testing-library/react";
import { vi } from "vitest";
import { workEn } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  type WorkBoardPage,
  type WorkItemRecord,
  type WorkTransport,
} from "@/features/work-app/transport/transport";

/*
 * Drag, keyboard move and conflict on the Work board. Pointer events are dispatched by hand
 * (jsdom has no layout), and every card, column and the board get fixed rectangles so a pointer
 * position means the same column in every test:
 *   columns, in DOM order: todo 0-100, in_progress 100-200, blocked 200-300, completed 300-400,
 *   active 400-500 (a Project column), paused 500-600; board 0-600 by 0-400.
 *   cards: the Nth card of a column sits at top 40 + 60N with a midpoint 20 px below its top.
 */

export const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export const taskA: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
  version: 1,
};
export const taskB: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a2",
  title: "Skicka faktura",
  status: "todo",
  due_at: null,
  version: 1,
};
export const projectCard: WorkItemRecord = {
  kind: "project",
  id: "019f0000-0000-7000-8000-0000000000f1",
  title: "Renovering",
  status: "active",
  due_at: null,
  version: 1,
};
export const board: WorkBoardPage = {
  columns: {
    todo: [taskA, taskB],
    in_progress: [],
    completed: [],
    active: [projectCard],
    paused: [],
  },
  next_cursor: null,
};
export const afterMove: WorkBoardPage = {
  columns: {
    todo: [taskB],
    in_progress: [{ ...taskA, status: "in_progress", version: 2 }],
    completed: [],
    active: [projectCard],
    paused: [],
  },
  next_cursor: null,
};

export function transport(
  overrides: Partial<WorkTransport> = {},
): WorkTransport {
  // Only the calls the board makes are provided; the view never reaches the others from here.
  return {
    updateTask: vi.fn().mockResolvedValue({
      task: { ...taskA, status: "in_progress", version: 2 },
    }),
    getWorkBoard: vi.fn().mockResolvedValue(afterMove),
    getTask: vi.fn(),
    ...overrides,
  } as unknown as WorkTransport;
}

export function rootBoard(work: WorkTransport) {
  return (
    <WorkView
      transport={work}
      initial={{ kind: "board", filters: {}, page: board }}
      labels={workEn}
    />
  );
}

export function rect(left: number, top: number, width: number, height: number) {
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON() {},
  };
}

export const handleOf = (title: string) =>
  screen.getByRole("button", { name: workEn.dragTaskFor(title) });

/** Dispatches a pointer event on the handle; jsdom has no PointerEvent, so the type is set by hand. */
export function pointer(
  target: Element,
  type: "pointerdown" | "pointermove" | "pointerup" | "pointercancel",
  x: number,
  y: number,
  pointerType = "mouse",
) {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: x,
    clientY: y,
    button: 0,
  });
  Object.defineProperties(event, {
    pointerType: { value: pointerType },
    pointerId: { value: 1 },
  });
  fireEvent(target, event);
}

/**
 * Lets already-dispatched work settle before a test asserts that something did NOT happen. There is
 * nothing to poll for an absence, so the wait is short; to wait for something that should happen,
 * use `waitFor`/`findBy*`, and to let the board's own timing pass (long press, edge dwell), use
 * `useBoardClock` and `advanceClock`.
 */
export function sleep(ms: number) {
  return act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

/**
 * Takes over the clock the board's drag reads (`performance.now` and its `setInterval` tick), so a
 * long press or an edge dwell passes by `advanceClock` instead of by waiting. `setTimeout` stays
 * real, which keeps `waitFor` working. Call `vi.useRealTimers()` when done (an `afterEach` does).
 */
export function useBoardClock() {
  vi.useFakeTimers({
    toFake: ["setInterval", "clearInterval", "performance"],
  });
}

/** Moves the clock taken over by `useBoardClock` forward and lets the board react to every tick. */
export function advanceClock(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

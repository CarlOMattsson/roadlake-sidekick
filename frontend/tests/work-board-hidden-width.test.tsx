import { act, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BoardView } from "@/features/work-app/board";
import { workEn } from "@/features/work-app/labels";
import type {
  WorkBoardFrame,
  WorkBoardPage,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport";

/*
 * The Work board in a room that is hidden (display:none) measures a width of 0. A hidden board must not
 * change its layout because of that: the Tavla at desktop width stays "columns", and the same column
 * nodes stay in place. jsdom has no layout, so the width is stubbed with getBoundingClientRect and the
 * ResizeObserver callbacks are fired by hand.
 */

function task(n: number, status: string, title: string): WorkItemRecord {
  return {
    kind: "task",
    id: `019f0000-0000-7000-8000-00000000000${n}`,
    title,
    status,
    due_at: null,
    version: 1,
  };
}

const page: WorkBoardPage = {
  columns: {
    todo: [
      task(1, "todo", "Ring Anna om offerten"),
      task(2, "todo", "Skicka faktura"),
    ],
    in_progress: [task(3, "in_progress", "Bygg webbplatsen")],
    blocked: [],
    completed: [task(4, "completed", "Boka revisorn")],
    active: [],
  },
  next_cursor: null,
};

const transport = {
  updateTask: vi.fn(),
  getWorkBoard: vi.fn().mockResolvedValue(page),
  getTask: vi.fn(),
  reorderBoardColumn: vi.fn().mockResolvedValue({ items: [] }),
} as unknown as WorkTransport;

const frame: WorkBoardFrame = { kind: "board", filters: {}, page };

let callbacks: Array<() => void> = [];
let width = 900;
let rectSpy: { mockRestore: () => void } | undefined;

/** Stubs the ResizeObserver so every observer's callback can be fired by the test. */
function stubObserver() {
  callbacks = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(cb: () => void) {
        callbacks.push(cb);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    },
  );
  rectSpy = vi
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockImplementation(
      () =>
        ({
          left: 0,
          top: 0,
          right: width,
          bottom: 0,
          width,
          height: 0,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect,
    );
}

/** Fires every observer, as a resize (or a room that is shown or hidden) does. */
function resize() {
  act(() => {
    for (const cb of callbacks) cb();
  });
}

function board() {
  return document.querySelector<HTMLElement>(".work-board");
}

afterEach(() => {
  rectSpy?.mockRestore();
  vi.unstubAllGlobals();
  width = 900;
});

it("keeps columns and the same column nodes when a hidden board reports width 0", () => {
  stubObserver();
  width = 900;
  render(
    <BoardView
      frame={frame}
      onChange={vi.fn()}
      transport={transport}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      layout="auto"
    />,
  );
  resize();
  expect(board()).toHaveAttribute("data-layout", "columns");
  const columns = document.querySelector(".work-columns");
  expect(columns).not.toBeNull();

  width = 0;
  resize();
  expect(board()).toHaveAttribute("data-layout", "columns");
  expect(document.querySelector(".work-columns")).toBe(columns);

  width = 900;
  resize();
  expect(board()).toHaveAttribute("data-layout", "columns");
  expect(document.querySelector(".work-columns")).toBe(columns);
});

it("still switches layout on a real width, both under and at 640 px", () => {
  stubObserver();
  width = 900;
  render(
    <BoardView
      frame={frame}
      onChange={vi.fn()}
      transport={transport}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      layout="auto"
    />,
  );
  resize();
  expect(board()).toHaveAttribute("data-layout", "columns");

  width = 390;
  resize();
  expect(board()).toHaveAttribute("data-layout", "single");

  width = 640;
  resize();
  expect(board()).toHaveAttribute("data-layout", "columns");
});

// A single board (under 640 px) that reports width 0 while hidden keeps its layout: measureWidth
// ignores a zero width (board.tsx), so a hidden room does not switch the board to columns.
it("keeps single when a single board reports width 0 while hidden", () => {
  stubObserver();
  width = 390;
  render(
    <BoardView
      frame={frame}
      onChange={vi.fn()}
      transport={transport}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      layout="auto"
    />,
  );
  resize();
  expect(board()).toHaveAttribute("data-layout", "single");

  width = 0;
  resize();
  expect(board()).toHaveAttribute("data-layout", "single");
});

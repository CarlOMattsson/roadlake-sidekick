import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { workEn } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import type {
  WorkBoardPage,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { sleep } from "./helpers/board-kanban-fixtures";

/*
 * Order inside one Task status column on the Work board. Pointer events are dispatched by hand
 * (jsdom has no layout), and the geometry is the same as in board-kanban.test.tsx:
 *   columns, in DOM order: todo 0-100, in_progress 100-200, blocked 200-300, completed 300-400,
 *   active 400-500 (a Project column), paused 500-600; board 0-600 by 0-400.
 *   cards: the Nth card of a column sits at top 40 + 60N with a midpoint 20 px below its top.
 * Dropping taskA at y 150 puts it after taskB (taskB's midpoint is 120), so the column is reordered.
 */

const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const taskA: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
  version: 1,
};
const taskB: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a2",
  title: "Skicka faktura",
  status: "todo",
  due_at: null,
  version: 1,
};
const board: WorkBoardPage = {
  columns: {
    todo: [taskA, taskB],
    in_progress: [],
    completed: [],
    active: [],
    paused: [],
  },
  next_cursor: null,
};

function transport(overrides: Partial<WorkTransport> = {}): WorkTransport {
  // Only the calls the board makes are provided; the view never reaches the others from here.
  return {
    reorderBoardColumn: vi.fn().mockResolvedValue({
      items: [
        { task_id: taskB.id, version: 1 },
        { task_id: taskA.id, version: 1 },
      ],
    }),
    updateTask: vi.fn(),
    getWorkBoard: vi.fn().mockResolvedValue(board),
    getTask: vi.fn(),
    ...overrides,
  } as unknown as WorkTransport;
}

function rootBoard(work: WorkTransport, page: WorkBoardPage = board) {
  return (
    <WorkView
      transport={work}
      initial={{ kind: "board", filters: {}, page }}
      labels={workEn}
    />
  );
}

function rect(left: number, top: number, width: number, height: number) {
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

beforeAll(() => {
  // jsdom has no pointer capture; the board only asks for it, so a no-op is enough here.
  if (!("setPointerCapture" in HTMLElement.prototype))
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
      value: () => undefined,
    });
});

beforeEach(() => {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(
    function (this: Element) {
      if (this.tagName === "ARTICLE") return rect(0, 0, 600, 400);
      const section = this.closest("[data-board-column]");
      if (!section) return rect(0, 0, 0, 0);
      const columns = Array.from(
        document.querySelectorAll("[data-board-column]"),
      );
      const left = columns.indexOf(section) * 100;
      if (this.hasAttribute("data-board-column"))
        return rect(left, 0, 100, 400);
      const cards = Array.from(section.querySelectorAll("[data-card-id]"));
      return rect(left + 8, 40 + cards.indexOf(this) * 60, 84, 40);
    },
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

const handleOf = (title: string) =>
  screen.getByRole("button", { name: workEn.dragTaskFor(title) });

/** Dispatches a pointer event on the handle; jsdom has no PointerEvent, so the type is set by hand. */
function pointer(
  target: Element,
  type: "pointerdown" | "pointermove" | "pointerup" | "pointercancel",
  x: number,
  y: number,
) {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: x,
    clientY: y,
    button: 0,
  });
  Object.defineProperties(event, {
    pointerType: { value: "mouse" },
    pointerId: { value: 1 },
  });
  fireEvent(target, event);
}

/** Drags taskA from the top of the todo column to below taskB and releases it there. */
function dragTaskABelowTaskB() {
  const handle = handleOf(taskA.title);
  pointer(handle, "pointerdown", 20, 60);
  pointer(handle, "pointermove", 50, 150);
  pointer(handle, "pointerup", 50, 150);
}

/** The card ids of one column in the order they are shown. */
function cardIds(column: HTMLElement): (string | null)[] {
  return Array.from(column.querySelectorAll("[data-card-id]"), (card) =>
    card.getAttribute("data-card-id"),
  );
}

it("drops a Task lower in a complete column and writes the new order with each version and a key", async () => {
  const reorderBoardColumn = vi.fn().mockResolvedValue({
    items: [
      { task_id: taskB.id, version: 1 },
      { task_id: taskA.id, version: 1 },
    ],
  });
  const updateTask = vi.fn();
  const getWorkBoard = vi.fn().mockResolvedValue(board);
  render(
    rootBoard(transport({ reorderBoardColumn, updateTask, getWorkBoard })),
  );

  dragTaskABelowTaskB();

  await waitFor(() => expect(reorderBoardColumn).toHaveBeenCalledTimes(1));
  expect(reorderBoardColumn).toHaveBeenCalledWith(
    "todo",
    [
      { taskId: taskB.id, version: 1 },
      { taskId: taskA.id, version: 1 },
    ],
    expect.stringMatching(KEY),
  );
  // A drop inside one column is an order write only; the status is not written.
  expect(updateTask).not.toHaveBeenCalled();
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
});

it("writes no order when the column is not complete, because another page is still to be read", async () => {
  const reorderBoardColumn = vi.fn();
  const updateTask = vi.fn();
  const partial: WorkBoardPage = { ...board, next_cursor: "cursor-2" };
  render(rootBoard(transport({ reorderBoardColumn, updateTask }), partial));

  dragTaskABelowTaskB();

  await sleep(20);
  expect(reorderBoardColumn).not.toHaveBeenCalled();
  expect(updateTask).not.toHaveBeenCalled();
  expect(
    cardIds(screen.getByRole("region", { name: workEn.taskStatus.todo })),
  ).toEqual([taskA.id, taskB.id]);
});

it("a refused order shows the conflict banner and puts the Tasks back in the order the server holds", async () => {
  const reorderBoardColumn = vi
    .fn()
    .mockRejectedValue(new HostToolError("conflict"));
  const getWorkBoard = vi.fn().mockResolvedValue(board);
  render(rootBoard(transport({ reorderBoardColumn, getWorkBoard })));

  dragTaskABelowTaskB();

  const banner = await screen.findByRole("alert");
  expect(banner).toHaveTextContent(workEn.boardConflict);
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(
      cardIds(screen.getByRole("region", { name: workEn.taskStatus.todo })),
    ).toEqual([taskA.id, taskB.id]),
  );
});

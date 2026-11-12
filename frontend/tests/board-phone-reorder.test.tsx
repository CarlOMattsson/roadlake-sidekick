import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { fillLabel } from "@/features/work-app/agenda-undo";
import { workEn, workSv } from "@/features/work-app/labels";
import type {
  WorkBoardPage,
  WorkItemRecord,
} from "@/features/work-app/transport";
import { elementWithText } from "./helpers/exact-text";
import {
  KEY,
  task,
  a,
  b,
  c,
  d,
  project,
  page,
  transport,
  Harness,
  rowOf,
  openGroup,
} from "./helpers/board-phone-fixtures";

afterEach(() => vi.unstubAllGlobals());

it("Flytta ned writes the whole column in its new order, and Flytta upp is disabled at the top", async () => {
  const user = userEvent.setup();
  const reorderBoardColumn = vi.fn().mockResolvedValue({ items: [] });
  render(<Harness work={transport({ reorderBoardColumn })} />);
  // A right click on the card opens the same group as Shift+F10.
  fireEvent.contextMenu(rowOf(a.title));
  const group = screen.getByRole("group", {
    name: workEn.moveListFor(a.title),
  });
  expect(
    within(group).getByRole("button", { name: workEn.moveUp }),
  ).toBeDisabled();
  await user.click(
    within(group).getByRole("button", { name: workEn.moveDown }),
  );
  expect(reorderBoardColumn).toHaveBeenCalledWith(
    "todo",
    [
      { taskId: b.id, version: 1 },
      { taskId: a.id, version: 1 },
    ],
    expect.stringMatching(KEY),
  );
});

it("offers no reorder buttons when the column is not whole on the board", async () => {
  const user = userEvent.setup();
  render(
    <Harness
      work={transport()}
      initial={{
        kind: "board",
        filters: {},
        page: { ...page, next_cursor: "cursor-2" },
      }}
    />,
  );
  await openGroup(user, a.title);
  expect(
    screen.getByRole("group", { name: workEn.moveListFor(a.title) }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.moveUp })).toBeNull();
  expect(screen.queryByRole("button", { name: workEn.moveDown })).toBeNull();
  // Visa fler sits in the foot, and the refresh icon beside it.
  expect(screen.getByRole("button", { name: workEn.more })).toBeInTheDocument();
});

it("offers no Flytta buttons in a section whose rows are not in the column's order while a row's Ångra lasts", async () => {
  const user = userEvent.setup();
  const e = task(5, "todo", "Beställ skåp");
  const f = task(6, "in_progress", "Boka målare");
  const moved: WorkItemRecord = { ...b, status: "in_progress", version: 2 };
  const updateTask = vi.fn().mockResolvedValue({ task: moved });
  // The column after the move: Skicka faktura stands in In progress between two of its rows, and it stays shown in
  // To do for its "Ångra", between "Ring Anna" and "Beställ skåp".
  const afterMove: WorkBoardPage = {
    columns: {
      todo: [a, e],
      in_progress: [c, moved, f],
      blocked: [],
      completed: [d],
      active: [project],
    },
    next_cursor: null,
  };
  const getWorkBoard = vi.fn().mockResolvedValue(afterMove);
  render(
    <Harness
      work={transport({ updateTask, getWorkBoard })}
      initial={{
        kind: "board",
        filters: {},
        page: {
          columns: {
            todo: [a, b, e],
            in_progress: [c, f],
            blocked: [],
            completed: [d],
            active: [project],
          },
          next_cursor: null,
        },
      }}
    />,
  );
  await openGroup(user, b.title);
  await user.click(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(b.title) }),
    ).getByRole("button", { name: workEn.taskStatus.in_progress }),
  );
  await screen.findByRole("button", { name: workEn.agendaUndo });
  // The column neighbour of "Beställ skåp" is the place of "Skicka faktura", not the row shown above it: no step is offered.
  await openGroup(user, e.title);
  const lower = screen.getByRole("group", {
    name: workEn.moveListFor(e.title),
  });
  expect(
    within(lower).queryByRole("button", { name: workEn.moveUp }),
  ).toBeNull();
  expect(
    within(lower).queryByRole("button", { name: workEn.moveDown }),
  ).toBeNull();
  // "Boka målare" has "Skicka faktura" between it and "Bygg webbplatsen" in the column, but not on the screen.
  await openGroup(user, f.title);
  const upper = screen.getByRole("group", {
    name: workEn.moveListFor(f.title),
  });
  expect(
    within(upper).queryByRole("button", { name: workEn.moveUp }),
  ).toBeNull();
  expect(
    within(upper).queryByRole("button", { name: workEn.moveDown }),
  ).toBeNull();
});

it("a conflict keeps the banner and the sections", async () => {
  const user = userEvent.setup();
  const { HostToolError } = await import("@/features/mcp-apps/bridge");
  const updateTask = vi.fn().mockRejectedValue(new HostToolError("conflict"));
  render(<Harness work={transport({ updateTask })} />);
  await user.click(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaComplete, { title: a.title }),
    }),
  );
  expect(await screen.findByText(workEn.boardConflict)).toBeInTheDocument();
  expect(
    elementWithText(`${workEn.taskStatus.todo} (2)`, "h3"),
  ).toBeInTheDocument();
});

it("has the top refresh row only in the columns layout", () => {
  const { unmount } = render(<Harness work={transport()} layout="columns" />);
  expect(screen.queryByRole("group", { name: "Columns" })).toBeNull();
  expect(screen.getAllByRole("button", { name: /^Drag / })).toHaveLength(4);
  expect(document.querySelector(".work-board-foot")).toBeNull();
  unmount();
  render(<Harness work={transport()} layout="single" />);
  expect(document.querySelector(".work-board-foot")).not.toBeNull();
});

it("auto stays columns in jsdom, and follows the measured width when ResizeObserver reports one", () => {
  render(<Harness work={transport()} layout="auto" />);
  expect(document.querySelector(".work-board")).toHaveAttribute(
    "data-layout",
    "columns",
  );
});

it("auto turns single under 640 px and back to columns at 640 px or more", () => {
  // Every observer gets the resize, as in a browser: the board's own, and others in the tree (other
  // components measure their boxes too), so the test does not depend on which observer was made last.
  const callbacks = new Set<() => void>();
  const callback = () => callbacks.forEach((cb) => cb());
  vi.stubGlobal(
    "ResizeObserver",
    class {
      private readonly cb: () => void;
      constructor(cb: () => void) {
        this.cb = cb;
      }
      observe() {
        callbacks.add(this.cb);
      }
      disconnect() {
        callbacks.delete(this.cb);
      }
      unobserve() {}
    },
  );
  let width = 390;
  const spy = vi
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockImplementation(() => ({
      left: 0,
      top: 0,
      right: width,
      bottom: 0,
      width,
      height: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }));
  render(<Harness work={transport()} layout="auto" />);
  act(() => callback());
  expect(document.querySelector(".work-board")).toHaveAttribute(
    "data-layout",
    "single",
  );
  width = 640;
  act(() => callback());
  expect(document.querySelector(".work-board")).toHaveAttribute(
    "data-layout",
    "columns",
  );
  width = 0;
  act(() => callback());
  expect(document.querySelector(".work-board")).toHaveAttribute(
    "data-layout",
    "columns",
  );
  spy.mockRestore();
});

it("uses Swedish labels for the section headings, the fold and the move list", async () => {
  const user = userEvent.setup();
  render(<Harness work={transport()} labels={workSv} />);
  expect(screen.queryByRole("group", { name: "Kolumner" })).toBeNull();
  expect(
    elementWithText(`${workSv.taskStatus.todo} (2)`, "h3"),
  ).toBeInTheDocument();
  expect(
    elementWithText(`${workSv.taskStatus.completed} (1)`, "button"),
  ).toHaveAttribute("aria-expanded", "false");
  expect(
    screen.getByRole("region", { name: workSv.projects }),
  ).toBeInTheDocument();
  await openGroup(user, a.title);
  const group = screen.getByRole("group", {
    name: workSv.moveListFor(a.title),
  });
  fireEvent.keyDown(group, { key: "Escape" });
  expect(
    screen.queryByRole("group", { name: workSv.moveListFor(a.title) }),
  ).toBeNull();
});

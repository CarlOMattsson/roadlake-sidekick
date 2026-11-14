import {
  boardLabelsEn,
  boardLabelsSv,
} from "@/features/work-app/board/board-labels";
import {
  agendaLabelsEn,
  agendaLabelsSv,
} from "@/features/work-app/agenda/agenda-labels";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
import { fillLabel } from "@/features/work-app/agenda/agenda-undo";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type { WorkAgendaFrame } from "@/features/work-app/transport/transport";
import {
  task,
  other,
  makeTransport,
  renderAgenda,
  glyphOf,
  undoButton,
  openRow,
  resetAgendaEnvironment,
} from "@tests/helpers/agenda-view-fixtures";

afterEach(resetAgendaEnvironment);

/**
 * Renders two groups (Idag and Försenade) with the first group heading given the box (top, bottom), on its sticky line
 * at 88 px. `moves` says what the menu's scrollIntoView scrolls (jsdom has none: the test supplies one): the page, the
 * agenda's own scroll box, or nothing. Returns the scrollBy spies of the page and of the box, and a restore; the test
 * opens its row's menu and calls restore.
 */
function renderOverHeading(
  top: number,
  bottom: number,
  moves: "page" | "box" | "none",
) {
  const { transport } = makeTransport();
  renderAgenda([task, other], transport);
  const head = document.querySelector<HTMLElement>(".work-agenda-group-head");
  if (!head) throw new Error("no group heading");
  // jsdom reads an inline top for getComputedStyle and has no layout: the box is the test's.
  head.style.top = "88px";
  vi.spyOn(head, "getBoundingClientRect").mockReturnValue({
    top,
    bottom,
    height: bottom - top,
    left: 0,
    right: 0,
    width: 0,
    x: 0,
    y: top,
    toJSON: () => ({}),
  } as DOMRect);
  // The agenda is its own scroll box in the "box" case: overflow auto, and its scrollTop is the test's (jsdom has no layout).
  const article = head.closest<HTMLElement>(".work-agenda");
  if (!article) throw new Error("no agenda");
  if (moves === "box") {
    article.style.overflowY = "auto";
    Object.defineProperty(article, "scrollTop", {
      configurable: true,
      writable: true,
      value: 0,
    });
  }
  const pageBy = vi.fn();
  const boxBy = vi.fn();
  // The page scrolls its root element (standards mode): its scrollTop is the page's place.
  const root = document.documentElement;
  Object.defineProperty(root, "scrollTop", {
    configurable: true,
    writable: true,
    value: 0,
  });
  Object.defineProperty(root, "scrollBy", {
    configurable: true,
    writable: true,
    value: pageBy,
  });
  Object.defineProperty(article, "scrollBy", {
    configurable: true,
    writable: true,
    value: boxBy,
  });
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    writable: true,
    value: vi.fn(() => {
      if (moves === "page") root.scrollTop = 40;
      if (moves === "box") article.scrollTop = 40;
    }),
  });
  // The window's scrollBy (the old correction) is spied too: it must not be called in any mode.
  const windowBy = vi.spyOn(window, "scrollBy").mockImplementation(() => {});
  return {
    pageBy,
    boxBy,
    windowBy,
    restore: () => {
      windowBy.mockRestore();
      Reflect.deleteProperty(root, "scrollTop");
      Reflect.deleteProperty(root, "scrollBy");
      Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    },
  };
}

it("after the menu scrolls in, a group heading that the scroll pushed above its sticky line goes back under it, with the 8 under it", () => {
  const over = renderOverHeading(70, 100, "page");
  try {
    openRow(task.title);
    // 100 + 8 − 88: the heading's bottom and the 8 under it stand on the sticky line.
    expect(over.pageBy).toHaveBeenCalledTimes(1);
    expect(over.pageBy).toHaveBeenCalledWith(0, 20);
    expect(over.boxBy).not.toHaveBeenCalled();
  } finally {
    over.restore();
  }
});

it("the correction scrolls the box that the menu's scroll moved, not the page", () => {
  const over = renderOverHeading(70, 100, "box");
  try {
    openRow(task.title);
    expect(over.boxBy).toHaveBeenCalledTimes(1);
    expect(over.boxBy).toHaveBeenCalledWith(0, 20);
    expect(over.pageBy).not.toHaveBeenCalled();
  } finally {
    over.restore();
  }
});

it("no correction when the menu's scroll moved nothing, so a heading above its line does not make the page jump", () => {
  const over = renderOverHeading(70, 100, "none");
  try {
    openRow(task.title);
    expect(over.pageBy).not.toHaveBeenCalled();
    expect(over.boxBy).not.toHaveBeenCalled();
    expect(over.windowBy).not.toHaveBeenCalled();
  } finally {
    over.restore();
  }
});

it("a group heading that stands on its sticky line is not scrolled", () => {
  const over = renderOverHeading(88, 118, "page");
  try {
    openRow(task.title);
    expect(over.pageBy).not.toHaveBeenCalled();
  } finally {
    over.restore();
  }
});

it("a read shows Loading as a status line of the agenda", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  // The read stays open, so the view is busy while the test looks at it. (A row write shows its state in its row.)
  mock.getWorkAgenda.mockImplementationOnce(() => new Promise(() => {}));
  renderAgenda([task, other], transport);
  await user.click(screen.getByRole("button", { name: workEn.refresh }));
  const loading = screen.getByText(workEn.loading);
  expect(loading.tagName).toBe("P");
  expect(loading).toHaveAttribute("role", "status");
  expect(loading).toHaveClass("work-agenda-loading");
  expect(loading.parentElement).toHaveClass("work-agenda");
});

it("the refused-change notice names no view: the agenda, the board and To sort share it", () => {
  expect(boardLabelsSv.conflict).toBe("Listan har lästs om, försök igen.");
  expect(boardLabelsEn.conflict).toBe("The list was refreshed. Try again.");
  expect(boardLabelsSv.conflict).not.toMatch(/Tavlan/);
});

it("the Swedish Undo line of a status change reads 'Flyttad till {status}' and names no Task", () => {
  expect(fillLabel(workSv.movedTo, { status: "Klar" })).toBe(
    "Flyttad till Klar",
  );
});

it("the Undo line of a due move reads 'Flyttad till {date}', with the date as the row's inline date gives it", () => {
  expect(fillLabel(workSv.movedTo, { status: "imorgon" })).toBe(
    "Flyttad till imorgon",
  );
});

it("the labels of the new row menu hint and the overdue move count are set in labels.ts", () => {
  expect(workEn.rowMenuHint).toBe("Touch and hold a task for more options.");
  expect(workSv.rowMenuHint).toBe("Håll inne en uppgift för fler val.");
  expect(workEn.moveAllOverdue(1)).toBe("Move 1 overdue task to tomorrow");
  expect(workEn.moveAllOverdue(5)).toBe("Move 5 overdue tasks to tomorrow");
  expect(workSv.moveAllOverdue(1)).toBe("Flytta 1 försenad till imorgon");
  expect(workSv.moveAllOverdue(5)).toBe("Flytta 5 försenade till imorgon");
  expect(workEn.moreActions).toBe("More options");
  expect(workSv.moreActions).toBe("Fler val");
});

it("has Swedish and English agenda labels in labels.ts and fills their placeholders", () => {
  expect(workSv.agendaUndo).toBe("Ångra");
  expect(workEn.agendaUndo).toBe("Undo");
  expect(agendaLabelsSv.moving).toBe("Flyttar…");
  expect(agendaLabelsEn.moving).toBe("Moving…");
  expect(fillLabel("Hej {name}, {missing}", { name: "Anna" })).toBe(
    "Hej Anna, {missing}",
  );
});

it("a status change from the open quick choices closes them, and Undo keeps them closed", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  renderAgenda([task], transport);
  openRow(task.title);
  const group = screen.getByRole("group", { name: workEn.status });
  await user.click(
    within(group).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  await undoButton();
  // The change went through: the quick choices are closed, and the row shows its Undo line.
  expect(
    screen.queryByRole("group", { name: workEn.status }),
  ).not.toBeInTheDocument();

  await user.click(await undoButton());

  await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(2));
  expect(
    screen.queryByRole("group", { name: workEn.status }),
  ).not.toBeInTheDocument();
});

it("Undo closes the quick choices of its row when they are opened after the change", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  renderAgenda([task], transport);
  // A glyph tap leaves the Undo line; the row's quick choices are then opened and still open when Undo is pressed.
  await user.click(glyphOf(task.title));
  await undoButton();
  openRow(task.title);
  expect(
    screen.getByRole("group", { name: workEn.status }),
  ).toBeInTheDocument();
  await user.click(await undoButton());
  await waitFor(() =>
    expect(
      screen.queryByRole("group", { name: workEn.status }),
    ).not.toBeInTheDocument(),
  );
});

it("a click on the Undo line's background opens no record and does not undo the change", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  const onOpen = vi.fn();
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items: [task, other], next_cursor: null },
  };
  render(
    <AgendaView
      frame={frame}
      onChange={vi.fn()}
      transport={transport}
      labels={workEn}
      moves={0}
      onOpen={onOpen}
      shortcuts={false}
    />,
  );
  await user.click(glyphOf(task.title));
  const undo = await undoButton();
  const line = undo.closest(".work-agenda-undo");
  if (!line) throw new Error("no Undo line");
  // The line's own background, not the button: the click lands on the line.
  await user.click(line);
  expect(onOpen).not.toHaveBeenCalled();
  expect(mock.updateTask).toHaveBeenCalledTimes(1);
  expect(undo).toBeInTheDocument();
});

it("the Undo button of a row is a compact secondary button (sk-btn--secondary sk-btn--compact) in the row's Undo wrapper", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  renderAgenda([task], transport);
  await user.click(glyphOf(task.title));
  const undo = await undoButton();
  expect(undo).toHaveClass("sk-btn--secondary", "sk-btn--compact");
  expect(undo).not.toHaveClass("sk-btn--tonal");
  expect(undo.parentElement).toHaveClass("work-agenda-undo");
});

import { agendaLabelsEn } from "@/features/work-app/agenda/agenda-labels";
import { boardLabelsEn } from "@/features/work-app/board/board-labels";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { fillLabel } from "@/features/work-app/agenda/agenda-undo";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { workEn } from "@/features/work-app/shared/labels";
import type { WorkBoardPage } from "@/features/work-app/transport/transport";
import { elementWithText } from "@tests/helpers/exact-text";
import {
  KEY,
  a,
  b,
  c,
  d,
  page,
  transport,
  Harness,
  search,
  rowOf,
  openGroup,
} from "@tests/helpers/board-phone-fixtures";
import { chooseColumn, columnTab, tabNames } from "./column-tabs";

afterEach(() => vi.unstubAllGlobals());

it("shows one status at a time under column tabs with counts, in board order, with an empty status as a tab too", async () => {
  const user = userEvent.setup();
  render(<Harness work={transport()} />);
  expect(screen.queryByRole("group", { name: "Columns" })).toBeNull();
  expect(tabNames(boardLabelsEn.columnTabs)).toEqual([
    `${workEn.taskStatus.todo} 2`,
    `${workEn.taskStatus.in_progress} 1`,
    `${workEn.taskStatus.blocked} 0`,
    `${workEn.taskStatus.completed} 1`,
    `${workEn.projects} 1`,
  ]);
  // Only the chosen column draws a section; its heading stays for screen readers.
  await chooseColumn(user, workEn.taskStatus.todo);
  expect(columnTab(workEn.taskStatus.todo)).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(
    screen
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-label")),
  ).toEqual([workEn.taskStatus.todo]);
  expect(elementWithText(`${workEn.taskStatus.todo} (2)`, "h3")).toHaveClass(
    "work-visually-hidden",
  );
  expect(screen.getByRole("button", { name: a.title })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: b.title })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: c.title })).toBeNull();
  await chooseColumn(user, workEn.taskStatus.in_progress);
  expect(screen.getByRole("button", { name: c.title })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: a.title })).toBeNull();
  expect(screen.queryByRole("button", { name: /^Drag / })).toBeNull();
  expect(document.querySelector(".work-board")).toHaveAttribute(
    "data-layout",
    "single",
  );
});

it("an empty status tab says so, and Klar is a tab whose rows are open at once (no fold)", async () => {
  const user = userEvent.setup();
  render(<Harness work={transport()} />);
  await chooseColumn(user, workEn.taskStatus.blocked);
  expect(
    screen.getByRole("region", { name: workEn.taskStatus.blocked }),
  ).toHaveTextContent(boardLabelsEn.noCards);
  await chooseColumn(user, workEn.taskStatus.completed);
  expect(
    screen.queryByRole("button", {
      name: `${workEn.taskStatus.completed} (1)`,
    }),
  ).toBeNull();
  expect(screen.getByRole("button", { name: d.title })).toBeInTheDocument();
  expect(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaReopen, { title: d.title }),
    }),
  ).toBeInTheDocument();
});

it("reads the board with the search only once the text changes, not with the text it mounts with", async () => {
  const work = transport();
  const { rerender } = render(search(work, "anna"));
  await act(() => new Promise((resolve) => setTimeout(resolve, 400)));
  expect(work.getWorkBoard).not.toHaveBeenCalled();
  rerender(search(work, "annas"));
  await waitFor(() =>
    expect(work.getWorkBoard).toHaveBeenCalledWith({ q: "annas" }),
  );
});

it("the search filters the titles without regard to case, and says so when nothing matches", async () => {
  const user = userEvent.setup();
  const work = transport();
  const { rerender } = render(search(work, "ANNA"));
  expect(screen.getByRole("button", { name: a.title })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: b.title })).toBeNull();
  expect(screen.queryByRole("button", { name: c.title })).toBeNull();
  expect(screen.queryByRole("region", { name: workEn.projects })).toBeNull();
  // A filter is active: a Task's move list offers no Move up or Move down.
  await openGroup(user, a.title);
  expect(
    screen.getByRole("group", { name: boardLabelsEn.moveListFor(a.title) }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: boardLabelsEn.moveUp }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: boardLabelsEn.moveDown }),
  ).toBeNull();
  rerender(search(work, "zzz"));
  // A search with no hit names the text; the "Rensa sökningen" button comes only with a clear from the shell.
  // The text rests 300 ms before the board reads with it, and the line shows once that read has answered. A read
  // for an earlier text can land first on a loaded machine, so wait for this one instead of looking straight away.
  expect(
    await screen.findByText(fillLabel(agendaLabelsEn.noMatch, { q: "zzz" })),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: agendaLabelsEn.clearSearch }),
  ).toBeNull();
  expect(
    screen.queryByRole("region", { name: workEn.taskStatus.todo }),
  ).toBeNull();
});

it("the glyph marks a Task done with update_task, its version and a key; the card stays in its place with Klar and Undo, and the glyph takes focus", async () => {
  const user = userEvent.setup();
  const moved: WorkBoardPage = {
    ...page,
    columns: {
      ...page.columns,
      todo: [b],
      completed: [d, { ...a, status: "completed", version: 2 }],
    },
  };
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...a, status: "completed", version: 2 } });
  const getWorkBoard = vi.fn().mockResolvedValue(moved);
  const work = transport({ updateTask, getWorkBoard });
  render(<Harness work={work} />);
  await chooseColumn(user, workEn.taskStatus.todo);
  await user.click(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaComplete, { title: a.title }),
    }),
  );
  expect(updateTask).toHaveBeenCalledWith(
    a.id,
    1,
    { status: "completed" },
    expect.stringMatching(KEY),
  );
  expect(getWorkBoard).toHaveBeenCalledWith({});
  const undo = await screen.findByRole("button", { name: /^Undo/ });
  // The card stays in To do, where it was, and its line says the new status in place of the meta line.
  const card = rowOf(a.title);
  const todo = screen.getByRole("region", { name: workEn.taskStatus.todo });
  expect(todo).toContainElement(card);
  // The Ångra and its message are the receipt bar's; the card has a state line and no button of its own.
  expect(undo.closest(".sk-receipt-slot")).toHaveTextContent(
    `${workEn.taskStatus.completed}: ${a.title}`,
  );
  const wrap = card.querySelector<HTMLElement>(".work-agenda-undo");
  if (!wrap) throw new Error("no state line in the card");
  expect(within(wrap).getByRole("status")).toHaveTextContent(
    workEn.taskStatus.completed,
  );
  expect(wrap.querySelector("button")).toBeNull();
  // Focus goes to the glyph, which is the card's own control, not to the Undo line.
  const glyph = card.querySelector<HTMLElement>(".work-card-done");
  if (!glyph) throw new Error("no done toggle on the card");
  await waitFor(() => expect(glyph).toHaveFocus());
  // The row stands on its place for its Ångra, but the counts say where the card is now: To do no
  // longer counts it and Klar does (heading and tabs). The row says Klar and carries data-undo for the ring, title and › in CSS.
  expect(card).toHaveAttribute("data-undo", "on");
  expect(
    elementWithText(`${workEn.taskStatus.todo} (1)`, "h3"),
  ).toBeInTheDocument();
  expect(tabNames(boardLabelsEn.columnTabs)).toEqual([
    `${workEn.taskStatus.todo} 1`,
    `${workEn.taskStatus.in_progress} 1`,
    `${workEn.taskStatus.blocked} 0`,
    `${workEn.taskStatus.completed} 2`,
    `${workEn.projects} 1`,
  ]);
});

it("the counts of Status change when the card is tapped, and stay as they are when the Ångra has run out", async () => {
  vi.useFakeTimers();
  try {
    const moved: WorkBoardPage = {
      ...page,
      columns: {
        ...page.columns,
        todo: [b],
        completed: [d, { ...a, status: "completed", version: 2 }],
      },
    };
    const updateTask = vi
      .fn()
      .mockResolvedValue({ task: { ...a, status: "completed", version: 2 } });
    render(
      <Harness
        work={transport({
          updateTask,
          getWorkBoard: vi.fn().mockResolvedValue(moved),
        })}
      />,
    );
    fireEvent.click(columnTab(workEn.taskStatus.todo));
    fireEvent.click(
      screen.getByRole("button", {
        name: fillLabel(workEn.agendaComplete, { title: a.title }),
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(
      elementWithText(`${workEn.taskStatus.todo} (1)`, "h3"),
    ).toBeInTheDocument();
    expect(tabNames(boardLabelsEn.columnTabs)).toContain(
      `${workEn.taskStatus.todo} 1`,
    );
    expect(tabNames(boardLabelsEn.columnTabs)).toContain(
      `${workEn.taskStatus.completed} 2`,
    );
    expect(rowOf(a.title)).toHaveAttribute("data-undo", "on");
    expect(within(rowOf(a.title)).getByRole("status")).toHaveTextContent(
      workEn.taskStatus.completed,
    );
    act(() => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    expect(
      elementWithText(`${workEn.taskStatus.todo} (1)`, "h3"),
    ).toBeInTheDocument();
    expect(tabNames(boardLabelsEn.columnTabs)).toContain(
      `${workEn.taskStatus.todo} 1`,
    );
    expect(tabNames(boardLabelsEn.columnTabs)).toContain(
      `${workEn.taskStatus.completed} 2`,
    );
    expect(screen.queryByRole("button", { name: a.title })).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

it("while a move is written, the single layout shows no status line above the list", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn(() => new Promise<never>(() => {}));
  render(<Harness work={transport({ updateTask })} />);
  await chooseColumn(user, workEn.taskStatus.todo);
  await user.click(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaComplete, { title: a.title }),
    }),
  );
  expect(updateTask).toHaveBeenCalledTimes(1);
  // The card keeps its place and no "Moving" or "Loading" line is added above the rows.
  expect(screen.queryByText(agendaLabelsEn.moving)).toBeNull();
  expect(screen.queryByText(workEn.loading)).toBeNull();
  expect(screen.queryByRole("button", { name: /^Undo/ })).toBeNull();
  expect(rowOf(a.title)).toBeInTheDocument();
});

it("the glyph of a done Task opens it again as To do", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...d, status: "todo", version: 2 } });
  const work = transport({ updateTask });
  render(<Harness work={work} />);
  // Klar is its own tab: the Task's glyph is reached once the tab is chosen.
  await chooseColumn(user, workEn.taskStatus.completed);
  await user.click(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaReopen, { title: d.title }),
    }),
  );
  expect(updateTask).toHaveBeenCalledWith(
    d.id,
    1,
    { status: "todo" },
    expect.stringMatching(KEY),
  );
});

it("a status picked in the expanded group is written, and the card's own status does nothing", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...a, status: "blocked", version: 2 } });
  render(<Harness work={transport({ updateTask })} />);
  await chooseColumn(user, workEn.taskStatus.todo);
  await openGroup(user, a.title);
  const group = screen.getByRole("group", {
    name: boardLabelsEn.moveListFor(a.title),
  });
  await user.click(
    within(group).getByRole("button", { name: workEn.taskStatus.todo }),
  );
  expect(updateTask).not.toHaveBeenCalled();
  await user.click(
    within(group).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  expect(updateTask).toHaveBeenCalledWith(
    a.id,
    1,
    { status: "blocked" },
    expect.stringMatching(KEY),
  );
});

it("a card moved to an empty status section shows that section with its new count while the Ångra lasts", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...a, status: "blocked", version: 2 } });
  const moved: WorkBoardPage = {
    ...page,
    columns: {
      ...page.columns,
      todo: [b],
      blocked: [{ ...a, status: "blocked", version: 2 }],
    },
  };
  render(
    <Harness
      work={transport({
        updateTask,
        getWorkBoard: vi.fn().mockResolvedValue(moved),
      })}
    />,
  );
  // Blocked has no card, so its tab counts 0 before the move.
  expect(tabNames(boardLabelsEn.columnTabs)).toContain(
    `${workEn.taskStatus.blocked} 0`,
  );
  await chooseColumn(user, workEn.taskStatus.todo);
  await openGroup(user, a.title);
  await user.click(
    within(
      screen.getByRole("group", { name: boardLabelsEn.moveListFor(a.title) }),
    ).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  await screen.findByRole("button", { name: /^Undo/ });
  // The card stands in To do for its Ångra, but the new number is seen where it went.
  expect(tabNames(boardLabelsEn.columnTabs)).toContain(
    `${workEn.taskStatus.blocked} 1`,
  );
  expect(tabNames(boardLabelsEn.columnTabs)).toContain(
    `${workEn.taskStatus.todo} 1`,
  );
  expect(
    elementWithText(`${workEn.taskStatus.todo} (1)`, "h3"),
  ).toBeInTheDocument();
  expect(rowOf(a.title)).toHaveAttribute("data-undo", "on");
  await chooseColumn(user, workEn.taskStatus.blocked);
  expect(
    elementWithText(`${workEn.taskStatus.blocked} (1)`, "h3"),
  ).toBeInTheDocument();
  const blocked = screen.getByRole("region", {
    name: workEn.taskStatus.blocked,
  });
  expect(blocked.querySelector("li")).toBeNull();
});

it("a status picked in the row menu keeps the focus: on the hidden menu button when that opened the menu, else on the row's title", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn(() => new Promise<never>(() => {}));
  render(<Harness work={transport({ updateTask })} />);
  await chooseColumn(user, workEn.taskStatus.todo);
  // Opened by the hidden button: the focus goes back to it.
  await user.click(
    screen.getByRole("button", { name: workEn.rowMenuButton(a.title) }),
  );
  await user.click(
    within(
      screen.getByRole("group", { name: boardLabelsEn.moveListFor(a.title) }),
    ).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  expect(
    screen.queryByRole("group", { name: boardLabelsEn.moveListFor(a.title) }),
  ).toBeNull();
  expect(
    within(rowOf(a.title)).getByRole("button", {
      name: workEn.rowMenuButton(a.title),
    }),
  ).toHaveFocus();
});

it("a status picked in a menu opened by the keyboard returns the focus to the row's title, not to the page", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn(() => new Promise<never>(() => {}));
  render(<Harness work={transport({ updateTask })} />);
  await chooseColumn(user, workEn.taskStatus.todo);
  await openGroup(user, b.title);
  await user.click(
    within(
      screen.getByRole("group", { name: boardLabelsEn.moveListFor(b.title) }),
    ).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  expect(updateTask).toHaveBeenCalledTimes(1);
  expect(
    screen.queryByRole("group", { name: boardLabelsEn.moveListFor(b.title) }),
  ).toBeNull();
  expect(document.activeElement).not.toBe(document.body);
  expect(rowOf(b.title).contains(document.activeElement)).toBe(true);
});

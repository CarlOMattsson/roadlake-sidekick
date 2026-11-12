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
import { fillLabel, UNDO_MS } from "@/features/work-app/agenda/agenda-undo";
import { workEn } from "@/features/work-app/shared/labels";
import type { WorkBoardPage } from "@/features/work-app/transport/transport";
import { elementWithText } from "./helpers/exact-text";
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
} from "./helpers/board-phone-fixtures";

afterEach(() => vi.unstubAllGlobals());

it("lists the statuses as sections with counts, in board order, and leaves out an empty status", () => {
  render(<Harness work={transport()} />);
  expect(screen.queryByRole("group", { name: "Columns" })).toBeNull();
  expect(
    elementWithText(`${workEn.taskStatus.todo} (2)`, "h3"),
  ).toBeInTheDocument();
  expect(
    elementWithText(`${workEn.taskStatus.in_progress} (1)`, "h3"),
  ).toBeInTheDocument();
  expect(
    elementWithText(`${workEn.taskStatus.completed} (1)`, "button"),
  ).toBeInTheDocument();
  expect(elementWithText(`${workEn.projects} (1)`, "h3")).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: workEn.taskStatus.blocked }),
  ).toBeNull();
  expect(
    screen
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-label")),
  ).toEqual([
    workEn.taskStatus.todo,
    workEn.taskStatus.in_progress,
    workEn.taskStatus.completed,
    workEn.projects,
  ]);
  expect(screen.getByRole("button", { name: a.title })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: c.title })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Drag / })).toBeNull();
  expect(document.querySelector(".work-board")).toHaveAttribute(
    "data-layout",
    "single",
  );
});

it("folds Klar: its rows show only after the heading button opens it", async () => {
  const user = userEvent.setup();
  render(<Harness work={transport()} />);
  const fold = elementWithText(`${workEn.taskStatus.completed} (1)`, "button");
  expect(fold).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("button", { name: d.title })).toBeNull();
  await user.click(fold);
  expect(fold).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: d.title })).toBeInTheDocument();
  expect(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaReopen, { title: d.title }),
    }),
  ).toBeInTheDocument();
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
    screen.getByRole("group", { name: workEn.moveListFor(a.title) }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.moveUp })).toBeNull();
  expect(screen.queryByRole("button", { name: workEn.moveDown })).toBeNull();
  rerender(search(work, "zzz"));
  // A search with no hit names the text; the "Rensa sökningen" button comes only with a clear from the shell.
  expect(
    screen.getByText(fillLabel(workEn.agendaNoMatch, { q: "zzz" })),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: workEn.agendaClearSearch }),
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
  const undo = await screen.findByRole("button", { name: workEn.agendaUndo });
  // The card stays in To do, where it was, and its line says the new status in place of the meta line.
  const card = rowOf(a.title);
  const todo = screen.getByRole("region", { name: workEn.taskStatus.todo });
  expect(todo).toContainElement(card);
  const wrap = undo.closest(".work-agenda-undo");
  if (!wrap) throw new Error("no Undo line in the card");
  expect(card).toContainElement(wrap as HTMLElement);
  expect(within(wrap as HTMLElement).getByRole("status")).toHaveTextContent(
    workEn.taskStatus.completed,
  );
  // Focus goes to the glyph, which is the card's own control, not to the Undo line.
  const glyph = card.querySelector<HTMLElement>(".work-card-done");
  if (!glyph) throw new Error("no done toggle on the card");
  await waitFor(() => expect(glyph).toHaveFocus());
  // The row stands on its place for its Ångra, but the counts say where the card is now: To do no
  // longer counts it and Klar does. The row says Klar and carries data-undo for the ring, title and › in CSS.
  expect(card).toHaveAttribute("data-undo", "on");
  expect(
    elementWithText(`${workEn.taskStatus.todo} (1)`, "h3"),
  ).toBeInTheDocument();
  const fold = elementWithText(`${workEn.taskStatus.completed} (2)`, "button");
  expect(fold).toHaveAttribute("aria-expanded", "false");
  expect(fold).toHaveClass("sk-fold");
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
    expect(
      elementWithText(`${workEn.taskStatus.completed} (2)`, "button"),
    ).toBeInTheDocument();
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
    expect(
      elementWithText(`${workEn.taskStatus.completed} (2)`, "button"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: a.title })).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

it("while a move is written, the single layout shows no status line above the list", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn(() => new Promise<never>(() => {}));
  render(<Harness work={transport({ updateTask })} />);
  await user.click(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaComplete, { title: a.title }),
    }),
  );
  expect(updateTask).toHaveBeenCalledTimes(1);
  // The card keeps its place and no "Moving" or "Loading" line is added above the rows.
  expect(screen.queryByText(workEn.agendaMoving)).toBeNull();
  expect(screen.queryByText(workEn.loading)).toBeNull();
  expect(screen.queryByRole("button", { name: workEn.agendaUndo })).toBeNull();
  expect(rowOf(a.title)).toBeInTheDocument();
});

it("the glyph of a done Task opens it again as To do", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...d, status: "todo", version: 2 } });
  const work = transport({ updateTask });
  render(<Harness work={work} />);
  // Klar is folded: the Task's glyph is reached once the heading button opens it.
  await user.click(
    elementWithText(`${workEn.taskStatus.completed} (1)`, "button"),
  );
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
  await openGroup(user, a.title);
  const group = screen.getByRole("group", {
    name: workEn.moveListFor(a.title),
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
  // Blocked has no card, so it draws no section before the move.
  expect(
    screen.queryByRole("region", { name: workEn.taskStatus.blocked }),
  ).toBeNull();
  await openGroup(user, a.title);
  await user.click(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(a.title) }),
    ).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  await screen.findByRole("button", { name: workEn.agendaUndo });
  // The card stands in To do for its Ångra, but the new number is seen where it went.
  expect(
    elementWithText(`${workEn.taskStatus.blocked} (1)`, "h3"),
  ).toBeInTheDocument();
  expect(
    elementWithText(`${workEn.taskStatus.todo} (1)`, "h3"),
  ).toBeInTheDocument();
  expect(rowOf(a.title)).toHaveAttribute("data-undo", "on");
  const blocked = screen.getByRole("region", {
    name: workEn.taskStatus.blocked,
  });
  expect(blocked.querySelector("li")).toBeNull();
});

it("a status picked in the row menu keeps the focus: on the hidden menu button when that opened the menu, else on the row's title", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn(() => new Promise<never>(() => {}));
  render(<Harness work={transport({ updateTask })} />);
  // Opened by the hidden button: the focus goes back to it.
  await user.click(
    screen.getByRole("button", { name: workEn.rowMenuButton(a.title) }),
  );
  await user.click(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(a.title) }),
    ).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  expect(
    screen.queryByRole("group", { name: workEn.moveListFor(a.title) }),
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
  await openGroup(user, b.title);
  await user.click(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(b.title) }),
    ).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  expect(updateTask).toHaveBeenCalledTimes(1);
  expect(
    screen.queryByRole("group", { name: workEn.moveListFor(b.title) }),
  ).toBeNull();
  expect(document.activeElement).not.toBe(document.body);
  expect(rowOf(b.title).contains(document.activeElement)).toBe(true);
});

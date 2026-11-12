import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { elementWithText } from "./helpers/exact-text";
import { WorkView } from "@/features/work-app/view/work-view";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  rootFromToolResult,
  type WorkAgendaPage,
  type WorkItemRecord,
  type WorkTask,
} from "@/features/work-app/transport/transport";
import {
  KEY,
  agendaTask,
  anna,
  bo,
  boardDomain,
  boardPage,
  boardProject,
  boardTask,
  boardTaskB,
  keyOf,
  movedPage,
  openBoardGroup,
  projectA,
  rootBoard,
  rootTask,
  taskA,
  transport,
} from "./helpers/work-app-fixtures";

const agendaProject: WorkItemRecord = {
  ...boardProject,
  agenda_group: "today",
};

const agendaDomain: WorkItemRecord = {
  ...boardDomain,
  agenda_group: "upcoming",
};

it("opens the board and the agenda from their tool results and keeps only the filters the tool shows", () => {
  expect(
    rootFromToolResult({ columns: { todo: [boardTask] }, next_cursor: "c2" }),
  ).toEqual({
    kind: "board",
    filters: {},
    page: { columns: { todo: [boardTask] }, next_cursor: "c2" },
  });
  expect(
    rootFromToolResult({
      columns: {},
      next_cursor: null,
      filters: { status: "todo", tags: ["lag"], kind: "task", bogus: "x" },
    }),
  ).toEqual({
    kind: "board",
    filters: { status: "todo", tags: ["lag"] },
    page: { columns: {}, next_cursor: null },
  });
  expect(
    rootFromToolResult({
      items: [agendaTask],
      next_cursor: null,
      filters: { kind: "task", sort: "due_asc" },
    }),
  ).toEqual({
    kind: "agenda",
    filters: { kind: "task", sort: "due_asc" },
    page: { items: [agendaTask], next_cursor: null },
  });
  expect(rootFromToolResult({ items: [], next_cursor: null })).toEqual({
    kind: "agenda",
    filters: {},
    page: { items: [], next_cursor: null },
  });
  expect(
    rootFromToolResult({ columns: { todo: [{ kind: "task" }] } }),
  ).toBeUndefined();
  expect(rootFromToolResult({ items: [{ id: 1 }] })).toBeUndefined();
});

it("shows one column per status with its count, and a card opens its Task and Back returns without a new read", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(rootBoard(work));
  const todo = screen.getByRole("region", { name: workEn.taskStatus.todo });
  expect(
    within(todo).getByRole("heading", { level: 3, name: "To do (2)" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: workEn.taskStatus.blocked }),
  ).toHaveTextContent("Nothing here.");
  await user.click(within(todo).getByRole("button", { name: boardTask.title }));
  expect(
    await screen.findByRole("heading", { level: 2, name: taskA.title }),
  ).toHaveFocus();
  expect(work.getTask).toHaveBeenLastCalledWith(taskA.id);
  await user.click(screen.getByRole("button", { name: /^Tillbaka till / }));
  expect(
    await screen.findByRole("heading", { level: 2, name: workEn.board }),
  ).toHaveFocus();
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.todo }),
    ).getByRole("button", { name: boardTask.title }),
  ).toBeInTheDocument();
  expect(work.getWorkBoard).not.toHaveBeenCalled();
});

it("returns to the board at the scroll position it was left at", async () => {
  const user = userEvent.setup();
  const work = transport();
  const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  Object.defineProperty(window, "scrollY", { configurable: true, value: 166 });
  render(rootBoard(work));
  await user.click(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.todo }),
    ).getByRole("button", { name: boardTask.title }),
  );
  await screen.findByRole("heading", { level: 2, name: taskA.title });
  scrollTo.mockClear();
  await user.click(screen.getByRole("button", { name: /^Tillbaka till / }));
  await screen.findByRole("heading", { level: 2, name: workEn.board });
  expect(scrollTo).toHaveBeenLastCalledWith(0, 166);
  scrollTo.mockRestore();
  Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
});

it("opens a Project card as a Project and shows a Domain card without navigation", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(rootBoard(work));
  expect(screen.queryByRole("button", { name: boardDomain.title })).toBeNull();
  expect(screen.getByText(boardDomain.title)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: boardProject.title }));
  expect(
    await screen.findByRole("heading", { level: 2, name: projectA.title }),
  ).toBeInTheDocument();
  expect(work.getProject).toHaveBeenCalledWith(projectA.id);
});

it("moves a Task through its status list with update_task, its version and a key, then reads the board again", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, status: "in_progress", version: 2 },
  });
  const getWorkBoard = vi.fn().mockResolvedValue(movedPage);
  const work = transport({ updateTask, getWorkBoard });
  render(rootBoard(work));
  await openBoardGroup(user, boardTask.title);
  const list = screen.getByRole("group", {
    name: workEn.moveListFor(boardTask.title),
  });
  // All four statuses are listed; the Task's own status is pressed and picking it writes nothing.
  const current = within(list).getByRole("button", {
    name: workEn.taskStatus.todo,
  });
  expect(current).toHaveAttribute("aria-pressed", "true");
  await user.click(current);
  expect(updateTask).not.toHaveBeenCalled();
  await user.click(
    within(list).getByRole("button", { name: workEn.taskStatus.in_progress }),
  );
  expect(updateTask).toHaveBeenCalledTimes(1);
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { status: "in_progress" },
    expect.stringMatching(KEY),
  );
  expect(getWorkBoard).toHaveBeenCalledTimes(1);
  expect(getWorkBoard).toHaveBeenCalledWith({});
  const undo = await screen.findByRole("button", { name: workEn.agendaUndo });
  expect(
    within(undo.parentElement as HTMLElement).getByRole("status"),
  ).toHaveTextContent(workEn.taskStatus.in_progress);
  const doing = screen.getByRole("region", {
    name: workEn.taskStatus.in_progress,
  });
  expect(
    within(doing).getByRole("button", { name: boardTask.title }),
  ).toBeInTheDocument();
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.todo }),
    ).queryByRole("button", { name: boardTask.title }),
  ).toBeNull();
});

it("a board move offers Undo, which writes the previous status at the new version and reads the board again", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockResolvedValueOnce({
      task: { ...taskA, status: "in_progress", version: 2 },
    })
    .mockResolvedValueOnce({ task: { ...taskA, status: "todo", version: 3 } });
  const getWorkBoard = vi
    .fn()
    .mockResolvedValueOnce(movedPage)
    .mockResolvedValueOnce(boardPage);
  const work = transport({ updateTask, getWorkBoard });
  render(rootBoard(work));
  await openBoardGroup(user, boardTask.title);
  const list = screen.getByRole("group", {
    name: workEn.moveListFor(boardTask.title),
  });
  await user.click(
    within(list).getByRole("button", { name: workEn.taskStatus.in_progress }),
  );
  const undo = await screen.findByRole("button", { name: workEn.agendaUndo });
  await waitFor(() => expect(undo).toBeEnabled());
  expect(
    within(undo.parentElement as HTMLElement).getByRole("status"),
  ).toHaveTextContent(workEn.taskStatus.in_progress);
  await user.click(undo);
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
  // The previous status ("todo"), against the version the move returned (2), with a key of its own.
  expect(updateTask).toHaveBeenLastCalledWith(
    taskA.id,
    2,
    { status: "todo" },
    expect.any(String),
  );
  expect(getWorkBoard).toHaveBeenCalledTimes(2);
  expect(
    await within(
      screen.getByRole("region", { name: workEn.taskStatus.todo }),
    ).findByRole("button", { name: boardTask.title }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: workEn.agendaUndo }),
    ).not.toBeInTheDocument(),
  );
});

it("keeps a card in its column until the server answers the move", async () => {
  const user = userEvent.setup();
  const answer: { resolve?: (value: { task: WorkTask }) => void } = {};
  const updateTask = vi.fn(
    () =>
      new Promise<{ task: WorkTask }>((resolve) => {
        answer.resolve = resolve;
      }),
  );
  const getWorkBoard = vi.fn().mockResolvedValue(movedPage);
  const work = transport({ updateTask, getWorkBoard });
  render(rootBoard(work));
  await openBoardGroup(user, boardTask.title);
  await user.click(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(boardTask.title) }),
    ).getByRole("button", { name: workEn.taskStatus.in_progress }),
  );
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.todo }),
    ).getByRole("button", { name: boardTask.title }),
  ).toBeInTheDocument();
  expect(getWorkBoard).not.toHaveBeenCalled();
  act(() => {
    answer.resolve?.({ task: { ...taskA, status: "in_progress", version: 2 } });
  });
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.in_progress }),
    ).getByRole("button", { name: boardTask.title }),
  ).toBeInTheDocument();
});

it("reads the Task version with get_task when the card has none", async () => {
  const user = userEvent.setup();
  const noVersion: WorkItemRecord = {
    kind: "task",
    id: taskA.id,
    title: taskA.title,
    status: "todo",
  };
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...taskA, status: "completed", version: 2 } });
  const work = transport({ updateTask });
  render(
    rootBoard(work, { columns: { todo: [noVersion] }, next_cursor: null }),
  );
  await openBoardGroup(user, taskA.title);
  await user.click(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(taskA.title) }),
    ).getByRole("button", { name: workEn.taskStatus.completed }),
  );
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(work.getTask).toHaveBeenCalledWith(taskA.id);
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { status: "completed" },
    expect.stringMatching(KEY),
  );
});

it("sends one move for a double-clicked status", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn(() => new Promise<never>(() => {}));
  const work = transport({ updateTask });
  render(rootBoard(work));
  await openBoardGroup(user, boardTask.title);
  await user.dblClick(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(boardTask.title) }),
    ).getByRole("button", { name: workEn.taskStatus.in_progress }),
  );
  expect(updateTask).toHaveBeenCalledTimes(1);
});

it("reuses the key when a failed move is retried, and reads nothing on a failure", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValue({ task: { ...taskA, status: "blocked", version: 2 } });
  const getWorkBoard = vi.fn().mockResolvedValue(boardPage);
  const work = transport({ updateTask, getWorkBoard });
  render(rootBoard(work));
  await openBoardGroup(user, boardTask.title);
  await user.click(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(boardTask.title) }),
    ).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(workEn.moveFailed);
  expect(getWorkBoard).not.toHaveBeenCalled();
  await user.click(within(alert).getByRole("button", { name: workEn.retry }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
  expect(updateTask.mock.calls[1]).toEqual([
    taskA.id,
    1,
    { status: "blocked" },
    expect.stringMatching(KEY),
  ]);
  expect(keyOf(updateTask, 1)).toBe(keyOf(updateTask, 0));
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
});

it("shows a move conflict as a banner, reads the board again and keeps the banner until Reload", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("conflict"));
  const getWorkBoard = vi
    .fn()
    .mockResolvedValueOnce({
      columns: {
        completed: [{ ...boardTask, status: "completed", version: 2 }],
      },
      next_cursor: null,
    })
    .mockResolvedValue(boardPage);
  const work = transport({ updateTask, getWorkBoard });
  render(rootBoard(work));
  await openBoardGroup(user, boardTask.title);
  await user.click(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(boardTask.title) }),
    ).getByRole("button", { name: workEn.taskStatus.in_progress }),
  );
  const banner = await screen.findByRole("alert");
  expect(banner).toHaveTextContent(workEn.boardConflict);
  expect(banner).toHaveFocus();
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.completed }),
    ).getByRole("button", { name: boardTask.title }),
  ).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(workEn.boardConflict);
  await user.click(within(banner).getByRole("button", { name: workEn.reload }));
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("alert")).toBeNull();
});

it("shows a refused move as calm text without retry or a read", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockRejectedValue(new HostToolError("forbidden"));
  const getWorkBoard = vi.fn();
  const work = transport({ updateTask, getWorkBoard });
  render(rootBoard(work));
  await openBoardGroup(user, boardTask.title);
  await user.click(
    within(
      screen.getByRole("group", { name: workEn.moveListFor(boardTask.title) }),
    ).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  expect(await screen.findByText(workEn.forbiddenWrite)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.retry })).toBeNull();
  expect(getWorkBoard).not.toHaveBeenCalled();
});

it("lists the statuses as plain buttons in the Tab order, and Escape closes the group to the card's title", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(rootBoard(work));
  const move = screen.getByRole("button", { name: boardTask.title });
  await openBoardGroup(user, boardTask.title);
  const list = screen.getByRole("group", {
    name: workEn.moveListFor(boardTask.title),
  });
  await user.tab();
  expect(
    within(list).getByRole("button", { name: workEn.taskStatus.todo }),
  ).toHaveFocus();
  await user.tab();
  expect(
    within(list).getByRole("button", { name: workEn.taskStatus.in_progress }),
  ).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("group")).toBeNull();
  expect(move).toHaveFocus();
  expect(work.updateTask).not.toHaveBeenCalled();
});

it("shows more board cards with the cursor and the filters of the root", async () => {
  const user = userEvent.setup();
  const getWorkBoard = vi.fn().mockResolvedValue({
    columns: {
      todo: [
        {
          kind: "task",
          id: "019f0000-0000-7000-8000-0000000000f2",
          title: "Ny uppgift",
          status: "todo",
          version: 1,
        },
      ],
    },
    next_cursor: null,
  });
  const work = transport({ getWorkBoard });
  render(
    rootBoard(
      work,
      { columns: { todo: [boardTask] }, next_cursor: "cursor-2" },
      { status: "todo" },
    ),
  );
  await user.click(screen.getByRole("button", { name: workEn.more }));
  expect(getWorkBoard).toHaveBeenCalledWith({ status: "todo" }, "cursor-2");
  const todo = screen.getByRole("region", { name: workEn.taskStatus.todo });
  expect(
    await within(todo).findByRole("button", { name: "Ny uppgift" }),
  ).toBeInTheDocument();
  expect(
    within(todo).getByRole("button", { name: boardTask.title }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.more })).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.refresh }));
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(2));
  expect(getWorkBoard).toHaveBeenLastCalledWith({ status: "todo" });
});

it("opens an agenda grouped by its agenda groups, opens a Task and goes back to the agenda", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(
    <WorkView
      transport={work}
      initial={{
        kind: "agenda",
        filters: {},
        page: {
          items: [agendaTask, agendaProject, agendaDomain],
          next_cursor: null,
        } satisfies WorkAgendaPage,
      }}
      labels={workEn}
    />,
  );
  // Only Overdue has a count in its heading ("Overdue (1)"); Today names its day, e.g. "Today, Thu 29 Oct".
  // The count is its own element (.sk-count), so the heading is found by its full text.
  await waitFor(() =>
    expect(
      elementWithText(`${workEn.agendaGroup.overdue} (1)`, "h3"),
    ).toBeInTheDocument(),
  );
  expect(
    screen.getByRole("heading", {
      level: 3,
      name: new RegExp(`^${workEn.agendaGroup.today}, .+$`),
    }),
  ).toBeInTheDocument();
  // The domain has no due date, so it falls under "No date", not "Upcoming".
  expect(
    screen.getByRole("heading", {
      level: 3,
      name: workEn.agendaGroup.undated,
    }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: agendaDomain.title })).toBeNull();
  await user.click(screen.getByRole("button", { name: agendaTask.title }));
  expect(
    await screen.findByRole("heading", { level: 2, name: taskA.title }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^Tillbaka till / }));
  expect(
    await screen.findByRole("heading", { level: 2, name: workEn.agenda }),
  ).toBeInTheDocument();
  expect(work.getWorkAgenda).not.toHaveBeenCalled();
});

it("lists agenda records in the order they arrived when none carries a group", () => {
  render(
    <WorkView
      transport={transport()}
      initial={{
        kind: "agenda",
        filters: {},
        page: {
          // Both without a due date, so both fall in one client-made group.
          items: [{ ...boardTask, due_at: null }, { ...boardTaskB }],
          next_cursor: null,
        },
      }}
      labels={workEn}
    />,
  );
  // The agenda still shows its group heading; the order inside that group is the arrival order.
  expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(1);
  expect(
    screen.getByRole("heading", {
      level: 3,
      name: workEn.agendaGroup.undated,
    }),
  ).toBeInTheDocument();
  const titles = screen
    .getAllByRole("button")
    .map((button) => button.textContent);
  expect(titles.indexOf(boardTask.title)).toBeLessThan(
    titles.indexOf(boardTaskB.title),
  );
});

it("names each row menu button after its Contact in Swedish and English", async () => {
  const work = transport({
    listTaskContacts: vi.fn().mockResolvedValue({
      items: [anna, bo],
      next_cursor: null,
    }),
  });
  const { unmount } = render(rootTask(work));
  await screen.findByRole("button", { name: bo.display_name });
  // The remove-link entry is in each row's own menu (a hidden button opens it), not in the Task's ⋯.
  expect(
    screen.getByRole("button", { name: "More options for Anna Andersson" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "More options for Bo Berg" }),
  ).toBeInTheDocument();
  unmount();
  render(
    <WorkView
      transport={work}
      initial={{ kind: "task", id: taskA.id }}
      labels={workSv}
    />,
  );
  await screen.findByRole("button", { name: bo.display_name });
  expect(
    screen.getByRole("button", { name: "Fler val för Anna Andersson" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Fler val för Bo Berg" }),
  ).toBeInTheDocument();
});

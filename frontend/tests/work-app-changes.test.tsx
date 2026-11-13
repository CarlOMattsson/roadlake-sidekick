import { boardLabelsEn } from "@/features/work-app/board/board-labels";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WorkView } from "@/features/work-app/view/work-view";
import { workEn } from "@/features/work-app/shared/labels";
import { linksLabelsEn } from "@/features/work-app/shared/links-labels";
import { cardLabelsEn } from "@/features/work-app/shared/card-labels";
import {
  rootFromToolResult,
  type WorkItemRecord,
  type WorkTransport,
} from "@/features/work-app/transport/transport";
import {
  KEY,
  agendaTask,
  anna,
  boardPage,
  boardTask,
  contactRoot,
  movedPage,
  openBoardGroup,
  openEdit,
  openMoreMenu,
  projectA,
  rootBoard,
  rootTask,
  taskA,
  taskB,
  transport,
} from "./helpers/work-app-fixtures";

const cardTask: WorkItemRecord = {
  kind: "task",
  id: taskA.id,
  title: taskA.title,
  status: "todo",
  due_at: null,
  version: 1,
};

function workChangesRoot() {
  return rootFromToolResult({
    card: {
      kind: "work_changes",
      items: [cardTask],
      total: 1,
      truncated: false,
    },
  });
}

/** A Task as the board and the agenda list it; the Task opened from either row is `taskA`. */
const listedTask: WorkItemRecord = {
  kind: "task",
  id: taskA.id,
  title: taskA.title,
  status: "todo",
  due_at: null,
  version: 1,
};

function rootBoardWith(work: WorkTransport, items: WorkItemRecord[]) {
  return (
    <WorkView
      transport={work}
      initial={{
        kind: "board",
        filters: {},
        page: { columns: { todo: items }, next_cursor: null },
      }}
      labels={workEn}
    />
  );
}

function rootAgendaWith(work: WorkTransport, items: WorkItemRecord[]) {
  return (
    <WorkView
      transport={work}
      initial={{
        kind: "agenda",
        filters: {},
        page: { items, next_cursor: null },
      }}
      labels={workEn}
    />
  );
}

/** Opens the listed Task, edits its title and saves; the Task view shows the saved title. */
async function openAndSaveTitle(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: taskA.title }));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ring Anna idag");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await screen.findByText(workEn.saved);
}

it("shows a work_changes card inline as a compact list with Open and no status buttons", () => {
  const work = transport();
  render(
    <WorkView
      transport={work}
      initial={workChangesRoot()}
      labels={workEn}
      cardLabels={cardLabelsEn}
      fullscreen={vi.fn()}
    />,
  );
  expect(screen.getByText(cardTask.title)).toBeInTheDocument();
  expect(
    screen.queryByRole("group", { name: cardLabelsEn.statusGroup }),
  ).toBeNull();
  expect(screen.getAllByRole("button")).toHaveLength(1);
  expect(
    screen.getByRole("button", { name: "Show all (1)" }),
  ).toBeInTheDocument();
  expect(work.updateTask).not.toHaveBeenCalled();
});

it("changes a Task status from a work_changes card only in fullscreen", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, status: "completed", version: 2 },
  });
  const work = transport({ updateTask });
  render(
    <WorkView
      transport={work}
      initial={workChangesRoot()}
      labels={workEn}
      cardLabels={cardLabelsEn}
      shortcuts
    />,
  );
  const group = screen.getByRole("group", {
    name: cardLabelsEn.statusGroup,
  });
  await user.click(
    within(group).getByRole("button", {
      name: cardLabelsEn.taskStatus.completed,
    }),
  );
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask.mock.calls[0]).toEqual([
    taskA.id,
    1,
    { status: "completed" },
    expect.any(String),
  ]);
});

it("a Project board keeps its project_id on every re-read: after a move, after Undo and on Refresh", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockResolvedValueOnce({
      task: { ...taskA, status: "in_progress", version: 2 },
    })
    .mockResolvedValueOnce({ task: { ...taskA, status: "todo", version: 3 } });
  const getWorkBoard = vi.fn().mockResolvedValue(movedPage);
  const work = transport({ updateTask, getWorkBoard });
  const filters = { project_id: projectA.id };
  render(rootBoard(work, boardPage, filters));
  await openBoardGroup(user, boardTask.title);
  const list = screen.getByRole("group", {
    name: boardLabelsEn.moveListFor(boardTask.title),
  });
  await user.click(
    within(list).getByRole("button", { name: workEn.taskStatus.in_progress }),
  );
  const undo = await screen.findByRole("button", { name: /^Undo/ });
  await waitFor(() => expect(undo).toBeEnabled());
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
  expect(getWorkBoard).toHaveBeenLastCalledWith(filters);
  await user.click(undo);
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(2));
  expect(getWorkBoard).toHaveBeenLastCalledWith(filters);
  await user.click(screen.getByRole("button", { name: workEn.refresh }));
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(3));
  expect(getWorkBoard).toHaveBeenLastCalledWith(filters);
});

it("a board result keeps project_id among its filters, and an agenda result drops it", async () => {
  const user = userEvent.setup();
  expect(
    rootFromToolResult({
      columns: { todo: [boardTask] },
      next_cursor: null,
      filters: { project_id: projectA.id, status: "todo" },
    }),
  ).toEqual({
    kind: "board",
    filters: { project_id: projectA.id, status: "todo" },
    page: { columns: { todo: [boardTask] }, next_cursor: null },
  });
  const agenda = rootFromToolResult({
    items: [agendaTask],
    next_cursor: null,
    filters: { project_id: projectA.id, kind: "task" },
  });
  expect(agenda).toEqual({
    kind: "agenda",
    filters: { kind: "task" },
    page: { items: [agendaTask], next_cursor: null },
  });
  if (agenda?.kind !== "agenda") throw new Error("no agenda frame");
  const getWorkAgenda = vi
    .fn()
    .mockResolvedValue({ items: [agendaTask], next_cursor: null });
  render(
    <WorkView
      transport={transport({ getWorkAgenda })}
      initial={agenda}
      labels={workEn}
    />,
  );
  await user.click(await screen.findByRole("button", { name: workEn.refresh }));
  await waitFor(() => expect(getWorkAgenda).toHaveBeenCalledTimes(1));
  expect(getWorkAgenda).toHaveBeenCalledWith({ kind: "task" });
  expect(getWorkAgenda.mock.calls[0]?.[0]).not.toHaveProperty("project_id");
});

it("reads the board again when Back returns from a saved Task", async () => {
  const user = userEvent.setup();
  const work = transport({
    getWorkBoard: vi.fn().mockResolvedValue({
      columns: {
        todo: [{ ...listedTask, title: "Ring Anna idag", version: 2 }],
      },
      next_cursor: null,
    }),
    updateTask: vi.fn().mockResolvedValue({
      task: { ...taskA, title: "Ring Anna idag", version: 2 },
    }),
  });
  render(rootBoardWith(work, [listedTask]));
  await openAndSaveTitle(user);
  expect(work.getWorkBoard).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: /^Tillbaka till / }));
  expect(
    await screen.findByRole("button", { name: "Ring Anna idag" }),
  ).toBeInTheDocument();
  expect(work.getWorkBoard).toHaveBeenCalledTimes(1);
});

it("reads the agenda again when Back returns from a saved Task", async () => {
  const user = userEvent.setup();
  const work = transport({
    getWorkAgenda: vi.fn().mockResolvedValue({
      items: [
        {
          ...listedTask,
          title: "Ring Anna idag",
          version: 2,
          agenda_group: "today",
        },
      ],
      next_cursor: null,
    }),
    updateTask: vi.fn().mockResolvedValue({
      task: { ...taskA, title: "Ring Anna idag", version: 2 },
    }),
  });
  render(rootAgendaWith(work, [{ ...listedTask, agenda_group: "today" }]));
  await openAndSaveTitle(user);
  expect(work.getWorkAgenda).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: /^Tillbaka till / }));
  expect(
    await screen.findByRole("button", { name: "Ring Anna idag" }),
  ).toBeInTheDocument();
  expect(work.getWorkAgenda).toHaveBeenCalledTimes(1);
});

it("does not read the board again when Back follows no save", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(rootBoardWith(work, [listedTask]));
  await user.click(screen.getByRole("button", { name: taskA.title }));
  await screen.findByRole("heading", { level: 2, name: taskA.title });
  await user.click(screen.getByRole("button", { name: /^Tillbaka till / }));
  expect(
    await screen.findByRole("button", { name: taskA.title }),
  ).toBeInTheDocument();
  expect(work.getWorkBoard).not.toHaveBeenCalled();
});

it("shows the High priority in the Task view of a high-priority Task", async () => {
  const work = transport({
    getTask: vi.fn().mockResolvedValue({
      task: { ...taskA, priority: "high" },
    }),
  });
  render(rootTask(work));
  await screen.findByRole("heading", { level: 2, name: taskA.title });
  expect(screen.getByText(workEn.priorityLevel.high)).toHaveAttribute(
    "data-priority",
    "high",
  );
});

it("shows no priority marker in the Task view of a normal Task", async () => {
  const work = transport();
  render(rootTask(work));
  await screen.findByRole("heading", { level: 2, name: taskA.title });
  expect(document.querySelector("[data-priority]")).toBeNull();
});

it("shows no more-menu and no remove link in a Contact's Task row, and its ring marks the Task done with Undo", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...taskB, status: "completed", version: 2 } });
  const work = transport({ updateTask });
  render(contactRoot(work));
  const row = (
    await screen.findByRole("button", { name: taskB.title })
  ).closest("li") as HTMLElement;
  // The Task's link is removed from the Task view, so the Contact's row has no ⋯ and no "Remove link".
  expect(
    within(row).queryByRole("button", { name: /More options|Fler val/ }),
  ).toBeNull();
  expect(
    within(row).queryByRole("button", {
      name: linksLabelsEn.removeReferenceFor(taskB.title),
    }),
  ).toBeNull();
  await user.click(
    within(row).getByRole("button", {
      name: workEn.agendaComplete.replace("{title}", taskB.title),
    }),
  );
  expect(
    await within(row).findByRole("button", { name: /^Undo/ }),
  ).toBeInTheDocument();
  expect(updateTask).toHaveBeenCalledTimes(1);
  expect(updateTask).toHaveBeenCalledWith(
    taskB.id,
    expect.any(Number),
    { status: "completed" },
    expect.stringMatching(KEY),
  );
});

it("keeps the nickname list out of the ⋯ menu and shows it in the editor, closed again by Cancel", async () => {
  const user = userEvent.setup();
  render(contactRoot(transport()));
  await openMoreMenu(user);
  expect(screen.queryByRole("button", { name: workEn.addAlias })).toBeNull();
  await user.click(await screen.findByRole("button", { name: workEn.edit }));
  const group = await screen.findByRole("group", {
    name: workEn.aliasesHeading,
  });
  expect(within(group).getByLabelText(workEn.aliasValue)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: workEn.cancel }));
  expect(screen.queryByLabelText(workEn.aliasValue)).toBeNull();
});

it("shows no Tasks or Projects heading for a Contact with no Tasks and no Projects", async () => {
  const work = transport({
    getContactContext: vi.fn().mockResolvedValue({
      contact: anna,
      projects: { items: [], next_cursor: null },
      tasks: { items: [], next_cursor: null },
    }),
  });
  render(contactRoot(work));
  await screen.findByRole("heading", { level: 2, name: anna.display_name });
  expect(
    screen.queryByRole("heading", { level: 3, name: workEn.tasks }),
  ).toBeNull();
  expect(
    screen.queryByRole("heading", { level: 3, name: workEn.projects }),
  ).toBeNull();
  expect(screen.queryByText(workEn.noTasks)).toBeNull();
});

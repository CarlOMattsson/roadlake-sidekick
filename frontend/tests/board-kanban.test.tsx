import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { workEn } from "@/features/work-app/labels";
import { type WorkTask } from "@/features/work-app/transport";
import {
  KEY,
  taskA,
  taskB,
  projectCard,
  board,
  afterMove,
  transport,
  rootBoard,
  rect,
  handleOf,
  pointer,
  sleep,
} from "./helpers/board-kanban-fixtures";

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

it("drags a Task with the mouse into another status and writes it with its version and a key", async () => {
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, status: "in_progress", version: 2 },
  });
  const getWorkBoard = vi.fn().mockResolvedValue(afterMove);
  render(rootBoard(transport({ updateTask, getWorkBoard })));
  const handle = handleOf(taskA.title);

  pointer(handle, "pointerdown", 20, 60);
  pointer(handle, "pointermove", 150, 60);
  expect(handle.closest("li")).toHaveStyle({ opacity: "0.5" });
  pointer(handle, "pointerup", 150, 60);

  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { status: "in_progress" },
    expect.stringMatching(KEY),
  );
  expect(getWorkBoard).toHaveBeenCalledTimes(1);
  const doing = screen.getByRole("region", {
    name: workEn.taskStatus.in_progress,
  });
  expect(
    await within(doing).findByRole("button", { name: taskA.title }),
  ).toBeInTheDocument();
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.todo }),
    ).queryByRole("button", { name: taskA.title }),
  ).toBeNull();
});

it("shows the dragged Task in its target column until the board is read again", async () => {
  let answer: (value: { task: WorkTask }) => void = () => undefined;
  const updateTask = vi.fn(
    () =>
      new Promise<{ task: WorkTask }>((resolve) => {
        answer = resolve;
      }),
  );
  render(rootBoard(transport({ updateTask })));
  const handle = handleOf(taskA.title);
  pointer(handle, "pointerdown", 20, 60);
  pointer(handle, "pointermove", 150, 60);
  pointer(handle, "pointerup", 150, 60);

  const doing = screen.getByRole("region", {
    name: workEn.taskStatus.in_progress,
  });
  // The card is shown in its target column and says a write is running; it is not disabled for other cards' sake.
  expect(
    (await within(doing).findByRole("button", { name: taskA.title })).closest(
      "li",
    ),
  ).toHaveAttribute("aria-busy", "true");
  act(() => {
    answer({
      task: {
        id: taskA.id,
        title: taskA.title,
        status: "in_progress",
        due_at: null,
        version: 2,
      },
    });
  });
  expect(
    await within(doing).findByRole("button", { name: taskA.title }),
  ).toBeEnabled();
});

it("does not write when the Task is dropped in its own column, or on a column that is not a Task status", async () => {
  const updateTask = vi.fn();
  render(rootBoard(transport({ updateTask })));
  const handle = handleOf(taskA.title);

  pointer(handle, "pointerdown", 20, 60);
  pointer(handle, "pointermove", 50, 120);
  pointer(handle, "pointerup", 50, 120);
  pointer(handle, "pointerdown", 20, 60);
  pointer(handle, "pointermove", 450, 60);
  pointer(handle, "pointerup", 450, 60);

  await sleep(20);
  expect(updateTask).not.toHaveBeenCalled();
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.todo }),
    ).getByRole("button", { name: taskA.title }),
  ).toBeInTheDocument();
});

it("lists the four Task statuses as columns and every Project in one Projects column, never a Project status as a column", () => {
  render(rootBoard(transport()));

  const columns = Array.from(
    document.querySelectorAll<HTMLElement>("[data-board-column]"),
    (column) => column.dataset.boardColumn,
  );
  expect(columns).toEqual([
    "todo",
    "in_progress",
    "blocked",
    "completed",
    "project",
  ]);
  const projects = screen.getByRole("region", { name: workEn.projects });
  expect(
    within(projects).getByRole("heading", {
      level: 3,
      name: `${workEn.projects} (1)`,
    }),
  ).toBeInTheDocument();
  expect(
    within(projects).getByRole("button", { name: projectCard.title }),
  ).toBeInTheDocument();
  // "Active" names the Project's own status on its card, not a column beside "In progress".
  expect(
    screen.queryByRole("region", { name: workEn.projectStatus.active }),
  ).toBeNull();
  expect(within(projects).getByText(workEn.projectStatus.active)).toHaveClass(
    "work-card-status",
  );
});

it("a touch that moves before the long press scrolls, and a held touch drags", async () => {
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, status: "in_progress", version: 2 },
  });
  render(rootBoard(transport({ updateTask })));
  const handle = handleOf(taskA.title);

  pointer(handle, "pointerdown", 20, 60, "touch");
  pointer(handle, "pointermove", 150, 60, "touch");
  pointer(handle, "pointerup", 150, 60, "touch");
  await sleep(300);
  expect(updateTask).not.toHaveBeenCalled();

  pointer(handle, "pointerdown", 20, 60, "touch");
  await sleep(300);
  pointer(handle, "pointermove", 150, 60, "touch");
  pointer(handle, "pointerup", 150, 60, "touch");
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { status: "in_progress" },
    expect.stringMatching(KEY),
  );
});

it("a drag held at the board edge moves the Task to the neighbouring column", async () => {
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, status: "in_progress", version: 2 },
  });
  render(rootBoard(transport({ updateTask })));
  const handle = handleOf(taskA.title);

  pointer(handle, "pointerdown", 20, 60);
  // The edge strips sit at the board's own edges; x 590 is inside the 32 px strip on the right.
  pointer(handle, "pointermove", 590, 60);
  await sleep(700);
  pointer(handle, "pointerup", 590, 60);

  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { status: "in_progress" },
    expect.stringMatching(KEY),
  );
});

it("Escape cancels a drag in progress, so releasing the pointer writes nothing", async () => {
  const updateTask = vi.fn();
  render(rootBoard(transport({ updateTask })));
  const handle = handleOf(taskA.title);

  pointer(handle, "pointerdown", 20, 60);
  pointer(handle, "pointermove", 150, 60);
  fireEvent.keyDown(handle, { key: "Escape" });
  pointer(handle, "pointerup", 150, 60);

  await sleep(20);
  expect(updateTask).not.toHaveBeenCalled();
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.todo }),
    ).getByRole("button", { name: taskA.title }),
  ).toBeInTheDocument();
});

describe("keyboard", () => {
  it("ArrowRight on the focused handle moves the Task to the next status with its version and a key", async () => {
    const user = userEvent.setup();
    const updateTask = vi.fn().mockResolvedValue({
      task: { ...taskA, status: "in_progress", version: 2 },
    });
    const getWorkBoard = vi.fn().mockResolvedValue(afterMove);
    render(rootBoard(transport({ updateTask, getWorkBoard })));
    const handle = handleOf(taskA.title);
    act(() => handle.focus());

    await user.keyboard("{ArrowRight}");

    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledWith(
      taskA.id,
      1,
      { status: "in_progress" },
      expect.stringMatching(KEY),
    );
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
    expect(
      await within(
        screen.getByRole("region", { name: workEn.taskStatus.in_progress }),
      ).findByRole("button", { name: taskA.title }),
    ).toBeInTheDocument();
  });

  it("after an arrow move the Task's handle keeps focus in its new column", async () => {
    const user = userEvent.setup();
    const updateTask = vi.fn().mockResolvedValue({
      task: { ...taskA, status: "in_progress", version: 2 },
    });
    const getWorkBoard = vi.fn().mockResolvedValue(afterMove);
    render(rootBoard(transport({ updateTask, getWorkBoard })));
    act(() => handleOf(taskA.title).focus());

    await user.keyboard("{ArrowRight}");

    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
    const doing = screen.getByRole("region", {
      name: workEn.taskStatus.in_progress,
    });
    const moved = await within(doing).findByRole("button", {
      name: workEn.dragTaskFor(taskA.title),
    });
    await waitFor(() => expect(moved).toHaveFocus());
    expect(moved.closest("li")).toHaveAttribute("data-card-id", taskA.id);
  });

  it("ArrowLeft in the first status and a Project card without a handle write nothing", async () => {
    const user = userEvent.setup();
    const updateTask = vi.fn();
    render(rootBoard(transport({ updateTask })));
    act(() => handleOf(taskB.title).focus());

    await user.keyboard("{ArrowLeft}");

    expect(updateTask).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", {
        name: workEn.dragTaskFor(projectCard.title),
      }),
    ).toBeNull();
  });
});

it("a refused drag shows the conflict banner and puts the Task back in its column", async () => {
  const updateTask = vi.fn().mockRejectedValue(new HostToolError("conflict"));
  const getWorkBoard = vi.fn().mockResolvedValue(board);
  render(rootBoard(transport({ updateTask, getWorkBoard })));
  const handle = handleOf(taskA.title);

  pointer(handle, "pointerdown", 20, 60);
  pointer(handle, "pointermove", 150, 60);
  pointer(handle, "pointerup", 150, 60);

  const banner = await screen.findByRole("alert");
  expect(banner).toHaveTextContent(workEn.boardConflict);
  await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.todo }),
    ).getByRole("button", { name: taskA.title }),
  ).toBeInTheDocument();
  expect(
    within(
      screen.getByRole("region", { name: workEn.taskStatus.in_progress }),
    ).queryByRole("button", { name: taskA.title }),
  ).toBeNull();
});

it("a failed drag puts the Task back, and Retry sends the same write with the same key", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockRejectedValueOnce(new Error("network down"))
    .mockResolvedValueOnce({
      task: { ...taskA, status: "in_progress", version: 2 },
    });
  const getWorkBoard = vi.fn().mockResolvedValue(afterMove);
  render(rootBoard(transport({ updateTask, getWorkBoard })));
  const handle = handleOf(taskA.title);

  pointer(handle, "pointerdown", 20, 60);
  pointer(handle, "pointermove", 150, 60);
  pointer(handle, "pointerup", 150, 60);

  await user.click(await screen.findByRole("button", { name: workEn.retry }));

  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
  expect(updateTask.mock.calls[1]?.[3]).toBe(updateTask.mock.calls[0]?.[3]);
  expect(updateTask.mock.calls[0]?.[3]).toEqual(expect.stringMatching(KEY));
});

import { act, render, screen, waitFor, within } from "@testing-library/react";
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
import { BoardView } from "@/features/work-app/board";
import { workDate } from "@/features/mcp-apps/ui/due";
import { workEn, workSv, type WorkLabels } from "@/features/work-app/labels";
import {
  type WorkItemRecord,
  type WorkTask,
} from "@/features/work-app/transport";
import {
  KEY,
  taskA,
  board,
  afterMove,
  transport,
  rootBoard,
  rect,
  handleOf,
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

describe("due chip on a card", () => {
  // 12:00 UTC on 26 October 2026 is 13:00 in Europe/Stockholm, the day the due dates are read in.
  const now = new Date("2026-10-26T12:00:00Z");
  const overdue: WorkItemRecord = {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000d1",
    title: "Betala hyran",
    status: "todo",
    due_at: "2026-10-25T09:00:00Z",
    version: 1,
  };
  const dueToday: WorkItemRecord = {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000d2",
    title: "Skicka kvittot",
    status: "todo",
    due_at: "2026-10-26T20:00:00Z",
    version: 1,
  };

  function renderDueBoard(items: WorkItemRecord[]) {
    render(
      <BoardView
        frame={{
          kind: "board",
          filters: {},
          page: {
            columns: {
              todo: items,
              in_progress: [],
              completed: [],
              active: [],
              paused: [],
            },
            next_cursor: null,
          },
        }}
        onChange={() => undefined}
        transport={transport()}
        labels={workEn}
        moves={0}
        onOpen={() => undefined}
        now={now}
      />,
    );
  }

  it("shows an overdue Task in the overdue tone and a Task due today in the today tone, with the exact date in the title", () => {
    renderDueBoard([overdue, dueToday]);

    const late = screen.getByText("1 day overdue", { selector: "time" });
    expect(late).toHaveAttribute("data-tone", "overdue");
    expect(late).toHaveAttribute("datetime", overdue.due_at);
    expect(late).toHaveAttribute(
      "title",
      workDate(overdue.due_at, now, workEn.dateLocale, { relative: false }),
    );

    // Inside a meta line "today" is lower case, as the agenda's and the board's lines have it.
    const today = screen.getByText("today", { selector: "time" });
    expect(today).toHaveAttribute("data-tone", "today");
    expect(today).toHaveAttribute("datetime", dueToday.due_at);
  });

  it("shows no due chip for a Task without a due date", () => {
    renderDueBoard([taskA]);

    const card = handleOf(taskA.title).closest("li");
    expect(card?.querySelector("time")).toBeNull();
    // A Task without a due date and without a Project has no meta line at all: its kind is not shown.
    expect(card?.querySelector(".work-card-meta")).toBeNull();
  });
});

describe("meta line of a card in a Project", () => {
  // The board data gives a Task's project id but not its name, and a Task's kind is not shown: the card has no meta line.
  const inProject: WorkItemRecord = {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000e1",
    title: "Fyll i deklarationen",
    status: "todo",
    due_at: null,
    version: 1,
    project_id: "019f0000-0000-7000-8000-0000000000e2",
  };

  function renderMetaBoard(labels: WorkLabels) {
    return render(
      <BoardView
        frame={{
          kind: "board",
          filters: {},
          page: {
            columns: {
              todo: [inProject],
              in_progress: [],
              completed: [],
              active: [],
              paused: [],
            },
            next_cursor: null,
          },
        }}
        onChange={() => undefined}
        transport={transport()}
        labels={labels}
        moves={0}
        onOpen={() => undefined}
      />,
    );
  }

  it("has no meta line, so neither the kind nor the word Project is shown", () => {
    renderMetaBoard(workEn);

    const card = handleOf(inProject.title).closest("li");
    expect(card?.querySelector(".work-card-meta")).toBeNull();
    expect(card).not.toHaveTextContent("Project");
  });

  it("shows no Projekt on a Swedish board, with lang set on the columns", () => {
    const { container } = renderMetaBoard(workSv);

    const card = screen
      .getByRole("button", { name: workSv.dragTaskFor(inProject.title) })
      .closest("li");
    expect(card?.querySelector(".work-card-meta")).toBeNull();
    expect(card).not.toHaveTextContent("Projekt");
    expect(container.querySelector(".work-columns")).toHaveAttribute(
      "lang",
      "sv",
    );
  });
});

describe("card and Shift+arrow", () => {
  it("shows a status glyph on each card and no kind in a Task's meta line", () => {
    render(rootBoard(transport()));

    // A Task's glyph is the drag grip, hidden from AT; a Project's glyph is labelled with its status.
    expect(
      handleOf(taskA.title).querySelector('[data-glyph="ring-empty"]'),
    ).not.toBeNull();
    expect(
      screen.getByRole("img", { name: workEn.projectStatus.active }),
    ).toHaveAttribute("data-glyph", "ring-empty");
    const card = handleOf(taskA.title).closest("li");
    expect(card?.querySelector(".work-card-meta")).toBeNull();
  });

  it("Shift+ArrowRight moves the Task to the next status with its version and a key", async () => {
    const user = userEvent.setup();
    const updateTask = vi.fn().mockResolvedValue({
      task: { ...taskA, status: "in_progress", version: 2 },
    });
    const getWorkBoard = vi.fn().mockResolvedValue(afterMove);
    render(rootBoard(transport({ updateTask, getWorkBoard })));
    act(() => handleOf(taskA.title).focus());

    await user.keyboard("{Shift>}{ArrowRight}{/Shift}");

    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledWith(
      taskA.id,
      1,
      { status: "in_progress" },
      expect.stringMatching(KEY),
    );
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
  });

  it("Shift+ArrowRight shows the Task in its target column while the write is pending; Shift+ArrowLeft in the first status writes nothing", async () => {
    const user = userEvent.setup();
    let answer: (value: { task: WorkTask }) => void = () => undefined;
    const updateTask = vi.fn(
      () =>
        new Promise<{ task: WorkTask }>((resolve) => {
          answer = resolve;
        }),
    );
    render(rootBoard(transport({ updateTask })));
    act(() => handleOf(taskA.title).focus());

    await user.keyboard("{Shift>}{ArrowLeft}{/Shift}");
    await sleep(20);
    expect(updateTask).not.toHaveBeenCalled();

    await user.keyboard("{Shift>}{ArrowRight}{/Shift}");
    const doing = screen.getByRole("region", {
      name: workEn.taskStatus.in_progress,
    });
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

  it("a refused Shift+arrow move shows the conflict banner and puts the Task back in its column", async () => {
    const user = userEvent.setup();
    const updateTask = vi.fn().mockRejectedValue(new HostToolError("conflict"));
    const getWorkBoard = vi.fn().mockResolvedValue(board);
    render(rootBoard(transport({ updateTask, getWorkBoard })));
    act(() => handleOf(taskA.title).focus());

    await user.keyboard("{Shift>}{ArrowRight}{/Shift}");

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(workEn.boardConflict);
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
    expect(
      within(
        screen.getByRole("region", { name: workEn.taskStatus.todo }),
      ).getByRole("button", { name: taskA.title }),
    ).toBeInTheDocument();
  });
});

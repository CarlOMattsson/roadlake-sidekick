import {
  render,
  screen,
  waitFor,
  within,
  fireEvent,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { BoardView } from "@/features/work-app/board/board";
import { workEn } from "@/features/work-app/shared/labels";
import {
  appendBoardPage,
  shownOrder,
} from "@/features/work-app/shared/work-items";
import type {
  WorkBoardFrame,
  WorkBoardPage,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";

/*
 * The phone's Status list (the "single" layout) sorts each section by due date, the overdue first and the undated
 * last in the server's order. A section the user has ordered (`manually_ordered`) keeps the server's order,
 * which is the user's. The columns layout shows the same order (board-kanban-cards.test.tsx). jsdom has no layout, so the
 * layout is forced with the `layout` prop.
 */

const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function id(n: number): string {
  return `019f0000-0000-7000-8000-0000000001${String(n).padStart(2, "0")}`;
}

function task(
  n: number,
  status: string,
  title: string,
  due_at: string | null = null,
): WorkItemRecord {
  return { kind: "task", id: id(n), title, status, due_at, version: 1 };
}

// Due dates in 2099 so the order never drifts with the clock.
const late = task(1, "todo", "Betala skatten", "2099-01-20");
const early = task(2, "todo", "Ring Anna", "2099-01-10");
const undated = task(3, "todo", "Beställ skåp");
const laterDoing = task(4, "in_progress", "Bygg webbplatsen", "2099-01-20");
const earlierDoing = task(5, "in_progress", "Boka målare", "2099-01-10");

/** A step of `early`, due before every Task: it still stands right after its Task (nestSteps). */
const stepOfEarly: WorkItemRecord = {
  kind: "step",
  id: id(6),
  title: "Steg i Ring Anna",
  status: "todo",
  due_at: "2099-01-05",
  version: 1,
  task_id: early.id,
};

/** To do is in the server's order `late, early, undated` (sorted by date: early, late, undated). In progress is
 *  `laterDoing, earlierDoing` and the user has ordered it (manually_ordered), so it keeps that order. */
const page: WorkBoardPage = {
  columns: {
    todo: [late, early, undated],
    in_progress: [laterDoing, earlierDoing],
  },
  next_cursor: null,
  manually_ordered: ["in_progress"],
};

function transport(overrides: Partial<WorkTransport> = {}): WorkTransport {
  return {
    updateTask: vi.fn(),
    getWorkBoard: vi.fn().mockResolvedValue(page),
    getTask: vi.fn(),
    reorderBoardColumn: vi.fn().mockResolvedValue({ items: [] }),
    ...overrides,
  } as unknown as WorkTransport;
}

/** The parent that owns the frame, as WorkView does: onChange replaces it. */
function Harness({
  work,
  initial,
}: {
  work: WorkTransport;
  initial: WorkBoardPage;
}) {
  const [frame, setFrame] = useState<WorkBoardFrame>({
    kind: "board",
    filters: {},
    page: initial,
  });
  return (
    <BoardView
      frame={frame}
      onChange={setFrame}
      transport={work}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      layout="single"
    />
  );
}

/** The titles of one section's rows, in the order they show. */
function titlesIn(sectionLabel: string): string[] {
  const section = screen.getByRole("region", { name: sectionLabel });
  return Array.from(
    section.querySelectorAll("li"),
    (row) =>
      row.querySelector("button:not(.work-card-done), .work-card-title")
        ?.textContent ?? "",
  );
}

/** The card's own list item, found by its title. */
function rowOf(title: string): HTMLElement {
  const row = screen.getByRole("button", { name: title }).closest("li");
  if (!row) throw new Error(`no row for ${title}`);
  return row;
}

describe("shownOrder: the order of a Status section on the phone", () => {
  const empty: WorkBoardPage = { columns: {}, next_cursor: null };

  it("sorts a section by due date, the overdue first, and leaves the undated last in the server's order", () => {
    const items = [undated, late, early, task(7, "todo", "Utan datum")];
    expect(shownOrder(empty, "todo", items).map((item) => item.title)).toEqual([
      "Ring Anna",
      "Betala skatten",
      "Beställ skåp",
      "Utan datum",
    ]);
  });

  it("keeps the server's order among Tasks with the same due date", () => {
    const first = task(8, "todo", "Först", "2099-01-10");
    const second = task(9, "todo", "Sedan", "2099-01-10");
    expect(
      shownOrder(empty, "todo", [second, first]).map((item) => item.title),
    ).toEqual(["Sedan", "Först"]);
  });

  it("keeps the server's order for a status the user has ordered", () => {
    const ordered: WorkBoardPage = {
      ...empty,
      manually_ordered: ["in_progress"],
    };
    expect(
      shownOrder(ordered, "in_progress", [laterDoing, earlierDoing]),
    ).toEqual([laterDoing, earlierDoing]);
    // Another status in the same page is still sorted.
    expect(shownOrder(ordered, "todo", [late, early])).toEqual([early, late]);
  });

  it("reads a page without manually_ordered as no ordered status, so every section is sorted", () => {
    expect(
      shownOrder(empty, "in_progress", [laterDoing, earlierDoing]),
    ).toEqual([earlierDoing, laterDoing]);
  });

  it("does not change the list it is given", () => {
    const items = [late, early, undated];
    shownOrder(empty, "todo", items);
    expect(items).toEqual([late, early, undated]);
  });
});

describe("appendBoardPage keeps the later page's fields", () => {
  it("takes manually_ordered and the cursor from the later page, and adds its records once", () => {
    const shown: WorkBoardPage = {
      columns: { todo: [late] },
      next_cursor: "cursor-2",
    };
    const later: WorkBoardPage = {
      columns: { todo: [late, early] },
      next_cursor: null,
      manually_ordered: ["todo"],
    };
    const merged = appendBoardPage(shown, later);
    expect(merged.columns.todo).toEqual([late, early]);
    expect(merged.next_cursor).toBeNull();
    expect(merged.manually_ordered).toEqual(["todo"]);
  });
});

describe("the phone's Status list in due-date order", () => {
  it("sorts an unordered section by due date and keeps an ordered section in the server's order", () => {
    render(<Harness work={transport()} initial={page} />);
    expect(titlesIn(workEn.taskStatus.todo)).toEqual([
      early.title,
      late.title,
      undated.title,
    ]);
    expect(titlesIn(workEn.taskStatus.in_progress)).toEqual([
      laterDoing.title,
      earlierDoing.title,
    ]);
  });

  it("Flytta ned in a date-sorted section writes the order shown, with the row moved one step", async () => {
    const user = userEvent.setup();
    const reorderBoardColumn = vi.fn().mockResolvedValue({ items: [] });
    // The server marks the column as ordered by the user once it is written, so the background read after the write
    // returns the page with "todo" in manually_ordered (backend: work_board_manual_statuses).
    const afterWrite: WorkBoardPage = {
      columns: {
        todo: [late, early, undated],
        in_progress: [laterDoing, earlierDoing],
      },
      next_cursor: null,
      manually_ordered: ["in_progress", "todo"],
    };
    const getWorkBoard = vi.fn().mockResolvedValue(afterWrite);
    render(
      <Harness
        work={transport({ reorderBoardColumn, getWorkBoard })}
        initial={page}
      />,
    );
    // Shown: early, late, undated. Moving early down one step gives late, early, undated. The server's order
    // (late, early, undated) moved early down would give late, undated, early, so the test tells them apart.
    fireEvent.contextMenu(rowOf(early.title));
    const group = screen.getByRole("group", {
      name: workEn.moveListFor(early.title),
    });
    await user.click(
      within(group).getByRole("button", { name: workEn.moveDown }),
    );
    expect(reorderBoardColumn).toHaveBeenCalledWith(
      "todo",
      [
        { taskId: late.id, version: 1 },
        { taskId: early.id, version: 1 },
        { taskId: undated.id, version: 1 },
      ],
      expect.stringMatching(KEY),
    );
    // The answer makes the column the user's order: it stays where it was moved.
    await waitFor(() =>
      expect(titlesIn(workEn.taskStatus.todo)).toEqual([
        late.title,
        early.title,
        undated.title,
      ]),
    );
  });

  it("lists a step right after its Task in a date-sorted section, though the step is due first", () => {
    render(
      <Harness
        work={transport()}
        initial={{
          columns: { todo: [late, early, undated, stepOfEarly] },
          next_cursor: null,
        }}
      />,
    );
    expect(titlesIn(workEn.taskStatus.todo)).toEqual([
      early.title,
      stepOfEarly.title,
      late.title,
      undated.title,
    ]);
  });
});

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { boardLabelsEn } from "@/features/work-app/board/board-labels";
import {
  columnMore,
  unshownIn,
  withTaskMoved,
} from "@/features/work-app/board/board-columns";
import { rootFromToolResult } from "@/features/work-app/transport/transport";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkBoardFrame,
  WorkBoardPage,
  WorkTask,
} from "@/features/work-app/transport/transport";
import {
  Harness,
  a,
  b,
  c,
  d,
  project,
  task,
  transport,
} from "@tests/helpers/board-phone-fixtures";

// The board's column headings count the server's totals (column_totals), and "Show more" stands only under a column
// that holds more than it shows. Simulated-host tests (the board with a fake transport), not a real host.

const totalsPage: WorkBoardPage = {
  columns: {
    todo: [a, b],
    in_progress: [c],
    blocked: [],
    completed: [d],
    active: [project],
  },
  next_cursor: "board-2",
  column_totals: {
    todo: 7,
    in_progress: 1,
    blocked: 0,
    completed: 3,
    active: 1,
  },
};

const frameOf = (page: WorkBoardPage): WorkBoardFrame => ({
  kind: "board",
  filters: {},
  page,
});
const region = (name: string) => screen.getByRole("region", { name });
const heading = (name: string) =>
  within(region(name)).getByRole("heading").textContent;

describe.each(["columns", "single"] as const)(
  "Column totals (%s layout)",
  (layout) => {
    it("counts the server's total in each heading and offers more only where the total is larger", () => {
      render(
        <Harness
          work={transport()}
          layout={layout}
          initial={frameOf(totalsPage)}
        />,
      );
      expect(heading(workEn.taskStatus.todo)).toContain("(7)");
      expect(heading(workEn.taskStatus.in_progress)).toContain("(1)");
      expect(
        within(region(workEn.taskStatus.todo)).getByRole("button", {
          name: boardLabelsEn.showMoreIn(workEn.taskStatus.todo),
        }),
      ).toBeInTheDocument();
      // In progress shows all of its one record; Projects all of its one.
      expect(
        screen.queryByRole("button", {
          name: boardLabelsEn.showMoreIn(workEn.taskStatus.in_progress),
        }),
      ).toBeNull();
      expect(
        screen.queryByRole("button", { name: boardLabelsEn.showMoreAll }),
      ).toBeNull();
      // An empty Blocked (0) offers nothing to read.
      expect(
        screen.queryByRole("button", {
          name: boardLabelsEn.showMoreIn(workEn.taskStatus.blocked),
        }),
      ).toBeNull();
      if (layout === "columns")
        expect(heading(workEn.taskStatus.blocked)).toContain("(0)");
      else
        expect(
          screen.queryByRole("region", { name: workEn.taskStatus.blocked }),
        ).toBeNull();
    });

    it("counts what it has read when the server sends no totals (an older server)", () => {
      const older = { ...totalsPage, column_totals: undefined };
      render(
        <Harness work={transport()} layout={layout} initial={frameOf(older)} />,
      );
      expect(heading(workEn.taskStatus.todo)).toContain("(2)");
      expect(
        screen.getAllByRole("button", { name: /^Show more/ }).length,
      ).toBeGreaterThan(1);
    });
  },
);

it("drops the button once the column's read brings every record, and the heading keeps the total", async () => {
  const user = userEvent.setup();
  const rest = [3, 4, 5, 6, 7].map((n) => task(n + 10, "todo", `Uppgift ${n}`));
  const getWorkBoard = vi.fn().mockResolvedValue({
    columns: { todo: [a, b, ...rest] },
    next_cursor: null,
  });
  render(
    <Harness
      work={transport({ getWorkBoard })}
      layout="columns"
      initial={frameOf(totalsPage)}
    />,
  );
  await user.click(
    screen.getByRole("button", {
      name: boardLabelsEn.showMoreIn(workEn.taskStatus.todo),
    }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("button", {
        name: boardLabelsEn.showMoreIn(workEn.taskStatus.todo),
      }),
    ).toBeNull(),
  );
  expect(
    within(region(workEn.taskStatus.todo)).getByRole("button", {
      name: "Uppgift 7",
    }),
  ).toBeInTheDocument();
  expect(heading(workEn.taskStatus.todo)).toContain("(7)");
});

describe("unshownIn and columnMore with totals", () => {
  it("counts a Task status column's unread records, and the Projects segment's in the other columns", () => {
    expect(unshownIn(totalsPage, "todo")).toBe(5);
    expect(unshownIn(totalsPage, "blocked")).toBe(0);
    expect(unshownIn(totalsPage, "project")).toBe(0);
    expect(
      unshownIn(
        { ...totalsPage, column_totals: { todo: 2, active: 4 } },
        "project",
      ),
    ).toBe(3);
    const older = { ...totalsPage, column_totals: undefined };
    expect(unshownIn(older, "todo")).toBe(0);
  });

  it("offers more only for a column with unread records", () => {
    const frame = frameOf(totalsPage);
    expect(columnMore(frame, "todo")).toBe("status");
    expect(columnMore(frame, "in_progress")).toBeUndefined();
    expect(columnMore(frame, "blocked")).toBeUndefined();
    expect(columnMore(frame, "project")).toBeUndefined();
  });

  it("moves one count with a Task that changes column, so the heading and the button stay right before the next read", () => {
    const done = {
      id: a.id,
      title: a.title,
      status: "completed",
      due_at: null,
      version: 2,
    } as WorkTask;
    const moved = withTaskMoved(totalsPage, done);
    expect(moved?.column_totals).toMatchObject({ todo: 6, completed: 4 });
    expect(unshownIn(moved!, "todo")).toBe(5);
    expect(unshownIn(moved!, "completed")).toBe(2);
  });
});

it("keeps the totals of a get_work_board result, and none that are not counts", () => {
  const base = { columns: { todo: [a] }, next_cursor: null };
  const root = rootFromToolResult({
    ...base,
    column_totals: { todo: 4, blocked: 0 },
  });
  expect(root?.kind === "board" && root.page.column_totals).toEqual({
    todo: 4,
    blocked: 0,
  });
  const bad = rootFromToolResult({ ...base, column_totals: { todo: "4" } });
  expect(bad?.kind === "board" && bad.page.column_totals).toBeUndefined();
});

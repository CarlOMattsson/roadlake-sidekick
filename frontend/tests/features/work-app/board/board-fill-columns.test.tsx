import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { boardLabelsEn } from "@/features/work-app/board/board-labels";
import {
  columnsToFill,
  withColumnsRead,
} from "@/features/work-app/board/board-columns";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkBoardFrame,
  WorkBoardPage,
  WorkFilters,
  WorkItemRecord,
} from "@/features/work-app/transport/transport";
import { Harness, transport } from "@tests/helpers/board-phone-fixtures";
import { chooseColumn, tabNames } from "./column-tabs";

// A column the server counts records in is never drawn empty: when the board's first page is filled by one long column,
// the others read their own first page. Simulated-host tests (the board with a fake transport), not a real host.

const row = (n: number, status: string, title: string): WorkItemRecord => ({
  kind: "task",
  id: `019f0000-0000-7000-8000-${String(n).padStart(12, "0")}`,
  title,
  status,
  due_at: null,
  version: 1,
});
const todos = Array.from({ length: 25 }, (_, n) =>
  row(100 + n, "todo", `Att göra ${n}`),
);
const doing = row(1, "in_progress", "Pågående sak");
const blocked = row(2, "blocked", "Blockerad sak");
const done = [3, 4, 5].map((n) => row(n, "completed", `Klar sak ${n}`));
const firstDone = done[0] as WorkItemRecord;

const totals = { todo: 40, in_progress: 1, blocked: 1, completed: 3 };
const crowded: WorkBoardPage = {
  columns: { todo: todos, in_progress: [], blocked: [], completed: [] },
  next_cursor: "board-2",
  column_totals: totals,
};
const frameOf = (page: WorkBoardPage = crowded): WorkBoardFrame => ({
  kind: "board",
  filters: {},
  page,
});
const region = (name: string) => screen.getByRole("region", { name });
const statusOf = (filters: WorkFilters = {}) =>
  typeof filters.status === "string" ? filters.status : "";

/** The server: the board's first page is the crowded one; a status read answers with that status's records. */
function server() {
  const byStatus: Record<string, WorkItemRecord[]> = {
    in_progress: [doing],
    blocked: [blocked],
    completed: done,
  };
  return vi.fn((filters: WorkFilters = {}): Promise<WorkBoardPage> => {
    const status = statusOf(filters);
    if (!status) return Promise.resolve(crowded);
    return Promise.resolve({
      columns: { [status]: byStatus[status] ?? [] },
      next_cursor: null,
    });
  });
}
/** The single layout shows one column at a time: choose it. The columns layout shows all of them. */
async function show(
  user: ReturnType<typeof userEvent.setup>,
  layout: "columns" | "single",
  status: keyof typeof workEn.taskStatus,
) {
  if (layout === "single") await chooseColumn(user, workEn.taskStatus[status]);
}
const moreIn = (status: "in_progress" | "blocked" | "completed") =>
  boardLabelsEn.showMoreIn(workEn.taskStatus[status]);

describe.each(["columns", "single"] as const)(
  "A column with records is never empty (%s layout)",
  (layout) => {
    it("reads the empty columns' first pages once on mount, without the loading line", async () => {
      const user = userEvent.setup();
      const getWorkBoard = server();
      render(
        <Harness
          work={transport({ getWorkBoard })}
          layout={layout}
          initial={frameOf()}
        />,
      );
      expect(screen.queryByText(workEn.loading)).toBeNull();
      await show(user, layout, "in_progress");
      expect(
        await within(region(workEn.taskStatus.in_progress)).findByText(
          doing.title,
        ),
      ).toBeInTheDocument();
      expect(
        within(region(workEn.taskStatus.in_progress)).queryByRole("button", {
          name: moreIn("in_progress"),
        }),
      ).toBeNull();
      // Blocked is reached with its tab (single), and its row is there without any press of Show more.
      await show(user, layout, "blocked");
      expect(
        await within(region(workEn.taskStatus.blocked)).findByText(
          blocked.title,
        ),
      ).toBeInTheDocument();
      expect(
        within(region(workEn.taskStatus.blocked)).queryByRole("button", {
          name: moreIn("blocked"),
        }),
      ).toBeNull();
      if (layout === "single")
        expect(tabNames(boardLabelsEn.columnTabs)).toEqual([
          `${workEn.taskStatus.todo} 40`,
          `${workEn.taskStatus.in_progress} 1`,
          `${workEn.taskStatus.blocked} 1`,
          `${workEn.taskStatus.completed} 3`,
        ]);
      // Three status reads, once: the board's own first page came with the frame.
      expect(getWorkBoard).toHaveBeenCalledTimes(3);
      expect(getWorkBoard).toHaveBeenCalledWith({ status: "in_progress" });
    });

    it("reads them again after Refresh, before the page is shown", async () => {
      const user = userEvent.setup();
      const getWorkBoard = server();
      render(
        <Harness
          work={transport({ getWorkBoard })}
          layout={layout}
          initial={frameOf({
            ...crowded,
            columns: {
              ...crowded.columns,
              in_progress: [doing],
              blocked: [blocked],
              completed: done,
            },
          })}
        />,
      );
      // Everything is shown, so nothing is read on mount.
      expect(getWorkBoard).not.toHaveBeenCalled();
      await user.click(screen.getByRole("button", { name: workEn.refresh }));
      await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(4));
      await show(user, layout, "in_progress");
      expect(
        await within(region(workEn.taskStatus.in_progress)).findByText(
          doing.title,
        ),
      ).toBeInTheDocument();
      await show(user, layout, "blocked");
      expect(
        within(region(workEn.taskStatus.blocked)).getByText(blocked.title),
      ).toBeInTheDocument();
      await show(user, layout, "in_progress");
      expect(
        within(region(workEn.taskStatus.in_progress)).queryByRole("button", {
          name: moreIn("in_progress"),
        }),
      ).toBeNull();
    });
  },
);

describe("Filling empty columns", () => {
  it("does not read again when a column read answers with nothing", async () => {
    const getWorkBoard = vi.fn(
      (filters: WorkFilters = {}): Promise<WorkBoardPage> =>
        Promise.resolve(
          statusOf(filters) ? { columns: {}, next_cursor: null } : crowded,
        ),
    );
    const onChange = vi.fn();
    render(
      <Harness
        work={transport({ getWorkBoard })}
        layout="columns"
        initial={frameOf()}
        onChange={onChange}
      />,
    );
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const last = onChange.mock.calls.at(-1)?.[0] as WorkBoardFrame;
    expect(last.columnCursors).toEqual({
      in_progress: null,
      blocked: null,
      completed: null,
    });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(getWorkBoard).toHaveBeenCalledTimes(3);
  });

  it("keeps the column's next cursor so Show more goes on from it", async () => {
    const onChange = vi.fn();
    const getWorkBoard = vi.fn(
      (filters: WorkFilters = {}): Promise<WorkBoardPage> => {
        if (statusOf(filters) === "completed")
          return Promise.resolve({
            columns: { completed: [firstDone] },
            next_cursor: "completed-2",
          });
        return Promise.resolve(
          statusOf(filters) ? { columns: {}, next_cursor: null } : crowded,
        );
      },
    );
    render(
      <Harness
        work={transport({ getWorkBoard })}
        layout="columns"
        initial={frameOf()}
        onChange={onChange}
      />,
    );
    await within(region(workEn.taskStatus.completed)).findByText(
      firstDone.title,
    );
    const last = onChange.mock.calls.at(-1)?.[0] as WorkBoardFrame;
    expect(last.columnCursors?.completed).toBe("completed-2");
    expect(
      within(region(workEn.taskStatus.completed)).getByRole("button", {
        name: boardLabelsEn.showMoreCountIn(2, workEn.taskStatus.completed),
      }),
    ).toBeInTheDocument();
  });
});

describe("columnsToFill", () => {
  it("names the Task columns with a total and no record on the page", () => {
    expect(columnsToFill(frameOf())).toEqual([
      "in_progress",
      "blocked",
      "completed",
    ]);
  });

  it("names nothing without totals, with a zero total, or for a column whose own read ended", () => {
    expect(
      columnsToFill(frameOf({ ...crowded, column_totals: undefined })),
    ).toEqual([]);
    expect(
      columnsToFill(
        frameOf({ ...crowded, column_totals: { ...totals, in_progress: 0 } }),
      ),
    ).not.toContain("in_progress");
    expect(
      columnsToFill({ ...frameOf(), columnCursors: { blocked: null } }),
    ).toEqual(["in_progress", "completed"]);
  });

  it("looks only at the filtered status on a board filtered to one", () => {
    expect(
      columnsToFill({
        ...frameOf({ ...crowded, columns: { todo: [] } }),
        filters: { status: "blocked" },
      }),
    ).toEqual(["blocked"]);
  });
});

describe("withColumnsRead", () => {
  it("merges the pages and sets each column's cursor (null when whole)", () => {
    const next = withColumnsRead(frameOf(), [
      {
        status: "blocked",
        page: { columns: { blocked: [blocked] }, next_cursor: null },
      },
      {
        status: "completed",
        page: { columns: { completed: done }, next_cursor: "c2" },
      },
    ]);
    expect(next.page.columns.blocked).toEqual([blocked]);
    expect(next.page.next_cursor).toBe("board-2");
    expect(next.columnCursors).toEqual({ blocked: null, completed: "c2" });
  });
});

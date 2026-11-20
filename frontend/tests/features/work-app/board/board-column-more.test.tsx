import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  boardLabelsEn,
  boardLabelsSv,
} from "@/features/work-app/board/board-labels";
import {
  columnMore,
  withBoardRead,
  withColumnPage,
} from "@/features/work-app/board/board-columns";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkBoardFrame,
  WorkBoardPage,
  WorkItemRecord,
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
import { chooseColumn } from "./column-tabs";

// "Show more" under each status column of the board, with a fake transport standing in for the host. These are
// simulated-host tests (the board with a fake transport), not tests in a real Claude or Android host.

const e = task(5, "todo", "Boka möte med revisorn");
const f = task(6, "todo", "Beställ nya kontorsstolar");
const g = task(7, "in_progress", "Granska avtalet");
const project2: WorkItemRecord = {
  ...project,
  id: "019f0000-0000-7000-8000-0000000000f2",
  title: "Trädgården",
};

/** A board page with more to read: every status column and the Projects column hold a card or are empty. */
const morePage: WorkBoardPage = {
  columns: {
    todo: [a, b],
    in_progress: [c],
    blocked: [],
    completed: [d],
    active: [project],
  },
  next_cursor: "board-2",
};

function frameOf(
  page: WorkBoardPage = morePage,
  filters: WorkBoardFrame["filters"] = {},
): WorkBoardFrame {
  return { kind: "board", filters, page };
}

const moreIn = (column: string) => boardLabelsEn.showMoreIn(column);
const region = (name: string) => screen.getByRole("region", { name });

/** The page a column read answers with: only the given records, in their columns. */
function answer(
  columns: Record<string, WorkItemRecord[]>,
  next_cursor: string | null,
): WorkBoardPage {
  return { columns, next_cursor };
}

describe("Show more in the columns layout", () => {
  it("gives every status column its own button, last in its region, and none outside the columns", () => {
    render(<Harness work={transport()} layout="columns" initial={frameOf()} />);
    const regions = screen.getAllByRole("region");
    expect(
      regions.map((section) => section.getAttribute("aria-label")),
    ).toEqual([
      workEn.taskStatus.todo,
      workEn.taskStatus.in_progress,
      workEn.taskStatus.blocked,
      workEn.taskStatus.completed,
      workEn.projects,
    ]);
    const all = screen.getAllByRole("button", { name: /^Show more/ });
    expect(all).toHaveLength(5);
    for (const button of all)
      expect(button.closest("section[aria-label]")).not.toBeNull();

    for (const status of [
      "todo",
      "in_progress",
      "blocked",
      "completed",
    ] as const) {
      const section = region(workEn.taskStatus[status]);
      const button = within(section).getByRole("button", {
        name: moreIn(workEn.taskStatus[status]),
      });
      expect(button).toHaveTextContent(boardLabelsEn.showMore);
      // Directly in its column and last in it, after the column's list of cards.
      expect(button.parentElement).toBe(section);
      expect(section.lastElementChild).toBe(button);
      const list = section.querySelector("ul.work-list");
      if (list)
        expect(
          list.compareDocumentPosition(button) &
            Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
    }
    // The Projects column reads the board's next page, so its button names no status.
    const projects = within(region(workEn.projects)).getByRole("button", {
      name: boardLabelsEn.showMoreAll,
    });
    expect(projects).toHaveTextContent(boardLabelsEn.showMoreAll);
    expect(region(workEn.projects).lastElementChild).toBe(projects);
    // An empty column with more to read shows its button instead of "Nothing here."
    expect(region(workEn.taskStatus.blocked)).not.toHaveTextContent(
      boardLabelsEn.noCards,
    );
  });

  it("comes after the column's last card in document order", () => {
    render(<Harness work={transport()} layout="columns" initial={frameOf()} />);
    const todo = region(workEn.taskStatus.todo);
    const last = within(todo).getAllByRole("listitem").at(-1) as HTMLElement;
    const button = within(todo).getByRole("button", {
      name: moreIn(workEn.taskStatus.todo),
    });
    expect(
      last.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows no button on a board that has no next page", () => {
    render(
      <Harness
        work={transport()}
        layout="columns"
        initial={frameOf({ ...morePage, next_cursor: null })}
      />,
    );
    expect(screen.queryByRole("button", { name: /^Show more/ })).toBeNull();
    expect(region(workEn.taskStatus.blocked)).toHaveTextContent(
      boardLabelsEn.noCards,
    );
  });

  it("reads one column with its status, adds the new card there, drops that button and moves focus to the card", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi.fn().mockResolvedValue(answer({ todo: [e] }, null));
    const work = transport({ getWorkBoard });
    render(<Harness work={work} layout="columns" initial={frameOf()} />);
    await user.click(
      within(region(workEn.taskStatus.todo)).getByRole("button", {
        name: moreIn(workEn.taskStatus.todo),
      }),
    );
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
    expect(getWorkBoard).toHaveBeenCalledWith({ status: "todo" }, undefined);

    const added = await within(region(workEn.taskStatus.todo)).findByText(
      e.title,
    );
    // The records already shown stay, and the new one joined its own column.
    expect(
      within(region(workEn.taskStatus.todo)).getByText(a.title),
    ).toBeInTheDocument();
    expect(
      within(region(workEn.taskStatus.in_progress)).queryByText(e.title),
    ).toBeNull();
    // The column is whole: its button is gone, the other columns keep theirs.
    expect(
      within(region(workEn.taskStatus.todo)).queryByRole("button", {
        name: /^Show more/,
      }),
    ).toBeNull();
    for (const status of ["in_progress", "blocked", "completed"] as const)
      expect(
        within(region(workEn.taskStatus[status])).getByRole("button", {
          name: moreIn(workEn.taskStatus[status]),
        }),
      ).toBeInTheDocument();
    await waitFor(() => {
      const card = added.closest("[data-card-id]") as HTMLElement;
      expect(card).toContainElement(document.activeElement as HTMLElement);
    });
  });

  it("keeps the button while the column has a next page, and the next click uses that cursor", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi
      .fn()
      .mockResolvedValueOnce(answer({ todo: [e] }, "todo-2"))
      .mockResolvedValueOnce(answer({ todo: [f] }, null));
    const work = transport({ getWorkBoard });
    render(<Harness work={work} layout="columns" initial={frameOf()} />);
    const button = () =>
      within(region(workEn.taskStatus.todo)).getByRole("button", {
        name: moreIn(workEn.taskStatus.todo),
      });
    await user.click(button());
    await within(region(workEn.taskStatus.todo)).findByText(e.title);
    expect(getWorkBoard).toHaveBeenLastCalledWith(
      { status: "todo" },
      undefined,
    );
    // Not whole yet: the button stays, and focus has not been taken from the user.
    expect(button()).toBeEnabled();
    await user.click(button());
    await within(region(workEn.taskStatus.todo)).findByText(f.title);
    expect(getWorkBoard).toHaveBeenLastCalledWith({ status: "todo" }, "todo-2");
    expect(
      within(region(workEn.taskStatus.todo)).queryByRole("button", {
        name: /^Show more/,
      }),
    ).toBeNull();
  });

  it("reads on past a page of cards already shown, with the cursor that page returned, and leaves the board's own cursor", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi
      .fn()
      .mockResolvedValueOnce(answer({ todo: [a, b] }, "todo-2"))
      .mockResolvedValueOnce(answer({ todo: [e] }, null));
    const onChange = vi.fn();
    const work = transport({ getWorkBoard });
    render(
      <Harness
        work={work}
        layout="columns"
        initial={frameOf()}
        onChange={onChange}
      />,
    );
    await user.click(
      within(region(workEn.taskStatus.todo)).getByRole("button", {
        name: moreIn(workEn.taskStatus.todo),
      }),
    );
    await within(region(workEn.taskStatus.todo)).findByText(e.title);
    expect(getWorkBoard).toHaveBeenCalledTimes(2);
    expect(getWorkBoard).toHaveBeenNthCalledWith(
      1,
      { status: "todo" },
      undefined,
    );
    expect(getWorkBoard).toHaveBeenNthCalledWith(
      2,
      { status: "todo" },
      "todo-2",
    );
    // The repeated cards were not added twice.
    expect(
      within(region(workEn.taskStatus.todo)).getAllByText(a.title),
    ).toHaveLength(1);
    // The board's own cursor and the column's end are both kept on the frame.
    const last = onChange.mock.calls.at(-1)?.[0] as WorkBoardFrame;
    expect(last.page.next_cursor).toBe("board-2");
    expect(last.columnCursors).toEqual({ todo: null });
  });

  it("reads the board's next page from the Projects column and ends every button when the board is whole", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi
      .fn()
      .mockResolvedValue(answer({ active: [project2] }, null));
    const work = transport({ getWorkBoard });
    render(<Harness work={work} layout="columns" initial={frameOf()} />);
    await user.click(
      within(region(workEn.projects)).getByRole("button", {
        name: boardLabelsEn.showMoreAll,
      }),
    );
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
    expect(getWorkBoard).toHaveBeenCalledWith({}, "board-2");
    expect(
      await within(region(workEn.projects)).findByText(project2.title),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Show more/ })).toBeNull();
  });

  it("on a board filtered to one status, only that column has the button and it reads the board's next page", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi.fn().mockResolvedValue(answer({ todo: [e] }, null));
    const work = transport({ getWorkBoard });
    render(
      <Harness
        work={work}
        layout="columns"
        initial={frameOf(
          answer({ todo: [a, b], in_progress: [c] }, "board-2"),
          { status: "todo" },
        )}
      />,
    );
    const buttons = screen.getAllByRole("button", { name: /^Show more/ });
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveAccessibleName(moreIn(workEn.taskStatus.todo));
    expect(
      within(region(workEn.taskStatus.todo)).getByRole("button", {
        name: moreIn(workEn.taskStatus.todo),
      }),
    ).toBe(buttons[0]);
    await user.click(buttons[0] as HTMLElement);
    expect(getWorkBoard).toHaveBeenCalledWith({ status: "todo" }, "board-2");
    expect(
      await within(region(workEn.taskStatus.todo)).findByText(e.title),
    ).toBeInTheDocument();
  });

  it("starts every column at its top again after Refresh", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi
      .fn()
      // The first To do read: a new card, and a next page for the column.
      .mockResolvedValueOnce(answer({ todo: [e] }, "todo-2"))
      // Refresh reads the whole board, which still has more to read.
      .mockResolvedValueOnce(
        answer(
          { todo: [a, b, e], in_progress: [c], active: [project] },
          "board-3",
        ),
      )
      // The To do read after Refresh.
      .mockResolvedValueOnce(answer({ todo: [f] }, null));
    const work = transport({ getWorkBoard });
    render(<Harness work={work} layout="columns" initial={frameOf()} />);
    const button = () =>
      within(region(workEn.taskStatus.todo)).getByRole("button", {
        name: moreIn(workEn.taskStatus.todo),
      });
    await user.click(button());
    await within(region(workEn.taskStatus.todo)).findByText(e.title);
    await user.click(screen.getByRole("button", { name: workEn.refresh }));
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(2));
    expect(getWorkBoard).toHaveBeenNthCalledWith(2, {});
    await user.click(button());
    await within(region(workEn.taskStatus.todo)).findByText(f.title);
    expect(getWorkBoard).toHaveBeenNthCalledWith(
      3,
      { status: "todo" },
      undefined,
    );
  });

  it("keeps the column's own filters and search in its read", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi
      .fn()
      .mockResolvedValue(answer({ in_progress: [g] }, null));
    const work = transport({ getWorkBoard });
    render(
      <Harness
        work={work}
        layout="columns"
        initial={frameOf(morePage, { tags: ["lag"] })}
      />,
    );
    await user.click(
      within(region(workEn.taskStatus.in_progress)).getByRole("button", {
        name: moreIn(workEn.taskStatus.in_progress),
      }),
    );
    expect(getWorkBoard).toHaveBeenCalledWith(
      { tags: ["lag"], status: "in_progress" },
      undefined,
    );
    expect(
      await within(region(workEn.taskStatus.in_progress)).findByText(g.title),
    ).toBeInTheDocument();
  });

  it("disables the buttons while a read runs and shows a failure line when it fails", async () => {
    const user = userEvent.setup();
    let reject: (reason: Error) => void = () => undefined;
    const getWorkBoard = vi.fn().mockReturnValue(
      new Promise((_resolve, fail) => {
        reject = fail;
      }),
    );
    const work = transport({ getWorkBoard });
    render(<Harness work={work} layout="columns" initial={frameOf()} />);
    await user.click(
      within(region(workEn.taskStatus.todo)).getByRole("button", {
        name: moreIn(workEn.taskStatus.todo),
      }),
    );
    for (const button of screen.getAllByRole("button", { name: /^Show more/ }))
      expect(button).toBeDisabled();
    await act(() => Promise.resolve(reject(new Error("offline"))));
    expect(await screen.findByText(boardLabelsEn.moreFailed)).toBeVisible();
    // The column can be tried again.
    expect(
      within(region(workEn.taskStatus.todo)).getByRole("button", {
        name: moreIn(workEn.taskStatus.todo),
      }),
    ).toBeEnabled();
  });
});

describe("Show more in the single layout (a phone)", () => {
  it("puts the button last in the chosen section, also in a section with no card, Klar's included", async () => {
    const user = userEvent.setup();
    render(<Harness work={transport()} layout="single" initial={frameOf()} />);
    const names = ["todo", "in_progress", "blocked", "completed"] as const;
    for (const status of names) {
      await chooseColumn(user, workEn.taskStatus[status]);
      // Only the chosen column is drawn, so no other section's button stands on the page.
      expect(screen.getAllByRole("region")).toHaveLength(1);
      const section = region(workEn.taskStatus[status]);
      const button = within(section).getByRole("button", {
        name: moreIn(workEn.taskStatus[status]),
      });
      expect(section.lastElementChild).toBe(button);
      const list = section.querySelector("ul.work-list");
      if (list)
        expect(
          list.compareDocumentPosition(button) &
            Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
    }
    // The empty Blocked section exists only for its button (no "Nothing here" line beside it).
    await chooseColumn(user, workEn.taskStatus.blocked);
    expect(
      region(workEn.taskStatus.blocked).querySelector("ul.work-list"),
    ).toBeNull();
    expect(screen.queryByText(boardLabelsEn.noCards)).toBeNull();
    await chooseColumn(user, workEn.projects);
    expect(
      within(region(workEn.projects)).getByRole("button", {
        name: boardLabelsEn.showMoreAll,
      }),
    ).toBeInTheDocument();
    // No button stands in a foot outside the sections.
    for (const each of screen.getAllByRole("button", { name: /^Show more/ }))
      expect(each.closest("section[aria-label]")).not.toBeNull();
  });

  it("reads one column's records and places them in that section", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi
      .fn()
      .mockResolvedValue(answer({ in_progress: [g] }, null));
    const work = transport({ getWorkBoard });
    render(<Harness work={work} layout="single" initial={frameOf()} />);
    await chooseColumn(user, workEn.taskStatus.in_progress);
    await user.click(
      within(region(workEn.taskStatus.in_progress)).getByRole("button", {
        name: moreIn(workEn.taskStatus.in_progress),
      }),
    );
    expect(getWorkBoard).toHaveBeenCalledWith(
      { status: "in_progress" },
      undefined,
    );
    expect(
      await within(region(workEn.taskStatus.in_progress)).findByText(g.title),
    ).toBeInTheDocument();
    expect(
      within(region(workEn.taskStatus.in_progress)).queryByRole("button", {
        name: /^Show more/,
      }),
    ).toBeNull();
  });
});

describe("Show more in Swedish", () => {
  it("names each button after its column in Swedish and reads the same way", async () => {
    const user = userEvent.setup();
    const getWorkBoard = vi.fn().mockResolvedValue(answer({ todo: [e] }, null));
    const work = transport({ getWorkBoard });
    render(
      <Harness
        work={work}
        layout="columns"
        labels={workSv}
        initial={frameOf()}
      />,
    );
    const todo = screen.getByRole("region", { name: workSv.taskStatus.todo });
    const button = within(todo).getByRole("button", {
      name: boardLabelsSv.showMoreIn(workSv.taskStatus.todo),
    });
    expect(button).toHaveTextContent(boardLabelsSv.showMore);
    expect(
      within(screen.getByRole("region", { name: workSv.projects })).getByRole(
        "button",
        { name: boardLabelsSv.showMoreAll },
      ),
    ).toBeInTheDocument();
    await user.click(button);
    expect(getWorkBoard).toHaveBeenCalledWith({ status: "todo" }, undefined);
    expect(await within(todo).findByText(e.title)).toBeInTheDocument();
  });
});

describe("columnMore", () => {
  const frame = (
    over: Partial<WorkBoardFrame> & { next?: string | null } = {},
  ): WorkBoardFrame => ({
    kind: "board",
    filters: {},
    page: {
      columns: {},
      next_cursor: over.next === undefined ? "c" : over.next,
    },
    ...over,
  });

  it("is undefined when the board has no next page", () => {
    expect(columnMore(frame({ next: null }), "todo")).toBeUndefined();
    expect(columnMore(frame({ next: null }), "active")).toBeUndefined();
  });

  it("reads a Task status column by status and every other column through the board", () => {
    expect(columnMore(frame(), "todo")).toBe("status");
    expect(columnMore(frame(), "completed")).toBe("status");
    expect(columnMore(frame(), "active")).toBe("board");
    expect(columnMore(frame(), "project")).toBe("board");
  });

  it("treats an empty status filter as no filter", () => {
    expect(columnMore(frame({ filters: { status: "" } }), "todo")).toBe(
      "status",
    );
  });

  it("gives only the filtered status its button, through the board", () => {
    const filtered = frame({ filters: { status: "todo" } });
    expect(columnMore(filtered, "todo")).toBe("board");
    expect(columnMore(filtered, "in_progress")).toBeUndefined();
    // Another column's read cursor does not matter on a board filtered to one status.
    expect(
      columnMore({ ...filtered, columnCursors: { todo: null } }, "todo"),
    ).toBe("board");
  });

  it("ends a column whose own read has no next page, and no other", () => {
    const read = frame({ columnCursors: { todo: null, blocked: "b2" } });
    expect(columnMore(read, "todo")).toBeUndefined();
    expect(columnMore(read, "blocked")).toBe("status");
    expect(columnMore(read, "in_progress")).toBe("status");
  });
});

describe("withColumnPage", () => {
  const shown: WorkBoardPage = {
    columns: { todo: [a, b], in_progress: [c] },
    next_cursor: "board-2",
    manually_ordered: ["todo"],
  };

  it("adds the new records to their own columns and keeps the board's cursor and orders", () => {
    const { page, added } = withColumnPage(shown, {
      columns: { todo: [b, e], in_progress: [g] },
      next_cursor: "todo-2",
      manually_ordered: [],
    });
    expect(added).toBe(2);
    expect(page.columns.todo).toEqual([a, b, e]);
    expect(page.columns.in_progress).toEqual([c, g]);
    expect(page.next_cursor).toBe("board-2");
    expect(page.manually_ordered).toEqual(["todo"]);
  });

  it("counts nothing when the page only repeats shown records", () => {
    const { page, added } = withColumnPage(shown, {
      columns: { todo: [a, b] },
      next_cursor: null,
    });
    expect(added).toBe(0);
    expect(page.columns.todo).toEqual([a, b]);
  });

  it("does not add a record twice when it comes under another column", () => {
    const { added, page } = withColumnPage(shown, {
      columns: { blocked: [{ ...a, status: "blocked" }] },
      next_cursor: null,
    });
    expect(added).toBe(0);
    expect(page.columns.blocked ?? []).toEqual([]);
  });
});

describe("withBoardRead", () => {
  it("replaces the page and clears the columns' own read cursors", () => {
    const next = answer({ todo: [a] }, "board-9");
    const read = withBoardRead(
      { ...frameOf(), columnCursors: { todo: "t2", blocked: null } },
      next,
    );
    expect(read.page).toBe(next);
    expect(read.columnCursors).toBeUndefined();
    expect(read.filters).toEqual({});
  });
});

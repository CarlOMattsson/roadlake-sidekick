import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  boardLabelsEn,
  boardLabelsSv,
} from "@/features/work-app/board/board-labels";
import {
  COLUMN_VISIBLE,
  columnsToFill,
  windowCards,
} from "@/features/work-app/board/board-columns";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkBoardFrame,
  WorkBoardPage,
  WorkFilters,
  WorkItemRecord,
} from "@/features/work-app/transport/transport";
import { Harness, transport } from "@tests/helpers/board-phone-fixtures";
import { chooseColumn } from "./column-tabs";

// A column draws up to ten cards before a quiet "Show N more"; two cards never hide behind a button, and a card waiting on a
// Contact names them as the agenda does. Simulated-host tests (the board with a fake transport), not a real host.

const row = (
  n: number,
  status: string,
  extra: Partial<WorkItemRecord> = {},
): WorkItemRecord => ({
  kind: "task",
  id: `019f0000-0000-7000-8000-${String(n).padStart(12, "0")}`,
  title: `Uppgift ${n}`,
  status,
  due_at: null,
  version: 1,
  ...extra,
});
const many = (count: number, status = "todo", from = 100) =>
  Array.from({ length: count }, (_, n) => row(from + n, status));

const frameOf = (
  page: WorkBoardPage,
  filters: WorkFilters = {},
): WorkBoardFrame => ({ kind: "board", filters, page });
const region = (name: string) => screen.getByRole("region", { name });
const cardsIn = (label: string) =>
  within(region(label)).queryAllByRole("listitem");
const moreButtons = () =>
  screen.queryAllByRole("button", { name: /^Show (\d+ )?more/ });

describe.each(["columns", "single"] as const)(
  "A column's first ten cards (%s layout)",
  (layout) => {
    async function open(page: WorkBoardPage, work = transport()) {
      const user = userEvent.setup();
      render(<Harness work={work} layout={layout} initial={frameOf(page)} />);
      if (layout === "single") await chooseColumn(user, workEn.taskStatus.todo);
      return user;
    }

    it("draws two cards of a column whole, with no button", async () => {
      await open({
        columns: { todo: many(2), in_progress: [], blocked: [], completed: [] },
        next_cursor: null,
      });
      expect(cardsIn(workEn.taskStatus.todo)).toHaveLength(2);
      expect(moreButtons()).toHaveLength(0);
    });

    it("draws ten of twelve cards and offers the other two as `Show 2 more`", async () => {
      const user = await open({
        columns: { todo: many(12) },
        next_cursor: null,
      });
      const todo = workEn.taskStatus.todo;
      expect(cardsIn(todo)).toHaveLength(COLUMN_VISIBLE);
      const button = within(region(todo)).getByRole("button", {
        name: boardLabelsEn.showMoreCountIn(2, todo),
      });
      expect(button).toHaveTextContent(boardLabelsEn.showMoreCount(2));
      expect(button).toHaveTextContent("Show 2 more");
      // The column's own count still names all twelve.
      expect(within(region(todo)).getByRole("heading")).toHaveTextContent(
        "(12)",
      );
      await user.click(button);
      expect(cardsIn(todo)).toHaveLength(12);
      expect(moreButtons()).toHaveLength(0);
      // The first card that was held back takes focus, so the keys go on from there.
      await waitFor(() =>
        expect(document.activeElement?.closest("li")).toBe(cardsIn(todo)[10]),
      );
    });

    it("counts the cards held back and the records not read yet together, and reads on only once every card is drawn", async () => {
      const getWorkBoard = vi.fn().mockResolvedValue({
        columns: { todo: many(15, "todo", 200) },
        next_cursor: null,
      });
      const todo = workEn.taskStatus.todo;
      const user = await open(
        {
          columns: { todo: many(25) },
          next_cursor: "board-2",
          column_totals: { todo: 40 },
        },
        transport({ getWorkBoard }),
      );
      await user.click(
        within(region(todo)).getByRole("button", {
          name: boardLabelsEn.showMoreCountIn(30, todo),
        }),
      );
      // Pressing it draws the 25 that were read; nothing is read yet, and 15 are left.
      expect(cardsIn(todo)).toHaveLength(25);
      const calls = getWorkBoard.mock.calls.length;
      await user.click(
        within(region(todo)).getByRole("button", {
          name: boardLabelsEn.showMoreCountIn(15, todo),
        }),
      );
      await waitFor(() => expect(cardsIn(todo)).toHaveLength(40));
      expect(getWorkBoard.mock.calls.length).toBeGreaterThan(calls);
      expect(moreButtons()).toHaveLength(0);
    });
  },
);

describe("A column that holds more than the page shows", () => {
  it("reads its own first page, so two cards are never one card and a button (a card dragged into Pågår)", async () => {
    const moved = row(1, "in_progress", { title: "Boka plattsättare" });
    const other = row(2, "in_progress", { title: "Prata ihop sig" });
    const getWorkBoard = vi.fn((filters: WorkFilters = {}) => {
      const answer: WorkBoardPage = {
        columns:
          filters.status === "in_progress"
            ? { in_progress: [other, moved] }
            : {},
        next_cursor: null,
      };
      return Promise.resolve(answer);
    });
    render(
      <Harness
        work={transport({ getWorkBoard })}
        layout="columns"
        initial={frameOf({
          columns: { todo: many(25), in_progress: [moved] },
          next_cursor: "board-2",
          column_totals: { todo: 40, in_progress: 2 },
        })}
      />,
    );
    const label = workEn.taskStatus.in_progress;
    expect(
      await within(region(label)).findByRole("button", { name: other.title }),
    ).toBeInTheDocument();
    expect(cardsIn(label)).toHaveLength(2);
    expect(
      within(region(label)).queryByRole("button", {
        name: /^Show (\d+ )?more/,
      }),
    ).toBeNull();
  });

  it("is named for the status read when it shows fewer than ten of the records it holds", () => {
    const page: WorkBoardPage = {
      columns: { todo: many(25), in_progress: many(1, "in_progress", 300) },
      next_cursor: "board-2",
      column_totals: { todo: 40, in_progress: 2, blocked: 0, completed: 12 },
    };
    expect(columnsToFill(frameOf(page))).toEqual(["in_progress", "completed"]);
    expect(
      columnsToFill({ ...frameOf(page), columnCursors: { completed: null } }),
    ).toEqual(["in_progress"]);
  });
});

describe("windowCards", () => {
  const list = Array.from({ length: 13 }, (_, n) => n);
  it("holds back the cards after the first ten", () => {
    expect(windowCards(list, false, () => false)).toEqual({
      drawn: list.slice(0, 10),
      hidden: [10, 11, 12],
    });
  });
  it("keeps a pinned card (one that stands for its Ångra) and draws everything once expanded", () => {
    expect(windowCards(list, false, (n) => n === 12)).toEqual({
      drawn: [...list.slice(0, 10), 12],
      hidden: [10, 11],
    });
    expect(windowCards(list, true, () => false)).toEqual({
      drawn: list,
      hidden: [],
    });
  });
});

describe("The button's words", () => {
  it("says `Visa N till` in Swedish and `Show N more` in English", () => {
    expect(boardLabelsSv.showMoreCount(2)).toBe("Visa 2 till");
    expect(boardLabelsEn.showMoreCount(2)).toBe("Show 2 more");
    expect(boardLabelsSv.showMoreCountIn(2, "Pågår")).toContain("Visa 2 till");
    expect(boardLabelsEn.showMoreCountIn(2, "Done")).toContain("Show 2 more");
  });

  it("draws the Swedish words when the board is Swedish", () => {
    render(
      <Harness
        work={transport()}
        layout="columns"
        labels={workSv}
        initial={frameOf({ columns: { todo: many(12) }, next_cursor: null })}
      />,
    );
    expect(
      within(region(workSv.taskStatus.todo)).getByRole("button", {
        name: boardLabelsSv.showMoreCountIn(2, workSv.taskStatus.todo),
      }),
    ).toHaveTextContent("Visa 2 till");
  });

  it("keeps the number out when it is not known (an older server)", () => {
    render(
      <Harness
        work={transport()}
        layout="columns"
        initial={frameOf({ columns: { todo: many(25) }, next_cursor: "b-2" })}
      />,
    );
    expect(
      within(region(workEn.taskStatus.todo)).getByRole("button", {
        name: boardLabelsEn.showMoreIn(workEn.taskStatus.todo),
      }),
    ).toHaveTextContent(boardLabelsEn.showMore);
  });
});

describe("The waiting line of a card", () => {
  const waiting = (extra: Partial<WorkItemRecord> = {}) =>
    row(7, "in_progress", {
      title: "Svar från hyresgästen",
      waiting: true,
      waiting_since: "2026-11-11T09:00:00Z",
      waiting_on_contact_id: "c-1",
      ...extra,
    });
  const page = (card: WorkItemRecord): WorkBoardPage => ({
    columns: { todo: [], in_progress: [card] },
    next_cursor: null,
  });

  it("names the Contact the server names, as the agenda does", () => {
    render(
      <Harness
        work={transport()}
        layout="columns"
        initial={frameOf(
          page(waiting({ waiting_on_contact_name: "Erik Sjöstrand" })),
        )}
      />,
    );
    expect(
      screen.getByText(/^Waiting on Erik Sjöstrand since /),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Waiting on someone/)).toBeNull();
  });

  it("says someone when the server gives no name (no contacts:read)", () => {
    render(
      <Harness
        work={transport()}
        layout="columns"
        initial={frameOf(page(waiting()))}
      />,
    );
    expect(screen.getByText(/^Waiting on someone since /)).toBeInTheDocument();
  });
});

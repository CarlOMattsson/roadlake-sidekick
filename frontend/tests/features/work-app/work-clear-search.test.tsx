import { agendaLabelsEn } from "@/features/work-app/agenda/agenda-labels";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { workEn } from "@/features/work-app/shared/labels";
import { boardLabelsEn } from "@/features/work-app/board/board-labels";
import { WorkFullscreen } from "@/features/work-app/fullscreen/work-fullscreen";
import type {
  WorkAgendaPage,
  WorkBoardPage,
  WorkFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { workShellLabelsEn } from "@/features/work-app/shell/work-shell-labels";

const agendaItem: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Agenda-uppgift",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: null,
  agenda_group: "today",
};
const boardItem: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Board-uppgift",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: null,
};
const agendaPage: WorkAgendaPage = { items: [agendaItem], next_cursor: null };
const boardPage: WorkBoardPage = {
  columns: { todo: [boardItem] },
  next_cursor: null,
};

type Fake = {
  transport: WorkTransport;
  getWorkAgenda: Mock;
  getWorkBoard: Mock;
};

/** Only the reads the fullscreen shell makes on its first tab are faked; the rest stay absent. */
function fakeTransport(): Fake {
  const getWorkAgenda = vi.fn().mockResolvedValue(agendaPage);
  const getWorkBoard = vi.fn().mockResolvedValue(boardPage);
  return {
    transport: {
      getWorkAgenda,
      getWorkBoard,
      getWorkHierarchy: vi.fn().mockResolvedValue({
        kind: "hierarchy",
        nodes: [],
        truncated: false,
      }),
      listContacts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
      listUnsortedTasks: vi.fn().mockResolvedValue({
        items: [],
        next_cursor: null,
      }),
      listDomains: vi.fn().mockResolvedValue([]),
    } as unknown as WorkTransport,
    getWorkAgenda,
    getWorkBoard,
  };
}

function mount(initial: WorkFrame, transport: WorkTransport) {
  return render(
    <WorkFullscreen
      transport={transport}
      initial={initial}
      labels={workEn}
      shellLabels={workShellLabelsEn}
    />,
  );
}

/**
 * Makes the Status board measure `width` px: under 640 it is a phone (the single layout), where a search with no hit
 * shows the "Rensa sökningen" button; wider it is the columns layout. The ResizeObserver stub reports once when observation starts.
 */
function stubBoardWidth(width: number) {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      private readonly report: () => void;
      constructor(report: () => void) {
        this.report = report;
      }
      observe() {
        this.report();
      }
      disconnect() {}
      unobserve() {}
    },
  );
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: width,
    bottom: 0,
    width,
    height: 0,
    toJSON: () => ({}),
  } as DOMRect);
}

// These two tests mount the whole fullscreen shell and type into it, which is quick on an idle machine. Their own
// limit keeps a machine busy with other test files from turning that into a timeout.
const SLOW_TEST_MS = 60_000;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Rensa sökningen in the fullscreen Work app", () => {
  it(
    "empties the agenda search and closes it, so the rows come back",
    async () => {
      const user = userEvent.setup();
      mount(
        { kind: "agenda", filters: {}, page: agendaPage },
        fakeTransport().transport,
      );

      await user.click(
        await screen.findByRole("button", { name: "Search tasks" }),
      );
      await user.type(
        screen.getByRole("searchbox", { name: "Search tasks" }),
        "zzz",
      );
      expect(screen.queryByText("Agenda-uppgift")).not.toBeInTheDocument();

      await user.click(
        screen.getByRole("button", { name: agendaLabelsEn.clearSearch }),
      );
      // The search closes in a later render, not within the click itself, so wait for it instead of assuming it.
      await waitFor(() =>
        expect(
          screen.queryByRole("searchbox", { name: "Search tasks" }),
        ).not.toBeInTheDocument(),
      );
      expect(await screen.findByText("Agenda-uppgift")).toBeInTheDocument();
    },
    SLOW_TEST_MS,
  );

  it(
    "empties the Status search and closes it, so the board comes back",
    async () => {
      stubBoardWidth(400);
      const user = userEvent.setup();
      const fake = fakeTransport();
      mount({ kind: "board", filters: {}, page: boardPage }, fake.transport);

      await user.click(
        await screen.findByRole("button", { name: "Search tasks" }),
      );
      await user.type(
        screen.getByRole("searchbox", { name: "Search tasks" }),
        "zzz",
      );
      expect(screen.queryByText("Board-uppgift")).not.toBeInTheDocument();
      // After a rest the board reads the server with the text and, while it reads, replaces the "no hit" row (and its
      // button) with a loading line. A click that lands in that moment is lost, so wait until the read is done.
      await waitFor(() =>
        expect(fake.getWorkBoard).toHaveBeenCalledWith({ q: "zzz" }),
      );
      await waitFor(() => {
        expect(screen.queryByText(workEn.loading)).not.toBeInTheDocument();
        expect(
          screen.getByRole("button", { name: agendaLabelsEn.clearSearch }),
        ).toBeInTheDocument();
      });

      await user.click(
        screen.getByRole("button", { name: agendaLabelsEn.clearSearch }),
      );
      // The search closes in a later render, not within the click itself, so wait for it instead of assuming it.
      await waitFor(() =>
        expect(
          screen.queryByRole("searchbox", { name: "Search tasks" }),
        ).not.toBeInTheDocument(),
      );
      expect(await screen.findByText("Board-uppgift")).toBeInTheDocument();
    },
    SLOW_TEST_MS,
  );

  describe("the Status search reads the whole board", () => {
    const other: WorkItemRecord = {
      ...boardItem,
      id: "019f0000-0000-7000-8000-0000000000b2",
      title: "Köp mjölk",
    };
    const later: WorkItemRecord = {
      ...boardItem,
      id: "019f0000-0000-7000-8000-0000000000b3",
      title: "Boka tandläkare",
    };

    async function openSearch(user: ReturnType<typeof userEvent.setup>) {
      await user.click(
        await screen.findByRole("button", { name: "Search tasks" }),
      );
      return screen.getByRole("searchbox", { name: "Search tasks" });
    }

    it("holds the columns layout to the same cards as the phone layout", async () => {
      stubBoardWidth(1200);
      const user = userEvent.setup();
      const page: WorkBoardPage = {
        columns: { todo: [boardItem, other] },
        next_cursor: null,
      };
      const fake = fakeTransport();
      fake.getWorkBoard.mockResolvedValue(page);
      mount({ kind: "board", filters: {}, page }, fake.transport);

      await user.type(await openSearch(user), "mjölk");

      expect(screen.getByText("Köp mjölk")).toBeInTheDocument();
      expect(screen.queryByText("Board-uppgift")).not.toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /To do \(1\)/ }),
      ).toBeVisible();
    });

    it("holds the phone layout to the same cards as the columns layout", async () => {
      stubBoardWidth(400);
      const user = userEvent.setup();
      const page: WorkBoardPage = {
        columns: { todo: [boardItem, other] },
        next_cursor: null,
      };
      const fake = fakeTransport();
      fake.getWorkBoard.mockResolvedValue(page);
      mount({ kind: "board", filters: {}, page }, fake.transport);

      await user.type(await openSearch(user), "mjölk");

      expect(screen.getByText("Köp mjölk")).toBeInTheDocument();
      expect(screen.queryByText("Board-uppgift")).not.toBeInTheDocument();
    });

    it("finds a card on a page not loaded yet by reading the server with the text", async () => {
      const user = userEvent.setup();
      const first: WorkBoardPage = {
        columns: { todo: [boardItem] },
        next_cursor: "page-2",
      };
      const found: WorkBoardPage = {
        columns: { todo: [later] },
        next_cursor: null,
      };
      const fake = fakeTransport();
      fake.getWorkBoard.mockImplementation((filters: { q?: string }) =>
        Promise.resolve(filters.q ? found : first),
      );
      mount({ kind: "board", filters: {}, page: first }, fake.transport);

      await user.type(await openSearch(user), "tandläkare");

      expect(await screen.findByText("Boka tandläkare")).toBeInTheDocument();
      expect(screen.queryByText("Board-uppgift")).not.toBeInTheDocument();
      expect(screen.queryByText(/No tasks match/)).not.toBeInTheDocument();
      expect(fake.getWorkBoard).toHaveBeenLastCalledWith({ q: "tandläkare" });
    });

    it("says nothing matches only after the server answered, and starts over when the text is cleared", async () => {
      const user = userEvent.setup();
      const first: WorkBoardPage = {
        columns: { todo: [boardItem] },
        next_cursor: "page-2",
      };
      const none: WorkBoardPage = { columns: {}, next_cursor: null };
      const fake = fakeTransport();
      fake.getWorkBoard.mockImplementation((filters: { q?: string }) =>
        Promise.resolve(filters.q ? none : first),
      );
      mount({ kind: "board", filters: {}, page: first }, fake.transport);

      const box = await openSearch(user);
      await user.type(box, "zzz");
      expect(
        await screen.findByText(agendaLabelsEn.noMatch.replace("{q}", "zzz")),
      ).toBeInTheDocument();

      await user.clear(box);
      expect(await screen.findByText("Board-uppgift")).toBeInTheDocument();
      expect(fake.getWorkBoard).toHaveBeenLastCalledWith({});
    });

    it("keeps the text when it asks for the next page of a search", async () => {
      const user = userEvent.setup();
      const first: WorkBoardPage = {
        columns: { todo: [boardItem] },
        next_cursor: "page-2",
      };
      const hits: WorkBoardPage = {
        columns: { todo: [later] },
        next_cursor: "hits-2",
      };
      const fake = fakeTransport();
      fake.getWorkBoard.mockImplementation(
        (filters: { q?: string }, cursor?: string | null) =>
          Promise.resolve(
            cursor
              ? { columns: { todo: [other] }, next_cursor: null }
              : filters.q
                ? hits
                : first,
          ),
      );
      mount({ kind: "board", filters: {}, page: first }, fake.transport);

      await user.type(await openSearch(user), "k");
      await screen.findByText("Boka tandläkare");
      await user.click(
        screen.getByRole("button", { name: boardLabelsEn.showMore }),
      );

      expect(fake.getWorkBoard).toHaveBeenLastCalledWith({ q: "k" }, "hits-2");
      expect(await screen.findByText("Köp mjölk")).toBeInTheDocument();
    });
  });
});

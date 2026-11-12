import { describe, expect, it } from "vitest";
import {
  initialRefreshState,
  refreshReducer,
  type RefreshAction,
} from "@/features/work-app/fullscreen/parts/refresh-reducer";
import {
  initialToolsState,
  isOpenOver,
  toolsReducer,
  type ToolsAction,
} from "@/features/work-app/fullscreen/parts/tools-reducer";
import {
  filtersOf,
  isTabFrame,
  marking,
} from "@/features/work-app/fullscreen/parts/tab-data";
import type {
  WorkFrame,
  WorkTransport,
} from "@/features/work-app/transport/transport";

function tools(...actions: ToolsAction[]) {
  return actions.reduce(toolsReducer, initialToolsState);
}
function refresh(...actions: RefreshAction[]) {
  return actions.reduce(refreshReducer, initialRefreshState);
}

describe("tools reducer", () => {
  it("opening the new-Task field closes search and clears its text", () => {
    const state = tools(
      { type: "openSearch", tab: "board" },
      { type: "query", tab: "board", query: "milk" },
      { type: "openCreate", tab: "board" },
    );
    expect(state.createOpen.board).toBe(true);
    expect(state.searchOpen.board).toBe(false);
    expect(state.queries.board).toBe("");
  });

  it("opening search closes the new-Task field and asks for focus once per press", () => {
    const state = tools(
      { type: "openCreate", tab: "agenda" },
      { type: "openSearch", tab: "agenda" },
    );
    expect(state.createOpen.agenda).toBe(false);
    expect(state.searchOpen.agenda).toBe(true);
    expect(state.searchFocus).toBe(1);
    expect(
      toolsReducer(state, { type: "openSearch", tab: "agenda" }).searchFocus,
    ).toBe(2);
  });

  it("closing search clears the text; closing create leaves search alone", () => {
    const state = tools(
      { type: "openSearch", tab: "agenda" },
      { type: "query", tab: "agenda", query: "x" },
      { type: "closeSearch", tab: "agenda" },
    );
    expect(state.searchOpen.agenda).toBe(false);
    expect(state.queries.agenda).toBe("");
    const created = tools(
      { type: "openCreate", tab: "agenda" },
      { type: "closeCreate", tab: "agenda" },
    );
    expect(created.createOpen.agenda).toBe(false);
  });

  it("keeps each tab's tools apart", () => {
    const state = tools(
      { type: "openSearch", tab: "agenda" },
      { type: "query", tab: "agenda", query: "a" },
      { type: "openCreate", tab: "hierarchy" },
    );
    expect(state.searchOpen.agenda).toBe(true);
    expect(state.queries.agenda).toBe("a");
    expect(state.createOpen.agenda).toBe(false);
    expect(state.createOpen.hierarchy).toBe(true);
  });

  it("holds one open menu: the last tab to open it, none after it closes", () => {
    const open = tools(
      { type: "more", tab: "agenda", open: true },
      { type: "more", tab: "board", open: true },
    );
    expect(open.moreOpen).toBe("board");
    expect(
      toolsReducer(open, { type: "more", tab: "board", open: false }).moreOpen,
    ).toBeUndefined();
  });

  it("an opened saved view restarts the tab's view and sets its notice", () => {
    const state = tools(
      { type: "query", tab: "agenda", query: "x" },
      { type: "query", tab: "board", query: "y" },
      { type: "viewApplied", tab: "agenda", several: true },
      { type: "viewApplied", tab: "board", several: false },
      { type: "viewApplied", tab: "board", several: true },
    );
    expect(state.viewKeys).toEqual({ agenda: 1, board: 2 });
    expect(state.severalPriorities).toEqual({ agenda: true, board: true });
    // The agenda's text goes with the view; the board keeps its own.
    expect(state.queries).toEqual({ agenda: "", board: "y" });
  });

  it("tracks the stack depth and returns the same state when it does not change", () => {
    const state = tools({ type: "depth", tab: "board", depth: 2 });
    expect(isOpenOver(state, "board")).toBe(true);
    expect(isOpenOver(state, "agenda")).toBe(false);
    expect(toolsReducer(state, { type: "depth", tab: "board", depth: 2 })).toBe(
      state,
    );
    expect(
      isOpenOver(
        toolsReducer(state, { type: "depth", tab: "board", depth: 1 }),
        "board",
      ),
    ).toBe(false);
  });
});

describe("refresh reducer", () => {
  it("marks only the given tabs out of date", () => {
    const state = refresh({ type: "stale", tabs: ["board", "hierarchy"] });
    expect(state.stale).toEqual({ board: true, hierarchy: true });
    expect(refreshReducer(state, { type: "stale", tabs: [] })).toBe(state);
  });

  it("consuming clears the mark and bumps the tab only when it must read again", () => {
    const marked = refresh({ type: "stale", tabs: ["board"] });
    const read = refreshReducer(marked, {
      type: "consume",
      tab: "board",
      bump: true,
    });
    expect(read.stale.board).toBe(false);
    expect(read.bumps.board).toBe(1);
    const upToDate = refreshReducer(marked, {
      type: "consume",
      tab: "board",
      bump: false,
    });
    expect(upToDate.stale.board).toBe(false);
    expect(upToDate.bumps).toEqual({});
  });

  it("Refresh uses the agenda's tick, the board's tick and the Projects tab's key", () => {
    const state = refresh(
      { type: "refresh", tab: "agenda" },
      { type: "refresh", tab: "board" },
      { type: "refresh", tab: "board" },
      { type: "refresh", tab: "hierarchy" },
    );
    expect(state.agendaTick).toBe(1);
    expect(state.boardTick).toBe(2);
    expect(state.bumps).toEqual({ hierarchy: 1 });
  });
});

describe("tab data", () => {
  it("knows the three tab frames", () => {
    expect(isTabFrame({ kind: "board" } as unknown as WorkFrame)).toBe(true);
    expect(isTabFrame({ kind: "task", id: "1" } as WorkFrame)).toBe(false);
  });

  it("carries filters only for a ready agenda or board", () => {
    const filters = { priority: "high" };
    const frame = { kind: "agenda", filters, page: {} };
    expect(
      filtersOf({ status: "ready", frame } as unknown as Parameters<
        typeof filtersOf
      >[0]),
    ).toEqual(filters);
    expect(filtersOf({ status: "loading" })).toEqual({});
    expect(filtersOf(undefined)).toEqual({});
  });

  it("tells when a write is answered, and leaves reads alone", async () => {
    let wrote = 0;
    const transport = {
      getWorkAgenda: () => Promise.resolve("read"),
      createTask: () => Promise.resolve("made"),
    } as unknown as WorkTransport;
    const marked = marking(transport, () => (wrote += 1)) as unknown as {
      getWorkAgenda: () => Promise<string>;
      createTask: () => Promise<string>;
    };
    expect(await marked.getWorkAgenda()).toBe("read");
    expect(wrote).toBe(0);
    expect(await marked.createTask()).toBe("made");
    expect(wrote).toBe(1);
  });
});

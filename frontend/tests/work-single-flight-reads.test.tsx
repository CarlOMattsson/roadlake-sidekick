import { act, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAgendaBulk } from "@/features/work-app/agenda/parts/use-agenda-bulk";
import { useAgendaSession } from "@/features/work-app/agenda/parts/use-agenda-session";
import { useRowWrites } from "@/features/work-app/agenda/parts/use-row-writes";
import type { RowState } from "@/features/work-app/agenda/parts/use-row-state";
import { useBoardCore } from "@/features/work-app/board/parts/use-board-core";
import {
  useHierarchyMore,
  useHierarchyRefresh,
} from "@/features/work-app/hierarchy/use-hierarchy-feed";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkAgendaFrame,
  WorkBoardFrame,
  WorkHierarchyFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { UnsortedView } from "@/features/work-app/unsorted/unsorted-view";

import { deferred } from "./helpers/deferred";

const empty = { items: [], next_cursor: null };

/** Two triggers that reach the page before React re-renders, which a disabled button cannot stop. */
function twice(trigger: () => void) {
  act(() => {
    trigger();
    trigger();
  });
}

function asTransport(methods: object) {
  return methods as unknown as WorkTransport;
}

const overdueTask: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring banken",
  status: "todo",
  due_at: "2026-10-20T09:00:00",
  version: 3,
  agenda_group: "overdue",
};

describe("the agenda's reads and bulk writes", () => {
  const frame: WorkAgendaFrame = { kind: "agenda", filters: {}, page: empty };
  // The row state the guarded paths touch; a row write or a move-all reads it only after the guard let it through.
  const rows = {
    resetForRead: vi.fn(),
    latest: (item: WorkItemRecord) => item,
    isTriagedNow: () => false,
  } as unknown as RowState;

  function mountAgenda(transport: WorkTransport) {
    return renderHook(() => {
      const mounted = { current: true };
      const session = useAgendaSession({
        transport,
        frame,
        onChange: vi.fn(),
        rows,
        mounted,
        stale: false,
        refreshTick: undefined,
        refreshKey: undefined,
      });
      const bulk = useAgendaBulk({
        transport,
        filters: {},
        now: new Date("2026-10-28T08:00:00"),
        session,
        rows,
        mounted,
      });
      const writes = useRowWrites({
        transport,
        labels: workEn,
        now: new Date("2026-10-28T08:00:00"),
        session,
        rows,
        mounted,
        keepFocus: vi.fn(),
        closeMenu: vi.fn(),
      });
      return { session, bulk, writes };
    });
  }

  it("reads once for two rereads in one tick", () => {
    const answer = deferred<typeof empty>();
    const getWorkAgenda = vi.fn(() => answer.promise);
    const { result } = mountAgenda(asTransport({ getWorkAgenda }));

    twice(() => result.current.session.reread());

    expect(getWorkAgenda).toHaveBeenCalledTimes(1);
  });

  it("reads again after a failed read, with the next trigger", async () => {
    const getWorkAgenda = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(empty);
    const { result } = mountAgenda(asTransport({ getWorkAgenda }));

    await act(async () => {
      result.current.session.reread();
      await Promise.resolve();
    });
    expect(getWorkAgenda).toHaveBeenCalledTimes(1);
    act(() => result.current.session.reread());

    expect(getWorkAgenda).toHaveBeenCalledTimes(2);
  });

  it("moves all overdue once for two presses in one tick, and again after a failed move", async () => {
    const answer = deferred<{ count: number; tasks: [] }>();
    const rescheduleTasks = vi
      .fn()
      .mockReturnValueOnce(answer.promise)
      .mockResolvedValue({ count: 0, tasks: [] });
    const getWorkAgenda = vi.fn().mockResolvedValue(empty);
    const { result } = mountAgenda(
      asTransport({ rescheduleTasks, getWorkAgenda }),
    );

    await act(async () => {
      result.current.bulk.moveAllOverdue([overdueTask]);
      result.current.bulk.moveAllOverdue([overdueTask]);
      await Promise.resolve();
    });
    expect(rescheduleTasks).toHaveBeenCalledTimes(1);

    await act(async () => {
      answer.reject(new Error("offline"));
      await answer.promise.catch(() => undefined);
    });
    await act(async () => {
      result.current.bulk.moveAllOverdue([overdueTask]);
      await Promise.resolve();
    });
    expect(rescheduleTasks).toHaveBeenCalledTimes(2);
  });

  it("writes no row while a read runs, and accepts the write once the read failed", async () => {
    const answer = deferred<typeof empty>();
    const getWorkAgenda = vi.fn(() => answer.promise);
    const updateTask = vi.fn(() => new Promise<never>(() => undefined));
    const { result } = mountAgenda(asTransport({ getWorkAgenda, updateTask }));

    act(() => result.current.session.reread());
    await act(async () => {
      result.current.writes.write(overdueTask, "completed");
      await Promise.resolve();
    });
    expect(updateTask).not.toHaveBeenCalled();

    await act(async () => {
      answer.reject(new Error("offline"));
      await answer.promise.catch(() => undefined);
    });
    await act(async () => {
      result.current.writes.write(overdueTask, "completed");
      await Promise.resolve();
    });
    expect(updateTask).toHaveBeenCalledTimes(1);
  });
});

describe("the To sort view's reads", () => {
  function mountUnsorted(listUnsortedTasks: ReturnType<typeof vi.fn>) {
    const listDomains = vi.fn().mockResolvedValue([]);
    render(
      <UnsortedView
        transport={asTransport({ listUnsortedTasks, listDomains })}
        labels={workEn}
      />,
    );
    return listUnsortedTasks;
  }
  const refresh = () => screen.getByRole("button", { name: workEn.refresh });

  it("reads once for two presses on refresh in one tick", async () => {
    const list = mountUnsorted(vi.fn().mockResolvedValue(empty));
    await screen.findByText(workEn.unsortedEmpty);
    expect(list).toHaveBeenCalledTimes(1);
    const answer = deferred<typeof empty>();
    list.mockReturnValueOnce(answer.promise);

    twice(() => refresh().click());

    expect(list).toHaveBeenCalledTimes(2);
  });

  it("reads again after a failed read", async () => {
    const list = mountUnsorted(
      vi
        .fn()
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValue(empty),
    );
    await screen.findByRole("alert");
    expect(list).toHaveBeenCalledTimes(1);

    act(() => refresh().click());

    expect(list).toHaveBeenCalledTimes(2);
  });
});

describe("the Projects list's reads", () => {
  const hierarchy: WorkHierarchyFrame = {
    kind: "hierarchy",
    nodes: [],
    truncated: false,
    next_cursor: "page-2",
  };
  const page = { ...hierarchy, next_cursor: undefined };

  it("asks for one more page for two presses on Show more in one tick", () => {
    const answer = deferred<WorkHierarchyFrame>();
    const getWorkHierarchy = vi.fn(() => answer.promise);
    const { result } = renderHook(() =>
      useHierarchyMore({
        frame: hierarchy,
        transport: asTransport({ getWorkHierarchy }),
        onChange: vi.fn(),
        refreshKey: 1,
      }),
    );

    twice(() => result.current.loadMore());

    expect(getWorkHierarchy).toHaveBeenCalledTimes(1);
  });

  it("asks for the page again after a failed page", async () => {
    const getWorkHierarchy = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(page);
    const { result } = renderHook(() =>
      useHierarchyMore({
        frame: hierarchy,
        transport: asTransport({ getWorkHierarchy }),
        onChange: vi.fn(),
        refreshKey: 1,
      }),
    );

    await act(async () => {
      result.current.loadMore();
      await Promise.resolve();
    });
    expect(result.current.more).toBe("failed");
    act(() => result.current.loadMore());

    expect(getWorkHierarchy).toHaveBeenCalledTimes(2);
  });

  it("reads the list once while one read is on its way, then once more for the follow-up, also after a failed read", async () => {
    const first = deferred<WorkHierarchyFrame>();
    const getWorkHierarchy = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue(hierarchy);
    const { rerender } = renderHook(
      ({ refreshKey }) =>
        useHierarchyRefresh({
          frame: hierarchy,
          transport: asTransport({ getWorkHierarchy }),
          onChange: vi.fn(),
          stale: false,
          refreshKey,
        }),
      { initialProps: { refreshKey: 0 } },
    );

    act(() => rerender({ refreshKey: 1 }));
    act(() => rerender({ refreshKey: 2 }));
    expect(getWorkHierarchy).toHaveBeenCalledTimes(1);

    await act(async () => {
      first.reject(new Error("offline"));
      await first.promise.catch(() => undefined);
    });
    expect(getWorkHierarchy).toHaveBeenCalledTimes(2);
  });
});

describe("the board's reload", () => {
  const board: WorkBoardFrame = {
    kind: "board",
    filters: {},
    page: { columns: {}, next_cursor: null },
  };

  function mountBoard(getWorkBoard: ReturnType<typeof vi.fn>) {
    return renderHook(() =>
      useBoardCore({
        frame: board,
        onChange: vi.fn(),
        transport: asTransport({ getWorkBoard }),
        stale: false,
      }),
    );
  }

  it("reads once for two reloads in one tick", () => {
    const answer = deferred<typeof board.page>();
    const getWorkBoard = vi.fn(() => answer.promise);
    const { result } = mountBoard(getWorkBoard);

    twice(() => result.current.reload());

    expect(getWorkBoard).toHaveBeenCalledTimes(1);
  });

  it("reads again after a failed reload, with the next trigger", async () => {
    const getWorkBoard = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(board.page);
    const { result } = mountBoard(getWorkBoard);

    await act(async () => {
      result.current.reload();
      await Promise.resolve();
    });
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
    act(() => result.current.reload());

    expect(getWorkBoard).toHaveBeenCalledTimes(2);
  });
});

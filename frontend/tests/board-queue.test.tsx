import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { BoardView } from "@/features/work-app/board";
import { workEn } from "@/features/work-app/labels";
import { WorkView } from "@/features/work-app/work-view";
import type {
  WorkBoardFrame,
  WorkBoardPage,
  WorkItemRecord,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport";

/*
 * The board's card writes queue per card. A tap on a card whose write is still running
 * waits behind it and says so ("Väntar…"); another card is not held up; a write is shown at once from its answer, and
 * the board is read once, in the background, when the queues are empty. Simulated: the transport is a mock, so this is
 * not a test against a real host.
 */

const taskA: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
  version: 1,
};
const taskB: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a2",
  title: "Skicka faktura",
  status: "todo",
  due_at: null,
  version: 1,
};
const board: WorkBoardPage = {
  columns: { todo: [taskA, taskB], in_progress: [], completed: [] },
  next_cursor: null,
};

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void };
function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function written(card: WorkItemRecord, status: string, version: number) {
  return { task: { ...card, status, version } as WorkTask };
}

function view(work: Partial<WorkTransport>) {
  return render(
    <WorkView
      transport={
        {
          getTask: vi.fn(),
          getWorkBoard: vi.fn(),
          ...work,
        } as unknown as WorkTransport
      }
      initial={{ kind: "board", filters: {}, page: board }}
      labels={workEn}
    />,
  );
}

/** The board on a phone (the single layout), owning its frame as WorkView does. */
function Phone({ work, page }: { work: WorkTransport; page: WorkBoardPage }) {
  const [frame, setFrame] = useState<WorkBoardFrame>({
    kind: "board",
    filters: {},
    page,
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

const handle = (card: WorkItemRecord) =>
  screen.getByRole("button", { name: workEn.dragTaskFor(card.title) });
const column = (status: string) =>
  screen.getByRole("region", { name: workEn.taskStatus[status as "todo"] });
const stepRight = (card: WorkItemRecord) =>
  act(() => {
    fireEvent.keyDown(handle(card), { key: "ArrowRight" });
  });

describe("board card write queue", () => {
  it("queues a second tap on the same card, shows Waiting at once, and runs it with the version the first answer gave", async () => {
    const first = deferred<{ task: WorkTask }>();
    const updateTask = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue(written(taskA, "blocked", 3));
    const getWorkBoard = vi.fn(
      () => new Promise<WorkBoardPage>(() => undefined),
    );
    view({ updateTask, getWorkBoard });

    stepRight(taskA);
    expect(screen.queryByText(workEn.queued)).toBeNull();
    stepRight(taskA);
    // The second tap is received: the card says so, and nothing is written for it yet.
    expect(await screen.findByText(workEn.queued)).toBeInTheDocument();
    expect(updateTask).toHaveBeenCalledTimes(1);

    await act(async () => {
      first.resolve(written(taskA, "in_progress", 2));
      await Promise.resolve();
    });
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    expect(updateTask.mock.calls[0]?.[1]).toBe(1);
    expect(updateTask.mock.calls[0]?.[2]).toEqual({ status: "in_progress" });
    // The queued tap reads the version the first write gave, and steps on from the status that write gave.
    expect(updateTask.mock.calls[1]?.[0]).toBe(taskA.id);
    expect(updateTask.mock.calls[1]?.[1]).toBe(2);
    expect(updateTask.mock.calls[1]?.[2]).toEqual({ status: "blocked" });
    await waitFor(() =>
      expect(
        within(column("blocked")).getByRole("button", {
          name: workEn.dragTaskFor(taskA.title),
        }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(workEn.queued)).toBeNull();
  });

  it("does not hold up another card while one card's write hangs", async () => {
    const hanging = deferred<{ task: WorkTask }>();
    const updateTask = vi.fn((id: string) =>
      id === taskA.id
        ? hanging.promise
        : Promise.resolve(written(taskB, "in_progress", 2)),
    );
    view({
      updateTask,
      getWorkBoard: vi.fn(() => new Promise<WorkBoardPage>(() => undefined)),
    });

    stepRight(taskA);
    stepRight(taskB);
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    expect(updateTask.mock.calls.map((call) => call[0])).toEqual([
      taskA.id,
      taskB.id,
    ]);
    // B's card is not marked as waiting; A's buttons are not disabled by B's write.
    expect(screen.queryByText(workEn.queued)).toBeNull();
    expect(
      within(column("in_progress")).getByRole("button", {
        name: workEn.dragTaskFor(taskB.title),
      }),
    ).toBeEnabled();
  });

  it("a status change is one write, shows the card in its new column before the board is read, and reads the board once afterwards", async () => {
    const read = deferred<WorkBoardPage>();
    const updateTask = vi
      .fn()
      .mockResolvedValue(written(taskA, "in_progress", 2));
    const getWorkBoard = vi.fn(() => read.promise);
    view({ updateTask, getWorkBoard });

    stepRight(taskA);
    await waitFor(() =>
      expect(
        within(column("in_progress")).getByRole("button", {
          name: workEn.dragTaskFor(taskA.title),
        }),
      ).toBeInTheDocument(),
    );
    // The board read is still open: the card did not wait for it.
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: workEn.agendaUndo }),
    ).toBeInTheDocument();
    expect(handle(taskA).closest("li")).not.toHaveAttribute("aria-busy");

    await act(async () => {
      read.resolve({
        columns: {
          todo: [taskB],
          in_progress: [{ ...taskA, status: "in_progress", version: 2 }],
          completed: [],
        },
        next_cursor: null,
      });
      await Promise.resolve();
    });
    await new Promise((done) => setTimeout(done, 30));
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
    expect(updateTask).toHaveBeenCalledTimes(1);
  });

  it("a read that started before a write answered is not used over the write: the board is read again afterwards", async () => {
    const firstRead = deferred<WorkBoardPage>();
    const old: WorkBoardPage = {
      columns: {
        todo: [taskB],
        in_progress: [{ ...taskA, status: "in_progress", version: 2 }],
        completed: [],
      },
      next_cursor: null,
    };
    const fresh: WorkBoardPage = {
      columns: {
        todo: [],
        in_progress: [
          { ...taskA, status: "in_progress", version: 2 },
          { ...taskB, status: "in_progress", version: 2 },
        ],
        completed: [],
      },
      next_cursor: null,
    };
    const updateTask = vi.fn((id: string) =>
      Promise.resolve(
        id === taskA.id
          ? written(taskA, "in_progress", 2)
          : written(taskB, "in_progress", 2),
      ),
    );
    const getWorkBoard = vi
      .fn<() => Promise<WorkBoardPage>>()
      .mockReturnValueOnce(firstRead.promise)
      .mockResolvedValue(fresh);
    view({ updateTask, getWorkBoard });

    stepRight(taskA);
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
    // B is moved while the first read is open; the read's answer is from before B's write.
    stepRight(taskB);
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    await act(async () => {
      firstRead.resolve(old);
      await Promise.resolve();
    });
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(2));
    expect(
      within(column("in_progress")).getByRole("button", {
        name: workEn.dragTaskFor(taskB.title),
      }),
    ).toBeInTheDocument();
    expect(
      within(column("todo")).queryByRole("button", {
        name: workEn.dragTaskFor(taskB.title),
      }),
    ).toBeNull();
  });

  it("(2) an older Refresh that answers last does not put a confirmed move back", async () => {
    const write = deferred<{ task: WorkTask }>();
    const refresh = deferred<WorkBoardPage>();
    const moved: WorkBoardPage = {
      columns: {
        todo: [taskB],
        in_progress: [{ ...taskA, status: "in_progress", version: 2 }],
        completed: [],
      },
      next_cursor: null,
    };
    const updateTask = vi.fn(() => write.promise);
    const getWorkBoard = vi
      .fn<() => Promise<WorkBoardPage>>()
      .mockReturnValueOnce(refresh.promise)
      .mockResolvedValue(moved);
    view({ updateTask, getWorkBoard });

    stepRight(taskA);
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: workEn.refresh }));
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
    await act(async () => {
      write.resolve(written(taskA, "in_progress", 2));
      await Promise.resolve();
    });
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(2));
    // The Refresh read started before the write was confirmed; it answers last, with the card still in To do.
    await act(async () => {
      refresh.resolve(board);
      await Promise.resolve();
    });
    await new Promise((done) => setTimeout(done, 30));
    expect(
      within(column("in_progress")).getByRole("button", {
        name: workEn.dragTaskFor(taskA.title),
      }),
    ).toBeInTheDocument();
    expect(
      within(column("todo")).queryByRole("button", {
        name: workEn.dragTaskFor(taskA.title),
      }),
    ).toBeNull();
  });

  it("(6) a queued Undo is written against the version the card has when it runs", async () => {
    const second = deferred<{ task: WorkTask }>();
    const updateTask = vi
      .fn()
      .mockResolvedValueOnce(written(taskA, "in_progress", 2))
      .mockReturnValueOnce(second.promise)
      .mockResolvedValue(written(taskA, "todo", 4));
    view({
      updateTask,
      getWorkBoard: vi.fn(() => new Promise<WorkBoardPage>(() => undefined)),
    });

    stepRight(taskA);
    await screen.findByRole("button", { name: workEn.agendaUndo });
    // A further move is running when Undo is tapped: the Undo waits and then carries the version that move left.
    stepRight(taskA);
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: workEn.agendaUndo }));
    await act(async () => {
      second.resolve(written(taskA, "blocked", 3));
      await Promise.resolve();
    });
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(3));
    expect(updateTask.mock.calls[2]?.[1]).toBe(3);
    expect(updateTask.mock.calls[2]?.[2]).toEqual({ status: "todo" });
  });

  it("(10) the waiting mark is announced from a status region that is not inside a busy row", async () => {
    const first = deferred<{ task: WorkTask }>();
    view({
      updateTask: vi.fn(() => first.promise),
      getWorkBoard: vi.fn(() => new Promise<WorkBoardPage>(() => undefined)),
    });
    const region = screen.getByRole("status");
    expect(region).toBeEmptyDOMElement();

    stepRight(taskA);
    stepRight(taskA);
    await screen.findByText(workEn.queued);
    // The same region, mounted before the news, now says it; no busy element holds it.
    expect(screen.getByRole("status")).toBe(region);
    expect(region).toHaveTextContent(`${taskA.title}: ${workEn.queued}`);
    expect(region.closest("[aria-busy]")).toBeNull();
    expect(handle(taskA).closest("li")).toHaveAttribute("aria-busy", "true");
  });

  it("(5) a queued order is worked out when it runs, from the versions and order the answer before it gave", async () => {
    const taskC: WorkItemRecord = {
      ...taskB,
      id: "019f0000-0000-7000-8000-0000000000a3",
      title: "Boka möte",
    };
    const three: WorkBoardPage = {
      columns: { todo: [taskA, taskB, taskC], in_progress: [], completed: [] },
      next_cursor: null,
    };
    const first = deferred<{ items: { task_id: string; version: number }[] }>();
    const reorderBoardColumn = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue({ items: [] });
    render(
      <Phone
        work={
          {
            getTask: vi.fn(),
            getWorkBoard: vi.fn(
              () => new Promise<WorkBoardPage>(() => undefined),
            ),
            reorderBoardColumn,
          } as unknown as WorkTransport
        }
        page={three}
      />,
    );
    const moveDown = async () => {
      const name = workEn.moveListFor(taskA.title);
      // The quick choices stay open after a choice; if they closed, the card's menu opens again.
      if (!screen.queryByRole("group", { name }))
        fireEvent.contextMenu(
          screen
            .getByRole("button", { name: taskA.title })
            .closest("li") as HTMLElement,
        );
      const group = await screen.findByRole("group", { name });
      fireEvent.click(
        within(group).getByRole("button", { name: workEn.moveDown }),
      );
    };

    await moveDown();
    await waitFor(() => expect(reorderBoardColumn).toHaveBeenCalledTimes(1));
    // A second step on the same card while the first order is still being written: it waits.
    await moveDown();
    expect(reorderBoardColumn).toHaveBeenCalledTimes(1);
    await act(async () => {
      first.resolve({
        items: [
          { task_id: taskB.id, version: 2 },
          { task_id: taskA.id, version: 2 },
          { task_id: taskC.id, version: 2 },
        ],
      });
      await Promise.resolve();
    });
    await waitFor(() => expect(reorderBoardColumn).toHaveBeenCalledTimes(2));
    // One more step from where the card stands now (second), with the versions the first answer gave.
    expect(reorderBoardColumn.mock.calls[1]?.[1]).toEqual([
      { taskId: taskB.id, version: 2 },
      { taskId: taskC.id, version: 2 },
      { taskId: taskA.id, version: 2 },
    ]);
  });

  it("(N2) a move queued behind a write that got no answer replays it first, then writes its own intent with its own key", async () => {
    let fail: (error: Error) => void = () => undefined;
    const updateTask = vi
      .fn()
      .mockReturnValueOnce(
        new Promise((_, reject) => {
          fail = reject;
        }),
      )
      .mockResolvedValueOnce(written(taskA, "in_progress", 2))
      .mockResolvedValue(written(taskA, "blocked", 3));
    view({
      updateTask,
      getWorkBoard: vi.fn(() => new Promise<WorkBoardPage>(() => undefined)),
    });

    stepRight(taskA);
    stepRight(taskA);
    await act(async () => {
      fail(new Error("timeout"));
      await Promise.resolve();
    });
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(3));
    const [one, replay, own] = updateTask.mock.calls;
    expect(replay?.slice(0, 3)).toEqual(one?.slice(0, 3));
    expect(replay?.[3]).toBe(one?.[3]);
    expect(own?.[1]).toBe(2);
    expect(own?.[2]).toEqual({ status: "blocked" });
    expect(own?.[3]).not.toBe(one?.[3]);
  });

  it("(N2) a second Flytta ned behind an order that got no answer is one more step, not the same order again", async () => {
    const taskC: WorkItemRecord = {
      ...taskB,
      id: "019f0000-0000-7000-8000-0000000000a3",
      title: "Boka möte",
    };
    const three: WorkBoardPage = {
      columns: { todo: [taskA, taskB, taskC], in_progress: [], completed: [] },
      next_cursor: null,
    };
    let fail: (error: Error) => void = () => undefined;
    const reorderBoardColumn = vi
      .fn()
      .mockReturnValueOnce(
        new Promise((_, reject) => {
          fail = reject;
        }),
      )
      .mockResolvedValueOnce({
        items: [
          { task_id: taskB.id, version: 2 },
          { task_id: taskA.id, version: 2 },
          { task_id: taskC.id, version: 2 },
        ],
      })
      .mockResolvedValue({ items: [] });
    render(
      <Phone
        work={
          {
            getTask: vi.fn(),
            getWorkBoard: vi.fn(
              () => new Promise<WorkBoardPage>(() => undefined),
            ),
            reorderBoardColumn,
          } as unknown as WorkTransport
        }
        page={three}
      />,
    );
    fireEvent.contextMenu(
      screen
        .getByRole("button", { name: taskA.title })
        .closest("li") as HTMLElement,
    );
    const group = await screen.findByRole("group", {
      name: workEn.moveListFor(taskA.title),
    });
    const down = within(group).getByRole("button", { name: workEn.moveDown });
    fireEvent.click(down);
    fireEvent.click(down);
    await act(async () => {
      fail(new Error("timeout"));
      await Promise.resolve();
    });
    await waitFor(() => expect(reorderBoardColumn).toHaveBeenCalledTimes(3));
    const [one, replay, own] = reorderBoardColumn.mock.calls;
    expect(replay?.[2]).toBe(one?.[2]);
    expect(own?.[1]).toEqual([
      { taskId: taskB.id, version: 2 },
      { taskId: taskC.id, version: 2 },
      { taskId: taskA.id, version: 2 },
    ]);
    expect(own?.[2]).not.toBe(one?.[2]);
  });

  it("(N3) an Undo that was used leaves no Undo of an earlier move behind", async () => {
    const second = deferred<{ task: WorkTask }>();
    const updateTask = vi
      .fn()
      .mockResolvedValueOnce(written(taskA, "in_progress", 2))
      .mockReturnValueOnce(second.promise)
      .mockResolvedValue(written(taskA, "todo", 4));
    view({
      updateTask,
      getWorkBoard: vi.fn(() => new Promise<WorkBoardPage>(() => undefined)),
    });

    stepRight(taskA);
    await screen.findByRole("button", { name: workEn.agendaUndo });
    stepRight(taskA);
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: workEn.agendaUndo }));
    await act(async () => {
      second.resolve(written(taskA, "blocked", 3));
      await Promise.resolve();
    });
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(3));
    await new Promise((done) => setTimeout(done, 30));
    expect(
      screen.queryByRole("button", { name: workEn.agendaUndo }),
    ).toBeNull();
  });

  it("(N4) a read asked for by a new refreshKey while another read runs is made when that one ends", async () => {
    const first = deferred<WorkBoardPage>();
    const getWorkBoard = vi
      .fn<() => Promise<WorkBoardPage>>()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue(board);
    const work = {
      getTask: vi.fn(),
      getWorkBoard,
    } as unknown as WorkTransport;
    const initial: WorkBoardFrame = { kind: "board", filters: {}, page: board };
    const shown = (refreshKey: number) => (
      <WorkView
        transport={work}
        initial={initial}
        labels={workEn}
        refreshKey={refreshKey}
      />
    );
    const { rerender } = render(shown(0));
    fireEvent.click(screen.getByRole("button", { name: workEn.refresh }));
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
    rerender(shown(1));
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
    await act(async () => {
      first.resolve(board);
      await Promise.resolve();
    });
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(2));
  });

  it("(N4) only the read started last is used: an older background read does not overwrite a later reload", async () => {
    const quiet = deferred<WorkBoardPage>();
    const reloaded = deferred<WorkBoardPage>();
    const withB = (status: string): WorkBoardPage => ({
      columns: {
        todo: status === "todo" ? [taskB] : [],
        in_progress: [{ ...taskA, status: "in_progress", version: 2 }],
        completed: status === "completed" ? [{ ...taskB, status }] : [],
      },
      next_cursor: null,
    });
    const getWorkBoard = vi
      .fn<() => Promise<WorkBoardPage>>()
      .mockReturnValueOnce(quiet.promise)
      .mockReturnValueOnce(reloaded.promise);
    const work = {
      getTask: vi.fn(),
      getWorkBoard,
      updateTask: vi.fn().mockResolvedValue(written(taskA, "in_progress", 2)),
    } as unknown as WorkTransport;
    const initial: WorkBoardFrame = { kind: "board", filters: {}, page: board };
    const shown = (refreshKey: number) => (
      <WorkView
        transport={work}
        initial={initial}
        labels={workEn}
        refreshKey={refreshKey}
      />
    );
    const { rerender } = render(shown(0));
    stepRight(taskA);
    // The background read after the write is open; a reload is asked for and starts a newer read.
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(1));
    rerender(shown(1));
    await waitFor(() => expect(getWorkBoard).toHaveBeenCalledTimes(2));
    await act(async () => {
      reloaded.resolve(withB("completed"));
      await Promise.resolve();
    });
    await act(async () => {
      quiet.resolve(withB("todo"));
      await Promise.resolve();
    });
    await new Promise((done) => setTimeout(done, 30));
    expect(
      within(column("completed")).getByRole("button", {
        name: workEn.dragTaskFor(taskB.title),
      }),
    ).toBeInTheDocument();
  });

  it("(N6) a move that goes through on Try again offers its Undo", async () => {
    const updateTask = vi
      .fn()
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValue(written(taskA, "in_progress", 2));
    view({
      updateTask,
      getWorkBoard: vi.fn(() => new Promise<WorkBoardPage>(() => undefined)),
    });
    stepRight(taskA);
    fireEvent.click(await screen.findByRole("button", { name: workEn.retry }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByRole("button", { name: workEn.agendaUndo }),
    ).toBeInTheDocument();
  });

  it("(N7) a move queued behind an Undo that got no answer replays the Undo first and uses the version it left", async () => {
    let fail: (error: Error) => void = () => undefined;
    const updateTask = vi
      .fn()
      .mockResolvedValueOnce(written(taskA, "in_progress", 2))
      .mockReturnValueOnce(
        new Promise((_, reject) => {
          fail = reject;
        }),
      )
      .mockResolvedValueOnce(written(taskA, "todo", 3))
      .mockResolvedValue(written(taskA, "in_progress", 4));
    view({
      updateTask,
      getWorkBoard: vi.fn(() => new Promise<WorkBoardPage>(() => undefined)),
    });
    stepRight(taskA);
    fireEvent.click(
      await screen.findByRole("button", { name: workEn.agendaUndo }),
    );
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    // A move is asked for while the Undo is unanswered; the Undo then fails with no answer.
    stepRight(taskA);
    await act(async () => {
      fail(new Error("timeout"));
      await Promise.resolve();
    });
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(4));
    const [, undo, replay, own] = updateTask.mock.calls;
    expect(replay?.slice(0, 3)).toEqual(undo?.slice(0, 3));
    expect(replay?.[3]).toBe(undo?.[3]);
    expect(own?.[1]).toBe(3);
  });
});

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import type {
  WorkBoardPage,
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  KEY,
  agendaTask,
  boardPage,
  boardTask,
  taskA,
  transport,
} from "@tests/helpers/work-app-fixtures";

// Mark as done in a Task view goes back to the list the Task was opened from, and the board shows the Task in Klar
// with its Ångra. Simulated-host tests (the view with a fake transport, the shell's Back stood in for by a spy), not
// tests in a real Claude or Android host.

/** The board as the host reads it once the Task has this status and version: it stands in that Task status column. */
function boardWith(status: string, version: number): WorkBoardPage {
  const columns = Object.fromEntries(
    Object.entries(boardPage.columns).map(([key, list]) => [
      key,
      list.filter((item) => item.id !== taskA.id),
    ]),
  );
  columns[status] = [
    ...(columns[status] ?? []),
    { ...boardTask, status, version },
  ];
  return { ...boardPage, columns };
}

/** A transport that behaves like the host: update_task answers with the Task changed, and the board reads that state. */
function work(overrides: Partial<WorkTransport> = {}): WorkTransport {
  let board = boardPage;
  return transport({
    updateTask: vi
      .fn()
      .mockImplementation(
        (_id: string, version: number, changes: WorkTaskChanges) => {
          const task = {
            ...taskA,
            ...changes,
            version: version + 1,
          } as WorkTask;
          board = boardWith(task.status, task.version);
          return Promise.resolve({ task });
        },
      ),
    getWorkBoard: vi.fn().mockImplementation(() => Promise.resolve(board)),
    getWorkAgenda: vi
      .fn()
      .mockResolvedValue({ items: [agendaTask], next_cursor: null }),
    ...overrides,
  });
}

function renderBoard(host: WorkTransport, labels: WorkLabels) {
  return render(
    <WorkView
      transport={host}
      initial={{ kind: "board", filters: {}, page: boardPage }}
      labels={labels}
    />,
  );
}

const region = (name: string) => screen.getByRole("region", { name });

// The board's Ångra names its card ("Undo <title>"); the Task view's own Undo is just the word.
const undoOf = (labels: WorkLabels) => new RegExp(`^${labels.agendaUndo}`);

describe.each([
  ["English", workEn],
  ["Swedish", workSv],
] as const)("Mark as done from the board (%s)", (_name, labels) => {
  it("goes back to the board with the card in Klar and its Ångra", async () => {
    const host = work();
    renderBoard(host, labels);
    const user = userEvent.setup();
    await user.click(
      within(region(labels.taskStatus.todo)).getByRole("button", {
        name: boardTask.title,
      }),
    );
    await user.click(
      await screen.findByRole("button", { name: labels.markDone }),
    );

    // The Task view is left for the board, and no write ran twice.
    expect(
      await screen.findByRole("heading", { level: 2, name: labels.board }),
    ).toBeInTheDocument();
    expect(host.updateTask).toHaveBeenCalledTimes(1);
    expect(host.updateTask).toHaveBeenCalledWith(
      taskA.id,
      1,
      { status: "completed" },
      expect.stringMatching(KEY),
    );
    expect(screen.queryByRole("button", { name: labels.markDone })).toBeNull();
    // The card stands in Klar, not in To do, with the Ångra beside it.
    const done = region(labels.taskStatus.completed);
    expect(
      within(done).getByRole("button", { name: boardTask.title }),
    ).toBeInTheDocument();
    expect(
      within(region(labels.taskStatus.todo)).queryByRole("button", {
        name: boardTask.title,
      }),
    ).toBeNull();
    expect(
      within(done).getByRole("button", { name: undoOf(labels) }),
    ).toBeEnabled();
  });

  it("writes the earlier status back from the board's Ångra and returns the card to its column", async () => {
    const host = work();
    renderBoard(host, labels);
    const user = userEvent.setup();
    await user.click(
      within(region(labels.taskStatus.todo)).getByRole("button", {
        name: boardTask.title,
      }),
    );
    await user.click(
      await screen.findByRole("button", { name: labels.markDone }),
    );
    await user.click(
      await screen.findByRole("button", { name: undoOf(labels) }),
    );

    await waitFor(() => expect(host.updateTask).toHaveBeenCalledTimes(2));
    expect(host.updateTask).toHaveBeenNthCalledWith(
      2,
      taskA.id,
      2,
      { status: "todo" },
      expect.stringMatching(KEY),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: undoOf(labels) })).toBeNull(),
    );
    expect(
      within(region(labels.taskStatus.todo)).getByRole("button", {
        name: boardTask.title,
      }),
    ).toBeInTheDocument();
  });
});

describe("Mark as done on a Task with nothing to go back to", () => {
  it("stays in the Task view with its Undo in place when it is the root and there is no shell Back", async () => {
    const host = work();
    render(
      <WorkView
        transport={host}
        initial={{ kind: "task", id: taskA.id }}
        labels={workEn}
      />,
    );
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: workEn.markDone }),
    );
    const undo = await screen.findByRole("button", { name: workEn.agendaUndo });
    expect(undo).toHaveFocus();
    expect(
      screen.getByRole("heading", { level: 2, name: taskA.title }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 2, name: workEn.board }),
    ).toBeNull();
  });

  it("does not leave the Task view when the write fails", async () => {
    const host = work({
      updateTask: vi.fn().mockRejectedValue(new HostToolError("forbidden")),
    });
    renderBoard(host, workEn);
    const user = userEvent.setup();
    await user.click(
      within(region(workEn.taskStatus.todo)).getByRole("button", {
        name: boardTask.title,
      }),
    );
    await user.click(
      await screen.findByRole("button", { name: workEn.markDone }),
    );
    await waitFor(() => expect(host.updateTask).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(workEn.forbiddenWrite)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: taskA.title }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 2, name: workEn.board }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: workEn.markDone })).toBeEnabled();
  });

  it("stays with its Undo on a shell layer that was not opened from a list (the card's own Task, a record page)", async () => {
    const host = work();
    const onLeave = vi.fn();
    render(
      <WorkView
        transport={host}
        initial={{ kind: "task", id: taskA.id }}
        labels={workEn}
        onLeave={onLeave}
      />,
    );
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: workEn.markDone }),
    );
    expect(
      await screen.findByRole("button", { name: workEn.agendaUndo }),
    ).toHaveFocus();
    expect(onLeave).not.toHaveBeenCalled();
  });

  it("does not leave a shell layer when the write fails", async () => {
    const host = work({
      updateTask: vi.fn().mockRejectedValue(new HostToolError("forbidden")),
    });
    const onLeave = vi.fn();
    render(
      <WorkView
        transport={host}
        initial={{ kind: "task", id: taskA.id }}
        labels={workEn}
        onLeave={onLeave}
        openedFrom="board"
      />,
    );
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: workEn.markDone }),
    );
    await waitFor(() => expect(host.updateTask).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(workEn.forbiddenWrite)).toBeInTheDocument();
    expect(onLeave).not.toHaveBeenCalled();
  });
});

describe("Mark as done on a layer of the shell's stack", () => {
  /** A board kept mounted under the layer, and the Task layer on top of it, as the shell shows them. */
  function renderLayers(
    host: WorkTransport,
    onLeave: () => void,
    openedFrom: string,
  ) {
    return render(
      <>
        <div data-testid="board">
          <WorkView
            transport={host}
            initial={{ kind: "board", filters: {}, page: boardPage }}
            labels={workEn}
          />
        </div>
        <div data-testid="layer">
          <WorkView
            transport={host}
            initial={{ kind: "task", id: taskA.id }}
            labels={workEn}
            onLeave={onLeave}
            openedFrom={openedFrom}
          />
        </div>
      </>,
    );
  }

  it("leaves with the shell's Back and hands the Task to the board below, which shows its Ångra", async () => {
    const host = work();
    const onLeave = vi.fn();
    renderLayers(host, onLeave, "board");
    const board = within(screen.getByTestId("board"));
    const layer = within(screen.getByTestId("layer"));
    const user = userEvent.setup();
    await user.click(
      await layer.findByRole("button", { name: workEn.markDone }),
    );

    await waitFor(() => expect(onLeave).toHaveBeenCalledTimes(1));
    expect(host.updateTask).toHaveBeenCalledTimes(1);
    // The board below has the card in Klar with its Ångra, without reading the board again.
    const done = board.getByRole("region", {
      name: workEn.taskStatus.completed,
    });
    expect(
      within(done).getByRole("button", { name: boardTask.title }),
    ).toBeInTheDocument();
    expect(
      within(done).getByRole("button", { name: undoOf(workEn) }),
    ).toBeEnabled();
    expect(
      within(
        board.getByRole("region", { name: workEn.taskStatus.todo }),
      ).queryByRole("button", { name: boardTask.title }),
    ).toBeNull();
    // The layer shows no Ångra of its own: it is being left.
    expect(layer.queryByRole("button", { name: undoOf(workEn) })).toBeNull();
    expect(host.getWorkBoard).not.toHaveBeenCalled();

    await user.click(
      within(done).getByRole("button", { name: undoOf(workEn) }),
    );
    await waitFor(() => expect(host.updateTask).toHaveBeenCalledTimes(2));
    expect(host.updateTask).toHaveBeenNthCalledWith(
      2,
      taskA.id,
      2,
      { status: "todo" },
      expect.stringMatching(KEY),
    );
  });

  it("leaves with the shell's Back from an agenda without handing anything to a board", async () => {
    const host = work();
    const onLeave = vi.fn();
    renderLayers(host, onLeave, "agenda");
    const board = within(screen.getByTestId("board"));
    const user = userEvent.setup();
    await user.click(
      await within(screen.getByTestId("layer")).findByRole("button", {
        name: workEn.markDone,
      }),
    );
    await waitFor(() => expect(onLeave).toHaveBeenCalledTimes(1));
    expect(host.updateTask).toHaveBeenCalledTimes(1);
    // The board is not the list the Task came from: its card stays where it was, with no Ångra.
    expect(
      within(
        board.getByRole("region", { name: workEn.taskStatus.todo }),
      ).getByRole("button", { name: boardTask.title }),
    ).toBeInTheDocument();
    expect(board.queryByRole("button", { name: undoOf(workEn) })).toBeNull();
  });
});

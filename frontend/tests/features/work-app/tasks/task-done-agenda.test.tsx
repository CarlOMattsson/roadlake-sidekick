import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { agendaLabelsFor } from "@/features/work-app/agenda/agenda-labels";
import { keepHeld } from "@/features/work-app/agenda/parts/agenda-helpers";
import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import type {
  WorkItemRecord,
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

// Mark as done in a Task view opened from the Agenda goes back to the Agenda, and the Agenda shows the Task's row as done
// with its Ångra, as after a tick there. Simulated-host tests (the view with a fake transport, the shell's Back stood
// in for by a spy), not tests in a real Claude or Android host.

/**
 * A transport that behaves like the host: update_task answers with the Task changed, and the agenda reads only the
 * open Tasks, so a Task marked done is no longer in it.
 */
function work(): WorkTransport {
  let open = true;
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
          open = task.status !== "completed";
          return Promise.resolve({ task });
        },
      ),
    getWorkAgenda: vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve({ items: open ? [agendaTask] : [], next_cursor: null }),
      ),
    getWorkBoard: vi.fn().mockResolvedValue(boardPage),
  });
}

const agendaFrame = {
  kind: "agenda" as const,
  filters: {},
  page: { items: [agendaTask], next_cursor: null },
};

// The agenda's Ångra names its row ("Undo <title>"); the line beside it says the Task is done.
const undoOf = (labels: WorkLabels) =>
  new RegExp(`^${labels.agendaUndo} ${boardTask.title}$`);

describe.each([
  ["English", workEn],
  ["Swedish", workSv],
] as const)("Mark as done from the agenda (%s)", (_name, labels) => {
  it("goes back to the agenda with the row done and its Ångra", async () => {
    const host = work();
    render(<WorkView transport={host} initial={agendaFrame} labels={labels} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: agendaTask.title }));
    await user.click(
      await screen.findByRole("button", { name: labels.markDone }),
    );

    expect(
      await screen.findByRole("heading", { level: 2, name: labels.agenda }),
    ).toBeInTheDocument();
    expect(host.updateTask).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: labels.markDone })).toBeNull();
    // The Task saved under the agenda makes it read again; the read no longer lists the done Task, but its row stays
    // with its Ångra until the time to undo is up.
    await waitFor(() => expect(host.getWorkAgenda).toHaveBeenCalled());
    const undo = await screen.findByRole("button", { name: undoOf(labels) });
    expect(undo).toBeEnabled();
    expect(undo.closest(".work-agenda-undo")).toHaveTextContent(
      agendaLabelsFor(labels.dateLocale).doneInStatus,
    );
    expect(
      screen.getByRole("button", { name: agendaTask.title }),
    ).toBeInTheDocument();
  });

  it("writes the earlier status back from the agenda's Ångra", async () => {
    const host = work();
    render(<WorkView transport={host} initial={agendaFrame} labels={labels} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: agendaTask.title }));
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
      screen.getByRole("button", { name: agendaTask.title }),
    ).toBeInTheDocument();
  });
});

describe("Mark as done on a shell layer opened from the agenda", () => {
  /** An agenda and a board kept mounted under the layer, and the Task layer on top, as the shell shows them. */
  function renderLayers(host: WorkTransport, onLeave: () => void) {
    return render(
      <>
        <div data-testid="agenda">
          <WorkView transport={host} initial={agendaFrame} labels={workEn} />
        </div>
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
            openedFrom="agenda"
          />
        </div>
      </>,
    );
  }

  it("hands the Task to the agenda below, which shows its Ångra, and leaves the board as it was", async () => {
    const host = work();
    const onLeave = vi.fn();
    renderLayers(host, onLeave);
    const agenda = within(screen.getByTestId("agenda"));
    const board = within(screen.getByTestId("board"));
    const user = userEvent.setup();
    await user.click(
      await within(screen.getByTestId("layer")).findByRole("button", {
        name: workEn.markDone,
      }),
    );

    await waitFor(() => expect(onLeave).toHaveBeenCalledTimes(1));
    expect(host.updateTask).toHaveBeenCalledTimes(1);
    expect(
      await agenda.findByRole("button", { name: undoOf(workEn) }),
    ).toBeEnabled();
    expect(board.queryByRole("button", { name: /^Undo/ })).toBeNull();
    expect(
      within(
        board.getByRole("region", { name: workEn.taskStatus.todo }),
      ).getByRole("button", { name: boardTask.title }),
    ).toBeInTheDocument();
  });
});

describe("keepHeld", () => {
  const record = (id: string): WorkItemRecord => ({ ...agendaTask, id });
  const ids = (items: WorkItemRecord[]) => items.map((item) => item.id);

  it("puts a held record the read left out back after the record it followed", () => {
    const before = [record("a"), record("b"), record("c")];
    const read = [record("a"), record("c")];
    expect(ids(keepHeld(before, read, (key) => key === "task:b"))).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("puts a held first record first, and keeps a read that lists it as read", () => {
    const before = [record("a"), record("b")];
    expect(
      ids(keepHeld(before, [record("b")], (key) => key === "task:a")),
    ).toEqual(["a", "b"]);
    const read = [record("b"), record("a")];
    expect(keepHeld(before, read, () => true)).toBe(read);
  });

  it("lets a record that is not held leave", () => {
    const before = [record("a"), record("b")];
    expect(ids(keepHeld(before, [record("a")], () => false))).toEqual(["a"]);
  });
});

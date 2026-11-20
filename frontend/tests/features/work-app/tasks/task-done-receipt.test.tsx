import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { receiptRunning } from "@tests/helpers/receipt-bar";
import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import type {
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { WorkView } from "@/features/work-app/view/work-view";

// Mark as done in the Task room: the control shows its new state at once ("Återöppna") and stays where it is with focus on
// it; the change is confirmed, with Ångra, in the receipt bar at the view's foot (designsystem §0.6), and no plain
// "Sparat" is added. Simulated-host tests (the view with a fake transport), not a real host.

const task: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring Anna om offerten",
  status: "in_progress",
  due_at: null,
  version: 1,
};

function transport(): WorkTransport {
  return {
    getTask: vi.fn().mockResolvedValue({ task }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    updateTask: vi
      .fn()
      .mockImplementation(
        (_id: string, version: number, changes: WorkTaskChanges) =>
          Promise.resolve({
            task: { ...task, ...changes, version: version + 1 },
          }),
      ),
  } as unknown as WorkTransport;
}

function renderTask(work: WorkTransport, labels: WorkLabels) {
  return render(
    <WorkView
      transport={work}
      initial={{ kind: "task", id: task.id }}
      labels={labels}
    />,
  );
}

const slot = () => document.querySelector(".sk-receipt-slot") as HTMLElement;

describe.each([
  ["English", workEn],
  ["Swedish", workSv],
] as const)("Mark as done in the Task room (%s)", (_name, labels) => {
  it("shows Reopen in the button's place with focus on it, and Klar with Ångra in the receipt bar, no Saved line", async () => {
    const work = transport();
    renderTask(work, labels);
    const user = userEvent.setup();
    const done = await screen.findByRole("button", { name: labels.markDone });
    const row = done.closest(".work-task-props") as HTMLElement;
    const before = row.nextElementSibling;
    await user.click(done);

    const reopen = await screen.findByRole("button", {
      name: labels.reopenTask,
    });
    expect(reopen.closest(".work-task-props")).toBe(row);
    await waitFor(() => expect(reopen).toHaveFocus());
    // Nothing is added under the controls, and nothing is Saved: the bar holds the one receipt.
    expect(row.nextElementSibling).toBe(before);
    expect(screen.queryByText(labels.saved)).toBeNull();
    expect(
      within(slot()).getByText(`${labels.taskStatus.completed}: ${task.title}`),
    ).toBeVisible();
    // Ångra is only in the bar, not on the row.
    expect(
      within(slot()).getByRole("button", { name: labels.agendaUndo }),
    ).toBeEnabled();
    expect(
      screen.getAllByRole("button", { name: labels.agendaUndo }),
    ).toHaveLength(1);
  });

  it("writes the earlier status back from Ångra in the bar, with no Saved line, and Mark done returns with focus", async () => {
    const work = transport();
    renderTask(work, labels);
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: labels.markDone }),
    );
    await user.click(
      await screen.findByRole("button", { name: labels.agendaUndo }),
    );

    await waitFor(() => expect(work.updateTask).toHaveBeenCalledTimes(2));
    expect(work.updateTask).toHaveBeenNthCalledWith(
      2,
      task.id,
      2,
      { status: "in_progress" },
      expect.any(String),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: labels.agendaUndo }),
      ).toBeNull(),
    );
    const again = await screen.findByRole("button", { name: labels.markDone });
    expect(again).toBeVisible();
    // The bar's button left with its receipt: focus is back on the control, never on the page.
    await waitFor(() => expect(again).toHaveFocus());
    expect(screen.queryByText(labels.saved)).toBeNull();
  });

  it("lets the bar go once the time to undo is up; Reopen stays and keeps focus", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const work = transport();
      renderTask(work, labels);
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await user.click(
        await screen.findByRole("button", { name: labels.markDone }),
      );
      const reopen = await screen.findByRole("button", {
        name: labels.reopenTask,
      });
      await waitFor(() => expect(reopen).toHaveFocus());
      expect(
        within(slot()).getByRole("button", { name: labels.agendaUndo }),
      ).toBeVisible();
      await receiptRunning();
      await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 1000));
      expect(
        screen.queryByRole("button", { name: labels.agendaUndo }),
      ).toBeNull();
      expect(slot()).toBeEmptyDOMElement();
      expect(
        screen.getByRole("button", { name: labels.reopenTask }),
      ).toHaveFocus();
    } finally {
      vi.useRealTimers();
    }
  });
});

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
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

// Mark as done in the Task room is answered where the button is: Ångra takes the place of "Återöppna" (the status chip
// already says "Klar"), takes focus, adds no line and leaves no plain "Sparat". Simulated-host tests (the view with a
// fake transport), not a real host.

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

describe.each([
  ["English", workEn],
  ["Swedish", workSv],
] as const)("Mark as done in the Task room (%s)", (_name, labels) => {
  it("puts Undo where Reopen will stand, with focus on it, no second Klar and no Saved line", async () => {
    const work = transport();
    renderTask(work, labels);
    const user = userEvent.setup();
    const done = await screen.findByRole("button", { name: labels.markDone });
    const row = done.closest(".work-task-props") as HTMLElement;
    const before = row.nextElementSibling;
    await user.click(done);

    const undo = await screen.findByRole("button", {
      name: labels.agendaUndo,
    });
    expect(undo).toBeEnabled();
    expect(undo.closest(".work-task-props")).toBe(row);
    expect(undo).toHaveFocus();
    // One way back: no Reopen beside Undo, no line of its own under the controls, no Saved.
    expect(
      screen.queryByRole("button", { name: labels.reopenTask }),
    ).toBeNull();
    expect(row.nextElementSibling).toBe(before);
    expect(screen.queryByText(labels.saved)).toBeNull();
    // Klar is drawn once (the status chip); the receipt's own word is for screen readers only.
    const visible = screen
      .getAllByText(labels.taskStatus.completed)
      .filter((node) => !node.classList.contains("work-visually-hidden"));
    expect(visible).toHaveLength(1);
    expect(
      screen.getByText(labels.taskStatus.completed, {
        selector: "[role=status]",
      }),
    ).toHaveClass("work-visually-hidden");
  });

  it("writes the earlier status back from Undo, with no Saved line, and Mark done returns", async () => {
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
    expect(
      await screen.findByRole("button", { name: labels.markDone }),
    ).toBeVisible();
    expect(screen.queryByText(labels.saved)).toBeNull();
  });

  it("shows Reopen once the time to undo is up", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const work = transport();
      renderTask(work, labels);
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await user.click(
        await screen.findByRole("button", { name: labels.markDone }),
      );
      const undo = await screen.findByRole("button", {
        name: labels.agendaUndo,
      });
      // Focus starts on Undo and does not hold the time: it runs out, and focus moves to the title.
      expect(undo).toHaveFocus();
      await act(() => vi.advanceTimersByTimeAsync(UNDO_MS + 1000));
      expect(
        await screen.findByRole("button", { name: labels.reopenTask }),
      ).toBeVisible();
      expect(
        screen.queryByRole("button", { name: labels.agendaUndo }),
      ).toBeNull();
      expect(screen.getByRole("heading", { name: task.title })).toHaveFocus();
    } finally {
      vi.useRealTimers();
    }
  });
});

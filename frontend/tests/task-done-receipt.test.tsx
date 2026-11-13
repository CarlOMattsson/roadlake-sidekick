import { render, screen, waitFor, within } from "@testing-library/react";
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
import { WorkView } from "@/features/work-app/view/work-view";

// Mark as done in the Task room is answered where the button is: "Klar" with Ångra, in the family's receipt shape, and
// no plain "Sparat" line far away from it. Simulated-host tests (the view with a fake transport), not a real host.

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
  it("shows the done line with Undo right under the button, and no plain Saved line", async () => {
    const work = transport();
    renderTask(work, labels);
    const user = userEvent.setup();
    const done = await screen.findByRole("button", { name: labels.markDone });
    await user.click(done);

    const line = await screen.findByText(labels.taskStatus.completed, {
      selector: "[role=status]",
    });
    const undo = within(line.parentElement!).getByRole("button", {
      name: labels.agendaUndo,
    });
    expect(undo).toBeEnabled();
    expect(screen.queryByText(labels.saved)).toBeNull();
    // The line stands with the controls it answers, before the description and the sections.
    expect(
      screen
        .getByRole("button", { name: labels.reopenTask })
        .compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("writes the earlier status back from Undo and ends the line", async () => {
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
  });
});

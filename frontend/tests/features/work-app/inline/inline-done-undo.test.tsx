import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
  type InlineSummaryLabels,
} from "@/features/work-app/inline/inline-summary-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkFrame,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";

/*
 * The Task card's Done is undoable for UNDO_MS, as the Agenda's is: the card shows the Task's new state ("Done" in its
 * status line, no Undo of its own) and the receipt bar at its foot offers Ångra, which writes the earlier status back
 * against the version Done left. Simulated host: this proves the card's wiring, not a real Claude or Android host.
 */

const task: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000f1",
  title: "Ring Anna om offerten",
  status: "in_progress",
  due_at: null,
  version: 1,
};
const frame: WorkFrame = { kind: "task", id: task.id, task };

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

function transportWith(updateTask: ReturnType<typeof vi.fn>): WorkTransport {
  return {
    getTask: vi.fn().mockResolvedValue({ task }),
    updateTask,
  } as unknown as WorkTransport;
}

function renderCard(
  updateTask: ReturnType<typeof vi.fn>,
  labels: InlineSummaryLabels = inlineSummaryLabelsEn,
  initial: WorkFrame = frame,
) {
  const announce = vi.fn();
  render(
    <WorkView
      transport={transportWith(updateTask)}
      initial={initial}
      labels={labels === inlineSummaryLabelsSv ? workSv : workEn}
      inlineLabels={labels}
      fullscreen={vi.fn()}
      onModelContext={announce}
    />,
  );
  return announce;
}

/** Clicks and lets the write's promise settle; timers stay under the test's control. */
async function click(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
    await vi.advanceTimersByTimeAsync(0);
  });
}

const en = inlineSummaryLabelsEn;
const done = (version: number): { task: WorkTask } => ({
  task: { ...task, status: "completed", version },
});

it("shows the new state on the card and Ångra in the receipt bar, with focus on the card's open link", async () => {
  renderCard(vi.fn().mockResolvedValue(done(2)));
  await click(en.complete);

  // The card says the new state in its status line; the bar says what happened.
  expect(screen.getByText(en.taskStatus.completed)).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    `${en.taskStatus.completed}: Ring Anna om offerten`,
  );
  // Ångra is in the bar and nowhere on the card itself.
  const undo = screen.getByRole("button", { name: en.undo });
  expect(undo.closest(".sk-receipt")).not.toBeNull();
  expect(document.querySelectorAll(".work-compact-undo")).toHaveLength(0);
  expect(screen.queryByRole("button", { name: en.complete })).toBeNull();
  // Done's button went: focus did not fall to the page, it is on the link that stays.
  expect(screen.getByRole("button", { name: en.showTask })).toHaveFocus();
});

it("says it in Swedish: Klar and Ångra", async () => {
  renderCard(vi.fn().mockResolvedValue(done(2)), inlineSummaryLabelsSv);
  await click(inlineSummaryLabelsSv.complete);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Klar: Ring Anna om offerten",
  );
  expect(screen.getByRole("button", { name: "Ångra" })).toBeInTheDocument();
});

it("writes the earlier status back against the version Done left, with a new key, and gives Done its focus", async () => {
  const updateTask = vi
    .fn()
    .mockResolvedValueOnce(done(7))
    .mockResolvedValueOnce({ task: { ...task, version: 8 } });
  const announce = renderCard(updateTask);
  await click(en.complete);
  await click(en.undo);

  expect(updateTask).toHaveBeenLastCalledWith(
    task.id,
    7,
    { status: "in_progress" },
    expect.any(String),
  );
  expect(updateTask.mock.calls[1]?.[3]).not.toBe(updateTask.mock.calls[0]?.[3]);
  expect(announce).toHaveBeenLastCalledWith(en.undoneNote);
  // The card is as it was: Done is back, holds focus, and the receipt bar is gone.
  const again = screen.getByRole("button", { name: en.complete });
  expect(again).toHaveFocus();
  expect(screen.queryByRole("button", { name: en.undo })).toBeNull();
  expect(screen.getByText(en.taskStatus.in_progress)).toBeInTheDocument();
});

it("takes the receipt away when its time is up, and keeps the card done", async () => {
  renderCard(vi.fn().mockResolvedValue(done(2)));
  await click(en.complete);

  await act(async () => {
    await vi.advanceTimersByTimeAsync(UNDO_MS - 1);
  });
  expect(screen.getByRole("button", { name: en.undo })).toBeInTheDocument();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(screen.queryByRole("button", { name: en.undo })).toBeNull();
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
  expect(screen.getByText(en.taskStatus.completed)).toBeInTheDocument();
  // Focus stayed on Open, which is still there, so it never fell to the page.
  expect(screen.getByRole("button", { name: en.showTask })).toHaveFocus();
});

it("holds the receipt time while the pointer is over the bar, and runs on with the time left", async () => {
  renderCard(vi.fn().mockResolvedValue(done(2)));
  await click(en.complete);
  const bar = screen
    .getByRole("button", { name: en.undo })
    .closest(".sk-receipt") as HTMLElement;

  await act(async () => {
    await vi.advanceTimersByTimeAsync(UNDO_MS - 4000);
  });
  fireEvent.pointerEnter(bar);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(UNDO_MS * 3);
  });
  expect(screen.getByRole("button", { name: en.undo })).toBeInTheDocument();
  fireEvent.pointerLeave(bar);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3999);
  });
  expect(screen.getByRole("button", { name: en.undo })).toBeInTheDocument();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(screen.queryByRole("button", { name: en.undo })).toBeNull();
});

it("shows a failed Undo with Try again, which repeats it with the same key", async () => {
  const updateTask = vi
    .fn()
    .mockResolvedValueOnce(done(2))
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ task: { ...task, version: 3 } });
  renderCard(updateTask);
  await click(en.complete);
  await click(en.undo);

  expect(screen.getByRole("alert")).toHaveTextContent(en.undoFailed);
  // The bar's Ångra was used; the error row's Try again repeats it.
  expect(screen.queryByRole("button", { name: en.undo })).toBeNull();
  await click(en.retry);

  expect(updateTask).toHaveBeenCalledTimes(3);
  expect(updateTask.mock.calls[2]?.[3]).toBe(updateTask.mock.calls[1]?.[3]);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("button", { name: en.complete })).toBeInTheDocument();
});

it.each([
  ["en", inlineSummaryLabelsEn],
  ["sv", inlineSummaryLabelsSv],
] as const)(
  "shows a failed Done as the family's write error row at the card's full width, not a box in a narrow column (%s)",
  async (_lang, labels) => {
    const updateTask = vi.fn().mockRejectedValueOnce(new Error("offline"));
    renderCard(updateTask, labels);
    await click(labels.complete);

    const alert = screen.getByRole("alert");
    // The row, not the read error's two-column box, whose first column is the narrow icon column.
    expect(alert).toHaveClass("sk-error--row");
    expect(alert).not.toHaveClass("sk-error--card");
    expect(alert).toHaveTextContent(labels.doneFailed);
    // The sentence is one line of text and the button says Try again, so the sentence does not.
    expect(labels.doneFailed).not.toMatch(/försök igen|try again/i);
    expect(
      screen.getByRole("button", { name: labels.retry }),
    ).toBeInTheDocument();
    // A failure is a row under the control, never a receipt in the bar.
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  },
);

it("treats a reply that does not show the earlier status as a failure, not as undone", async () => {
  const updateTask = vi
    .fn()
    .mockResolvedValueOnce(done(2))
    .mockResolvedValueOnce(done(3));
  renderCard(updateTask);
  await click(en.complete);
  await click(en.undo);

  expect(screen.getByRole("alert")).toHaveTextContent(en.undoFailed);
  expect(screen.queryByRole("button", { name: en.complete })).toBeNull();
  expect(screen.getByRole("button", { name: en.retry })).toBeInTheDocument();
});

it("writes a recurring Task's due date and completion back, since Done reopened it for its next date", async () => {
  const recurring: WorkTask = {
    ...task,
    status: "todo",
    due_at: "2026-11-13T09:00:00Z",
    recurrence: { frequency: "weekly" },
    last_completed_at: "2026-11-06T09:00:00Z",
  } as WorkTask;
  const updateTask = vi
    .fn()
    .mockResolvedValueOnce({
      task: {
        ...recurring,
        due_at: "2026-11-20T09:00:00Z",
        last_completed_at: "2026-11-13T09:00:00Z",
        version: 2,
      },
    })
    .mockResolvedValueOnce({ task: { ...recurring, version: 3 } });
  renderCard(updateTask, en, { kind: "task", id: task.id, task: recurring });
  await click(en.complete);
  await click(en.undo);

  expect(updateTask).toHaveBeenLastCalledWith(
    task.id,
    2,
    {
      due_at: "2026-11-13T09:00:00Z",
      last_completed_at: "2026-11-06T09:00:00Z",
    },
    expect.any(String),
  );
});

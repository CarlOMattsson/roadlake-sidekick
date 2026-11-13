import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { UNDO_MS } from "@/features/work-app/agenda/agenda-undo";
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
import { readStylesheet } from "./helpers/stylesheet";

/*
 * The Task card's Done is undoable for UNDO_MS, as the Agenda's is: "Done" and Undo stand where Done stood, and Undo
 * writes the earlier status back against the version Done left. Simulated host: this proves the card's wiring, not
 * a real Claude or Android host.
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

it("shows Done and Undo in place of Done, with focus on Undo", async () => {
  renderCard(vi.fn().mockResolvedValue(done(2)));
  await click(en.complete);

  expect(screen.getByRole("status")).toHaveTextContent(en.taskStatus.completed);
  const undo = screen.getByRole("button", { name: en.undo });
  expect(undo).toHaveFocus();
  expect(screen.queryByRole("button", { name: en.complete })).toBeNull();
  // 44 px minimum on a touch pointer comes from the stylesheet (jsdom loads no CSS).
  expect(undo).toHaveClass("work-compact-action");
  expect(
    readStylesheet("features/work-app/inline/inline-summary.css").styleOf(
      undo,
      { room: "sidekick-work" },
    )["min-height"],
  ).toBe("var(--sk-tap)");
});

it("says it in Swedish: Klar and Ångra", async () => {
  renderCard(vi.fn().mockResolvedValue(done(2)), inlineSummaryLabelsSv);
  await click(inlineSummaryLabelsSv.complete);
  expect(screen.getByRole("status")).toHaveTextContent(/^Klar$/);
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
  // The card is as it was: Done is back, holds focus, and the Undo line is gone.
  const again = screen.getByRole("button", { name: en.complete });
  expect(again).toHaveFocus();
  expect(screen.queryByRole("button", { name: en.undo })).toBeNull();
  expect(screen.getByText(en.taskStatus.in_progress)).toBeInTheDocument();
});

it("takes the Undo away when its time is up, and keeps the card done", async () => {
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
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByText(en.taskStatus.completed)).toBeInTheDocument();
  // Focus was on Undo: it moves to Open, which stays, so it never falls to the page.
  expect(screen.getByRole("button", { name: en.showTask })).toHaveFocus();
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

  expect(screen.getByRole("alert")).toHaveTextContent(en.saveFailed);
  // The Undo line stays while there is time, so it can be pressed again too.
  expect(screen.getByRole("button", { name: en.undo })).toBeInTheDocument();
  await click(en.retry);

  expect(updateTask).toHaveBeenCalledTimes(3);
  expect(updateTask.mock.calls[2]?.[3]).toBe(updateTask.mock.calls[1]?.[3]);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("button", { name: en.complete })).toBeInTheDocument();
});

it("treats a reply that does not show the earlier status as a failure, not as undone", async () => {
  const updateTask = vi
    .fn()
    .mockResolvedValueOnce(done(2))
    .mockResolvedValueOnce(done(3));
  renderCard(updateTask);
  await click(en.complete);
  await click(en.undo);

  expect(screen.getByRole("alert")).toHaveTextContent(en.saveFailed);
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

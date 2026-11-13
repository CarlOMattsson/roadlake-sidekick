import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { workSv } from "@/features/work-app/shared/labels";
import { TaskSteps } from "@/features/work-app/tasks/task-steps";
import type {
  WorkAction,
  WorkStep,
  WorkTransport,
} from "@/features/work-app/transport/transport";

// jsdom has no CSS global; the row controls use CSS.escape to find a control by its Step id.
if (!("CSS" in globalThis)) {
  vi.stubGlobal("CSS", { escape: (value: string) => value });
}

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";

function step(id: string, title: string, actionCount?: number): WorkStep {
  return {
    id,
    title,
    status: "todo",
    due_at: null,
    version: 1,
    position: 0,
    ...(actionCount === undefined ? {} : { action_count: actionCount }),
  };
}
const bare = step("019f0000-0000-7000-8000-0000000000b1", "Ring Anna", 0);
const busy = step("019f0000-0000-7000-8000-0000000000b2", "Skriv offert", 1);
const unknown = step("019f0000-0000-7000-8000-0000000000b3", "Skicka faktura");

const action: WorkAction = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  step_id: busy.id,
  title: "Ring receptionen",
  status: "todo",
  due_at: null,
  version: 1,
  position: 0,
};

function renderSteps(overrides: Record<string, unknown> = {}) {
  const work = {
    listTaskSteps: vi.fn().mockResolvedValue({
      items: [bare, busy, unknown],
      next_cursor: null,
    }),
    reorderTaskSteps: vi.fn(),
    archiveTaskStep: vi.fn(),
    restoreTaskStep: vi.fn(),
    completeTaskStep: vi.fn(),
    updateTaskStep: vi.fn(),
    createTaskStep: vi.fn(),
    listStepActions: vi
      .fn()
      .mockResolvedValue({ items: [action], next_cursor: null }),
    archiveStepAction: vi.fn().mockResolvedValue({
      action: { ...action, version: 2, archived_at: "2026-11-02T08:00:00Z" },
    }),
    restoreStepAction: vi.fn(),
    ...overrides,
  };
  render(
    <TaskSteps
      taskId={TASK_ID}
      transport={work as unknown as WorkTransport}
      labels={workSv}
    />,
  );
  return work;
}

async function openMenu(title: string): Promise<HTMLElement> {
  const row = (await screen.findByRole("checkbox", { name: title })).closest(
    "li",
  ) as HTMLElement;
  fireEvent.contextMenu(row);
  return row;
}

function showButton(row: HTMLElement) {
  return row.querySelector<HTMLButtonElement>(".work-step-actions-open");
}

it("draws Visa åtgärder only for a Step that has actions or whose count is unknown", async () => {
  renderSteps();

  expect(showButton(await openMenu(bare.title))).toBeNull();
  expect(showButton(await openMenu(busy.title))).not.toBeNull();
  // An older server sends no count: the button stays as it was.
  expect(showButton(await openMenu(unknown.title))).not.toBeNull();
});

it("keeps the other menu buttons for a Step without actions", async () => {
  renderSteps();

  await openMenu(bare.title);
  expect(
    screen.getByRole("button", { name: `Flytta upp: ${bare.title}` }),
  ).toBeInTheDocument();
});

it("follows the count when the last action is archived: the button stays while open and goes when closed", async () => {
  const user = userEvent.setup();
  const work = renderSteps();
  const row = await openMenu(busy.title);

  await user.click(showButton(row)!);
  await screen.findByText(action.title);
  await user.click(
    screen.getByRole("button", { name: `Arkivera: ${action.title}` }),
  );
  await screen.findByText(`Arkiverade ”${action.title}”.`);
  expect(work.archiveStepAction).toHaveBeenCalledTimes(1);
  // Open: the button is still there to close the section.
  expect(showButton(row)).toHaveAttribute("aria-expanded", "true");

  await user.click(showButton(row)!);
  expect(showButton(row)).toBeNull();
});

it("keeps the count of a Step through a check, which the Step write answers without", async () => {
  const user = userEvent.setup();
  renderSteps({
    completeTaskStep: vi.fn().mockResolvedValue({
      step: { ...busy, version: 2, status: "completed" },
    }),
  });
  await user.click(await screen.findByRole("checkbox", { name: busy.title }));
  await screen.findByText(workSv.stepDone);

  expect(showButton(await openMenu(busy.title))).not.toBeNull();
  expect(showButton(await openMenu(bare.title))).toBeNull();
});

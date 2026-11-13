import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import {
  stepActionsLabelsEn,
  stepActionsLabelsSv,
} from "@/features/work-app/steps/step-actions-labels";
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
    completeStepAction: vi.fn(),
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

async function stepRow(title: string): Promise<HTMLElement> {
  return (await screen.findByRole("checkbox", { name: title })).closest(
    "li",
  ) as HTMLElement;
}

it("says how many actions a Step has under its title, and only when it has some", async () => {
  renderSteps();

  expect(showButton(await stepRow(bare.title))).toBeNull();
  const count = showButton(await stepRow(busy.title));
  expect(count).toHaveTextContent("1 åtgärd");
  expect(count).toHaveAttribute("aria-expanded", "false");
  // An older server sends no count: nothing is drawn.
  expect(showButton(await stepRow(unknown.title))).toBeNull();
});

it("opens and closes the actions from the count, with no entry in the Step's menu", async () => {
  const user = userEvent.setup();
  const work = renderSteps();
  const row = await stepRow(busy.title);
  expect(work.listStepActions).not.toHaveBeenCalled();

  await user.click(showButton(row)!);
  await screen.findByText(action.title);
  expect(showButton(row)).toHaveAttribute("aria-expanded", "true");
  expect(work.listStepActions).toHaveBeenCalledWith(busy.id);

  await user.click(showButton(row)!);
  expect(screen.queryByText(action.title)).not.toBeInTheDocument();

  fireEvent.contextMenu(row);
  expect(
    screen.queryByRole("button", { name: /åtgärder/ }),
  ).not.toBeInTheDocument();
});

it("words the count in English", () => {
  expect(stepActionsLabelsEn.countMeta(1)).toBe("1 action");
  expect(stepActionsLabelsEn.countMeta(2)).toBe("2 actions");
  expect(stepActionsLabelsSv.countMeta(1)).toBe("1 åtgärd");
  expect(stepActionsLabelsSv.countMeta(3)).toBe("3 åtgärder");
});

it("keeps the menu buttons for a Step without actions", async () => {
  renderSteps();

  await openMenu(bare.title);
  expect(
    screen.getByRole("button", { name: `Flytta upp: ${bare.title}` }),
  ).toBeInTheDocument();
});

it("follows the count when the last action is archived: the count stays while open and goes when closed", async () => {
  const user = userEvent.setup();
  const work = renderSteps();
  const row = await stepRow(busy.title);

  await user.click(showButton(row)!);
  await screen.findByText(action.title);
  fireEvent.contextMenu(
    screen.getByRole("checkbox", { name: action.title }).closest("li")!,
  );
  await user.click(
    screen.getByRole("button", { name: `Arkivera: ${action.title}` }),
  );
  await screen.findByText(`Arkiverade ”${action.title}”.`);
  expect(work.archiveStepAction).toHaveBeenCalledTimes(1);
  // Open: the count is still there to close the section.
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

  expect(showButton(await stepRow(busy.title))).not.toBeNull();
  expect(showButton(await stepRow(bare.title))).toBeNull();
});

it("says how many of the actions are done once they have been read, and follows a tick", async () => {
  const user = userEvent.setup();
  const second: WorkAction = {
    ...action,
    id: "019f0000-0000-7000-8000-0000000000c2",
    title: "Skicka mejlet",
    position: 1,
  };
  const work = renderSteps({
    listStepActions: vi
      .fn()
      .mockResolvedValue({ items: [action, second], next_cursor: null }),
    completeStepAction: vi.fn().mockResolvedValue({
      action: { ...action, status: "completed", version: 2 },
    }),
  });
  const row = await stepRow(busy.title);
  expect(showButton(row)).toHaveTextContent("1 åtgärd");

  await user.click(showButton(row)!);
  await screen.findByText(action.title);
  expect(showButton(row)).toHaveTextContent("2 åtgärder");

  await user.click(screen.getByRole("checkbox", { name: action.title }));
  expect(work.completeStepAction).toHaveBeenCalled();
  expect(showButton(row)).toHaveTextContent("1 av 2 åtgärder klara");
});

it("words how many are done in both languages", () => {
  expect(stepActionsLabelsSv.countMeta(2, 1)).toBe("1 av 2 åtgärder klara");
  expect(stepActionsLabelsSv.countMeta(1, 1)).toBe("1 av 1 åtgärd klar");
  expect(stepActionsLabelsEn.countMeta(2, 1)).toBe("1 of 2 actions done");
  expect(stepActionsLabelsEn.countMeta(1, 1)).toBe("1 of 1 action done");
  expect(stepActionsLabelsEn.countMeta(2, 0)).toBe("2 actions");
});

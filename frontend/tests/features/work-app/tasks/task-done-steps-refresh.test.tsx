import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkStep,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";

// Marking a Task done completes its Steps on the server. The open Task reads them again, keeps the Project's name
// and holds the Steps' new versions, so the next tick is not refused as stale. Simulated host (the view with a fake
// transport), not a real host.

const TITLE = "Kontorsflytt Östermalm";
const first: WorkStep = {
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Ring Johan",
  status: "todo",
  due_at: null,
  version: 1,
};
const second: WorkStep = {
  id: "019f0000-0000-7000-8000-0000000000b2",
  title: "Mejla bekräftelse till Erik",
  status: "todo",
  due_at: null,
  version: 1,
};
const task: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Bekräfta flyttdatum",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: "019f0000-0000-7000-8000-0000000000c1",
  project_title: TITLE,
};

/** A server that completes every Step when the Task is done, and answers update_task without the Project's name. */
function serverTransport() {
  const state = { done: false, firstDone: false };
  const steps = (): WorkStep[] => [
    state.done || state.firstDone
      ? { ...first, status: "completed", version: 2 }
      : first,
    state.done ? { ...second, status: "completed", version: 2 } : second,
  ];
  const { project_title: _name, ...answer } = task;
  void _name;
  return {
    getTask: vi.fn(() =>
      Promise.resolve({
        task: {
          ...task,
          version: state.done ? 3 : 1,
          status: state.done ? "completed" : "todo",
        },
      }),
    ),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskSteps: vi.fn(() =>
      Promise.resolve({ items: steps(), next_cursor: null }),
    ),
    completeTaskStep: vi.fn(() => {
      state.firstDone = true;
      return Promise.resolve({
        step: { ...first, status: "completed", version: 2 },
      });
    }),
    updateTaskStep: vi.fn((id: string, version: number) =>
      Promise.resolve({
        step: { ...second, id, status: "todo", version: version + 1 },
      }),
    ),
    updateTask: vi.fn(() => {
      state.done = true;
      return Promise.resolve({
        task: { ...answer, status: "completed", version: 3 },
      });
    }),
  } as unknown as WorkTransport;
}

it("shows both Steps done after Mark done, keeps the Project's name, and the next Step write is not stale", async () => {
  const work = serverTransport();
  const user = userEvent.setup();
  render(
    <WorkView
      transport={work}
      initial={{ kind: "task", id: task.id }}
      labels={workEn}
    />,
  );
  await user.click(await screen.findByRole("checkbox", { name: first.title }));
  expect(
    await screen.findByRole("heading", { name: workEn.stepsProgress(1, 2) }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: workEn.markDone }));

  expect(
    await screen.findByRole("heading", { name: workEn.stepsProgress(2, 2) }),
  ).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: second.title })).toBeChecked();
  // The place chip still names the Project, not the word "Project".
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: new RegExp(TITLE) }),
    ).toBeInTheDocument(),
  );

  // Unchecking the Step the server completed writes against the version the re-read gave it.
  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: second.title })).toBeEnabled(),
  );
  await user.click(screen.getByRole("checkbox", { name: second.title }));
  await waitFor(() => expect(work.updateTaskStep).toHaveBeenCalledTimes(1));
  expect(work.updateTaskStep).toHaveBeenCalledWith(
    second.id,
    2,
    { status: "todo" },
    expect.any(String),
  );
  expect(screen.queryByRole("alert")).toBeNull();
});

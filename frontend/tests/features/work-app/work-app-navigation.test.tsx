import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { WorkView } from "@/features/work-app/view/work-view";
import { hierarchyDetailLabelsFor } from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { errorLabelsFor } from "@/features/mcp-apps/ui/states";
import {
  rootFromToolResult,
  type WorkContactContext,
} from "@/features/work-app/transport/transport";
import {
  KEY,
  anna,
  annaTasks,
  bo,
  projectA,
  rootProject,
  rootTask,
  step,
  stepId,
  taskA,
  taskB,
  taskC,
  transport,
} from "@tests/helpers/work-app-fixtures";

/** The option the status menu marks as the current status (aria-pressed), after the chip opened it. */
async function pressedStatusOption(name: string) {
  const group = await screen.findByRole("group", { name });
  return within(group)
    .getAllByRole("button")
    .find((option) => option.getAttribute("aria-pressed") === "true");
}

it("puts the kind of a Task and of a Project as an eyebrow in a top row above the title", async () => {
  const work = transport();
  const { unmount } = render(rootTask(work));
  const taskTitle = await screen.findByRole("heading", {
    level: 2,
    name: taskA.title,
  });
  // The top row (work-detail-bar) is the article's first child: the kind on the left, the actions on the right.
  const taskBar = taskTitle.closest("article")?.firstElementChild;
  expect(taskBar).toHaveClass("work-detail-bar");
  const taskEyebrow = taskBar?.querySelector("p.sk-eyebrow");
  expect(taskEyebrow).toHaveTextContent(workEn.task);
  expect(taskBar).toContainElement(
    screen.getByRole("button", { name: workEn.moreActions }),
  );
  expect(
    (taskBar?.compareDocumentPosition(taskTitle) ?? 0) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  unmount();

  render(rootProject(work));
  const projectTitle = await screen.findByRole("heading", {
    level: 2,
    name: projectA.title,
  });
  const projectBar = projectTitle.closest("article")?.firstElementChild;
  expect(projectBar).toHaveClass("work-detail-bar");
  const projectEyebrow = projectBar?.querySelector("p.sk-eyebrow");
  expect(projectEyebrow).toHaveTextContent(workEn.project);
  expect(
    (projectBar?.compareDocumentPosition(projectTitle) ?? 0) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

it("shows the contacts of a root task without a back button", async () => {
  const work = transport();
  render(rootTask(work));
  expect(
    await screen.findByRole("heading", { level: 2, name: taskA.title }),
  ).toBeInTheDocument();
  expect(screen.getByRole("list")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: anna.display_name }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Tillbaka till / })).toBeNull();
  expect(work.getTask).toHaveBeenCalledWith(taskA.id);
  expect(work.listTaskContacts).toHaveBeenCalledWith(taskA.id);
});

it("opens a contact and then a task from the contact context", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(rootTask(work));
  await user.click(
    await screen.findByRole("button", { name: anna.display_name }),
  );
  const contactHeading = await screen.findByRole("heading", {
    level: 2,
    name: anna.display_name,
  });
  expect(contactHeading).toHaveFocus();
  expect(work.getContactContext).toHaveBeenCalledWith(anna.id);
  await user.click(await screen.findByRole("button", { name: taskB.title }));
  expect(
    await screen.findByRole("heading", { level: 2, name: taskB.title }),
  ).toBeInTheDocument();
  expect(work.getTask).toHaveBeenLastCalledWith(taskB.id);
});

it("goes back one step at a time to the root", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(rootTask(work));
  await user.click(
    await screen.findByRole("button", { name: anna.display_name }),
  );
  await user.click(await screen.findByRole("button", { name: taskB.title }));
  await screen.findByRole("heading", { level: 2, name: taskB.title });
  await user.click(
    screen.getByRole("button", { name: `Tillbaka till ${workEn.contact}` }),
  );
  expect(
    await screen.findByRole("heading", { level: 2, name: anna.display_name }),
  ).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: `Tillbaka till ${workEn.task}` }),
  );
  expect(
    await screen.findByRole("heading", { level: 2, name: taskA.title }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();
});

it("shows a retryable error without leaking the backend message", async () => {
  const user = userEvent.setup();
  const work = transport({
    getTask: vi
      .fn()
      .mockRejectedValueOnce(new Error("PRIVATE_BACKEND_MESSAGE"))
      .mockResolvedValue({ task: taskA }),
  });
  render(rootTask(work));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Couldn’t load the task",
  );
  expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  expect(
    await screen.findByRole("heading", { level: 2, name: taskA.title }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(work.getTask).toHaveBeenCalledTimes(2);
});

it("replaces the navigation stack when a new initial opens the app", async () => {
  const user = userEvent.setup();
  const work = transport();
  const { rerender } = render(rootTask(work));
  await user.click(
    await screen.findByRole("button", { name: anna.display_name }),
  );
  await screen.findByRole("heading", { level: 2, name: anna.display_name });
  rerender(rootTask(work, taskB.id));
  expect(
    await screen.findByRole("heading", { level: 2, name: taskB.title }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Tillbaka till / })).toBeNull();
});

it("loads more contacts with the returned cursor", async () => {
  const user = userEvent.setup();
  const work = transport({
    listTaskContacts: vi
      .fn()
      .mockResolvedValueOnce({ items: [anna], next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [bo], next_cursor: null }),
  });
  render(rootTask(work));
  await user.click(await screen.findByRole("button", { name: workEn.more }));
  expect(
    await screen.findByRole("button", { name: bo.display_name }),
  ).toBeInTheDocument();
  expect(work.listTaskContacts).toHaveBeenLastCalledWith(taskA.id, "page-2");
  expect(screen.queryByRole("button", { name: workEn.more })).toBeNull();
});

it("shows an empty state for a task without contacts and when nothing is open", async () => {
  const work = transport({
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  });
  const { unmount } = render(rootTask(work));
  expect(await screen.findByText(workEn.noContacts)).toBeInTheDocument();
  unmount();
  render(<WorkView transport={work} labels={workEn} />);
  expect(screen.getByText(workEn.empty)).toBeInTheDocument();
});

it("opens the root only from a tool result that carries a task or contact context", () => {
  expect(rootFromToolResult({ task: { id: taskA.id } })).toEqual({
    kind: "task",
    id: taskA.id,
  });
  expect(
    rootFromToolResult({
      contact: { id: anna.id },
      projects: { items: [] },
      tasks: { items: [] },
    }),
  ).toEqual({ kind: "contact", id: anna.id });
  expect(rootFromToolResult({ contact: { id: anna.id } })).toBeUndefined();
  expect(rootFromToolResult(undefined)).toBeUndefined();
});

it("opens a card from a work_changes envelope, a compact card from a lone Contact and an error frame from isError", () => {
  const changed = {
    kind: "task",
    id: taskA.id,
    title: taskA.title,
    status: taskA.status,
    due_at: taskA.due_at,
    version: taskA.version,
  };
  expect(
    rootFromToolResult({
      card: {
        kind: "work_changes",
        total: 7,
        truncated: true,
        items: [changed],
      },
    }),
  ).toEqual({
    kind: "card",
    items: [changed],
    total: 7,
    truncated: true,
  });
  expect(
    rootFromToolResult({
      card: { kind: "work_changes", total: 1, truncated: false, items: [] },
    }),
  ).toEqual({ kind: "card", items: [], total: 1, truncated: false });
  expect(
    rootFromToolResult({
      card: { kind: "work_changes", total: 1, truncated: false, items: [{}] },
    }),
  ).toBeUndefined();
  expect(
    rootFromToolResult({ card: { kind: "other", items: [], total: 0 } }),
  ).toBeUndefined();
  expect(rootFromToolResult({ contact: anna })).toEqual({
    kind: "compact",
    entity: "contact",
    contact: anna,
  });
  expect(
    rootFromToolResult({
      contact: anna,
      projects: { items: [] },
      tasks: { items: [] },
    }),
  ).toMatchObject({ kind: "contact", id: anna.id, context: { contact: anna } });
  expect(rootFromToolResult({ task: { id: taskA.id } }, true)).toEqual({
    kind: "error",
  });
  expect(rootFromToolResult({ card: { kind: "work_changes" } }, true)).toEqual({
    kind: "error",
  });
});

it("opens the Project root from a get_project result", () => {
  expect(rootFromToolResult({ project: { id: projectA.id } })).toEqual({
    kind: "project",
    id: projectA.id,
  });
  expect(rootFromToolResult({ project: { title: "utan id" } })).toBeUndefined();
});

it("keeps the Task visible and shows a calm notice when contacts are forbidden", async () => {
  const work = transport({
    listTaskContacts: vi.fn().mockRejectedValue(new HostToolError("forbidden")),
  });
  render(rootTask(work));
  expect(
    await screen.findByRole("heading", { level: 2, name: taskA.title }),
  ).toBeInTheDocument();
  expect(await screen.findByText(workEn.contactsForbidden)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("button", { name: workEn.retry })).toBeNull();
});

it("retries only the contacts when they fail while the Task loads", async () => {
  const user = userEvent.setup();
  const work = transport({
    listTaskContacts: vi
      .fn()
      .mockRejectedValueOnce(new Error("PRIVATE_BACKEND_MESSAGE"))
      .mockResolvedValue({ items: [anna], next_cursor: null }),
  });
  render(rootTask(work));
  expect(
    await screen.findByRole("heading", { level: 2, name: taskA.title }),
  ).toBeInTheDocument();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    errorLabelsFor("en-GB").message,
  );
  expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  expect(
    await screen.findByRole("button", { name: anna.display_name }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(work.getTask).toHaveBeenCalledTimes(1);
  expect(work.listTaskContacts).toHaveBeenCalledTimes(2);
});

it("loads more tasks of a contact with the returned task cursor", async () => {
  const user = userEvent.setup();
  const work = transport({
    getContactContext: vi
      .fn()
      .mockResolvedValueOnce({
        contact: anna,
        projects: { items: [], next_cursor: null },
        tasks: { items: annaTasks, next_cursor: "task-page-2" },
      })
      .mockResolvedValueOnce({
        contact: anna,
        projects: { items: [], next_cursor: null },
        tasks: { items: [taskC], next_cursor: null },
      }),
  });
  render(rootTask(work));
  await user.click(
    await screen.findByRole("button", { name: anna.display_name }),
  );
  await user.click(await screen.findByRole("button", { name: workEn.more }));
  expect(
    await screen.findByRole("button", { name: taskC.title }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: taskB.title })).toBeInTheDocument();
  expect(work.getContactContext).toHaveBeenLastCalledWith(
    anna.id,
    "task-page-2",
  );
  expect(screen.queryByRole("button", { name: workEn.more })).toBeNull();
});

it("drops a late contact response after the user has navigated away", async () => {
  const user = userEvent.setup();
  let resolveAnna!: (value: WorkContactContext) => void;
  const work = transport({
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [anna, bo], next_cursor: null }),
    getContactContext: vi.fn((contactId: string) =>
      contactId === anna.id
        ? new Promise<WorkContactContext>((resolve) => {
            resolveAnna = resolve;
          })
        : Promise.resolve({
            contact: bo,
            projects: { items: [], next_cursor: null },
            tasks: { items: [], next_cursor: null },
          }),
    ),
  });
  render(rootTask(work));
  await user.click(
    await screen.findByRole("button", { name: anna.display_name }),
  );
  expect(work.getContactContext).toHaveBeenCalledWith(anna.id);
  await user.click(
    screen.getByRole("button", { name: `Tillbaka till ${workEn.task}` }),
  );
  expect(
    await screen.findByRole("heading", { level: 2, name: taskA.title }),
  ).toBeInTheDocument();
  await user.click(
    await screen.findByRole("button", { name: bo.display_name }),
  );
  expect(
    await screen.findByRole("heading", { level: 2, name: bo.display_name }),
  ).toBeInTheDocument();
  await act(async () => {
    resolveAnna({
      contact: anna,
      projects: { items: [], next_cursor: null },
      tasks: { items: annaTasks, next_cursor: null },
    });
    // Let the stale promise settle before asserting that it changed nothing.
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(
    screen.getByRole("heading", { level: 2, name: bo.display_name }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { level: 2, name: anna.display_name }),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: taskB.title })).toBeNull();
});

it("shows a known Task status translated and an unknown status as received", async () => {
  const work = transport({
    getContactContext: vi.fn().mockResolvedValue({
      contact: anna,
      projects: { items: [], next_cursor: null },
      tasks: { items: [taskC, ...annaTasks], next_cursor: null },
    }),
  });
  render(
    <WorkView
      transport={work}
      initial={{ kind: "contact", id: anna.id }}
      labels={workEn}
    />,
  );
  // The task row names a status only when its ring does not say it: not "To do", and never with a "Status:" prefix.
  // The ring itself is a labelled image with the translated status; an unknown status shows as received.
  expect(await screen.findByText("doing")).toBeInTheDocument();
  expect(
    screen.getAllByRole("img", { name: workEn.taskStatus.todo }).length,
  ).toBeGreaterThan(0);
  expect(screen.queryByText(/^Status:/)).toBeNull();
});

it("shows the Task status once, in its status chip, and the open menu marks it as pressed", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(rootTask(work));
  const dl = hierarchyDetailLabelsFor(workEn.dateLocale);
  const chip = await screen.findByRole("button", {
    name: `${dl.changeStatus}: ${workEn.taskStatus.todo}`,
  });
  expect(chip).toHaveTextContent(workEn.taskStatus.todo);
  expect(chip).toHaveAttribute("aria-expanded", "false");
  expect(
    screen.queryByText(`${workEn.status}: ${workEn.taskStatus.todo}`),
  ).toBeNull();
  await user.click(chip);
  expect(chip).toHaveAttribute("aria-expanded", "true");
  expect(await pressedStatusOption(workEn.status)).toHaveTextContent(
    workEn.taskStatus.todo,
  );
});

it("translates the Task status with the Swedish labels", async () => {
  const work = transport();
  render(
    <WorkView
      transport={work}
      initial={{ kind: "task", id: taskA.id }}
      labels={workSv}
    />,
  );
  const dl = hierarchyDetailLabelsFor(workSv.dateLocale);
  expect(
    await screen.findByRole("button", {
      name: `${dl.changeStatus}: ${workSv.taskStatus.todo}`,
    }),
  ).toHaveTextContent(workSv.taskStatus.todo);
});

it("completes a step with its version and reuses the key when the same click is retried", async () => {
  const user = userEvent.setup();
  const complete = vi
    .fn()
    .mockRejectedValueOnce(new Error("PRIVATE_BACKEND_MESSAGE"))
    .mockResolvedValue({ step: { ...step, status: "completed", version: 4 } });
  const work = transport({
    listTaskSteps: vi
      .fn()
      .mockResolvedValue({ items: [step], next_cursor: null }),
    completeTaskStep: complete,
  });
  render(rootTask(work));
  await user.click(await screen.findByRole("checkbox", { name: step.title }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    workEn.stepSaveFailed,
  );
  expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  expect(
    await screen.findByRole("checkbox", { name: step.title }),
  ).toBeChecked();
  expect(complete).toHaveBeenCalledTimes(2);
  expect(complete.mock.calls[0]).toEqual([
    stepId,
    3,
    expect.stringMatching(KEY),
  ]);
  expect(complete.mock.calls[1]).toEqual(complete.mock.calls[0]);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("unchecks a completed step through update_task_step with status to-do", async () => {
  const user = userEvent.setup();
  const done = { ...step, status: "completed", version: 4 };
  const updateStep = vi
    .fn()
    .mockResolvedValue({ step: { ...done, status: "todo", version: 5 } });
  const work = transport({
    listTaskSteps: vi
      .fn()
      .mockResolvedValue({ items: [done], next_cursor: null }),
    updateTaskStep: updateStep,
  });
  render(rootTask(work));
  const checkbox = await screen.findByRole("checkbox", { name: step.title });
  expect(checkbox).toBeChecked();
  await user.click(checkbox);
  await waitFor(() => expect(checkbox).not.toBeChecked());
  expect(updateStep).toHaveBeenCalledWith(
    stepId,
    4,
    { status: "todo" },
    expect.stringMatching(KEY),
  );
});

it("sends a double-clicked step only once", async () => {
  const user = userEvent.setup();
  const complete = vi.fn(() => new Promise<never>(() => {}));
  const work = transport({
    listTaskSteps: vi
      .fn()
      .mockResolvedValue({ items: [step], next_cursor: null }),
    completeTaskStep: complete,
  });
  render(rootTask(work));
  await user.dblClick(
    await screen.findByRole("checkbox", { name: step.title }),
  );
  expect(complete).toHaveBeenCalledTimes(1);
});
